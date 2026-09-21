from contextlib import contextmanager

from filelock import FileLock, Timeout
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@contextmanager
def single_writer(settings):
    """One DB-backed service writer, including when PostgreSQL spans hosts."""
    if settings.database_url and make_url(settings.database_url).get_backend_name() == "postgresql":
        engine = create_engine(settings.database_url)
        try:
            with engine.connect() as connection:
                acquired = connection.scalar(text("SELECT pg_try_advisory_lock(778320145)"))
                if not acquired:
                    raise RuntimeError("Another API owns this database; use --workers 1")
                try:
                    yield
                finally:
                    connection.execute(text("SELECT pg_advisory_unlock(778320145)"))
        finally:
            engine.dispose()
    else:
        from pathlib import Path
        path = Path(make_url(settings.database_url).database) if settings.database_url else settings.database_path
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(path.resolve()) + ".api.lock")
        try:
            lock.acquire(timeout=0)
        except Timeout as exc:
            raise RuntimeError("This database is already served by another API process; use --workers 1") from exc
        try:
            yield
        finally:
            lock.release()
