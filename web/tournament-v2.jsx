/* Uses the existing tournament API, drafts, components, account and catalog. */
function TournamentTableStatus({state,table,language,profile,run,busy}) {
  const t=k=>mt(language,k), session=table.session;
  const stamp=React.useMemo(()=>({server:Date.parse(state.server_now),local:performance.now()}),[state.server_now]);
  const [,tick]=React.useState(0);
  React.useEffect(()=>{const timer=setInterval(()=>tick(x=>x+1),1000);return()=>clearInterval(timer);},[]);
  if(!session)return null;
  const now=stamp.server+performance.now()-stamp.local;
  const remaining=session.ends_at?Math.max(0,Math.ceil((Date.parse(session.ends_at)-now)/1000)):null;
  const expired=Boolean(session.ends_at&&remaining===0);
  const player=state.players.find(p=>String(p.account_id||p.id)===String(profile?.id));
  const assigned=Boolean(player&&table.seats.includes(player.id));
  const checked=Boolean(assigned&&session.checked_in[player.id]);
  const ready=session.status==="READY_TO_START",waiting=["WAITING_FOR_CHECK_IN","READY_TO_START"].includes(session.status);
  const active=["IN_PROGRESS","TIME_EXPIRED","SCORE_PENDING"].includes(session.status);
  const duration=remaining===null?t("noTimeLimit"):Math.floor(remaining/60)+":"+String(remaining%60).padStart(2,"0");
  return <div className="my-3 rounded-xl border border-zinc-200 bg-warm p-3">
    <p className="font-semibold">{t(session.status)}</p>
    <ul className="my-2 flex flex-wrap gap-3 text-sm">{table.seats.map(id=><li key={id}><TournamentPerson person={state.players.find(p=>p.id===id)} language={language} fallback={v10(language,"Empty seat","空座位")}/> · {t(session.checked_in[id]?"checkedIn":"waitingCheckIn")}</li>)}</ul>
    {!profile&&waiting&&!state.settings.allow_guest_auto_enrollment&&<a className="underline" href={"/login?redirect_url="+encodeURIComponent(location.pathname+location.search+location.hash)}>{t("logIn")}</a>}
    {waiting&&<div className="flex flex-wrap gap-2">
      {assigned&&<TournamentButton disabled={busy||checked} onClick={()=>run("_check_in",{match_id:table.match_id})}>{t(checked?"checkedIn":"checkIn")}</TournamentButton>}
      {(assigned||profile?.is_admin)&&<TournamentButton disabled={busy||!ready} onClick={()=>run("_start_table",{match_id:table.match_id})}>{t("startMatch")}</TournamentButton>}
    </div>}
    {active&&session.ends_at&&<div className="mt-3"><b>{t("countdown")}: {duration}</b>{expired&&<p role="alert" className="mt-2 rounded-lg bg-red-100 p-3 text-xl font-black text-red-800">{t("timeUp")}</p>}<p className="mt-1 text-xs">{t("timeNote")}</p></div>}
    {profile?.is_admin&&active&&session.status!=="SCORE_PENDING"&&<details className="mt-3 text-sm"><summary>{t("resetTable")}</summary><TournamentButton disabled={busy} onClick={()=>{const reason=window.prompt(t("reason"));if(reason)run("reset_table",{match_id:table.match_id,reason});}}>{t("resetTable")}</TournamentButton></details>}
  </div>;
}
function TournamentCalculation({result,language}) {
  const t=k=>mt(language,k);
  if(result.rules.scoring_mode===placementMode)return <PlacementCalculation result={result} language={language}/>;
  return <div className="my-3 overflow-x-auto rounded-xl border p-3"><h4 className="font-bold">{t("calculation")}</h4>
    <table className="w-full text-left text-sm"><thead><tr>{["playerName","raw","returnPoint","pointDifference","convertedPoints","placement","placementPoints","gameScore"].map(k=><th className="p-2" key={k}>{t(k)}</th>)}</tr></thead>
    <tbody>{result.players.map(p=><tr key={p.id}><td className="p-2">{p.name}</td><td className="p-2">{p.rawScore}</td><td className="p-2">{p.returnPoint??result.rules.base_points}</td><td className="p-2">{p.pointDifference??"—"}</td><td className="p-2">{p.convertedPoints??"—"}<small> (÷ {result.rules.divisor??1000})</small></td><td className="p-2">{p.placement}</td><td className="p-2">{p.placementPoints}{p.placementPointsApplied===false&&" · "+t("winnerNoExtra")}</td><td className="p-2 font-bold">{p.gameScore}</td></tr>)}</tbody></table>
    {result.rules.scoring_mode==="return"&&<p className="mt-2 text-sm">{mt(language,"winnerFormula",{sum:result.players.find(p=>p.placement===1).winnerOtherTotal,score:result.players.find(p=>p.placement===1).gameScore})}</p>}
  </div>;
}
function TournamentPenalties({state,language,run,busy,canAdmin}) {
  const t=k=>mt(language,k);
  const [form,setForm]=useTournamentDraft("tm-penalty-"+state.id,{player_id:"",amount:"",reason:"",match_id:""});
  const active=!["locked","ended"].includes(state.status);
  const tables=[...state.rounds.flatMap(r=>r.tables.map(table=>({...table,roundLabel:t("round")+" "+r.number}))),...(state.finals?.tables||[]).map(table=>({...table,roundLabel:t("finals")}))];
  return <Card><h2 className="mb-3 text-xl font-bold">{t("penalty")}</h2>
    {canAdmin&&active&&<div className="space-y-3"><div className="grid gap-3 sm:grid-cols-2">
      <RegisteredUserCombobox label={t("playerName")} language={language} value={state.players.find(p=>p.id===form.player_id)||null} options={state.players} onChange={p=>setForm({...form,player_id:p?.id||"",match_id:""})} disabled={busy} required/>
      <TournamentField label={state.settings.scoring_mode===placementMode?v10(language,"Adjustment (positive deducts, negative rewards)","调整分（正数扣分，负数奖励）"):t("penaltyAmount")}><input className={inputStyle} type="number" min={state.settings.scoring_mode===placementMode?undefined:state.settings.min_unit} step={state.settings.scoring_mode===placementMode?"any":state.settings.min_unit||0.1} value={form.amount} onChange={e=>setForm({...form,amount:e.target.value})}/></TournamentField>
      <TournamentField label={t("penaltyReason")}><input className={inputStyle} maxLength="500" value={form.reason} onChange={e=>setForm({...form,reason:e.target.value})}/></TournamentField>
      <TournamentField label={t("optionalMatch")}><select className={inputStyle} value={form.match_id} onChange={e=>setForm({...form,match_id:e.target.value})}><option value="">{t("noLinkedMatch")}</option>{tables.filter(tb=>tb.seats.includes(form.player_id)).map(tb=><option key={tb.match_id} value={tb.match_id}>{tb.roundLabel} · {mt(language,"tableNumber",{number:tb.number})}</option>)}</select></TournamentField>
    </div><TournamentButton disabled={busy||!state.players.some(p=>p.id===form.player_id)||!form.reason.trim()||(state.settings.scoring_mode===placementMode?Number(form.amount)===0:Number(form.amount)<=0)} onClick={async()=>{if(await run("penalty_add",form))setForm({...form,amount:"",reason:"",match_id:""});}}>{t("addPenalty")}</TournamentButton></div>}
    <div className="mt-3 space-y-2">{(state.penalties||[]).map(p=><div className="rounded-xl bg-warm p-3 text-sm" key={p.id}>
      <p>{state.players.find(x=>x.id===p.player_id)?.name} · {Number(p.amount)>0?"−"+p.amount:"+"+Math.abs(Number(p.amount))} · {t("penalty_"+p.status)} · {new Date(p.created_at).toLocaleString()}</p>
      <p>{p.reason}</p>{p.revoke_reason&&<p>{t("reason")}: {p.revoke_reason}</p>}
      {canAdmin&&active&&p.status==="active"&&<div className="mt-2 flex gap-2"><TournamentButton disabled={busy} onClick={()=>{const amount=window.prompt(t("penaltyAmount"),p.amount);if(amount===null)return;const reason=window.prompt(t("penaltyReason"));if(reason)run("penalty_edit",{penalty_id:p.id,amount,reason});}}>{t("editPenalty")}</TournamentButton><TournamentButton disabled={busy} onClick={()=>{const reason=window.prompt(t("revokeReason"));if(reason)run("penalty_revoke",{penalty_id:p.id,reason});}}>{t("revokePenalty")}</TournamentButton></div>}
    </div>)}</div>
  </Card>;
}
function TournamentAccountBinding({player,state,language,run,busy}) {
 const bound=()=>player.account_id?{id:player.account_id,name:player.name}:null;
 const [choice,setChoice]=React.useState(bound),pending=React.useRef(false),lastBinding=React.useRef({id:player.id,account:player.account_id,name:player.name});
 React.useEffect(()=>{
  const old=lastBinding.current;lastBinding.current={id:player.id,account:player.account_id,name:player.name};
  setChoice(previous=>{
   if(old.id!==player.id||old.account!==player.account_id)return previous?.id===player.account_id?previous:bound();
   return old.name!==player.name&&previous?.id===player.account_id?{...previous,name:player.name}:previous;
  });
 },[player.id,player.account_id,player.name]);
 const select=async person=>{
  setChoice(person);if(!person||pending.current)return;
  pending.current=true;
  try{if(!await run("bind_account",{player_id:player.id,account_id:person.id}))setChoice(null);}
  finally{pending.current=false;}
 };
 return <RegisteredUserCombobox label={player.name} language={language} disabled={busy||["locked","ended"].includes(state.status)} value={choice} excludeIds={state.players.filter(other=>other.id!==player.id).map(other=>other.account_id||other.id)} onChange={select}/>;
}
function TournamentAccountBindings({state,language,run,busy}) {
 return <details className="my-3"><summary>{mt(language,"accountBindings")}</summary><p className="my-2 text-sm text-zinc-600">{mt(language,"bindingNote")}</p><div className="grid gap-3 sm:grid-cols-2">{state.players.filter(p=>p.participant_type!=="guest").map(p=><TournamentAccountBinding key={p.id} player={p} state={state} language={language} run={run} busy={busy}/>)}</div></details>;
}
