"""Session reservations through the real website auth/proxy, using isolated data."""
from datetime import datetime,timedelta,timezone
import requests
from test_web_score_bridge import website,login


def test_session_ranges_candidates_manual_table_ownership_and_edit_through_web(website):
    url,app,_=website
    one,two=login(url,2),login(url,3)
    def call(who,method,path,data=None,status=200):
        result=who.request(method,url+path,json=data,headers={"Origin":url},timeout=15)
        assert result.status_code==status,result.text
        return result.json()
    try:
        tables=call(one,"GET","/api/club-tables")["tables"]
        primary=next(t for t in tables if t["score_table_id"]=="web")["id"]
        other=next(t for t in tables if t["score_table_id"]=="A")["id"]
        start=datetime.now(timezone.utc)+timedelta(minutes=30)
        value=lambda minutes:(start+timedelta(minutes=minutes)).isoformat()
        first=call(one,"POST",f"/api/club-tables/{primary}/reservations",{
            "start_at":value(0),"end_at":value(60),"request_id":"first"})
        response=two.get(url+f"/api/club-tables/{other}/reservation-candidates",params={
            "start_at":value(20),"participant_ids":"photo-user-3"},timeout=15)
        assert response.status_code==200,response.text
        assert response.json()["default_table_id"]==primary
        assert response.json()["default_session_id"]==first["session_id"]
        manual=call(two,"POST",f"/api/club-tables/{other}/reservations",{
            "start_at":value(20),"end_at":value(100),"request_id":"manual-table"})
        assert manual["table_id"]==other and manual["session_id"]!=first["session_id"]
        second=call(two,"POST",f"/api/club-tables/{primary}/reservations",{
            "start_at":value(20),"end_at":value(90),"request_id":"second"})
        assert second["id"]!=first["id"] and second["session_id"]==first["session_id"]
        def reminders():return call(one,"GET","/api/club-tables/web/reservation-reminders")["reminders"]
        groups=reminders()
        assert len(groups)==1 and len(groups[0]["participants"])==2
        assert {p["name"] for p in groups[0]["participants"]}=={"photo2","photo3"}
        parse=lambda v:datetime.fromisoformat(v.replace("Z","+00:00"))
        assert abs((parse(groups[0]["start_at"])-start).total_seconds())<.001
        assert abs((parse(groups[0]["end_at"])-(start+timedelta(minutes=90))).total_seconds())<.001
        call(two,"POST","/api/table-reservations/"+first["id"],{"version":1,"status":"cancelled"},403)
        moved=call(two,"POST","/api/table-reservations/"+second["id"],{
            "version":1,"start_at":value(70),"end_at":value(150)})
        assert moved["session_id"]!=first["session_id"]
        group=reminders()[0]
        assert len(group["participants"])==1 and group["participants"][0]["name"]=="photo2"
        assert abs((parse(group["end_at"])-(start+timedelta(minutes=60))).total_seconds())<.001
        call(one,"POST","/api/table-reservations/"+first["id"],{"version":1,"status":"cancelled"})
        assert reminders()==[]
        invalid=call(one,"POST",f"/api/club-tables/{primary}/reservations",{
            "start_at":value(0),"end_at":value(-1),"request_id":"invalid-end"},409)
        assert invalid["detail"]["code"]=="invalid_reservation_end"
        assert requests.get(url+f"/api/club-tables/{primary}/reservation-candidates",timeout=15).status_code==401
        assert requests.post(url+f"/api/club-tables/{primary}/reservation-candidates",timeout=15).status_code==405
    finally:
        one.close();two.close()
