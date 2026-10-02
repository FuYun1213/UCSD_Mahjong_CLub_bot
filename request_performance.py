"""Request-local, credential-free timings for both HTTP services.

PERF_LOG_LEVEL=off|slow|all (default slow), PERF_SLOW_MS=500.
Only query counts/timings are logged; SQL, parameters and headers are never logged.
"""
import contextvars
from contextlib import contextmanager
import functools
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from urllib.parse import urlsplit

current = contextvars.ContextVar('request_performance', default=None)
logger = logging.getLogger('request.performance')

# Fixed names keep metrics free of user identities, table names and remote URLs.
STAGE_FIELDS = frozenset({
    'memberLockWaitMs', 'accountLockWaitMs', 'transactionMs', 'localFinalizeMs',
    'sheetsDurationMs', 'sheetsHistoryDurationMs', 'sheetsClubHistoryDurationMs',
    'sheetsPlayersDurationMs', 'nartsDurationMs',
})
COUNT_FIELDS = frozenset({'sheetsCallCount', 'nartsCallCount'})
STAGE_HEADERS = {
    'member_lock': 'memberLockWaitMs', 'account_lock': 'accountLockWaitMs',
    'transaction': 'transactionMs', 'local_finalize': 'localFinalizeMs',
    'sheets': 'sheetsDurationMs', 'narts': 'nartsDurationMs',
}
STAGE_HEADER_COUNTS = {'sheets': 'sheetsCallCount', 'narts': 'nartsCallCount'}


def observe(field, milliseconds):
    """Accumulate a fixed, numeric stage metric in the current request only."""
    if field not in STAGE_FIELDS:
        raise ValueError('Unknown performance stage')
    value = current.get()
    if value is not None:
        value[field] += max(0.0, float(milliseconds))


@contextmanager
def measure(field, count=None):
    """Time a stage, including failures; never record arguments or exception text."""
    if field not in STAGE_FIELDS or (count is not None and count not in COUNT_FIELDS):
        raise ValueError('Unknown performance stage')
    value = current.get()
    if value is None:
        yield
        return
    if count:
        value[count] += 1
    started = time.perf_counter()
    try:
        yield
    finally:
        value[field] += (time.perf_counter() - started) * 1000


class TimedRLock:
    """RLock with acquisition timing, retaining reentry and Condition semantics."""
    def __init__(self, field):
        if field not in STAGE_FIELDS:
            raise ValueError('Unknown performance stage')
        self._field = field
        self._lock = threading.RLock()

    def acquire(self, *args, **kwargs):
        with measure(self._field):
            return self._lock.acquire(*args, **kwargs)

    def release(self):
        return self._lock.release()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.release()

    def _release_save(self):
        return self._lock._release_save()

    def _acquire_restore(self, state):
        with measure(self._field):
            return self._lock._acquire_restore(state)

    def _is_owned(self):
        return self._lock._is_owned()

    def __getattr__(self, name):
        return getattr(self._lock, name)


def start(method, path):
    value = dict(requestId=uuid.uuid4().hex, method=method,
                 path=re.sub(r'/(join|join-table|table-join-tokens)/[^/]+', r'/\1/[redacted]', urlsplit(path).path),
                 status=500, durationMs=0, databaseDurationMs=0, databaseQueryCount=0,
                 databaseConnectionWaitMs=0, databasePoolAcquireMs=0, databaseErrorCount=0, databaseTimeoutCount=0, externalServiceDurationMs=0,
                 externalServiceCallCount=0, upstreamDurationMs=0, responseSize=0,
                 started=time.perf_counter())
    value.update({field: 0.0 for field in STAGE_FIELDS})
    value.update({field: 0 for field in COUNT_FIELDS})
    return value, current.set(value)


def finish(value, token):
    value['durationMs'] = (time.perf_counter()-value.pop('started'))*1000
    current.reset(token)
    mode = os.getenv('PERF_LOG_LEVEL', 'slow')
    if mode == 'all' or (mode != 'off' and value['durationMs'] >= float(os.getenv('PERF_SLOW_MS', '500'))):
        logger.warning(json.dumps({k: round(v,3) if isinstance(v,float) else v for k,v in value.items()}, separators=(',',':')))


def timed(field, count=None):
    def decorate(fn):
        @functools.wraps(fn)
        def call(*args, **kwargs):
            value = current.get()
            if value is None:
                return fn(*args, **kwargs)
            if count: value[count] += 1
            started = time.perf_counter()
            try: return fn(*args, **kwargs)
            except sqlite3.Error as error:
                value['databaseErrorCount']+=1
                if any(word in str(error).lower() for word in ('locked','busy','timeout')):value['databaseTimeoutCount']+=1
                raise
            finally: value[field] += (time.perf_counter()-started)*1000
        return call
    return decorate


class Cursor(sqlite3.Cursor):
    execute = timed('databaseDurationMs','databaseQueryCount')(sqlite3.Cursor.execute)
    executemany = timed('databaseDurationMs','databaseQueryCount')(sqlite3.Cursor.executemany)
    executescript = timed('databaseDurationMs','databaseQueryCount')(sqlite3.Cursor.executescript)
    fetchone = timed('databaseDurationMs')(sqlite3.Cursor.fetchone)
    fetchall = timed('databaseDurationMs')(sqlite3.Cursor.fetchall)
    fetchmany = timed('databaseDurationMs')(sqlite3.Cursor.fetchmany)


class Connection(sqlite3.Connection):
    def cursor(self, *args, **kwargs):
        kwargs.setdefault('factory', Cursor)
        return super().cursor(*args, **kwargs)
    def execute(self, sql, parameters=()): return self.cursor().execute(sql, parameters)
    def executemany(self, sql, parameters): return self.cursor().executemany(sql, parameters)
    def executescript(self, sql): return self.cursor().executescript(sql)
    commit = timed('databaseDurationMs')(sqlite3.Connection.commit)
    rollback = timed('databaseDurationMs')(sqlite3.Connection.rollback)


def headers():
    value = current.get()
    if value is None: return {}
    stages = ''.join(', %s;dur=%.3f' % (name, value[field]) +
        (';desc="%d calls"' % value[STAGE_HEADER_COUNTS[name]] if name in STAGE_HEADER_COUNTS else '')
        for name, field in STAGE_HEADERS.items())
    return {'X-Request-ID':value['requestId'], 'Server-Timing':
        'db;dur=%.3f;desc="%d queries", external;dur=%.3f;desc="%d calls"' % (
            value['databaseDurationMs'],value['databaseQueryCount'],value['externalServiceDurationMs'],value['externalServiceCallCount']) + stages}


def network(fn, url_getter):
    @functools.wraps(fn)
    def call(*args, **kwargs):
        value=current.get()
        if value is None: return fn(*args,**kwargs)
        host=urlsplit(url_getter(*args,**kwargs)).hostname
        local=host in {'127.0.0.1','localhost','::1'}
        started=time.perf_counter()
        if not local:value['externalServiceCallCount']+=1
        try:
            response=fn(*args,**kwargs)
            # Only trust timings from configured loopback services, never a remote API.
            if local:
                timing=response.headers.get('Server-Timing','')
                match=re.search(r'db;dur=([0-9.]+);desc="(\d+) queries"',timing)
                if match:value['databaseDurationMs']+=float(match[1]);value['databaseQueryCount']+=int(match[2])
                match=re.search(r'external;dur=([0-9.]+);desc="(\d+) calls"',timing)
                if match:value['externalServiceDurationMs']+=float(match[1]);value['externalServiceCallCount']+=int(match[2])
                for name, field in STAGE_HEADERS.items():
                    match = re.search(r'(?:^|,\s*)' + name + r';dur=([0-9.]+)(?:;desc="(\d+) calls")?(?=,|$)', timing)
                    if match:
                        value[field] += float(match[1])
                        if name in STAGE_HEADER_COUNTS and match[2] is not None:
                            value[STAGE_HEADER_COUNTS[name]] += int(match[2])
            return response
        finally:value['upstreamDurationMs' if local else 'externalServiceDurationMs']+=(time.perf_counter()-started)*1000
    return call


def install():
    if getattr(sqlite3.connect,'_performance_installed',False):return
    original=sqlite3.connect
    @timed('databaseConnectionWaitMs')
    def connect(*args,**kwargs):
        kwargs.setdefault('factory',Connection)
        return original(*args,**kwargs)
    connect._performance_installed=True
    sqlite3.connect=sqlite3.dbapi2.connect=connect
    import requests
    import urllib.request
    requests.Session.send=network(requests.Session.send,lambda self,request,**kw:request.url)
    urllib.request.OpenerDirector.open=network(urllib.request.OpenerDirector.open,
        lambda self,request,*a,**kw:request.full_url if hasattr(request,'full_url') else request)


class Middleware:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        value,token=start(scope['method'],scope['path'])
        pending_start=None
        json_response=False
        chunks=[]
        async def measured(message):
            nonlocal pending_start,json_response
            if message['type']=='http.response.start':
                value['status']=message['status'];pending_start=message
                json_response=any(k.lower()==b'content-type' and b'application/json' in v for k,v in message.get('headers',[]))
                if not json_response:
                    message['headers']=list(message.get('headers',[]))+[(k.lower().encode(),v.encode()) for k,v in headers().items()]
                    await send(message)
                return
            if not json_response:
                if message['type']=='http.response.body':value['responseSize']+=len(message.get('body',b''))
                await send(message);return
            if message['type']=='http.response.body':
                chunks.append(message.get('body',b''))
                if message.get('more_body'):return
                body=b''.join(chunks)
                original_headers=list(pending_start.get('headers',[]))
                if any(k.lower()==b'content-type' and b'application/json' in v for k,v in original_headers):
                    from account_images import public_avatars
                    try:body=json.dumps(public_avatars(json.loads(body)),ensure_ascii=False,separators=(',',':')).encode()
                    except (ValueError,UnicodeError):pass
                pending_start['headers']=[(k,v) for k,v in original_headers if k.lower() not in {b'content-length',b'server-timing',b'x-request-id'}]+[(b'content-length',str(len(body)).encode())]+[(k.lower().encode(),v.encode()) for k,v in headers().items()]
                value['responseSize']=len(body)
                await send(pending_start)
                await send({**message,'body':body})
                return
            await send(message)
        try:await self.app(scope,receive,measured)
        finally:finish(value,token)
