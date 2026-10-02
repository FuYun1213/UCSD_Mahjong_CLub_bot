"""Reservation ranges, nearby session defaults, and grouped reminders in a real browser."""
import json
import os
from pathlib import Path
import subprocess
import pytest
import web_server
from test_web_score_bridge import website

@pytest.mark.skipif(os.getenv('NFC_BROWSER_TESTS') != '1', reason='Set NFC_BROWSER_TESTS=1 to run browser integration')
def test_reservation_sessions_browser(website, monkeypatch, tmp_path):
    url, app, _ = website
    accounts=json.loads(web_server.USERS_FILE.read_text(encoding='utf-8'))
    accounts['users']['photo1']['role']='admin'
    web_server.USERS_FILE.write_text(json.dumps(accounts),encoding='utf-8')
    monkeypatch.setattr(web_server,'sheet_player_names',lambda: [])
    monkeypatch.setattr(web_server,'build_dashboard',lambda *a,**kw:{'stats':{'member_count':8},'rankings':[],'recent_yakuman':[]})
    clock_file=tmp_path/'reservation-clock.txt'
    clock_file.write_text('2026-12-31T22:20:00-08:00',encoding='utf-8')
    monkeypatch.setattr(app.state.tables,'clock',lambda:clock_file.read_text(encoding='utf-8'))
    environment=os.environ.copy()
    environment.update(NFC_TEST_URL=url,SESSION_TEST_CLOCK=str(clock_file),NODE_PATH=str(Path(os.environ.get('NODE_PATH') or '.venv-api/browser-tests/node_modules').resolve()))
    result=subprocess.run(['node','tests/browser_reservation_sessions.cjs'],env=environment,capture_output=True,text=True,encoding='utf-8',timeout=180)
    assert result.returncode==0,result.stdout+result.stderr
    print(result.stdout)
