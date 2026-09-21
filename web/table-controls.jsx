/* Shared dashboard components. Language comes only from the global header. */
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
  const end=ReservationTime.dateParts(reservation,timezone,true);
  return end.time?mt(language,"reservationRangeDisplay",{start:format(parts),end:format(end)}):format(parts);
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
  const t=k=>mt(language,k),[date,setDate]=React.useState(()=>ReservationTime.create(reservation,table.timezone)),[note,setNote]=React.useState(reservation?.note||"");
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
    for(const prefix of ["","end_"]){if(!Number.isInteger(Number(date[prefix+"month"]))||Number(date[prefix+"month"])<1||Number(date[prefix+"month"])>12||!Number.isInteger(Number(date[prefix+"day"]))||Number(date[prefix+"day"])<1||Number(date[prefix+"day"])>31||!/^\d{2}:\d{2}$/.test(date[prefix+"time"]))throw new Error("invalid_reservation_time");}
    if(date.start_at&&date.end_at&&Date.parse(date.end_at)<=Date.parse(date.start_at))throw new Error("invalid_reservation_end");
    if(!selected.length||selected.length!==participants.length)throw new Error("registeredNameSelectRequired");if(selected.length>table.capacity)throw new Error("reservation_capacity_exceeded");
    const payload={...ReservationTime.payload(date),participant_ids:selected.map(person=>String(person.id)),note};
    const saved=await tournamentApi(reservation?"/api/table-reservations/"+reservation.id:"/api/club-tables/"+table.id+"/reservations",{...payload,...(reservation?{version:reservation.version,table_id:table.id}:{request_id:key.current})});
    await onSaved(saved);
  },"reservationSaved");};
  return <form data-reservation-form className="my-4 grid gap-3 sm:grid-cols-2" onSubmit={submit}><h3 className="font-bold sm:col-span-2">{t(reservation?"editReservation":"reserveTable")}</h3>
    <p className="text-sm text-zinc-600 sm:col-span-2">{mt(language,"inputTimezone",{timezone:table.timezone})}</p>
    {[false,true].map(end=><fieldset key={String(end)} className="sm:col-span-2" data-reservation-time={end?"end":"start"}><legend className="mb-2 font-semibold">{t(end?"reservationEnd":"reservationStart")}</legend><div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {["month","day","time"].map(field=>{const name=(end?"end_":"")+field,label=end?{month:"reservationEndMonth",day:"reservationEndDay",time:"reservationEndClock"}[field]:{month:"reservationMonth",day:"reservationDay",time:"reservationClock"}[field];return <div key={field} className={field==="time"?"col-span-2 sm:col-span-1":""}><TournamentField label={t(label)}><input aria-label={t(label)} className={inputStyle} type={field==="time"?"time":"number"} inputMode={field==="time"?undefined:"numeric"} min={field==="time"?undefined:"1"} max={field==="month"?"12":field==="day"?"31":undefined} required value={date[name]} onChange={e=>editDate(name,e.target.value)}/></TournamentField></div>;})}
    </div></fieldset>)}
    <div className="sm:col-span-2"><TournamentButton disabled={busy} onClick={()=>setDate(previous=>ReservationTime.resetDuration(previous))}>{t("reservationResetDuration")}</TournamentButton></div>
    {nearby&&!reservation&&<p data-reservation-nearby className="rounded-lg bg-amber-50 p-3 text-sm sm:col-span-2">{tableWasChosen?t("reservationNearbyRespect"):mt(language,"reservationNearbySelected",{table:nearby.table_number})}</p>}
    {reservation&&<p className="text-xs text-zinc-600 sm:col-span-2">{t("reservationKeepYear")}</p>}
    <ReservationParticipants values={participants.length?participants:[null]} onChange={setParticipants} capacity={table.capacity} language={language} disabled={busy}/>
    <div className="sm:col-span-2"><TournamentField label={t("reservationNote")}><input aria-label={t("reservationNote")} className={inputStyle} value={note} maxLength={500} onChange={e=>setNote(e.target.value)}/></TournamentField></div>
    <div className="flex flex-wrap gap-2 sm:col-span-2"><button className={buttonStyle} disabled={busy||resolving||!date.start_at||!month||!day||!time||!date.end_month||!date.end_day||!date.end_time||!selected.length||selected.length!==participants.length||participants.length>table.capacity}>{t(reservation?"saveReservation":"reserveTable")}</button>{reservation&&<TournamentButton disabled={busy} onClick={onCancel}>{t("cancelReservationEdit")}</TournamentButton>}</div>
    {resolving&&<p className="text-xs text-zinc-500 sm:col-span-2" role="status">{t("reservationResolving")}</p>}
    {resolveFailed&&<div className="sm:col-span-2"><TournamentButton disabled={busy||resolving} onClick={()=>setResolveAttempt(value=>value+1)}>{t("reservationRetryTimes")}</TournamentButton></div>}
    {message&&<p role="status" className="text-sm sm:col-span-2">{t(message==="stale_version"?"reservation_stale_version":message)}</p>}
  </form>;
}
function ReservationPeople({people,language}) {
  return <span className="inline-flex flex-wrap items-center gap-x-4 gap-y-2">{(people||[]).map(person=><span key={person.id||person.user_id} className="inline-flex items-center gap-2"><AccountAvatars.Avatar name={person.name} src={person.avatar} size={24} decorative/>{person.name||mt(language,"registeredNameUnknown")}</span>)}</span>;
}
function ReservationSessionGroups({table,language,renderReservation,expanded=false}) {
  const t=k=>mt(language,k),sessions=table.reservation_sessions||[];
  return <div data-reservation-sessions className="my-3 space-y-3">{sessions.map(session=>{
    const rows=session.reservations||(table.reservations||[]).filter(item=>item.session_id===session.id&&item.status==="active");
    return <article data-reservation-session={session.id} key={session.id} className="rounded-xl border border-zinc-200 p-3 text-sm">
      <p className="font-bold">{t("reservationSession")} · {reservationDisplay(session,table.timezone,language)}</p>
      <div className="mt-2"><ReservationPeople people={session.participants} language={language}/></div>
      <details open={expanded} className="mt-3"><summary className="cursor-pointer text-zinc-600">{t("reservationPersonalDetails")} ({rows.length})</summary><ul className="mt-2 space-y-2">{rows.map(renderReservation)}</ul></details>
    </article>;
  })}<ul className="space-y-2">{(!sessions.length?(table.reservations||[]):(table.reservations||[]).filter(item=>item.status!=="active"||!item.session_id)).map(renderReservation)}</ul></div>;
}
function TableReservations({table,profile,language,reload,adminMode=false,onAutoSelect,tableWasChosen=false}) {
  const t=k=>mt(language,k),[editing,setEditing]=React.useState(null),[generation,setGeneration]=React.useState(0),{busy,message,run,setMessage}=useTableAction(language,reload);
  const saved=async()=>{setEditing(null);setGeneration(g=>g+1);setMessage("reservationSaved");await reload();};
  const record=r=><li key={r.id} className="rounded-lg border border-zinc-200 p-3 text-sm" data-reservation-id={r.id}>
    <p className="font-bold">{reservationDisplay(r,table.timezone,language)} · {t("reservation_"+r.status)}</p>
    <p className="mt-1">{t("reservationCreator")}: {r.user_name||r.creator_name||t("registeredNameUnknown")}</p>
    <div className="mt-1 break-words">{t("reservationParticipants")}: <ReservationPeople people={r.participants} language={language}/></div>
    {r.note&&<p className="mt-1 break-words">{t("reservationNote")}: {r.note}</p>}
    {r.status==="active"&&(adminMode||String(r.created_by||r.user_id)===String(profile?.id))&&<div className="mt-2 flex flex-wrap gap-2">
      <TournamentButton disabled={busy} onClick={()=>setEditing(r)}>{t("editReservation")}</TournamentButton>
      <TournamentButton disabled={busy} onClick={()=>run(()=>tournamentApi("/api/table-reservations/"+r.id,{status:"cancelled",version:r.version}),"reservationCancelled")}>{t("cancelReservation")}</TournamentButton>
      {adminMode&&<TournamentButton disabled={busy} onClick={()=>run(()=>tournamentApi("/api/table-reservations/"+r.id,{status:"completed",version:r.version}),"reservationCompleted")}>{t("completeReservation")}</TournamentButton>}
    </div>}
  </li>;
  return <div className="my-4"><h3 className="font-bold">{mt(language,"tableNumber",{number:table.number})}{table.display_name&&" · "+table.display_name}</h3><p className="my-2 text-sm text-zinc-600">{t("reservationHelp")}</p>
    <p className="text-xs">{mt(language,"displayTimezone",{timezone:table.timezone})}</p>
    <ReservationSessionGroups table={table} language={language} renderReservation={record} expanded/>
    {!table.reservations?.length&&<p className="text-sm text-zinc-500">{t("noReservations")}</p>}
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
function TableSeatList({members,language}) {
  const t=k=>mt(language,k);
  return <ul className="my-3 grid gap-2 sm:grid-cols-2" data-table-seats>{CLUB_SEATS.map(seat=>{const member=(members||[]).find(m=>m.seat===seat);return <li key={seat} className="rounded-lg border border-zinc-200 p-3"><strong>{t("seat_"+seat)}</strong><span className="ml-2 inline-flex items-center gap-2">{member&&<AccountAvatars.Avatar name={member.name} src={member.avatar} size={28} decorative/>}{member?<span>{member.name}{member.participant_type==="guest"&&" · "+v10(language,"Guest","临时")}</span>:t("emptyTableSeat")}</span>{member&&<small className="mt-1 block break-all text-zinc-500">{t("method_"+member.join_method)}</small>}</li>;})}</ul>;
}
function TableMemberControls({table,profile,language,reload,entryToken=null}) {
  const t=k=>mt(language,k),{busy,message,run}=useTableAction(language,reload),self=table.members.find(m=>m.user_id===String(profile?.id));
  const [seat,setSeat]=React.useState(""),[open,setOpen]=React.useState(false),[mode,setMode]=React.useState("self"),dialog=React.useRef(null),trigger=React.useRef(null);
  const canAdd=Boolean((self||profile?.is_admin)&&!table.started_at&&table.player_count<table.capacity);
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
    <h3 className="mt-3 font-bold">{t("currentMembers")} ({table.player_count}/{table.capacity})</h3><TableSeatList members={table.members} language={language}/>
    <div className="flex flex-wrap items-end gap-2"><button ref={trigger} type="button" className={buttonStyle} data-main-seat-button disabled={busy||Boolean(table.started_at)||table.player_count>=table.capacity} onClick={()=>{if(!profile){tableLoginReturn();return;}setMode(self?"registered":"self");setOpen(true);}}>{t("joinTable")}</button>
      {self&&<TournamentButton disabled={busy||!table.can_leave} onClick={()=>run(()=>tournamentApi("/api/club-tables/"+table.id+"/leave",{}),"leftTable")}>{t("leaveTable")}</TournamentButton>}
    </div>
    {self&&!table.can_leave&&<p className="mt-2 text-sm">{t("cannot_leave_started")}</p>}
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
function OrdinaryTables({profile,language,selected,onSelect,onChanged}) {
  const t=k=>mt(language,k),[tables,setTables]=React.useState([]),[message,setMessage]=React.useState("");
  const load=async()=>{if(!profile)return;try{const data=await tournamentApi("/api/club-tables");setTables(data.tables);setMessage("");onChanged?.();return data.tables;}catch(e){setMessage(e.message);}};
  React.useEffect(()=>{load();const timer=setInterval(load,5000);return()=>clearInterval(timer);},[profile?.id]);
  const table=tables.find(r=>r.score_table_id===selected);
  const changeTable=id=>{const url=new URL(location.href),fragment=new URLSearchParams(url.hash.slice(1));fragment.delete("entry");url.hash=fragment.toString();history.replaceState(null,"",url);onSelect(id);};
  React.useEffect(()=>{if(!selected&&tables.length){const own=tables.find(r=>r.members.some(m=>m.user_id===String(profile?.id)));if(own)onSelect(own.score_table_id);}},[selected,tables.map(r=>r.id+":"+r.members.map(m=>m.user_id).join(",")).join("|"),profile?.id]);
  if(!profile)return null;
  return <div data-i18n-owned className="mb-4">
    {profile.is_admin&&<CreateClubTable language={language} tables={tables} collapsible onCreated={async item=>{await load();onSelect(item.score_table_id);}}/>}
    <TournamentField label={t("selectTable")}><select aria-label={t("selectTable")} className={inputStyle} value={table?.score_table_id||""} onChange={e=>changeTable(e.target.value)}><option value="">{t("selectTable")}</option>{tables.map(r=><option key={r.id} value={r.score_table_id}>{mt(language,"tableNumber",{number:r.number})}{r.display_name&&" · "+r.display_name}</option>)}</select></TournamentField>
    {!tables.length&&<p className="my-2">{t("noTables")}</p>}{message&&<p role="status">{t(message)}</p>}
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
