"""Avatar visibility and failed-image fallback in real reservation/seat/search UI."""
import json,os,subprocess
from pathlib import Path
import pytest
import web_server
from test_web_score_bridge import website
from test_discord_binding_avatars import PNG

@pytest.mark.skipif(os.getenv("NFC_BROWSER_TESTS")!="1",reason="Set NFC_BROWSER_TESTS=1 for browser verification")
def test_real_browser_avatars_in_reservations_seats_and_registered_search(website):
    url,_,_=website
    path=web_server.USERS_FILE
    data=json.loads(path.read_text(encoding="utf-8"))
    data["users"]["photo2"].update(avatar=PNG,discord_id="123456789012345678")
    data["users"]["photo3"].update(avatar="https://cdn.discordapp.com/avatars/test/missing.png",discord_id="234567890123456789")
    path.write_text(json.dumps(data),encoding="utf-8")
    env=os.environ.copy()
    env.update(NFC_TEST_URL=url,NODE_PATH=str(Path(".venv-api/browser-tests/node_modules").resolve()))
    result=subprocess.run(["node","tests/browser_account_avatars.cjs"],env=env,capture_output=True,text=True,encoding="utf-8",timeout=120)
    assert result.returncode==0,result.stdout+result.stderr
