"""Real website cookie/CSRF proxy integration for reminders and consensual swaps."""
from datetime import datetime, timedelta, timezone
import requests
import pytest
from test_web_score_bridge import website, login


def test_reminder_and_swap_through_real_website_sessions(website):
    url, _, _ = website
    sessions = [login(url, number) for number in (2, 3, 4)]
    one, two, outsider = sessions
    headers = {"Origin": url}
    def send(session, method, path, data=None, status=200, origin=None):
        result = session.request(method, url + path, json=data,
                                 headers=origin or headers, timeout=10)
        assert result.status_code == status, result.text
        return result.json()
    try:
        tables = send(one, "GET", "/api/club-tables")["tables"]
        table = next(item for item in tables if item["score_table_id"] == "web")
        registry = table["id"]
        base = "/api/club-tables/" + registry
        swaps = "/api/tables/web/seat-swap-requests"
        for path in (base + "/reservation-default", base + "/reservation-reminders", swaps):
            assert requests.get(url + path, timeout=10).status_code == 401
        assert requests.post(url + swaps, json={"target_user_id":"photo-user-3"}, timeout=10).status_code == 401
        default = send(one, "GET", base + "/reservation-default")
        parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
        assert parse(default["scheduled_at"]) > parse(default["server_now"])
        assert default["local_time"].endswith(":00")
        reservation = send(one, "POST", base + "/reservations", {
            "scheduled_at":(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
            "participant_ids":["photo-user-2", "photo-user-3"], "request_id":"bridge-reservation-v8"})
        def reminder():
            return send(one, "GET", base + "/reservation-reminders")["reminders"][0]
        assert all(not person["seated"] for person in reminder()["participants"])
        for session, seat in ((one,"east"), (two,"south")):
            send(session, "PUT", "/api/club-tables/web/my-seat", {"seat":seat})
        arrived = reminder()
        assert arrived["all_seated"]
        assert {p["name"] for p in arrived["participants"]} == {"photo2", "photo3"}
        before = send(one, "GET", "/api/tables/web")
        assert not before["started_at"]  # Reminder arrival never starts a game.
        created = send(one, "POST", swaps, {"target_user_id":"photo-user-3", "requester_user_id":"photo-user-4"})
        request = created["request"]
        assert request["requester"]["id"] == "photo-user-2"
        assert request["status"] == "pending" and created["table_state"]["players"] == before["players"]
        assert (parse(request["expires_at"]) - parse(request["requested_at"])).total_seconds() == 60
        route = "/api/seat-swap-requests/" + request["id"]
        send(one, "POST", route + "/accept", {}, 403)
        send(outsider, "POST", route + "/decline", {}, 403)
        send(two, "POST", route + "/cancel", {}, 403)
        send(two, "POST", route + "/accept", {}, 403, {"Origin":url + ".evil.invalid"})
        visible = send(two, "GET", swaps)["requests"][0]
        assert visible["can_accept"] and visible["can_decline"] and not visible["can_cancel"]
        assert send(outsider, "GET", swaps)["requests"] == []
        accepted = send(two, "POST", route + "/accept", {})
        assert accepted["request"]["status"] == "accepted"
        players = accepted["table_state"]["players"]
        assert players["east"]["id"] == "photo-user-3" and players["south"]["id"] == "photo-user-2"
        assert send(two, "POST", route + "/accept", {})["table_state"]["players"] == players
        current = reminder()
        assert current["all_seated"]
        assert {p["name"]:p["seat"] for p in current["participants"]} == {"photo2":"south", "photo3":"east"}
        send(two, "POST", base + "/leave", {})
        assert not reminder()["all_seated"]
        assert next(p for p in reminder()["participants"] if p["name"] == "photo3")["seat"] is None
        send(one, "POST", "/api/table-reservations/" + reservation["id"], {"status":"cancelled", "version":reservation["version"]})
        assert send(one, "GET", base + "/reservation-reminders")["reminders"] == []
    finally:
        for session in sessions:
            session.close()


@pytest.mark.parametrize("method,path", [
    ("PUT", "/api/tables/web/seat-swap-requests"),
    ("GET", "/api/seat-swap-requests/example/accept"),
    ("PUT", "/api/seat-swap-requests/example/decline"),
    ("POST", "/api/club-tables/web/reservation-reminders"),
    ("POST", "/api/club-tables/web/reservation-default"),
])
def test_swap_reminder_proxy_methods_are_exact(website, method, path):
    url, _, _ = website
    response = requests.request(method, url + path, timeout=10)
    assert response.status_code == 405
