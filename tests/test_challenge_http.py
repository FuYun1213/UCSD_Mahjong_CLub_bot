import json
from contextlib import closing
import requests
import pytest
import web_server
import mahjong_store
import registered_names
import competition_http
from competition_service import SLUG
from test_web_score_bridge import website

@pytest.fixture
def challenge(website,tmp_path,monkeypatch):
    url,app,sheets=website
    monkeypatch.setattr(web_server,"MAHJONG_DB_FILE",tmp_path/"club.sqlite3")
    monkeypatch.setattr(web_server,"LIVE_DB_FILE",tmp_path/"live.sqlite3")
    monkeypatch.setattr(web_server,"YAKUMAN_UPLOAD_DIR",tmp_path/"images")
    monkeypatch.setenv("NFC_DATABASE_PATH",str(tmp_path/"scores.sqlite3"))
    with closing(mahjong_store.connect(web_server.MAHJONG_DB_FILE)):pass
    directory=registered_names.read_accounts(web_server.USERS_FILE);directory["users"]["photo1"]["role"]="admin"
    registered_names.write_accounts(web_server.USERS_FILE,directory)
    api=competition_http.service(web_server);api.seed()
    sessions=[]
    for name in ("photo1","photo2"):
        session=requests.Session();response=session.post(url+"/api/login",json={"username":name,"password":"photo-test-password"},headers={"Origin":url});assert response.status_code==200;sessions.append(session)
    yield url,api,*sessions
    for s in sessions:s.close()

@pytest.mark.parametrize("suffix",["content","rules","rebuild","images","image-delete","game-correction"])
def test_admin_writes_require_global_admin(challenge,suffix):
    url,api,admin,user=challenge
    assert requests.post(url+"/api/competitions/"+SLUG+"/"+suffix,json={},headers={"Origin":url}).status_code==401
    assert user.post(url+"/api/competitions/"+SLUG+"/"+suffix,json={},headers={"Origin":url}).status_code==403

@pytest.mark.parametrize("path",["manage",SLUG+"/admin",SLUG+"/games"])
def test_admin_reads_are_private(challenge,path):
    url,api,admin,user=challenge
    assert requests.get(url+"/api/competitions/"+path).status_code==401
    assert user.get(url+"/api/competitions/"+path).status_code==403
    assert admin.get(url+"/api/competitions/"+path).status_code==200


def test_same_origin_and_public_endpoints(challenge):
    url,api,admin,user=challenge
    assert requests.get(url+"/api/competitions/featured").json()["competition"]["slug"]==SLUG
    assert requests.get(url+"/challenges/"+SLUG).status_code==200
    assert admin.post(url+"/api/competitions/"+SLUG+"/content",json={},headers={"Origin":"https://wrong.example"}).status_code==403
