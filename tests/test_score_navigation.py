"""Global login preserves scoring routes; table credentials remain redacted."""
from urllib.parse import quote
import requests
import pytest
from mahjong_api.logging_filters import redact_table_token
from test_web_score_bridge import website


@pytest.mark.parametrize("prefix",["/join/","/join-table/","/api/table-join-tokens/"])
def test_entry_credentials_redacted_in_paths_and_login_returns(prefix):
    target=prefix+"syntheticSecretToken123456"
    for line in ["GET "+target+" HTTP/1.1", "GET /login?redirect_url="+quote(target,safe="")+" HTTP/1.1"]:
        assert "syntheticSecretToken123456" not in redact_table_token(line)
        assert redact_table_token(line).endswith(" HTTP/1.1")


def test_spa_routes_and_auth_return_destinations(website):
    base,_,_=website
    for path in ["/reservations","/manual-score?table=web","/join/syntheticSecretToken123456"]:
        response=requests.get(base+path,timeout=10)
        assert response.status_code==200
        assert '<div id="root"></div>' in response.text
    for path,target in [("/api/manual-score/preview","/manual-score?table=web"),
                        ("/api/table-join-tokens/syntheticSecretToken123456/join","/join/syntheticSecretToken123456"),
                        ("/api/club-tables/web/reservations","/reservations?table=web")]:
        response=requests.post(base+path,json={},headers={"Referer":base+target},timeout=10)
        assert response.status_code==401
        assert quote(target,safe="") in response.json()["detail"]["redirect_url"]
    embed=requests.get(base+"/score?embedded=1&table=web",timeout=10).text
    assert 'login-form' not in embed and 'type="password"' not in embed
    script=requests.get(base+"/score-i18n.js",timeout=10).text
    assert "login-form" not in script and "api('/api/login'" not in script


def test_entry_source_fragment_in_encoded_login_return_is_redacted():
    target="/?page=record&table=3#entry=syntheticSecretToken123456"
    value="GET /login?redirect_url="+quote(target,safe="")+" HTTP/1.1"
    assert "syntheticSecretToken123456" not in redact_table_token(value)
    assert "HTTP/1.1" in redact_table_token(value)
