"""The real website must forward seat PUT bodies, sessions and CSRF headers."""
import requests
import pytest

from test_web_score_bridge import website, login


def test_my_seat_cookie_bridge_join_move_replay_and_origin(website):
    url, app, _ = website
    route = url + "/api/club-tables/web/my-seat"
    anonymous = requests.put(route, json={"seat": "east"}, timeout=10)
    assert anonymous.status_code == 401
    one, two = login(url, 1), login(url, 2)
    try:
        joined = one.put(route, json={"seat": "east", "user_id": "photo-user-2"}, headers={"Origin": url}, timeout=10)
        # Extra IDs can be rejected; they can never impersonate another player.
        if joined.status_code == 422:
            joined = one.put(route, json={"seat": "east"}, headers={"Origin": url}, timeout=10)
        assert joined.status_code == 200, joined.text
        assert joined.json()["players"]["east"]["id"] == "photo-user-1"
        assert not joined.json()["players"]["south"]
        moved = one.put(route, json={"seat": "south"}, headers={"Origin": url}, timeout=10)
        assert moved.status_code == 200, moved.text
        state = moved.json()["players"]
        assert state["east"] is None and state["south"]["id"] == "photo-user-1"
        replay = one.put(route, json={"seat": "south"}, headers={"Origin": url}, timeout=10)
        assert replay.status_code == 200 and replay.json()["players"] == state
        occupied = two.put(route, json={"seat": "south"}, headers={"Origin": url}, timeout=10)
        assert occupied.status_code == 409 and occupied.json()["detail"]["code"] == "seat_occupied"
        rejected = one.put(route, json={"seat": "north"}, headers={"Origin": url + ".evil.invalid"}, timeout=10)
        assert rejected.status_code == 403
        unchanged = one.get(url + "/api/tables/web", timeout=10).json()
        assert unchanged["players"] == state
        other = one.put(url + "/api/club-tables/A/my-seat", json={"seat": "east"}, headers={"Origin": url}, timeout=10)
        assert other.status_code == 409 and other.json()["detail"]["code"] == "already_at_other_table"
    finally:
        one.close(); two.close()


def test_guest_seat_map_is_real_occupancy_without_account_identity(website):
    url, _, _ = website
    user = login(url, 2)
    try:
        response = user.put(url + "/api/club-tables/web/my-seat", json={"seat": "west"}, headers={"Origin": url}, timeout=10)
        assert response.status_code == 200, response.text
        public = requests.get(url + "/api/club-tables/web/seat-map", timeout=10)
        assert public.status_code == 200
        body = public.json()
        assert body["players"] == {"east": None, "south": None, "west": {"occupied": True}, "north": None}
        assert "photo-user" not in public.text and "photo2" not in public.text
        assert "match_id" not in body and "seats" not in body
        assert requests.get(url + "/api/tables/web", timeout=10).status_code == 401
        assert requests.get(url + "/api/club-tables", timeout=10).status_code == 401
    finally:
        user.close()


@pytest.mark.parametrize("method,path", [("post","/api/club-tables/web/my-seat"),
    ("get","/api/club-tables/web/my-seat"), ("put","/api/club-tables/web/leave"),
    ("put","/api/manual-score/upload"), ("put","/api/club-tables/web/seat-map")])
def test_new_proxy_write_allowlist_is_exact(website, method, path):
    url, _, _ = website
    response = getattr(requests, method)(url + path, timeout=10)
    assert response.status_code == 405
