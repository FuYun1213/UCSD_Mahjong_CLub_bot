/* Shared dashboard components. Language comes only from the global header. */
function ClubLobby({language,profile,dashboard,onNavigate}) {
  const say=(en,cn)=>language==="CN"?cn:en;
  const [tables,setTables]=React.useState([]),[loaded,setLoaded]=React.useState(false),[error,setError]=React.useState("");
  const reading=React.useRef(null),live=React.useRef(false);
  async function load(force=false){
    if(!profile||!live.current)return;
    while(reading.current){if(!force)return reading.current;await reading.current;}
    const request=(async()=>{
      try{const data=await tournamentApi("/api/club-tables");if(live.current){setTables((data.tables||[]).filter(table=>!table.tournament_id&&table.status==="open"));setLoaded(true);setError("");}}
      catch(e){if(live.current)setError(e.message||"requestFailed");}
    })();
    reading.current=request;
    try{await request;}finally{reading.current=null;}
  }
  React.useEffect(()=>{live.current=true;load();const timer=setInterval(()=>{if(document.visibilityState==="visible")load();},10000);return()=>{live.current=false;clearInterval(timer);};},[profile?.id]);
  const seated=tables.find(table=>table.members.some(member=>member.user_id===String(profile?.id)));
  const reservations=tables.flatMap(table=>(table.reservations||[]).filter(row=>row.status==="active").map(row=>({...row,table})));
  const myReservation=reservations.find(row=>row.participants?.some(person=>String(person.id||person.user_id)===String(profile?.id)));
  const waiting=new Set(reservations.flatMap(row=>(row.participants||[]).filter(person=>person.remaining_games===null||person.remaining_games>0).map(person=>person.id||person.user_id))).size;
  const myTable=seated||myReservation?.table;
  return <div className="club-lobby" data-i18n-owned>
    <div className="club-page-heading"><div><p className="club-eyebrow">YOUR CLUB, YOUR TABLE.</p><h1>{say("Club lobby","今日大厅")}</h1><p>{say("Find your table, plan your next game, and record the result.","看看谁在桌上，约好下一局，记下今天的成绩。")}</p></div><button className="club-secondary-button" type="button" onClick={()=>onNavigate("matches")}>{say("Game history","查看对局记录")} →</button></div>
    <div className="club-lobby-top"><section className="club-hero"><span className="club-eyebrow">A SEAT AT THE TABLE.</span><h2>{say("Four players.","四个人，一张桌。 ")}<br/>{say("One more game.","下一局，在这里相遇。")}</h2><div className="club-hero-actions"><button type="button" onClick={()=>onNavigate("reservations")}>{say("Reserve a game","预约下一局")} →</button><button type="button" className="club-hero-secondary" onClick={()=>onNavigate("manual-score")}>{say("Manual score","手动登分")}</button></div><span className="club-hero-wind" aria-hidden="true">東</span></section>
      <section className="club-status-card"><p className="club-eyebrow">{say("YOUR NEXT MOVE","我的当前状态")}</p><h2>{seated?say("You're at Table "+seated.number,"你已入座 "+seated.number+" 桌"):myReservation?say("Your game is reserved","你的下一局已预约"):say("Ready for your next game?","准备好下一局了吗？")}</h2><p>{seated?say(seated.started_at?"Your game is underway.":"Seats are filling. You can help seat other members.",seated.started_at?"本局正在进行，可以从牌桌页面登分。":"正在等同伴入座，你也可以帮其他成员上桌。"):myReservation?reservationDisplay(myReservation,myReservation.table.timezone,language):say("Choose a table and arrival time to join the queue.","选择牌桌和到场时间，加入预约队列。")}</p><a className="club-text-link" href={myTable?"/?page=record&table="+encodeURIComponent(myTable.score_table_id):"/reservations"}>{myTable?say("Open my table","查看我的牌桌"):say("View reservations","查看预约与队列")} →</a></section>
    </div>
    <div className="club-lobby-stats"><div><span>{say("Open tables","开放牌桌")}</span><strong>{loaded?tables.length:"—"}</strong></div><div><span>{say("Games underway","正在对局")}</span><strong>{loaded?tables.filter(table=>table.started_at).length:"—"}</strong></div><div><span>{say("Members reserved","预约成员")}</span><strong>{loaded?waiting:"—"}</strong></div><div><span>{say("Club members","社团成员")}</span><strong>{dashboard?.stats?.member_count??"—"}</strong></div></div>
    <section className="club-live-tables"><div className="club-section-heading"><h2>{say("At the tables","牌桌动态")}</h2><a href="/reservations">{say("Reservations & queue","预约与队列")} →</a></div>
      {!loaded&&!error&&<p role="status">{say("Loading tables…","正在加载牌桌…")}</p>}
      {error&&<p role="alert">{mt(language,error)} <button type="button" className="club-text-link" onClick={load}>{say("Retry","重试")}</button></p>}
      {loaded&&!tables.length&&<p className="club-empty">{say("No open tables right now.","当前暂无开放牌桌。")}</p>}
      <div className="club-table-grid">{tables.map(table=><ClubLobbyTable key={table.id} table={table} profile={profile} language={language} reload={()=>load(true)}/>)}</div>
    </section>
  </div>;
}
function ClubLobbyTable({table,profile,language,reload}) {
  const say=(en,cn)=>language==="CN"?cn:en,t=(key,values)=>mt(language,key,values),{busy,message,run,setMessage}=useTableAction(language,reload);
  const self=table.members.find(member=>member.user_id===String(profile?.id));
  const [modal,setModal]=React.useState(null),[swaps,setSwaps]=React.useState([]),[now,setNow]=React.useState(Date.now());
  const clockOffset=React.useRef(0),trigger=React.useRef(null);
  const locked=Boolean(table.started_at||table.pending_match_id);
  const pending=swaps.find(request=>request.status==="pending"&&Date.parse(request.expires_at)>now+clockOffset.current);
  const incoming=pending?.can_accept,pendingName=incoming?pending?.requester.name:pending?.target.name;
  function updateSwaps(data){if(data.server_now)clockOffset.current=Date.parse(data.server_now)-Date.now();if(data.requests)setSwaps(data.requests);else if(data.request)setSwaps(old=>[data.request,...old.filter(request=>request.id!==data.request.id)]);}
  React.useEffect(()=>{
    if(!self){setSwaps([]);return;}
    let active=true,reading=false;
    async function poll(){
      if(reading||document.visibilityState!=="visible")return;reading=true;
      try{const data=await tournamentApi("/api/tables/"+encodeURIComponent(table.score_table_id)+"/seat-swap-requests");if(active){updateSwaps(data);await reload();}}catch{}finally{reading=false;}
    }
    poll();const timer=setInterval(poll,5000),tick=setInterval(()=>setNow(Date.now()),1000);
    return()=>{active=false;clearInterval(timer);clearInterval(tick);};
  },[table.id,table.current_match_id,self?.user_id]);
  React.useEffect(()=>{
    if(!modal||busy)return;
    if(modal.mode==="incoming"){
      const request=swaps.find(row=>row.id===modal.request.id);
      if(!request||request.status!=="pending"||Date.parse(request.expires_at)<=now+clockOffset.current)setModal(null);
    }else if(!table.members.some(member=>member.user_id===modal.target.user_id&&member.seat===modal.target.seat)||modal.matchId!==table.current_match_id)setModal(null);
  },[table.members,table.current_match_id,swaps,now,busy,modal]);
  function close(){if(!busy){setModal(null);requestAnimationFrame(()=>trigger.current?.focus());}}
  function join(seat){
    if(!profile){tableLoginReturn();return;}
    run(async()=>{
      try{
        const response=await fetch("/api/club-tables/"+encodeURIComponent(table.id)+"/my-seat",{method:"PUT",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({seat,match_id:table.current_match_id})});
        if(response.status===401){location.assign(globalLoginUrl());throw new Error("requestFailed");}
        const data=await response.json();
        if(!response.ok){const code=data.detail?.code;throw new Error(Object.prototype.hasOwnProperty.call(MahjongI18n.entries,code)?code:"requestFailed");}
        return data;
      }catch(error){await reload();throw new Error(Object.prototype.hasOwnProperty.call(MahjongI18n.entries,error.message)?error.message:"requestFailed");}
    },"joinedTable");
  }
  function leave(){
    if(table.started_at){
      if(!window.confirm(t("flowCancelGameConfirm")))return;
      const key="mahjong-cancel-game:"+table.score_table_id+":"+table.current_match_id;
      const request_id=sessionStorage.getItem(key)||MahjongI18n.key();sessionStorage.setItem(key,request_id);
      run(async()=>{const result=await tournamentApi("/api/club-tables/"+table.id+"/cancel-game",{match_id:table.current_match_id,request_id,reason:"wrong_players"});sessionStorage.removeItem(key);return result;},"flowCancelGameSaved");
    }else run(()=>tournamentApi("/api/club-tables/"+table.id+"/leave",{match_id:table.current_match_id,reason:"seat_card"}),"pSeatLeft");
  }
  function act(member,event){if(!profile){tableLoginReturn();return;}trigger.current=event.currentTarget;setMessage("");if(member.user_id===String(profile.id))leave();else setModal({mode:"action",target:member,matchId:table.current_match_id});}
  function remove(){
    const member=modal.target;if(!window.confirm(t("seatActionConfirm",{name:member.name,seat:t("seat_"+member.seat)})))return;
    run(async()=>{const result=await tournamentApi("/api/club-tables/"+table.id+"/seats/"+encodeURIComponent(member.user_id)+"/remove",{match_id:modal.matchId,seat:member.seat});setModal(null);return result;},"seatActionRemoved");
  }
  function sendSwap(){run(async()=>{const result=await tournamentApi("/api/tables/"+encodeURIComponent(table.score_table_id)+"/seat-swap-requests",{target_user_id:modal.target.user_id,match_id:modal.matchId});updateSwaps(result);setModal(null);return result;},"localSaved");}
  function respond(action){run(async()=>{const result=await tournamentApi("/api/seat-swap-requests/"+encodeURIComponent(modal.request.id)+"/"+action,{});updateSwaps(result);setModal(null);return result;},action==="accept"?"swapAccepted":"swapDeclined");}
  const request=modal?.mode==="incoming"?modal.request:modal?.mode==="swap"&&self?{requester:{name:self.name,seat:self.seat},target:{name:modal.target.name,seat:modal.target.seat}}:null;
  const latest=swaps[0],statusKey={accepted:"swapAccepted",declined:"swapDeclined",expired:"swapExpired",cancelled:"swapCancelled",invalidated:"swapInvalidated"}[latest?.status==="pending"&&!pending?"expired":latest?.status];
  return <article data-club-table={table.id} className="club-table-card">
    <div className="club-table-title"><h3>{mt(language,"tableNumber",{number:table.number})}</h3><span className={"club-badge "+(table.started_at?"club-badge-live":"")}>{table.started_at?say("In progress","对局中"):say("Forming","等待入座")}</span></div>
    {table.display_name&&<p className="club-table-description">{table.display_name}</p>}
    <TableSeatList members={table.members} language={language} onJoin={join} onAction={act} currentUserId={profile?.id} disabled={busy} joinDisabled={locked||table.player_count>=table.capacity} started={Boolean(table.started_at)}/>
    <div className="club-table-actions"><a className="club-primary-button" href={"/?page=record&table="+encodeURIComponent(table.score_table_id)}>{say("Open table","查看牌桌")} →</a><a className="club-secondary-button" href={"/manual-score?table="+encodeURIComponent(table.id)}>{say("Enter scores","登分")}</a></div>
    {message&&<p className="club-table-message" role="status">{mt(language,message)}</p>}
    {pending?<div className="club-table-message" data-lobby-swap-status role="status"><p>{t(incoming?"swapIncoming":"swapPending",{name:pendingName})} {t("swapCountdown",{seconds:Math.max(0,Math.ceil((Date.parse(pending.expires_at)-now-clockOffset.current)/1000))})}</p>{incoming&&<button type="button" className="club-secondary-button" disabled={busy} onClick={event=>{trigger.current=event.currentTarget;setMessage("");setModal({mode:"incoming",request:pending});}}>{t("swapReceiveTitle")}</button>}</div>:statusKey&&<p className="club-table-message" data-lobby-swap-status role="status">{t(statusKey)}</p>}
    {modal&&<ClubSeatDialog busy={busy} close={close}>
      <h2>{t(modal.mode==="action"?"seatActionTitle":modal.mode==="incoming"?"swapReceiveTitle":"swapConfirmTitle")}</h2>
      {modal.mode==="action"?<><p>{modal.target.name} · {t("seat_"+modal.target.seat)}</p><div className="club-dialog-actions"><button type="button" className="club-primary-button" data-lobby-swap disabled={busy||!self||locked||Boolean(pending)} onClick={()=>setModal({...modal,mode:"swap"})}>{t("seatActionSwap")}</button><button type="button" className="club-secondary-button" data-lobby-remove disabled={busy||locked} onClick={remove}>{t("seatActionRemove")}</button></div>{locked?<p>{t("seatActionStartedPending")}</p>:!self&&<p>{t("must_join_first")}</p>}</>:<><p>{t(modal.mode==="incoming"?"swapReceiveNote":"swapConfirmNote",{name:request?.requester.name})}</p>{request&&[request.requester,request.target].map((person,index)=><p key={index}>{t("swapSeatChange",{name:person.name,from:t("seat_"+person.seat),to:t("seat_"+(index?request.requester.seat:request.target.seat))})}</p>)}<div className="club-dialog-actions">{modal.mode==="incoming"?<><button type="button" className="club-primary-button" disabled={busy||!incoming} onClick={()=>respond("accept")}>{t("swapAccept")}</button><button type="button" className="club-secondary-button" disabled={busy} onClick={()=>respond("decline")}>{t("swapDecline")}</button></>:<button type="button" className="club-primary-button" disabled={busy||locked||!self} onClick={sendSwap}>{t("swapSend")}</button>}</div></>}
      {message&&<p role="alert">{mt(language,message)}</p>}<button type="button" className="club-secondary-button" disabled={busy} onClick={close}>{say("Close","关闭")}</button>
    </ClubSeatDialog>}
  </article>;
}
function ClubSeatDialog({busy,close,children}){
  const dialog=React.useRef(null),id=React.useId();
  React.useEffect(()=>{dialog.current.showModal();return()=>dialog.current?.close();},[]);
  React.useEffect(()=>{const title=dialog.current?.querySelector("h2");if(title)title.id=id;},[children,id]);
  return <dialog ref={dialog} className="club-seat-dialog" aria-labelledby={id} aria-busy={busy} onCancel={event=>{event.preventDefault();close();}}>{children}</dialog>;
}
function TournamentTimeLimit({value,onChange,language}) {
  const t=k=>mt(language,k),limited=value!==null;
  return <div className="my-3 grid gap-3 sm:grid-cols-2">
    <TournamentField label={t("timeMode")}><select aria-label={t("timeMode")} className={inputStyle} value={limited?"limited":"unlimited"} onChange={e=>onChange(e.target.value==="unlimited"?null:"")}>
      <option value="unlimited">{t("noTimeLimit")}</option><option value="limited">{t("limitedTime")}</option>
    </select></TournamentField>
    {limited&&<TournamentField label={t("durationMinutes")}><input aria-label={t("durationMinutes")} className={inputStyle} type="number" min="0.0166666667" max="10080" step="any" value={value===""?"":Number(value)/60} onChange={e=>onChange(e.target.value===""?"":Math.round(Number(e.target.value)*60))}/></TournamentField>}
  </div>;
}
function TournamentDeleteControl({item,language,onDeleted}) {
  const t=k=>mt(language,k),[name,setName]=React.useState(""),[reason,setReason]=React.useState(""),[message,setMessage]=React.useState(""),[busy,setBusy]=React.useState(false),pending=React.useRef(false);
  return <details className="my-4 rounded-xl border border-red-200 p-3"><summary className="font-bold text-red-800">{t("deleteTournament")}</summary>
    <p className="my-3">{mt(language,"deleteTournamentNote",{name:item.name})}</p>
    <TournamentField label={t("confirmTournamentName")}><input aria-label={t("confirmTournamentName")} className={inputStyle} value={name} onChange={e=>setName(e.target.value)}/></TournamentField>
    <TournamentField label={t("deleteReason")}><input aria-label={t("deleteReason")} className={inputStyle} value={reason} onChange={e=>setReason(e.target.value)}/></TournamentField>
    <TournamentButton disabled={busy||name.trim()!==item.name||!reason.trim()} onClick={async()=>{
      if(pending.current||!window.confirm(mt(language,"deleteAgain",{name:item.name})))return;pending.current=true;setBusy(true);
      try{await tournamentApi("/api/tournaments/"+item.id+"/delete",{request_id:MahjongI18n.key(),version:item.version,confirm_name:name,reason});setMessage("deletedSuccess");onDeleted();}
      catch(e){setMessage(e.message);}finally{pending.current=false;setBusy(false);}
    }}>{t("deleteTournament")}</TournamentButton>{message&&<p role="status">{t(message)}</p>}
  </details>;
}
function useTableAction(language,onUpdated) {
  const [message,setMessage]=React.useState(""),[busy,setBusy]=React.useState(false),pending=React.useRef(false);
  async function run(fn,success="localSaved") {
    if(pending.current)return null;pending.current=true;setBusy(true);setMessage("");
    try{const result=await fn();setMessage(success);if(onUpdated)await onUpdated();return result;}
    catch(e){setMessage(e.message||"requestFailed");return null;}
    finally{pending.current=false;setBusy(false);}
  }
  return {message,busy,run,setMessage};
}
const CLUB_SEATS = ["east","south","west","north"];
function tableReservationHref(table) {return "/reservations"+(table?"?table="+encodeURIComponent(table.id):"");}
function tableLoginReturn() {location.assign("/login?redirect_url="+encodeURIComponent(location.pathname+location.search+location.hash));}
function reservationDateParts(reservation,timezone) {
  return ReservationTime.dateParts(reservation,timezone);
}
function reservationDisplay(reservation,timezone,language) {
  const parts=reservationDateParts(reservation,timezone);
  const format=p=>mt(language,"reservationDateDisplay",{month:String(p.month).padStart(2,"0"),day:String(p.day).padStart(2,"0"),time:p.time});
  return format(parts);
}
function selectedRegisteredUsers(values) {
  return [...new Map(values.filter(person=>person&&person.id&&person.name).map(person=>[String(person.id),person])).values()];
}
function ReservationParticipants({values,onChange,capacity,language,disabled}) {
  const t=k=>mt(language,k),selected=selectedRegisteredUsers(values);
  return <fieldset className="sm:col-span-2" disabled={disabled}><legend className="mb-2 font-semibold">{t("reservationParticipants")} ({selected.length}/{capacity})</legend>
    <p className="mb-2 text-sm text-zinc-600">{t("registeredNameParticipantsHelp")}</p>
    <div className="space-y-3">{values.map((value,index)=><div key={index} className="rounded-lg border border-zinc-200 p-3">
      <RegisteredUserCombobox value={value} onChange={person=>onChange(values.map((previous,i)=>i===index?person:previous))} language={language} label={mt(language,"registeredNameParticipant",{number:index+1})} disabled={disabled} required excludeIds={selected.filter(person=>person.id!==value?.id).map(person=>person.id)}/>
      <TournamentButton aria-label={mt(language,"removeParticipantNumber",{number:index+1})} disabled={disabled} onClick={()=>onChange(values.length>1?values.filter((_,i)=>i!==index):[null])}>{t("removeSelection")}</TournamentButton>
    </div>)}</div>
    <div className="my-2"><TournamentButton disabled={disabled||values.length>=capacity} onClick={()=>onChange([...values,null])}>{t("registeredNameAddParticipant")}</TournamentButton></div>
  </fieldset>;
}
function ReservationEditor({table,profile,language,reservation,onSaved,onCancel,onAutoSelect,tableWasChosen=false}) {
  const t=k=>mt(language,k),[date,setDate]=React.useState(()=>ReservationTime.create(reservation,table.timezone)),[note,setNote]=React.useState(reservation?.note||""),[plannedGames,setPlannedGames]=React.useState(()=>reservation?.planned_games==="any"?"any":Number.isInteger(reservation?.planned_games)?String(reservation.planned_games):reservation?"":"1");
  const {month,day,time}=date,editDate=(field,value)=>setDate(previous=>ReservationTime.editDate(previous,field,value));
  const [participants,setParticipants]=React.useState(reservation?(reservation.participants||[]).map(p=>({id:String(p.id||p.user_id),name:p.name||mt(language,"registeredNameUnknown"),avatar:p.avatar||""})):[profile?.id?{id:String(profile.id),name:profile.name,avatar:profile.avatar||""}:null]);
  const {busy,message,run,setMessage}=useTableAction(language),key=React.useRef(MahjongI18n.key()),[nearby,setNearby]=React.useState(null),[resolving,setResolving]=React.useState(false),[resolveFailed,setResolveFailed]=React.useState(false),[resolveAttempt,setResolveAttempt]=React.useState(0);
  const selected=selectedRegisteredUsers(participants),participantKey=selected.map(person=>person.id).join(",");
  React.useEffect(()=>{
    if(reservation)return;
    let active=true;
    tournamentApi("/api/club-tables/"+encodeURIComponent(table.id)+"/reservation-default")
      .then(value=>{if(active)setDate(previous=>ReservationTime.applyDefault(previous,value));})
      .catch(error=>{if(active)setMessage(error.message||"requestFailed");});
    return()=>{active=false;};
  },[table.id,reservation?.id]);
  React.useEffect(()=>{
    if(!month||!day||!/^\d{2}:\d{2}$/.test(time)||!participantKey){setResolving(false);setResolveFailed(false);return;}
    let active=true;setResolving(true);setResolveFailed(false);
    const timer=setTimeout(async()=>{
      try{
        const query=new URLSearchParams({...ReservationTime.startPayload(date),participant_ids:participantKey});
        if(date.reference_start)query.set("reference_start",date.reference_start);
        const result=await tournamentApi("/api/club-tables/"+encodeURIComponent(table.id)+"/reservation-candidates?"+query);
        if(!active)return;
        setDate(previous=>ReservationTime.applyResolved(previous,result,date.revision));setMessage("");
        const candidate=result.candidates?.find(item=>item.id===result.default_session_id)||result.candidates?.[0]||null;
        setNearby(candidate);
        if(!reservation&&!tableWasChosen&&candidate&&onAutoSelect)onAutoSelect(candidate.table_id);
      }catch(error){if(active){setNearby(null);setResolveFailed(true);setMessage(error.message||"requestFailed");}}
      finally{if(active)setResolving(false);}
    },250);
    return()=>{active=false;clearTimeout(timer);};
  },[table.id,month,day,time,date.revision,participantKey,tableWasChosen,reservation?.id,resolveAttempt]);
  const submit=event=>{event.preventDefault();if(!profile){tableLoginReturn();return;}if(resolving||!date.start_at){setMessage("reservationResolveRequired");return;}run(async()=>{
    if(!Number.isInteger(Number(month))||Number(month)<1||Number(month)>12||!Number.isInteger(Number(day))||Number(day)<1||Number(day)>31||!/^\d{2}:\d{2}$/.test(time))throw new Error("invalid_reservation_time");
    if(plannedGames!=="any"&&(!/^[1-9]\d*$/.test(plannedGames)||!Number.isSafeInteger(Number(plannedGames))))throw new Error("invalid_planned_games");
    if(!selected.length||selected.length!==participants.length)throw new Error("registeredNameSelectRequired");if(selected.length>table.capacity)throw new Error("reservation_capacity_exceeded");
    const payload={...ReservationTime.startPayload(date),planned_games:plannedGames==="any"?"any":Number(plannedGames),participant_ids:selected.map(person=>String(person.id)),note};
    const saved=await tournamentApi(reservation?"/api/table-reservations/"+reservation.id:"/api/club-tables/"+table.id+"/reservations",{...payload,...(reservation?{version:reservation.version,table_id:table.id}:{request_id:key.current})});
    await onSaved(saved);
  },"reservationSaved");};
  return <form data-reservation-form className="my-4 grid gap-3 sm:grid-cols-2" onSubmit={submit}><h3 className="font-bold sm:col-span-2">{t(reservation?"editReservation":"reserveTable")}</h3>
    <p className="text-sm text-zinc-600 sm:col-span-2">{mt(language,"inputTimezone",{timezone:table.timezone})}</p>
    <fieldset className="sm:col-span-2" data-reservation-time="start"><legend className="mb-2 font-semibold">{t("reservationStart")}</legend><div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {["month","day","time"].map(field=>{const label={month:"reservationMonth",day:"reservationDay",time:"reservationClock"}[field];return <div key={field} className={field==="time"?"col-span-2 sm:col-span-1":""}><TournamentField label={t(label)}><input aria-label={t(label)} className={inputStyle} type={field==="time"?"time":"number"} inputMode={field==="time"?undefined:"numeric"} min={field==="time"?undefined:"1"} max={field==="month"?"12":field==="day"?"31":undefined} required value={date[field]} onChange={e=>editDate(field,e.target.value)}/></TournamentField></div>;})}
    </div></fieldset>
    <div className="sm:col-span-2"><TournamentField label={t("reservationGameMode")}><select className={inputStyle} value={plannedGames==="any"?"any":"number"} onChange={e=>setPlannedGames(e.target.value==="any"?"any":plannedGames==="any"?"1":plannedGames)}><option value="number">{t("reservationFiniteGames")}</option><option value="any">{t("reservationAnyGames")}</option></select></TournamentField>{plannedGames!=="any"&&<TournamentField label={t("reservationPlannedGames")}><input className={inputStyle} type="number" min="1" step="1" required value={plannedGames} onChange={e=>setPlannedGames(e.target.value)}/></TournamentField>}<p className="mt-1 text-xs text-zinc-600">{t("reservationPlannedGamesHelp")}</p></div>
    {nearby&&!reservation&&<p data-reservation-nearby className="rounded-lg bg-amber-50 p-3 text-sm sm:col-span-2">{tableWasChosen?t("reservationNearbyRespect"):mt(language,"reservationNearbySelected",{table:nearby.table_number})}</p>}
    {reservation&&<p className="text-xs text-zinc-600 sm:col-span-2">{t("reservationKeepYear")}</p>}
    <ReservationParticipants values={participants.length?participants:[null]} onChange={setParticipants} capacity={table.capacity} language={language} disabled={busy}/>
    <div className="sm:col-span-2"><TournamentField label={t("reservationNote")}><input aria-label={t("reservationNote")} className={inputStyle} value={note} maxLength={500} onChange={e=>setNote(e.target.value)}/></TournamentField></div>
    <div className="flex flex-wrap gap-2 sm:col-span-2"><button data-reservation-submit className={buttonStyle} disabled={busy||resolving||!date.start_at||!month||!day||!time||!plannedGames||!selected.length||selected.length!==participants.length||participants.length>table.capacity}>{t(reservation?"saveReservation":"reserveTable")}</button>{reservation&&<TournamentButton disabled={busy} onClick={onCancel}>{t("cancelReservationEdit")}</TournamentButton>}</div>
    {resolving&&<p className="text-xs text-zinc-500 sm:col-span-2" role="status">{t("reservationResolving")}</p>}
    {resolveFailed&&<div className="sm:col-span-2"><TournamentButton disabled={busy||resolving} onClick={()=>setResolveAttempt(value=>value+1)}>{t("reservationRetryTimes")}</TournamentButton></div>}
    {message&&<p role="status" className="text-sm sm:col-span-2">{t(message==="stale_version"?"reservation_stale_version":message)}</p>}
  </form>;
}
function ReservationPeople({people,language}) {
  return <span className="inline-flex flex-wrap items-center gap-x-4 gap-y-2">{(people||[]).map(person=><span key={person.id||person.user_id} className="inline-flex items-center gap-2"><AccountAvatars.Avatar name={person.name} src={person.avatar} size={24} decorative/>{person.name||mt(language,"registeredNameUnknown")}</span>)}</span>;
}
function ReservationQueue({table,language,revision=0}) {
  const t=k=>mt(language,k),[queue,setQueue]=React.useState(null),[message,setMessage]=React.useState(""),[busy,setBusy]=React.useState(false);
  const [preview,setPreview]=React.useState(null),[dragging,setDragging]=React.useState("");
  const drag=React.useRef(null);
  const load=async()=>{try{const result=await tournamentApi("/api/club-tables/"+encodeURIComponent(table.id)+"/queue");setQueue(result);setMessage("");}catch(error){setMessage(error.message||"requestFailed");}};
  React.useEffect(()=>{let active=true;const refresh=async()=>{if(drag.current)return;try{const result=await tournamentApi("/api/club-tables/"+encodeURIComponent(table.id)+"/queue");if(active){setQueue(result);setMessage("");}}catch(error){if(active)setMessage(error.message||"requestFailed");}};refresh();const timer=setInterval(refresh,10000);return()=>{active=false;clearInterval(timer);if(drag.current){clearTimeout(drag.current.timer);drag.current.touchCleanup?.();if(drag.current.origin.hasPointerCapture?.(drag.current.pointerId))drag.current.origin.releasePointerCapture(drag.current.pointerId);}drag.current=null;};},[table.id,revision]);
  const batch=queue?.next_batch,waiting=queue?.waiting||[],reorderable=queue?.ordered_keys||[];
  const entries=new Map([...(batch?.status==="started"?[]:batch?.participants||[]),...waiting].filter(person=>person?.key).map(person=>[person.key,person]));
  const displayTime=value=>value?new Intl.DateTimeFormat(language==="CN"?"zh-CN":"en-US",{timeZone:table.timezone,dateStyle:"medium",timeStyle:"short"}).format(new Date(value)):t("queueTimeUnknown");
  const remaining=person=>person.planned_games==="any"||person.remaining_games==="any"?t("reservationAnyGames"):Number.isInteger(person.remaining_games)?mt(language,"queueRemaining",{count:person.remaining_games}):Number.isInteger(person.remaining_games_snapshot)?mt(language,"queueRemaining",{count:person.remaining_games_snapshot}):t("queueNeedsAssignment");
  const saveOrder=async ordered_keys=>{if(busy||!queue||ordered_keys.join("|")===reorderable.join("|"))return;setBusy(true);setMessage("");try{const result=await tournamentApi("/api/club-tables/"+encodeURIComponent(table.id)+"/queue/reorder",{version:queue.version,ordered_keys,request_id:MahjongI18n.key()});setQueue(result);setMessage("queueSaved");}catch(error){await load();setMessage(error.message==="stale_version"?"queue_stale_version":error.message||"requestFailed");}finally{setBusy(false);}};
  function endDrag(state,cancel=false){
    if(drag.current!==state)return;
    clearTimeout(state.timer);state.touchCleanup?.();drag.current=null;setDragging("");setPreview(null);
    if(state.origin.hasPointerCapture?.(state.pointerId))state.origin.releasePointerCapture(state.pointerId);
    if(state.active&&!cancel)saveOrder(state.order);
  }
  function cancelPendingDrag(state){
    if(drag.current!==state)return;
    clearTimeout(state.timer);state.touchCleanup?.();drag.current=null;
  }
  function movePreview(state,x,y){
    const target=state.origin.ownerDocument.elementFromPoint(x,y)?.closest("[data-queue-item]");
    const targetKey=target?.dataset.queuePerson,from=state.order.indexOf(state.key),to=state.order.indexOf(targetKey);
    if(from<0||to<0||from===to)return;
    state.order.splice(from,1);state.order.splice(to,0,state.key);setPreview([...state.order]);
  }
  function dragStart(event,key){
    if(busy||!queue?.can_reorder||!reorderable.includes(key)||event.pointerType==="mouse"&&event.button!==0)return;
    if(drag.current?.timer)clearTimeout(drag.current.timer);
    const pointerId=event.pointerId,origin=event.currentTarget,touch=event.pointerType==="touch";
    const state={key,pointerId,origin,startX:event.clientX,startY:event.clientY,active:false,order:[...reorderable],timer:null,touch,touchId:null,touchCleanup:null};
    drag.current=state;
    if(!touch)origin.setPointerCapture(pointerId);
    if(touch){
      const doc=origin.ownerDocument;
      const touchPoint=changed=>Array.from(changed||[]).find(point=>state.touchId===null||point.identifier===state.touchId);
      const move=moveEvent=>{
        if(drag.current!==state)return;
        const point=touchPoint(moveEvent.changedTouches);if(!point)return;
        if(state.touchId===null)state.touchId=point.identifier;
        if(!state.active){if(Math.hypot(point.clientX-state.startX,point.clientY-state.startY)>14)cancelPendingDrag(state);return;}
        moveEvent.preventDefault();movePreview(state,point.clientX,point.clientY);
      };
      const finish=finishEvent=>{
        if(drag.current!==state)return;
        const point=touchPoint(finishEvent.changedTouches);if(!point)return;
        if(state.touchId===null)state.touchId=point.identifier;
        endDrag(state,finishEvent.type==="touchcancel");
      };
      doc.addEventListener("touchmove",move,{passive:false});
      doc.addEventListener("touchend",finish,{passive:true});
      doc.addEventListener("touchcancel",finish,{passive:true});
      state.touchCleanup=()=>{doc.removeEventListener("touchmove",move);doc.removeEventListener("touchend",finish);doc.removeEventListener("touchcancel",finish);};
    }
    state.timer=setTimeout(()=>{
      if(drag.current!==state)return;
      state.active=true;setDragging(key);setPreview([...state.order]);
      if(touch&&!origin.hasPointerCapture?.(pointerId))try{origin.setPointerCapture(pointerId);}catch{}
    },600);
  }
  function dragMove(event){
    const state=drag.current;if(!state||state.pointerId!==event.pointerId||state.touch)return;
    if(!state.active){if(Math.hypot(event.clientX-state.startX,event.clientY-state.startY)>14)cancelPendingDrag(state);return;}
    event.preventDefault();
    movePreview(state,event.clientX,event.clientY);
  }
  function dragEnd(event,cancel=false){
    const state=drag.current;if(!state||state.pointerId!==event.pointerId)return;
    endDrag(state,cancel);
  }
  function keyboardMove(event,key){
    if(!["ArrowUp","ArrowDown"].includes(event.key))return;
    event.preventDefault();const from=reorderable.indexOf(key),to=from+(event.key==="ArrowUp"?-1:1);
    if(busy||from<0||to<0||to>=reorderable.length)return;
    const ordered_keys=[...reorderable];[ordered_keys[from],ordered_keys[to]]=[ordered_keys[to],ordered_keys[from]];saveOrder(ordered_keys);
  }
  const batchCount=batch?.status==="started"?0:(batch?.participants||[]).length;
  const shownOrder=preview||reorderable;
  const orderedPeople=shownOrder.map(key=>entries.get(key)).filter(Boolean);
  const shownBatch=preview?orderedPeople.slice(0,batchCount):(batch?.participants||[]);
  const shownWaiting=preview?orderedPeople.slice(batchCount):waiting;
  const personRow=person=><li key={person.key||person.user_id} className={"flex items-center justify-between gap-2 rounded-lg border bg-white p-2 "+(dragging===person.key?"border-emerald-700 shadow-md":"border-zinc-200")} data-queue-item data-queue-person={person.key}><span className="min-w-0"><strong>{person.name||person.user_name}</strong><small className="ml-2 text-zinc-600">{remaining(person)}</small></span>{queue?.can_reorder&&reorderable.includes(person.key)&&<button type="button" data-queue-drag-handle className="shrink-0 select-none rounded border px-3 py-1 text-lg leading-none disabled:opacity-40" style={{touchAction:"pan-y",WebkitTouchCallout:"none"}} disabled={busy} aria-label={mt(language,"queueDragHandle",{name:person.name||person.user_name})} onContextMenu={event=>event.preventDefault()} onPointerDown={event=>dragStart(event,person.key)} onPointerMove={dragMove} onPointerUp={dragEnd} onPointerCancel={event=>dragEnd(event,true)} onKeyDown={event=>keyboardMove(event,person.key)}>⠿</button>}</li>;
  return <section data-reservation-queue className="my-4 rounded-xl border border-amber-200 bg-amber-50 p-4"><h3 className="text-lg font-bold">{t("queueNextTable")} · {mt(language,"tableNumber",{number:table.number})}</h3>
    {queue?.can_reorder&&reorderable.length>1&&<p className="mt-1 text-sm text-zinc-700">{t("queueDragHint")}</p>}
    {batch?<><p className="mt-1 text-sm">{t("queueEstimatedStart")}: <strong>{displayTime(batch.prediction_source==="needs_configuration"?null:batch.estimated_start_at)}</strong> · {t("queueStatus_"+batch.status)}</p><ol className="mt-3 grid gap-2">{shownBatch.map(personRow)}</ol>{batch.prediction_source==="needs_configuration"&&<p className="mt-2 text-sm text-zinc-700">{t("queueNoDuration")}</p>}{batch.suggested_start_at&&batch.missing_players>0&&<p className="mt-2 text-sm text-zinc-700">{mt(language,"queueSuggestedArrival",{time:displayTime(batch.suggested_start_at)})}</p>}{batch.missing_players>0&&<p className="mt-2 text-sm font-semibold text-amber-900">{mt(language,batch.missing_players===1?"queueMissingOne":"queueMissing",{count:batch.missing_players})}</p>}</>:<p className="mt-2 text-sm">{t("queueNoBatch")}</p>}
    <h4 className="mt-5 font-semibold">{t("queueWaiting")}</h4>{shownWaiting.length?<ol className="mt-2 grid gap-2">{shownWaiting.map(personRow)}</ol>:<p className="mt-1 text-sm text-zinc-600">{t("queueNoWaiting")}</p>}
    {message&&<p className="mt-2 text-sm" role="status">{t(message)}</p>}
  </section>;
}
function ReservationSessionGroups({table,language,renderReservation,expanded=false}) {
  const t=k=>mt(language,k),sessions=(table.reservation_sessions||[]).filter(session=>session.status==="active"&&(session.participants||[]).length);
  return <div data-reservation-sessions className="my-3 space-y-3">{sessions.map(session=>{
    const rows=(session.reservations||((table.reservations||[]).filter(item=>item.session_id===session.id))).filter(item=>item.status==="active");
    return <article data-reservation-session={session.id} key={session.id} className="rounded-xl border border-zinc-200 p-3 text-sm">
      <p className="font-bold">{t("reservationSession")} · {reservationDisplay(session,table.timezone,language)}</p>
      <div className="mt-2"><ReservationPeople people={session.participants} language={language}/></div>
      <details open={expanded} className="mt-3"><summary className="cursor-pointer text-zinc-600">{t("reservationPersonalDetails")} ({rows.length})</summary><ul className="mt-2 space-y-2">{rows.map(renderReservation)}</ul></details>
    </article>;
  })}<ul className="space-y-2">{(!sessions.length?(table.reservations||[]).filter(item=>item.status==="active"):(table.reservations||[]).filter(item=>item.status==="active"&&!item.session_id)).map(renderReservation)}</ul></div>;
}
function TableReservations({table,profile,language,reload,adminMode=false,onAutoSelect,tableWasChosen=false}) {
  const t=k=>mt(language,k),[editing,setEditing]=React.useState(null),[generation,setGeneration]=React.useState(0),[queueRevision,setQueueRevision]=React.useState(0),{busy,message,run,setMessage}=useTableAction(language,reload);
  const saved=async()=>{setEditing(null);setGeneration(g=>g+1);setQueueRevision(g=>g+1);setMessage("reservationSaved");await reload();};
  const record=r=><li key={r.id} className="rounded-lg border border-zinc-200 p-3 text-sm" data-reservation-id={r.id}>
    <p className="font-bold">{reservationDisplay(r,table.timezone,language)} · {t("reservation_"+r.status)}</p>
    <p className="mt-1">{t("reservationCreator")}: {r.user_name||r.creator_name||t("registeredNameUnknown")}</p>
    {r.plan_status==="legacy_unknown"&&<p className="mt-1 text-amber-800">{t("reservationLegacyNeedsAssignment")}</p>}
    {r.plan_status!=="legacy_unknown"&&<p className="mt-1">{t("reservationPlannedGames")}: {r.planned_games==="any"?t("reservationAnyGames"):r.planned_games}</p>}
    <div className="mt-1 break-words">{t("reservationParticipants")}: <ReservationPeople people={r.participants} language={language}/></div>
    {r.note&&<p className="mt-1 break-words">{t("reservationNote")}: {r.note}</p>}
    {r.status==="active"&&(adminMode||String(r.created_by||r.user_id)===String(profile?.id))&&<div className="mt-2 flex flex-wrap gap-2">
      <TournamentButton disabled={busy} onClick={()=>setEditing(r)}>{t("editReservation")}</TournamentButton>
      <TournamentButton disabled={busy} onClick={()=>run(async()=>{const result=await tournamentApi("/api/table-reservations/"+r.id,{status:"cancelled",version:r.version});setQueueRevision(g=>g+1);return result;},"reservationCancelled")}>{t("cancelReservation")}</TournamentButton>
    </div>}
  </li>;
  return <div className="my-4"><h3 className="font-bold">{mt(language,"tableNumber",{number:table.number})}{table.display_name&&" · "+table.display_name}</h3>
    <p className="text-xs">{mt(language,"displayTimezone",{timezone:table.timezone})}</p>
    <ReservationQueue table={table} language={language} revision={queueRevision}/>
    <ReservationSessionGroups table={table} language={language} renderReservation={record} expanded/>
    {!(table.reservations||[]).some(item=>item.status==="active")&&<p className="text-sm text-zinc-500">{t("noReservations")}</p>}
    {(table.reservation_history||[]).length>0&&<details className="mt-4"><summary className="cursor-pointer font-semibold">{t("reservationHistory")}</summary><ul className="mt-2 space-y-2">{(table.reservation_history||[]).map(record)}</ul></details>}
    {message&&<p role="status" className="my-2 text-sm">{t(message==="stale_version"?"reservation_stale_version":message)}</p>}
    {profile&&table.status==="open"&&<ReservationEditor key={(editing?.id||"create")+"-"+generation} table={table} profile={profile} language={language} reservation={editing} onSaved={saved} onCancel={()=>setEditing(null)} onAutoSelect={onAutoSelect} tableWasChosen={tableWasChosen}/>}
  </div>;
}
function ReservationPage({language,profile}) {
  const t=k=>mt(language,k),[tables,setTables]=React.useState([]),[selected,setSelected]=React.useState(()=>new URLSearchParams(location.search).get("table")||""),[tableWasChosen,setTableWasChosen]=React.useState(false),[message,setMessage]=React.useState(""),[loaded,setLoaded]=React.useState(false);
  const load=async()=>{if(!profile)return;try{const response=await tournamentApi(profile.is_admin?"/api/admin/club-tables":"/api/club-tables");const items=response.tables;if(selected&&!items.some(r=>r.id===selected||r.score_table_id===selected)){const direct=await tournamentApi("/api/club-tables/"+encodeURIComponent(selected));items.push(direct);}setTables(items);setLoaded(true);setMessage("");}catch(e){setMessage(e.message);}};
  React.useEffect(()=>{load();const timer=setInterval(load,10000);return()=>clearInterval(timer);},[profile?.id,profile?.is_admin]);
  React.useEffect(()=>{const restore=()=>setSelected(new URLSearchParams(location.search).get("table")||"");window.addEventListener("popstate",restore);return()=>window.removeEventListener("popstate",restore);},[]);
  const table=tables.find(r=>r.id===selected||r.score_table_id===selected)||(!selected?tables.find(r=>r.status==="open"):null);
  const select=(id,manual=true)=>{if(manual)setTableWasChosen(true);setSelected(id);const url=new URL(location.href);url.searchParams.set("table",id);if(manual)history.pushState(null,"",url);else history.replaceState(null,"",url);};
  return <div data-i18n-owned><Card><h2 className="text-xl font-bold">{t("reservations")}</h2><p className="my-2 text-sm"><a className="underline" href="/?page=record">{t("backToScoring")}</a></p>
    {!profile?<TournamentButton onClick={tableLoginReturn}>{t("reserveTable")}</TournamentButton>:<>
      <TournamentField label={t("selectTable")}><select aria-label={t("selectTable")} className={inputStyle} value={table?.id||""} onChange={e=>select(e.target.value)}><option value="">{t("selectTable")}</option>{tables.map(r=><option key={r.id} value={r.id}>{mt(language,"tableNumber",{number:r.number})}{r.display_name&&" · "+r.display_name}{r.status!=="open"&&" · "+t("tableClosed")}</option>)}</select></TournamentField>
      {loaded&&!tables.length&&<p className="my-3">{t("noTables")}</p>}
      {table&&<TableReservations table={table} profile={profile} language={language} reload={load} adminMode={Boolean(profile.is_admin)} onAutoSelect={id=>select(id,false)} tableWasChosen={tableWasChosen}/>}
    </>}{message&&<p role="status" className="my-3">{t(message)}</p>}
  </Card></div>;
}
function TableSeatList({members,language,onRemove,onJoin,onAction,currentUserId,disabled=false,joinDisabled=false,started=false}) {
  const t=k=>mt(language,k);
  return <ul className="my-3 grid gap-2 sm:grid-cols-2" data-table-seats>{CLUB_SEATS.map(seat=>{const member=(members||[]).find(m=>m.seat===seat),mine=member?.user_id===String(currentUserId);return <li key={seat} data-table-seat={seat} data-seat-state={member?"occupied":"empty"} className="rounded-lg border border-zinc-200 p-3">{!member&&onJoin?<button type="button" data-lobby-join-seat={seat} className="club-empty-seat" disabled={disabled||joinDisabled} aria-label={t("seat_"+seat)+" · "+t("joinTable")} onClick={()=>onJoin(seat)}><strong>{t("seat_"+seat)}</strong><span>{t("emptyTableSeat")}</span><small>{v10(language,"Tap to join","点击上桌")}</small></button>:member&&onAction?<button type="button" data-lobby-seat-action={seat} className="club-occupied-seat" disabled={disabled} aria-label={t("seat_"+seat)+" · "+member.name+" · "+t(mine?(started?"flowCancelGame":"pSeatLeaveButton"):"seatActionTitle")} onClick={event=>onAction(member,event)}><strong>{t("seat_"+seat)}</strong><span className="inline-flex items-center gap-2"><AccountAvatars.Avatar name={member.name} src={member.avatar} size={28} decorative/><span>{member.name}</span></span><small>{t(mine?(started?"flowCancelGame":"pSeatLeave"):"seatActionTitle")}</small></button>:<><strong>{t("seat_"+seat)}</strong><span className="ml-2 inline-flex items-center gap-2">{member&&<AccountAvatars.Avatar name={member.name} src={member.avatar} size={28} decorative/>}{member?<span>{member.name}{member.participant_type==="guest"&&" · "+v10(language,"Guest","临时")}</span>:t("emptyTableSeat")}</span>{member&&<small className="mt-1 block break-all text-zinc-500">{t("method_"+member.join_method)}</small>}{member&&onRemove&&<button type="button" className="club-remove-player" disabled={disabled} aria-label={v10(language,"Remove "+member.name+" from table","让 "+member.name+" 下桌")} onClick={()=>onRemove(member)}>{v10(language,"Remove","下桌")}</button>}</>}</li>;})}</ul>;
}
function TableMemberControls({table,profile,language,reload,entryToken=null}) {
  const t=k=>mt(language,k),{busy,message,run}=useTableAction(language,reload),self=table.members.find(m=>m.user_id===String(profile?.id));
  const [seat,setSeat]=React.useState(""),[open,setOpen]=React.useState(false),[mode,setMode]=React.useState("self"),dialog=React.useRef(null),trigger=React.useRef(null);
  const canAdd=Boolean(profile&&!table.tournament_id&&!table.started_at&&table.player_count<table.capacity);
  const canCancel=Boolean(!table.tournament_id&&table.started_at&&table.player_count===4&&table.current_match_id&&(self||profile?.is_admin));
  React.useEffect(()=>{if(open){dialog.current?.querySelector("button")?.focus();}else trigger.current?.focus();},[open]);
  React.useEffect(()=>{if(seat&&table.members.some(member=>member.seat===seat))setSeat("");},[table.members.map(member=>member.seat).join(","),seat]);
  const joinSeat=()=>run(async()=>{
    let result;
    if(entryToken){
      const info=await tournamentApi("/api/table-join-tokens/"+encodeURIComponent(entryToken));
      if(info.purpose!=="table_landing"||info.table_id!==table.id)throw new Error("invalid_join_token");
      result=await tournamentApi("/api/table-join-tokens/"+encodeURIComponent(entryToken)+"/join",{request_id:MahjongI18n.key(),seat,table_id:table.id});
    }else result=await tournamentApi("/api/club-tables/"+table.id+"/join",{seat});
    setOpen(false);return result;
  },"joinedTable");
  function close(){if(!busy)setOpen(false);}
  function keyboard(event){
    if(event.key==="Escape"){event.preventDefault();close();}
    if(event.key!=="Tab")return;
    const nodes=[...dialog.current.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),a[href]')],first=nodes[0],last=nodes.at(-1);
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }
  return <div className="mt-4" data-table-member-controls>
    <h3 className="mt-3 font-bold">{t("currentMembers")} ({table.player_count}/{table.capacity})</h3><TableSeatList members={table.members} language={language} disabled={busy} onRemove={profile&&!table.tournament_id&&table.can_leave?member=>{
      if(!window.confirm(v10(language,"Remove "+member.name+" from this table?","确认让 "+member.name+" 下桌？")))return;
      run(()=>member.user_id===String(profile.id)?tournamentApi("/api/club-tables/"+table.id+"/leave",{match_id:table.current_match_id}):tournamentApi("/api/club-tables/"+table.id+"/seats/"+encodeURIComponent(member.user_id)+"/remove",{match_id:table.current_match_id,seat:member.seat}),"leftTable");
    }:null}/>
    <div className="flex flex-wrap items-end gap-2"><button ref={trigger} type="button" className={buttonStyle} data-main-seat-button disabled={busy||Boolean(table.started_at)||table.player_count>=table.capacity} onClick={()=>{if(!profile){tableLoginReturn();return;}setMode(self?"registered":"self");setOpen(true);}}>{t("joinTable")}</button>
      {canAdd&&<TournamentButton disabled={busy} onClick={()=>{setMode("registered");setOpen(true);}}>{v10(language,"Seat a member","帮成员上桌")}</TournamentButton>}
      {canCancel?<TournamentButton disabled={busy} onClick={()=>{
        if(!window.confirm(t("cancelGameConfirm")))return;
        run(async()=>{const storageKey="mahjong-cancel-game:"+table.id+":"+table.current_match_id;
          let request_id=sessionStorage.getItem(storageKey);
          if(!request_id){request_id=MahjongI18n.key();sessionStorage.setItem(storageKey,request_id);}
          const result=await tournamentApi("/api/club-tables/"+table.id+"/cancel-game",{match_id:table.current_match_id,request_id,reason:"wrong_players"});
          sessionStorage.removeItem(storageKey);return result;
        },"cancelGameSaved");
      }}>{t("cancelGame")}</TournamentButton>:self&&<TournamentButton disabled={busy||!table.can_leave} onClick={()=>run(()=>tournamentApi("/api/club-tables/"+table.id+"/leave",{}),"leftTable")}>{t("leaveTable")}</TournamentButton>}
    </div>
    {self&&!table.can_leave&&!canCancel&&<p className="mt-2 text-sm">{t("cannot_leave_started")}</p>}
    {open&&<div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4 sm:items-center" onMouseDown={event=>{if(event.target===event.currentTarget)close();}}>
      <section ref={dialog} role="dialog" aria-modal="true" aria-label={t("registeredSeatingTitle")} className="my-8 w-full max-w-lg rounded-2xl bg-white p-5 shadow-xl" onKeyDown={keyboard}>
        <div className="mb-4 flex items-center justify-between gap-3"><h3 className="text-lg font-bold">{t("registeredSeatingTitle")}</h3><TournamentButton disabled={busy} onClick={close}>{t("registeredSeatingClose")}</TournamentButton></div>
        <div role="tablist" aria-label={t("registeredSeatingTitle")} className="mb-4 flex flex-wrap gap-2"><TournamentButton role="tab" aria-selected={mode==="self"} onClick={()=>setMode("self")}>{t("registeredSeatingSelf")}</TournamentButton><TournamentButton role="tab" aria-selected={mode==="registered"} disabled={!canAdd} onClick={()=>setMode("registered")}>{t("registeredSeatingOther")}</TournamentButton></div>
        {mode==="self"?<div role="tabpanel"><p className="mb-3 text-sm">{t("registeredSeatingHelp")}</p>{self?<p>{t("registeredSeatingAlreadyHere")}</p>:<>
          <TournamentField label={t("chooseTableSeat")}><select className={inputStyle} aria-label={t("chooseTableSeat")} value={seat} onChange={e=>setSeat(e.target.value)}><option value="">{t("chooseTableSeat")}</option>{CLUB_SEATS.map(wind=><option key={wind} value={wind} disabled={table.members.some(m=>m.seat===wind)}>{t("seat_"+wind)}{table.members.some(m=>m.seat===wind)&&" · "+t("seatOccupied")}</option>)}</select></TournamentField>
          <TournamentButton disabled={busy||!seat||table.player_count>=table.capacity||Boolean(table.started_at)} onClick={joinSeat}>{t("registeredSeatingConfirm")}</TournamentButton>
        </>}</div>:<div role="tabpanel">{canAdd?<RegisteredTablePlayers table={table} language={language} reload={reload} onDone={()=>setOpen(false)}/>:<p>{t("mustJoinFirstNote")}</p>}</div>}
        {message&&<p role="status" className="my-2">{t(message)}</p>}
      </section>
    </div>}
    {!open&&message&&<p role="status" className="my-2">{t(message)}</p>}
  </div>;
}
function ScoringTableStatus({profile,language,requestedTable,entryToken,autoSelectFull=false,onResolved,onChanged}) {
  const [result,setResult]=React.useState(null),[error,setError]=React.useState(""),[retry,setRetry]=React.useState(0),[notice,setNotice]=React.useState(""),[tables,setTables]=React.useState([]),[selectedTable,setSelectedTable]=React.useState(requestedTable||"");
  const pinned=React.useRef(null),callbacks=React.useRef({onResolved,onChanged});callbacks.current={onResolved,onChanged};
  const requested=React.useRef(requestedTable||null);
  const autoEntry=React.useRef(autoSelectFull);
  React.useEffect(()=>{
    if(!profile)return;
    let live=true;
    tournamentApi("/api/club-tables").then(value=>{if(live)setTables(value.tables||[]);}).catch(()=>{});
    return()=>{live=false;};
  },[profile?.id]);
  React.useEffect(()=>{
    let live=true,running=false;
    async function load(){
      if(running||!profile)return;running=true;
      const query=new URLSearchParams();
      if(requested.current)query.set("table",requested.current);
      if(entryToken!==null)query.set("entry_token",entryToken);
      if(autoEntry.current&&!entryToken)query.set("auto_select_full","true");
      if(!requested.current&&pinned.current)query.set("current_table",pinned.current);
      try{
        const next=await tournamentApi("/api/scoring-table?"+query);
        if(!live)return;
        const changed=pinned.current!==null&&pinned.current!==next.table?.id;
        if(autoEntry.current&&["full_table_redirected","full_table_no_space"].includes(next.notice))requested.current=null;
        autoEntry.current=false;
        pinned.current=next.table?.id||null;setResult(next);setError("");setSelectedTable(next.table?.id||"");setNotice(previous=>next.notice||(previous==="full_table_no_space"&&next.table?"":previous));
        callbacks.current.onResolved(next.table?.score_table_id||"");if(changed)callbacks.current.onChanged?.();
      }catch(e){
        if(!live)return;setError(e.message);
        if(e.status===401){location.replace(globalLoginUrl());return;}
        // Never fall back from an invalid explicit link to an unrelated table.
        if(e.status===409||e.status===404){setResult(null);callbacks.current.onResolved("");}
      }finally{running=false;}
    }
    load();const timer=setInterval(load,5000);return()=>{live=false;clearInterval(timer);};
  },[profile?.id,requestedTable,entryToken,retry]);
  function chooseTable(tableId){
    autoEntry.current=false;
    requested.current=tableId||null;pinned.current=null;setSelectedTable(tableId||"");setResult(null);setError("");setNotice("");setRetry(value=>value+1);
  }
  const table=result?.table,t=k=>mt(language,k),say=(en,cn)=>language==="CN"?cn:en;
  return <div data-i18n-owned className="scoring-table-status" data-scoring-status>
    {!entryToken&&<TournamentField label={t("selectTable")}><select aria-label={t("selectTable")} className={inputStyle} value={selectedTable} onChange={event=>chooseTable(event.target.value)} disabled={!profile||!tables.length}>
      <option value="">{t("selectTable")}</option>{tables.map(item=><option key={item.id} value={item.id}>{mt(language,"tableNumber",{number:item.number})}{item.display_name&&" · "+item.display_name}</option>)}
    </select></TournamentField>}
    {notice&&<p className="table-notice" role="status">{notice==="full_table_redirected"?say("The previous table is full. Your table selection has been updated.","原桌已满，已自动切换桌次。"):notice==="full_table_no_space"?say("The previous table is full. No available table was found.","原桌已满，当前没有可加入的桌子。"):say("The previous table was closed or removed. Available tables have been checked again.","原桌子已关闭或删除，已重新查找可用桌子。")}</p>}
    {error&&<p className="table-notice" role="alert">{error==="table_not_found"?say("This table no longer exists.","该桌子不存在或已被删除。"):t(error)}</p>}
    {!result&&!error&&<p role="status">{say("Loading your table…","正在加载桌次…")}</p>}
    {table&&<>
      <p className="table-name" data-current-table={table.score_table_id}>{mt(language,"tableNumber",{number:table.number})}{table.display_name&&" · "+table.display_name}</p>
      {table.player_count>=table.capacity&&<p role="status">{say("This table is full.","该桌已满。")}</p>}
    </>}
    {result&&!table&&<p role="status">{say("No table is currently available.","当前没有可加入的桌子")}</p>}
    {(error||(result&&!table))&&<div className="flex flex-wrap gap-2"><TournamentButton onClick={()=>setRetry(v=>v+1)}>{say("Retry","稍后重试")}</TournamentButton>{profile?.is_admin&&<a className={buttonStyle} href="/?page=admin">{say("Manage tables","桌子管理")}</a>}</div>}
  </div>;
}

function TableJoinPage({language,profile,authReady=false}) {
  const t=k=>mt(language,k),token=location.pathname.split("/").at(-1),[info,setInfo]=React.useState(null),[message,setMessage]=React.useState(""),attempt=React.useRef(false),[retry,setRetry]=React.useState(0);
  const key=React.useRef(MahjongI18n.key()),target=location.pathname+location.search;
  React.useEffect(()=>{let live=true;tournamentApi("/api/table-join-tokens/"+encodeURIComponent(token)).then(r=>{if(live)setInfo(r);}).catch(e=>{if(live)setMessage(e.message);});return()=>{live=false;};},[token]);
  React.useEffect(()=>{
    if(!info)return;
    if(info.purpose==="table_landing"){if(profile){const destination=new URL(info.target||"/?page=record&table="+encodeURIComponent(info.score_table_id),location.origin);destination.hash=new URLSearchParams({entry:token}).toString();location.replace(destination.href);}return;}
    if(!profile){if(authReady&&!info.allow_guest_auto_enrollment)location.replace("/login?redirect_url="+encodeURIComponent(target));return;}
    if(attempt.current)return;attempt.current=true;setMessage("joiningTable");
    tournamentApi("/api/table-join-tokens/"+encodeURIComponent(token)+"/join",{request_id:key.current}).then(r=>location.replace(r.target)).catch(e=>{setMessage(e.message);tournamentApi("/api/table-join-tokens/"+encodeURIComponent(token)).then(setInfo).catch(()=>{});});
  },[profile?.id,authReady,info,retry]);
  return <div data-i18n-owned><Card><h2 className="text-xl font-bold">{info?mt(language,"tableNumber",{number:info.number}):t("joinTable")}</h2>{info?.display_name&&<p>{info.display_name}</p>}
    {!profile&&info?.allow_guest_auto_enrollment&&<GuestJoin tid={info.tournament_id} tableId={info.table_id} seat={info.seat||""} entryToken={token} language={language} onJoined={()=>location.assign(info.target)}/>}
    {info?.seat&&<p className="my-2 font-bold">{t("seat_"+info.seat)}</p>}{info?.purpose==="table_landing"&&!(!profile&&info.allow_guest_auto_enrollment)?<TableMemberControls table={{...info,id:info.table_id,player_count:info.player_count??info.members?.length??0,members:info.members||[]}} profile={profile} language={language} entryToken={token}/>:info?.members&&!(!profile&&info.allow_guest_auto_enrollment)&&<TableSeatList members={info.members} language={language}/>}
    {message&&<p className="my-4" role="status">{t(message)}</p>}
    {profile&&info&&message&&message!=="joiningTable"&&<div className="flex flex-wrap gap-2"><TournamentButton onClick={()=>{attempt.current=false;setRetry(x=>x+1);}}>{t("retryJoinTable")}</TournamentButton><a className={buttonStyle} href={info.target||"/?page=record&table="+encodeURIComponent(info.score_table_id)}>{t("openTablePage")}</a>{message==="already_at_other_table"&&<a className={buttonStyle} href="/?page=record">{t("returnToOwnTable")}</a>}</div>}
  </Card></div>;
}
function AdminTableToken({table,channel,purpose="table_landing",seat=null,language,reload}) {
  const t=k=>mt(language,k),[expiry,setExpiry]=React.useState(""),{busy,message,run}=useTableAction(language,reload);
  const matching=(table.tokens||[]).filter(r=>r.channel===channel&&(channel!=="qr"||((r.purpose||"table_landing")===purpose&&(r.seat||null)===seat))),current=matching.find(r=>!r.revoked_at)||matching[0];
  const url=current?.path?new URL(current.path,location.origin).href:"",label=channel==="nfc"?t("nfc"):seat?t("seat_"+seat):t("tableEntryQr");
  const rotate=()=>run(async()=>{
    if(current?.valid&&!window.confirm(t("rotateTokenConfirm")))return;
    return tournamentApi("/api/admin/club-tables/"+table.id+"/tokens",{request_id:MahjongI18n.key(),channel,purpose:channel==="nfc"?"table_join":purpose,seat,expires_at:expiry?new Date(expiry).toISOString():null});
  });
  return <div data-table-token={channel==="nfc"?"nfc":seat||"entry"} className="my-3 rounded-xl border border-zinc-200 p-3"><h4 className="font-bold">{mt(language,"tableNumber",{number:table.number})} · {label} · {t(current?.valid?"tokenValid":"tokenInvalid")}</h4>
    <TournamentField label={t("tokenExpiry")}><input aria-label={label+" · "+t("tokenExpiry")} className={inputStyle} type="datetime-local" value={expiry} onChange={e=>setExpiry(e.target.value)}/></TournamentField>
    <div className="my-2 flex flex-wrap gap-2"><TournamentButton disabled={busy||table.status!=="open"} onClick={rotate}>{t(channel==="qr"?(current?"rotateQr":"createQr"):(current?"rotateNfc":"createNfc"))}</TournamentButton>
    {current&&!current.revoked_at&&<TournamentButton disabled={busy} onClick={()=>{if(window.confirm(t("revokeConfirm")))run(()=>tournamentApi("/api/admin/table-tokens/"+current.id+"/revoke",{}));}}>{t("revokeToken")}</TournamentButton>}</div>
    {current?.valid&&<div>{channel==="qr"&&<img className="my-3 w-56 max-w-full" alt={mt(language,"tableNumber",{number:table.number})+" · "+label+" · "+t("qr")} src={"/api/admin/table-tokens/"+current.id+"/qr.png"}/>}
      <input className={inputStyle+" mb-2"} readOnly value={url} aria-label={label+" · "+t("tokenLink")}/>
      <div className="flex flex-wrap gap-2"><TournamentButton onClick={()=>run(async()=>{try{await navigator.clipboard.writeText(url);}catch{throw new Error("copyFailed");}},"copied")}>{t("copyLink")}</TournamentButton>
      {channel==="qr"?<TournamentButton onClick={()=>run(()=>downloadTournamentQr("/api/admin/table-tokens/"+current.id+"/qr.png","table-"+table.number+"-"+(seat||"entry")),"qrDownloaded")}>{t("download")}</TournamentButton>:<a className={buttonStyle} href={"/api/admin/table-tokens/"+current.id+"/ndef.json"} download>{t("exportNfc")}</a>}</div>
    </div>}{message&&<p role="status" className="mt-2">{t(message)}</p>}
  </div>;
}
function AdminTableCard({table,language,profile,reload}) {
  const t=k=>mt(language,k),[form,setForm]=React.useState({number:table.number,display_name:table.display_name,nfc_configured:Boolean(table.nfc_configured),nfc_label:table.nfc_label});
  const [reason,setReason]=React.useState(""),{busy,message,run}=useTableAction(language,reload);
  return <details className="my-3 rounded-xl border border-zinc-200 p-4"><summary className="cursor-pointer font-bold">
    {mt(language,"tableNumber",{number:table.number})} {table.display_name} · {t(table.status==="open"?"tableOpen":"tableClosed")} · {table.player_count}/{table.capacity}
    {" · "+t("reservations")+": "+table.reservations.filter(r=>r.status==="active").length}
    {" · "+t("qr")+": "+t(table.tokens.some(r=>r.channel==="qr"&&r.valid)?"tokenValid":"tokenInvalid")}
    {" · NFC: "+t(table.tokens.some(r=>r.channel==="nfc"&&r.valid)?"tokenValid":"tokenInvalid")}
  </summary><div className="my-3 grid gap-3 sm:grid-cols-2">
    <TournamentField label={t("tableNumberInput")}><input className={inputStyle} type="number" min="1" step="1" value={form.number} onChange={e=>setForm({...form,number:e.target.value})}/></TournamentField>
    <TournamentField label={t("tableDisplayName")}><input aria-label={t("tableDisplayName")} className={inputStyle} value={form.display_name} maxLength={120} onChange={e=>setForm({...form,display_name:e.target.value})}/></TournamentField>
    <TournamentField label={t("nfcLabel")}><input className={inputStyle} value={form.nfc_label} maxLength={120} onChange={e=>setForm({...form,nfc_label:e.target.value})}/></TournamentField>
    <label className="self-center"><input type="checkbox" checked={form.nfc_configured} onChange={e=>setForm({...form,nfc_configured:e.target.checked})}/> {t("nfcConfigured")}</label>
  </div><div className="flex flex-wrap gap-2"><TournamentButton disabled={busy||!(Number(form.number)>0)} onClick={()=>run(()=>tournamentApi("/api/admin/club-tables/"+table.id,{...form,number:Number(form.number)}))}>{t("saveTable")}</TournamentButton>
    <TournamentButton disabled={busy||table.player_count>0} onClick={()=>run(()=>tournamentApi("/api/admin/club-tables/"+table.id,{status:table.status==="open"?"closed":"open"}))}>{t(table.status==="open"?"closeTable":"openTable")}</TournamentButton></div>
    {message&&<p role="status">{t(message)}</p>}
    <h3 className="mt-4 font-bold">{t("fiveTableQrs")}</h3><p className="my-2 text-sm text-zinc-600">{t("fiveTableQrsHelp")}</p><div className="grid gap-3 md:grid-cols-2"><AdminTableToken table={table} channel="qr" purpose="table_landing" language={language} reload={reload}/>{CLUB_SEATS.map(seat=><AdminTableToken key={seat} table={table} channel="qr" purpose="seat_join" seat={seat} language={language} reload={reload}/>)}</div><AdminTableToken table={table} channel="nfc" language={language} reload={reload}/>
    <p className="my-2 text-sm text-zinc-600">{t("nfcInstructions")}</p>
    {!table.tournament_id?<><TableMemberControls table={table} profile={profile} language={language} reload={reload}/>
      {table.player_count>0&&<details className="my-3 rounded-lg border border-amber-200 p-3"><summary>{t("resetOrdinary")}</summary><p className="my-2 text-sm">{t("resetOrdinaryNote")}</p>
        <input aria-label={t("reason")} className={inputStyle} value={reason} onChange={e=>setReason(e.target.value)}/>
        <TournamentButton disabled={busy||!reason.trim()} onClick={()=>{if(window.confirm(t("resetOrdinaryNote")))run(()=>tournamentApi("/api/admin/club-tables/"+table.id+"/reset",{request_id:MahjongI18n.key(),reason}));}}>{t("resetOrdinary")}</TournamentButton>
      </details>}</>:<><h4 className="mt-3 font-bold">{t("currentMembers")}</h4><ul>{table.members.map(m=><li key={m.user_id} className="flex items-center gap-2"><AccountAvatars.Avatar name={m.name} src={m.avatar} size={28} decorative/>{m.name} · {t("method_"+m.join_method)}</li>)}</ul></>}
    <ReservationSessionGroups table={table} language={language} renderReservation={r=><li key={r.id} className="my-2 text-sm"><p>{reservationDisplay(r,table.timezone,language)} · {r.user_name||r.creator_name}</p><ReservationPeople people={r.participants} language={language}/></li>}/>
    <p className="my-3 text-sm"><a className="underline" href={tableReservationHref(table)}>{t("viewTableReservations")}</a></p>
  </details>;
}
function AdminTables({language,profile}) {
  const t=k=>mt(language,k),[tables,setTables]=React.useState([]),[tournaments,setTournaments]=React.useState([]),[scope,setScope]=React.useState("");
  const [loaded,setLoaded]=React.useState(false);
  const load=async()=>{const [a,b]=await Promise.all([tournamentApi("/api/admin/club-tables"),tournamentApi("/api/tournaments")]);setTables(a.tables);setTournaments(b.tournaments);setLoaded(true);};
  const {busy,message,run}=useTableAction(language,load);
  React.useEffect(()=>{if(profile?.is_admin)run(async()=>{},"");},[profile?.is_admin]);
  if(!profile?.is_admin)return null;
  return <div data-i18n-owned className="mb-5"><Card><h2 className="mb-3 text-xl font-bold">{t("tableManagement")}</h2>
    <TournamentField label={t("tableScope")}><select className={inputStyle} value={scope} onChange={e=>setScope(e.target.value)}><option value="">{t("venueTables")}</option>{tournaments.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></TournamentField>
    <CreateClubTable key={scope} language={language} tables={tables} scope={scope} onCreated={load}/>
    {message&&<p role="status">{t(message)}</p>}
    {loaded&&!tables.some(r=>(r.tournament_id||"")===scope)&&<p>{t("noTables")}</p>}
    {tables.filter(r=>(r.tournament_id||"")===scope).map(table=><AdminTableCard key={table.id} table={table} profile={profile} language={language} reload={load}/>)}
    {tournaments.find(r=>r.id===scope)&&<TournamentDeleteControl item={tournaments.find(r=>r.id===scope)} language={language} onDeleted={()=>{setScope("");load();}}/>}
  </Card></div>;
}

function CreateClubTable({language,tables,scope=null,onCreated,collapsible=false}) {
  const t=k=>mt(language,k),suggested=Math.max(0,...tables.filter(r=>(r.tournament_id||null)===(scope||null)).map(r=>r.number))+1;
  const [number,setNumber]=React.useState(String(suggested)),[display,setDisplay]=React.useState(""),previous=React.useRef(suggested);
  const {busy,message,run}=useTableAction(language);
  React.useEffect(()=>{const oldSuggested=previous.current;previous.current=suggested;setNumber(old=>old===String(oldSuggested)?String(suggested):old);},[suggested]);
  const valid=Number.isInteger(Number(number))&&Number(number)>0&&Number(number)<=1000000000;
  const content=<form className="my-4 grid gap-3 sm:grid-cols-3" onSubmit={e=>{e.preventDefault();if(!valid)return;run(async()=>{
    const result=await tournamentApi("/api/admin/club-tables",{number:Number(number),display_name:display,tournament_id:scope||null,request_id:MahjongI18n.key()});
    setNumber(String(Math.max(suggested,result.number+1)));setDisplay("");await onCreated(result);return result;
  },"tableCreated");}}>
    <TournamentField label={t("tableNumberInput")}><input required aria-label={t("tableNumberInput")} className={inputStyle} type="number" min="1" max="1000000000" step="1" value={number} onChange={e=>setNumber(e.target.value)}/></TournamentField>
    <TournamentField label={t("tableDisplayName")}><input aria-label={t("tableDisplayName")} className={inputStyle} maxLength={120} value={display} onChange={e=>setDisplay(e.target.value)}/></TournamentField>
    <button className={buttonStyle+" self-end"} disabled={busy||!valid}>{t("createTable")}</button>
    {message&&<p role="status" className="sm:col-span-3">{t(message)}</p>}
  </form>;
  return collapsible?<details className="my-3 rounded-xl border border-zinc-200 p-3"><summary className="cursor-pointer font-bold">{t("createTable")}</summary><p className="my-2 text-sm">{t("tableCreateHelp")}</p>{content}</details>:content;
}
function RegisteredTablePlayers({table,language,reload,onDone}) {
  const t=k=>mt(language,k),[selected,setSelected]=React.useState(null),[seat,setSeat]=React.useState("");
  const {busy,message,run}=useTableAction(language,reload),request=React.useRef(null),signature=selected?.id+":"+seat;
  React.useEffect(()=>{request.current=null;},[signature]);
  const occupied=(table.members||[]).map(person=>person.user_id);
  return <div className="my-4" data-registered-seating>
    <p className="my-2 text-sm">{t("registeredSeatingOtherHelp")}</p>
    <RegisteredUserCombobox value={selected} onChange={setSelected} language={language} label={t("registeredName")} excludeIds={occupied} required disabled={busy}/>
    <TournamentField label={t("chooseTableSeat")}><select className={inputStyle} aria-label={t("chooseTableSeat")} value={seat} onChange={event=>setSeat(event.target.value)} disabled={busy}><option value="">{t("chooseTableSeat")}</option>{CLUB_SEATS.filter(wind=>!table.members.some(member=>member.seat===wind)).map(wind=><option key={wind} value={wind}>{t("seat_"+wind)}</option>)}</select></TournamentField>
    <TournamentButton disabled={busy||!selected||!seat||table.player_count>=table.capacity} onClick={()=>run(async()=>{
      request.current=request.current||MahjongI18n.key();
      const result=await tournamentApi("/api/club-tables/"+table.id+"/players",{request_id:request.current,user_ids:[selected.id],join_method:"registered_name",seat});
      setSelected(null);setSeat("");onDone?.();return result;
    },"playersAdded")}>{t("registeredSeatingAdd")}</TournamentButton>
    {message&&<p role="status" className="my-2">{t(message)}</p>}
  </div>;
}
