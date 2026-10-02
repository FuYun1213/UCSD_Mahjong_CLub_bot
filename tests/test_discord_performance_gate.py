"""Regression reproducer: a slow Discord POST must not hold the score DB writer."""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from test_discord_reminders import reminders,reserve,jobs
from test_table_v3 import setup,make,USERS


def test_slow_discord_does_not_block_unrelated_seating(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table);other=make(tables,99)
    entered=threading.Event();release=threading.Event();original=sender.send
    def slow(*args):
        entered.set();release.wait(timeout=1)
        return original(*args)
    sender.send=slow
    with ThreadPoolExecutor(max_workers=2) as pool:
        future=pool.submit(worker.tick)
        assert entered.wait(timeout=5)
        start=time.perf_counter()
        tables.join(other['id'],USERS[5],'east')
        elapsed=time.perf_counter()-start
        release.set();future.result(timeout=10)
    print('Seating while Discord POST pending: %.2f ms'%(elapsed*1000))
    if os.getenv('PERF_GATE_EXPECT_SLOW'):
        assert elapsed>=.8
    else:
        assert elapsed<.5
    assert jobs(worker)[0].status=='sent' and len(sender.messages)==1
