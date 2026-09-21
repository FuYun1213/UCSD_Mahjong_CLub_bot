/* Reuses the dashboard's Card, account/session and shared language setting. */
const mt = (lang, key, vars) => MahjongI18n.t(lang, key, vars);
const inputStyle = "w-full rounded-xl border border-zinc-300 bg-white px-3 py-2 text-sm";
const buttonStyle = "rounded-xl border border-zinc-300 bg-white px-4 py-2 text-sm font-bold hover:bg-warm disabled:opacity-40";
function TournamentButton({children,...props}) { return <button type="button" className={buttonStyle} {...props}>{children}</button>; }
function TournamentField({label,children}) {return <label className="block text-sm font-semibold text-zinc-600"><span className="mb-1 block">{label}</span>{children}</label>;}
function useTournamentDraft(key, initial) {
  const restore = () => {try {return JSON.parse(localStorage.getItem(key)) ?? initial;} catch {return initial;}};
  const [value, update] = React.useState(restore);
  const currentKey = React.useRef(key);
  React.useEffect(() => {if(currentKey.current!==key){currentKey.current=key;update(restore());}},[key]);
  const save = next => {update(old => {const result=typeof next==="function"?next(old):next; localStorage.setItem(key,JSON.stringify(result)); return result;});};
  return [value,save];
}
async function tournamentApi(url, body) {
  let response;
  try {response=await fetch(url,{credentials:"include",cache:"no-store",...(body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})});}
  catch {throw Object.assign(new Error("requestFailed"),{network:true});}
  let value;try{value=await response.json();}catch{throw Object.assign(new Error("requestFailed"),{network:true});}
  if(response.status===401&&body!==undefined) location.assign(globalLoginUrl());
  if(!response.ok) {
    const code=typeof value.detail==="object"&&!Array.isArray(value.detail)?value.detail?.code:value.code;
    throw Object.assign(new Error(Object.prototype.hasOwnProperty.call(MahjongI18n.entries,code)?code:"requestFailed"),{status:response.status});
  }
  return value;
}
async function downloadTournamentQr(url, filename) {
  const response=await fetch(url);
  if(!response.ok)throw new Error("downloadError");
  const blob=await response.blob(), object=URL.createObjectURL(blob), anchor=document.createElement("a");
  anchor.href=object;anchor.download=filename+".png";document.body.append(anchor);anchor.click();anchor.remove();
  setTimeout(()=>URL.revokeObjectURL(object),1000);
}
function TournamentQr({language,target,title}) {
  const [error,setError]=React.useState("");
  const url="/api/qr.png?"+new URLSearchParams({target,filename:title});
  return <div className="my-4 rounded-xl border border-zinc-200 p-4"><h3 className="font-bold">{mt(language,"qr")} · {title}</h3>
    <img src={url} alt={mt(language,"qr")} className="my-2 h-40 w-40" />
    <p className="mb-2 text-sm text-zinc-500">{mt(language,"qrNote")}</p>
    <TournamentButton onClick={async()=>{try{await downloadTournamentQr(url,title);setError("");}catch(e){setError(e.message);}}}>{mt(language,"download")}</TournamentButton>
    {error&&<p role="alert">{mt(language,error)}</p>}
  </div>;
}
function DeliveryStatus({language,delivery,onRetry}) {
  if(!delivery)return null;
  return <div className="rounded-xl bg-warm p-3 text-sm" role="status">
    <b>{mt(language,"externalResult")}: </b>{mt(language,delivery.status)}
    {delivery.error_code&&<p>{mt(language,MahjongI18n.entries[delivery.error_code]?delivery.error_code:"requestFailed")}</p>}
    {["failed","pending"].includes(delivery.status)&&onRetry&&<div className="mt-2"><TournamentButton onClick={()=>onRetry(delivery.request_id)}>{mt(language,"retry")}</TournamentButton></div>}
  </div>;
}
function ExternalApiSettings({language,profile}) {
  const [config,setConfig]=React.useState(null),[message,setMessage]=React.useState(""),[busy,setBusy]=React.useState(false),[deliveries,setDeliveries]=React.useState([]);
  // Write-only secret: component memory only, never useTournamentDraft/localStorage.
  const [apiKey,setApiKey]=React.useState(""),operation=React.useRef(false);
  const load=async()=>{try{setConfig(await tournamentApi("/api/external-config"));setDeliveries((await tournamentApi("/api/external-deliveries")).deliveries);}catch(e){setMessage(e.message);}};
  React.useEffect(()=>{if(profile?.is_admin)load();},[profile?.is_admin]);
  if(!profile?.is_admin)return null;
  const run=async(action)=>{if(operation.current)return;operation.current=true;setBusy(true);setMessage("");try{
    if(action==="save"||action==="bind"){
      const body={endpoint:config.endpoint,enabled:action==="bind"?true:config.enabled,adapter:config.adapter,...(apiKey?{api_key:apiKey}:{})};
      const saved=await tournamentApi("/api/external-config",body);
      setApiKey("");setConfig(saved);setMessage("apiSavedChecking");
      // Read back committed server state; a click or a successful HTTP call alone is not proof.
      const current=await tournamentApi("/api/external-config");
      setConfig(current);
      if(current.endpoint!==body.endpoint.trim()||current.adapter!==body.adapter||current.enabled!==body.enabled||!current.saved_at||(body.api_key&&!current.key_configured))throw new Error("config_verification_failed");
      setMessage("apiSaved");
      if(action==="bind"){
        const test=await tournamentApi("/api/external-test",{});
        setConfig(c=>({...c,last_test:test}));setMessage("apiSaved");
      }
    }else if(action==="refresh"){await load();}
    else{
      if(apiKey)throw new Error("saveKeyFirst");
      const current=await tournamentApi("/api/external-config");
      if(current.endpoint!==config.endpoint||current.adapter!==config.adapter||current.enabled!==config.enabled)throw new Error("saveConfigFirst");
      const test=await tournamentApi("/api/external-test",{});
      setConfig(c=>({...c,...current,last_test:test}));setMessage(test.code);
    }
  }catch(e){setMessage(e.message);}finally{operation.current=false;setBusy(false);}};
  return <div data-i18n-owned className="mb-5"><Card><h2 className="mb-4 text-xl font-bold">{mt(language,"api")}</h2>
    {config&&<div className="space-y-4">
      <TournamentField label={mt(language,"endpoint")}><input aria-label={mt(language,"endpoint")} className={inputStyle} disabled={busy} value={config.endpoint} placeholder="https://…" onChange={e=>setConfig({...config,endpoint:e.target.value})}/></TournamentField>
      <p className="text-sm text-zinc-600">{mt(language,"keyHelp")}</p>
      {config.adapter==="narts"&&<TournamentField label={mt(language,"apiKey")}><input type="password" aria-label={mt(language,"apiKey")} className={inputStyle} value={apiKey} maxLength={4096} autoComplete="new-password" spellCheck={false} disabled={busy} placeholder={mt(language,config.key_configured?"keepKey":"enterKey")} onChange={e=>setApiKey(e.target.value)}/></TournamentField>}
      <TournamentButton disabled={busy} onClick={()=>setConfig({...config,adapter:"narts",endpoint:"https://riichi.one/api/external/v1/matches"})}>{mt(language,"nartsPreset")}</TournamentButton>
      <div className="flex flex-wrap gap-4">
        <label><input type="checkbox" disabled={busy} checked={config.enabled} onChange={e=>setConfig({...config,enabled:e.target.checked})}/> {mt(language,"enabled")}</label>
        <TournamentField label={mt(language,"adapter")}><select disabled={busy} className={inputStyle} value={config.adapter} onChange={e=>{setConfig({...config,adapter:e.target.value});setApiKey("");}}><option value="narts">NARTS</option><option value="json">{mt(language,"json")}</option></select></TournamentField>
      </div>
      <p className="text-sm text-zinc-500">{mt(language,"apiNote")}</p><p className="text-sm text-zinc-500">{mt(language,"testNote")}</p><p className="text-sm text-zinc-500">{mt(language,"nartsNote")}</p>
      <p>{mt(language,config.key_configured?"keyConfigured":"keyMissing")} · {mt(language,config.last_test?.code||"noTest")}{config.last_test&&" · "+new Date(config.last_test.at).toLocaleString()}</p>
      <p role="status" className="text-sm">{mt(language,config.enabled?"syncEnabled":"disabled")}{config.saved_at&&" · "+mt(language,"configSavedAt")+": "+new Date(config.saved_at).toLocaleString()}</p>
      <div className="flex flex-wrap gap-2">
        {config.adapter==="narts"&&<TournamentButton disabled={busy||(!apiKey&&!config.key_configured)} onClick={()=>run("bind")}>{mt(language,"saveEnableTest")}</TournamentButton>}
        <TournamentButton disabled={busy} onClick={()=>run("save")}>{mt(language,"saveConfig")}</TournamentButton>
        <TournamentButton disabled={busy} onClick={()=>run("test")}>{mt(language,"test")}</TournamentButton>
        <TournamentButton disabled={busy} onClick={()=>run("refresh")}>{mt(language,"refreshConfig")}</TournamentButton>
      </div>
    </div>}
    {message&&<p role="status" className="mt-3">{mt(language,message)}</p>}
    <GlobalTableLabels language={language}/>
    <details className="mt-4"><summary>{mt(language,"deliveries")}</summary><div className="space-y-2 mt-3">{deliveries.map(d=><DeliveryStatus key={d.request_id} language={language} delivery={d} onRetry={async key=>{if(busy)return;setBusy(true);try{await tournamentApi("/api/external-deliveries/"+key+"/retry",{});await load();}catch(e){setMessage(e.message);}finally{setBusy(false);}}}/>)}</div></details>
  </Card></div>;
}
function TournamentSettings({state,language,run,busy}) {
  const [saved,setForm]=useTournamentDraft("tm-settings-"+state.id,{...state.settings,name:state.name});
  const form={...state.settings,...saved};
  const t=k=>mt(language,k),change=(key,value)=>setForm({...form,[key]:value});
  const uma=Array.isArray(form.uma)?form.uma:String(form.uma).split(/[,，]/).map(Number);
  const numberFields={table_size:"tableSize",base_points:"basePoints",bye_score:"byeScore",qualifying_rank:"qualifyingRank"};
  return <details className="mb-5" open={["draft","registration"].includes(state.status)}><summary className="cursor-pointer text-lg font-bold">{t("settings")}</summary>
    <PlacementSettings language={language} value={form} onChange={setForm} disabled={state.rounds.length>0}/>
    {form.scoring_mode!==placementMode&&<p className="my-3 text-sm">{t(form.scoring_mode==="legacy"?"legacyRule":"returnRule")}</p>}
    {form.scoring_mode==="legacy"&&<TournamentButton disabled={busy} onClick={()=>setForm({...form,scoring_mode:"return",table_size:4,uma:uma.length===4?uma:[30,10,-10,-30]})}>{t("useReturnRule")}</TournamentButton>}
    <div className="mt-4 grid gap-3 sm:grid-cols-3">
      <TournamentField label={t("name")}><input className={inputStyle} value={form.name} onChange={e=>change("name",e.target.value)}/></TournamentField>
      {Object.entries(numberFields).filter(([key])=>form.scoring_mode!==placementMode||!["base_points","bye_score","table_size"].includes(key)).map(([key,label])=><TournamentField key={key} label={t(label)}><input className={inputStyle} type="number" step="any" value={form[key]} onChange={e=>change(key,e.target.value)}/></TournamentField>)}
      {form.scoring_mode!==placementMode&&<TournamentField label={t("returnPoint")}><input className={inputStyle} type="number" step="any" value={form.return_point} onChange={e=>change("return_point",e.target.value)}/></TournamentField>}
      <TournamentTimeLimit value={form.time_limit_seconds??null} onChange={value=>change("time_limit_seconds",value)} language={language}/>
      {form.scoring_mode!==placementMode&&uma.map((value,i)=><TournamentField key={"uma-"+i} label={mt(language,"placementSetting",{rank:i+1})}><input className={inputStyle} type="number" step="any" value={value} onChange={e=>change("uma",uma.map((v,j)=>j===i?e.target.value:v))}/></TournamentField>)}
      <TournamentField label={t("pairing")}><select className={inputStyle} value={form.pairing} onChange={e=>change("pairing",e.target.value)}><option value="swiss">{t("swiss")}</option><option value="random">{t("random")}</option></select></TournamentField>
      <label><input type="checkbox" checked={form.advance_on_tie} onChange={e=>change("advance_on_tie",e.target.checked)}/> {t("advanceOnTie")}</label>
    </div>
    <p className="my-3 text-sm text-zinc-500">{t("rulesNote")} {form.scoring_mode!==placementMode&&t("returnRuleNote")}</p>
    <div className="mt-3"><TournamentButton disabled={busy||!placementValid(form)||(form.time_limit_seconds!==null&&!(Number(form.time_limit_seconds)>0))||["ended","locked","finals_running"].includes(state.status)} onClick={()=> {
      const settings=Object.fromEntries(Object.keys(form).filter(k=>k!=="name"&&!["divisor","raw_step","min_unit"].includes(k)).map(k=>[k,form[k]]));
      for(const key of [...Object.keys(numberFields),"return_point"])settings[key]=Number(settings[key]);
      settings.uma=uma.map(Number);settings.time_limit_seconds=form.time_limit_seconds;
      run("settings",{name:form.name,settings});
    }}>{t("save")}</TournamentButton></div>
  </details>;
}
function TournamentSeating({tables,state,language,onConfirm,disabled}) {
  const [seats,setSeats]=React.useState(tables.map(t=>t.seats));
  React.useEffect(()=>setSeats(tables.map(t=>t.seats)),[JSON.stringify(tables.map(t=>t.seats))]);
  const names=Object.fromEntries(state.players.map(p=>[p.id,p.name])), all=tables.flatMap(table=>table.seats);
  const swap=(i,j,pid)=>{const next=seats.map(g=>g.slice());let old=next[i][j];if(pid)for(let a=0;a<next.length;a++)for(let b=0;b<next[a].length;b++)if(next[a][b]===pid)next[a][b]=old;next[i][j]=pid;setSeats(next);};
  return <div><div className="grid gap-3 md:grid-cols-2">{tables.map((table,i)=><div className="rounded-xl border p-3" key={table.number}><b>{mt(language,"tableNumber",{number:table.display_number||table.number})}{table.name&&" · "+table.name}</b>
    {seats[i]?.map((pid,j)=><div key={j} className="my-2 flex gap-2 items-center"><span>{"ESWN"[j]||j+1}</span><RegisteredUserCombobox label={mt(language,"seat")+" "+table.number+"-"+(j+1)} language={language} value={state.players.find(p=>p.id===pid)||null} options={state.players.filter(p=>all.includes(p.id))} onChange={p=>swap(i,j,p?.id||null)} disabled={disabled}/></div>)}
  </div>)}</div><div className="mt-3"><TournamentButton disabled={disabled||seats.flat().some(id=>!id)||new Set(seats.flat()).size!==all.length} onClick={()=>onConfirm(seats)}>{mt(language,tables[0]?.hands?"startFinals":"confirmSeats")}</TournamentButton></div></div>;
}
function TournamentScoreTable({state,round,table,language,run,busy,canAdmin,profile}) {
  const t=k=>mt(language,k),names=Object.fromEntries(state.players.map(p=>[p.id,p.name]));
  const [scores,setScores]=useTournamentDraft("tm-score-"+table.match_id+"-"+round.revision,Object.fromEntries(table.seats.map(id=>[id,table.draft?.players.find(p=>p.id===id)?.rawScore??""])));
  const [preview,setPreview]=React.useState(null),[previewError,setPreviewError]=React.useState(""),[calculating,setCalculating]=React.useState(false);
  const signature=JSON.stringify([scores,state.settings]);
  const calculated=preview?.signature===signature?preview.result:null;
  const official=table.result||table.draft;
  const started=["IN_PROGRESS","TIME_EXPIRED","SCORE_PENDING"].includes(table.session?.status);
  async function calculate(){
    if(calculating)return;setCalculating(true);setPreviewError("");
    try{const result=await tournamentApi("/api/tournaments/"+state.id+"/tables/"+table.match_id+"/preview-score",{scores});setPreview({signature,result});}
    catch(e){setPreviewError(e.message);}finally{setCalculating(false);}
  }
  const target="/?"+new URLSearchParams({tournament:state.id,table:String(table.number)});
  return <div className="rounded-xl border border-zinc-200 p-4" id={"tm-table-"+table.number}>
    <h3 className="font-bold">{state.name} · {t("round")} {round.number} · {mt(language,"tableNumber",{number:table.display_number||table.number})}{table.name&&" · "+table.name}</h3>

    <TournamentTableStatus state={state} table={table} language={language} profile={profile} run={run} busy={busy}/>
    <div className="overflow-x-auto"><table className="my-3 w-full text-left text-sm"><thead><tr>{["seat","playerName","raw","placement",...(state.settings.scoring_mode===placementMode?[]:["uma"]),"gameScore"].map(k=><th className="p-2" key={k}>{t(k)}</th>)}</tr></thead>
      <tbody>{table.seats.map((id,i)=>{const result=official?.players.find(p=>p.id===id);return <tr key={id}><td className="p-2">{"ESWN"[i]||i+1}</td><td className="p-2"><TournamentPerson person={state.players.find(p=>p.id===id)} language={language} fallback={v10(language,"Empty seat","空座位")}/></td><td className="p-2">{canAdmin&&round.status!=="confirmed"?<input aria-label={names[id]+" "+t("raw")} className={inputStyle+" min-w-[100px]"} type="number" step={state.settings.raw_step} value={scores[id]??""} onChange={e=>setScores({...scores,[id]:e.target.value})}/>:result?.rawScore??"—"}</td><td className="p-2">{result?.placement??"—"}</td>{state.settings.scoring_mode!==placementMode&&<td className="p-2">{result?.placementPoints??"—"}</td>}<td className="p-2">{result?.gameScore??"—"}</td></tr>;})}</tbody>
    </table></div>
    {canAdmin&&round.status!=="confirmed"&&<div className="flex flex-wrap gap-2">
      <TournamentButton disabled={busy||calculating} onClick={calculate}>{t("previewCalculation")}</TournamentButton>
      <TournamentButton disabled={busy||!calculated||!started} onClick={()=>run("score_table",{table:table.number,scores},t("confirmScore")+"\\n"+state.name+" · "+t("round")+" "+round.number+" · "+t("table")+" "+table.number+"\\n"+calculated.players.map(p=>p.name+": "+p.rawScore+" → "+p.gameScore).join("\\n"))}>{t("scoreDraft")}</TournamentButton>
    </div>}
    {previewError&&<p role="alert">{t(previewError)}</p>}
    {(calculated||official)&&<TournamentCalculation language={language} result={calculated||official}/>}
    {table.draft&&!table.result&&<p className="my-2 text-sm">{t("draftNote")}</p>}
    {table.result&&<p className="my-2 text-sm">{t("localSaved")} · {t("confirmed")}</p>}
    <DeliveryStatus language={language} delivery={state.deliveries?.find(d=>d.request_id===table.result?.request_id)} onRetry={canAdmin?key=>run("_retry",{key}):null}/>
  </div>;
}
function TournamentFinalsTable({state,table,language,run,busy,canAdmin,profile}) {
  const t=k=>mt(language,k), names=Object.fromEntries(state.players.map(p=>[p.id,p.name]));
  const [deltas,setDeltas]=useTournamentDraft("tm-hand-"+state.id+"-"+table.number,Object.fromEntries(table.seats.map(id=>[id,""])));
  const started=["IN_PROGRESS","TIME_EXPIRED"].includes(table.session?.status);
  const [reason,setReason]=React.useState(""),last=table.hands.filter(h=>!h.void).at(-1);
  const mutate=async(action)=>{const ok=await run(action,{table:table.number,deltas,hand_id:last?.id,reason},
    t("confirmScore")+"\n"+state.name+" · "+t("table")+" "+table.number+"\n"+table.seats.map(id=>names[id]+": "+deltas[id]).join("\n"));
    if(ok&&action==="hand")setDeltas(Object.fromEntries(table.seats.map(id=>[id,""])));};
  return <div className="rounded-xl border p-4" id={"tm-table-"+table.number}><h3 className="font-bold">{state.name} · {t("finals")} · {mt(language,"tableNumber",{number:table.display_number||table.number})}{table.name&&" · "+table.name}</h3>
    <TournamentTableStatus state={state} table={table} language={language} profile={profile} run={run} busy={busy}/>
    <ul className="my-3 text-sm">{table.seats.map(id=>{const row=state.standings.find(r=>r.id===id);return <li key={id}>{names[id]} · {t("finalsStart")}: {row?.finals_start} · {t("finalsAdded")}: {row?.finals_added} · {t("total")}: {row?.score}</li>;})}</ul>
    <div className="my-3 grid gap-2 sm:grid-cols-2">{table.seats.map(id=><TournamentField key={id} label={names[id]+" · "+t("delta")}><input aria-label={names[id]+" "+t("delta")} className={inputStyle} type="number" step={state.settings.min_unit} value={deltas[id]??""} disabled={!canAdmin||state.status!=="finals_running"} onChange={e=>setDeltas({...deltas,[id]:e.target.value})}/></TournamentField>)}</div>
    {canAdmin&&state.status==="finals_running"&&<div className="space-y-3"><TournamentButton disabled={busy||!started} onClick={()=>mutate("hand")}>{t("saveHand")}</TournamentButton>
      {last&&<details><summary>{t("correctHand")} / {t("undoHand")}</summary><input className={inputStyle+" my-2"} placeholder={t("reason")} value={reason} onChange={e=>setReason(e.target.value)}/><div className="flex gap-2"><TournamentButton disabled={busy||!reason.trim()} onClick={()=>mutate("correct_hand")}>{t("correctHand")}</TournamentButton><TournamentButton disabled={busy||!reason.trim()} onClick={()=>run("undo_hand",{table:table.number,hand_id:last.id,reason})}>{t("undoHand")}</TournamentButton></div></details>}
    </div>}
    <h4 className="mt-4 font-bold">{t("history")}</h4><div className="space-y-2">{table.hands.map(h=><div key={h.id} className={"rounded-xl bg-warm p-3 text-sm "+(h.void?"opacity-60":"")}>
      <p>{t("hand")} {h.number} · {new Date(h.at).toLocaleString()} · {t(h.void?"corrected":"confirmed")}</p>
      <p>{table.seats.map(id=>names[id]+": "+h.deltas[id]).join(" / ")}</p>
      {h.reason&&<p>{h.reason}</p>}
      <DeliveryStatus language={language} delivery={state.deliveries?.find(d=>d.request_id===h.request_id)} onRetry={canAdmin?key=>run("_retry",{key}):null}/>
    </div>)}</div>
  </div>;
}
function TournamentRankings({state,language}) {
  const t=k=>mt(language,k), rows=state.standings||[],[target,setTarget]=React.useState("");
  const [selected,setSelected]=React.useState("");
  const final=state.finals?.status==="active";
  const cut=rows[Math.min(rows.length,state.settings.qualifying_rank)-1],leader=rows[0];
  const targetRow=rows.find(r=>r.id===target)||cut||leader, player=rows.find(r=>r.id===selected)||rows.at(-1);
  const gap=(a,b)=>b?+(b.score-a.score).toFixed(6):0;
  const needed=(a,b)=>Math.max(0,+(gap(a,b)+(state.settings.advance_on_tie?0:(state.settings.min_unit??0.1))).toFixed(6));
  return <Card><h2 className="mb-4 text-xl font-bold">{t("standings")}</h2><div className="overflow-x-auto">
    <table className="w-full text-sm text-left"><thead><tr>{["rank","playerName","roundScore","gameTotal","penaltyTotal","total","completedRounds",...(final?["preliminary","finalsStart","finalsAdded"]:[])].map(k=><th className="p-2" key={k}>{t(k)}</th>)}</tr></thead>
    <tbody>{rows.map(r=><tr key={r.id} className="border-t"><td className="p-2">{r.rank}</td><td className="p-2"><TournamentPerson person={r} language={language}/></td><td className="p-2">{r.round_score}</td><td className="p-2">{r.game_score}</td><td className="p-2">{r.penalty_total}</td><td className="p-2 font-bold">{r.score}</td><td className="p-2">{r.completed_rounds}</td>{final&&["preliminary_score","finals_start","finals_added"].map(k=><td className="p-2" key={k}>{r[k]}</td>)}</tr>)}</tbody></table>
    </div><p className="my-3 text-sm text-zinc-500">{t("tieRules")}</p>
    <h2 className="mt-6 mb-3 text-xl font-bold">{t("comeback")}</h2>
    {rows.length>0&&<><div className="grid gap-3 sm:grid-cols-2">
      <RegisteredUserCombobox label={t("playerName")} language={language} value={rows.find(r=>r.id===selected)||null} options={rows} onChange={p=>setSelected(p?.id||"")}/>
      <RegisteredUserCombobox label={t("target")} language={language} value={rows.find(r=>r.id===target)||null} options={rows} onChange={p=>setTarget(p?.id||"")}/>
    </div><p className="my-3 rounded-xl bg-warm p-3">{player.id===targetRow.id?t("sameTarget"):mt(language,"comebackNote",{points:needed(player,targetRow),mode:t(state.settings.advance_on_tie?"tie":"overtake")})}</p>
    <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr>{["rank","playerName","total","leaderGap","previousGap","cutoffGap","targetGap","netNeeded"].map(k=><th className="p-2" key={k}>{t(k)}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={r.id} className="border-t"><td className="p-2">{r.rank}</td><td className="p-2">{r.name}</td><td className="p-2">{r.score}</td><td className="p-2">{gap(r,leader)}</td><td className="p-2">{gap(r,rows[i-1])}</td><td className="p-2">{gap(r,cut)}</td><td className="p-2">{gap(r,targetRow)}</td><td className="p-2">{r.id===targetRow?.id?"—":needed(r,targetRow)}</td></tr>)}</tbody></table></div></>}
    <p className="mt-3 text-sm text-zinc-500">{t("cutoffNote")}</p>
  </Card>;
}
function TournamentMode({language,profile,players:clubPlayers=[]}) {
  const t=k=>mt(language,k),canAdmin=Boolean(profile?.is_admin);
  const [list,setList]=React.useState([]),[id,setId]=React.useState(()=>new URLSearchParams(location.search).get("tournament")||localStorage.getItem("tm-current")||"");
  const [state,setState]=React.useState(null),[catalog,setCatalog]=React.useState([]),[accounts,setAccounts]=React.useState([]),[message,setMessage]=React.useState(""),[busy,setBusy]=React.useState(false),busyRef=React.useRef(false);
  const [newName,setNewName]=useTournamentDraft("tm-new-name",""),[selectedPlayer,setSelectedPlayer]=useTournamentDraft("tm-registered-player",null),[permanent,setPermanent]=React.useState(false);
  const [finalForm,setFinalForm]=useTournamentDraft("tm-finals-"+id,{entrants:[],carry:"all",ratio:1});
  const [reason,setReason]=React.useState(""),[finalChoice,setFinalChoice]=React.useState(null);
  const [newLimit,setNewLimit]=useTournamentDraft("tm-new-time",null);
  const [newRules,setNewRules]=useTournamentDraft("tm-new-rules-v10",{scoring_mode:"return",allow_guest_auto_enrollment:false});
  const load=async()=>{try{setList((await tournamentApi("/api/tournaments")).tournaments);if(id){const next=await tournamentApi("/api/tournaments/"+id+(canAdmin?"/admin":""));setState(old=>old?.id===next.id&&old.version>next.version?old:next);}}catch(e){setMessage(e.message);}};
  React.useEffect(()=>{setState(null);load();const timer=setInterval(()=>{if(!busyRef.current)load();},5000);return()=>clearInterval(timer);},[id,canAdmin]);
  React.useEffect(()=>{if(id){localStorage.setItem("tm-current",id);const u=new URL(location.href);u.searchParams.set("tournament",id);history.replaceState(null,"",u);}},[id]);
  React.useEffect(()=>{if(state){const table=new URLSearchParams(location.search).get("table");if(table)document.getElementById("tm-table-"+table)?.scrollIntoView({block:"nearest"});}},[state?.id]);
  async function run(action,data={},confirmation) {
    if(busyRef.current)return false;
    const label={score_table:"scoreDraft",confirm_seats:"confirmSeats",confirm_round:"confirmRound",preview_finals:"previewFinals",start_finals:"startFinals",hand:"saveHand",correct_hand:"correctHand",undo_hand:"undoHand",reopen_round:"reopenRound",finish_swiss:"finishSwiss"}[action]||action;
    if(action!=="_retry"&&!window.confirm(confirmation||mt(language,"confirmAction",{action:t(label)})))return false;
    busyRef.current=true;setBusy(true);setMessage("");
    const cacheKey="tm-pending-"+(id||"create");
    try{
      if(action==="_retry"){await tournamentApi("/api/external-deliveries/"+data.key+"/retry",{});await load();}
      else {
        const signature=JSON.stringify([action,data]),cached=JSON.parse(localStorage.getItem(cacheKey)||"null");
        const body=cached?.signature===signature?cached.body:{...data,request_id:MahjongI18n.key(),...(action==="create"?{}:{version:state.version})};
        localStorage.setItem(cacheKey,JSON.stringify({signature,body}));
        if(["_check_in","_start_table"].includes(action)){
          const entryToken=new URLSearchParams(location.hash.slice(1)).get("entry");
          if(action==="_check_in"&&entryToken){
            const info=await tournamentApi("/api/table-join-tokens/"+encodeURIComponent(entryToken));
            const target=[...state.rounds.flatMap(round=>round.tables),...(state.finals?.tables||[])].find(table=>table.match_id===data.match_id);
            if(!target||info.purpose!=="table_landing"||info.tournament_id!==id||info.table_id!==target.table_id)throw new Error("invalid_join_token");
            // The server resolves the assigned wind from this session's saved roster.
            await tournamentApi("/api/table-join-tokens/"+encodeURIComponent(entryToken)+"/join",{request_id:body.request_id,confirm_entry:true,match_id:data.match_id});
          }else{
            await tournamentApi("/api/tournaments/"+id+"/tables/"+data.match_id+(action==="_check_in"?"/check-in":"/start"),{request_id:body.request_id});
          }
          localStorage.removeItem(cacheKey);await load();
        }else{
          const value=await tournamentApi(action==="create"?"/api/tournaments":"/api/tournaments/"+id+"/actions",action==="create"?body:{action,data:body});
          localStorage.removeItem(cacheKey);
          if(action==="create"){setId(value.id);setNewName("");}else setState(value);
        }
      }
      setMessage(action==="score_table"?"draftNote":"localSaved");
      return true;
    }catch(e){if(e.status)localStorage.removeItem(cacheKey);setMessage(e.message);if(e.message==="stale_version")await load();return false;}
    finally{busyRef.current=false;setBusy(false);}
  }
  const names=Object.fromEntries((state?.players||[]).map(p=>[p.id,p.name])),current=state?.rounds.at(-1);
  return <div data-i18n-owned className="space-y-5">
    <Card><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-bold">{t("tournament")}</h2><TournamentButton disabled={busy} onClick={load}>{t("refresh")}</TournamentButton></div>
      <TournamentField label={t("select")}><select className={inputStyle} value={id} onChange={e=>{const url=new URL(location.href),fragment=new URLSearchParams(url.hash.slice(1));fragment.delete("entry");url.hash=fragment.toString();history.replaceState(null,"",url);setId(e.target.value);}}><option value="">{t("select")}</option>{list.map(s=><option key={s.id} value={s.id}>{s.name} · {t(s.status)}</option>)}</select></TournamentField>
      {canAdmin?<div className="mt-4 flex gap-2"><input aria-label={t("name")} className={inputStyle} placeholder={t("name")} value={newName} onChange={e=>setNewName(e.target.value)}/><TournamentButton disabled={busy||!placementValid(newRules)||!newName.trim()||(newLimit!==null&&!(Number(newLimit)>0))} onClick={()=>run("create",{name:newName,settings:{...newRules,time_limit_seconds:newLimit}})}>{t("create")}</TournamentButton></div>:<p className="mt-4 text-sm">{t("adminOnly")}</p>}
      {canAdmin&&<PlacementSettings language={language} value={newRules} onChange={setNewRules}/>}
      {canAdmin&&<TournamentTimeLimit value={newLimit} onChange={setNewLimit} language={language}/>}
      {(message||busy)&&<p className="mt-4 rounded-xl bg-warm p-3" role="status">{t(busy?"busy":message)}</p>}
    </Card>
    {state&&<>
      <Card><h2 className="mb-4 text-xl font-bold">{state.name} · {t(state.status)}</h2>
        {canAdmin&&<TournamentDeleteControl item={state} language={language} onDeleted={()=>{setId("");setState(null);localStorage.removeItem("tm-current");const u=new URL(location.href);u.searchParams.delete("tournament");history.replaceState(null,"",u);tournamentApi("/api/tournaments").then(r=>setList(r.tournaments));}}/>}
        {canAdmin&&<TournamentSettings state={state} language={language} run={run} busy={busy}/>}
        {!profile&&<GuestJoin tid={state.id} language={language} onJoined={load}/>}
        {canAdmin&&<GuestAdmin state={state} language={language} run={run} busy={busy}/>}
        {canAdmin&&<a className={buttonStyle+" inline-block my-3"} href={"/manual-score?tournament="+state.id}>{v10(language,"Manual competition scoring","比赛手动登分")}</a>}
        {canAdmin&&<TournamentAccountBindings state={state} accounts={accounts} language={language} run={run} busy={busy}/>}
        <h3 className="font-bold">{t("players")} ({state.players.length})</h3>
        <ul data-tournament-roster className="my-3 flex flex-wrap gap-2">{state.players.map(p=><li className="rounded-xl bg-warm px-3 py-2 text-sm" key={p.id}><TournamentPerson person={p} language={language}/>{canAdmin&&["draft","registration"].includes(state.status)&&<button className="ml-2 underline" onClick={()=>run("remove_player",{player_id:p.id})}>{t("remove")}</button>}</li>)}</ul>
        {canAdmin&&["draft","registration"].includes(state.status)&&<div className="space-y-3">
          <RegisteredUserCombobox label={t("playerName")} language={language} value={selectedPlayer} onChange={setSelectedPlayer} excludeIds={state.players.map(p=>p.account_id||p.id)} disabled={busy}/>
          <div className="flex flex-wrap gap-2"><TournamentButton disabled={busy||!selectedPlayer} onClick={async()=>{if(await run("player",{registered_user_id:selectedPlayer.id}))setSelectedPlayer(null);}}>{t("add")}</TournamentButton>
          {state.status==="draft"&&<TournamentButton disabled={busy} onClick={()=>run("register")}>{t("register")}</TournamentButton>}
          <TournamentButton disabled={busy||state.players.length<state.settings.table_size} onClick={()=>run("start")}>{t("start")}</TournamentButton></div>
        </div>}
      </Card>
      <Card><h2 className="mb-3 text-xl font-bold">{t("rounds")}</h2>
        {canAdmin&&state.status==="running"&&state.rounds.every(r=>r.status==="confirmed")&&<TournamentButton disabled={busy} onClick={()=>run("pair")}>{t(state.preview?"regenerate":"generate")}</TournamentButton>}
        {state.preview&&<div className="mt-3"><h3 className="my-2 font-bold">{t("preview")} · {t("round")} {state.preview.number}</h3>
          <p className="my-2 text-sm">{t("byes")}: {state.preview.byes.map(p=>names[p]).join(", ")||"—"} · {t("byeScore")}: {state.preview.bye_score}</p><p className="mb-3 text-sm text-zinc-500">{t("byeNote")}</p>
          {canAdmin&&<TournamentSeating tables={state.preview.tables} state={state} language={language} disabled={busy} onConfirm={seats=>run("confirm_seats",{seats})}/>}
        </div>}
        {state.rounds.map(r=><details key={r.id} open={r.id===current?.id} className="my-4"><summary className="font-bold">{t("round")} {r.number} · {t(r.status)}</summary><p className="my-2 text-sm">{t("byes")}: {r.byes.map(p=>names[p]).join(", ")||"—"} · {r.bye_score}</p><div className="mt-3 space-y-3">{r.tables.map(table=><TournamentScoreTable key={table.match_id} state={state} round={r} table={table} language={language} run={run} busy={busy} canAdmin={canAdmin} profile={profile}/>)}</div></details>)}
        {canAdmin&&<div className="flex flex-wrap gap-2">
          {state.status==="round_pending"&&<TournamentButton disabled={busy} onClick={()=>run("confirm_round")}>{t("confirmRound")}</TournamentButton>}
          {state.status==="running"&&current?.status==="confirmed"&&!state.preview&&<TournamentButton disabled={busy} onClick={()=>run("finish_swiss")}>{t("finishSwiss")}</TournamentButton>}
          {["running","swiss_finished"].includes(state.status)&&current?.status==="confirmed"&&!state.preview&&!state.finals&&<details><summary>{t("reopenRound")}</summary><input className={inputStyle} placeholder={t("reason")} value={reason} onChange={e=>setReason(e.target.value)}/><TournamentButton disabled={busy||!reason.trim()} onClick={()=>run("reopen_round",{reason})}>{t("reopenRound")}</TournamentButton></details>}
        </div>}
      </Card>
      {state.settings.scoring_mode===placementMode?<PlacementRankings state={state} language={language}/>:<TournamentRankings state={state} language={language}/>}
      <TournamentPenalties state={state} language={language} run={run} busy={busy} canAdmin={canAdmin} profile={profile}/>
      {state.settings.scoring_mode!==placementMode&&(state.status==="swiss_finished"||state.finals)&&<Card><h2 className="mb-4 text-xl font-bold">{t("finals")}</h2>
        {canAdmin&&state.status==="swiss_finished"&&<div className="space-y-3"><h3>{t("entrants")}</h3><RegisteredUserCombobox key={finalForm.entrants.join("|")} label={t("entrants")} language={language} value={finalChoice} options={state.swiss_standings} excludeIds={finalForm.entrants} onChange={p=>{setFinalChoice(null);if(p)setFinalForm({...finalForm,entrants:[...finalForm.entrants,p.id]});}}/>
          <ul className="flex flex-wrap gap-2">{finalForm.entrants.map(id=><li className="rounded-lg border p-2" key={id}>{names[id]||t("registeredNameUnavailable")} <button type="button" className="underline" onClick={()=>setFinalForm({...finalForm,entrants:finalForm.entrants.filter(uid=>uid!==id)})}>{t("remove")}</button></li>)}</ul>
          <TournamentField label={t("carry")}><select className={inputStyle} value={finalForm.carry} onChange={e=>setFinalForm({...finalForm,carry:e.target.value})}>{["all","ratio","zero"].map(k=><option value={k} key={k}>{t(k)}</option>)}</select></TournamentField>
          {finalForm.carry==="ratio"&&<TournamentField label={t("carryRatio")}><input className={inputStyle} type="number" min="0" max="1" step=".01" value={finalForm.ratio} onChange={e=>setFinalForm({...finalForm,ratio:e.target.value})}/></TournamentField>}
          <TournamentButton disabled={busy} onClick={()=>run("preview_finals",finalForm)}>{t("previewFinals")}</TournamentButton>
        </div>}
        {state.finals?.status==="preview"&&<div className="mt-4"><ul className="my-3">{state.finals.entrants.map(p=><li key={p}>{names[p]} · {t("preliminary")}: {state.finals.starts[p].preliminary_score} · {t("finalsStart")}: {state.finals.starts[p].finals_start}</li>)}</ul>{canAdmin&&<TournamentSeating tables={state.finals.tables} state={state} language={language} disabled={busy} onConfirm={seats=>run("start_finals",{seats})}/>}</div>}
        {state.finals?.status==="active"&&<><h3 className="my-3 font-bold">{t("handScoring")}</h3><p className="mb-4 text-sm text-zinc-500">{t("handNote")}</p><div className="space-y-4">{state.finals.tables.map(table=><TournamentFinalsTable key={table.number} state={state} table={table} language={language} run={run} busy={busy} canAdmin={canAdmin} profile={profile}/>)}</div></>}
      </Card>}
      {canAdmin&&<Card><div className="flex flex-wrap gap-2">
        {["swiss_finished","finals_running"].includes(state.status)&&<TournamentButton disabled={busy} onClick={()=>run("finish")}>{t("finish")}</TournamentButton>}
        {state.status==="ended"&&<TournamentButton disabled={busy} onClick={()=>run("lock")}>{t("lock")}</TournamentButton>}
        {["locked","ended"].includes(state.status)&&<><input className={inputStyle} value={reason} placeholder={t("reason")} onChange={e=>setReason(e.target.value)}/><TournamentButton disabled={busy||!reason.trim()} onClick={()=>run(state.status==="locked"?"unlock":"resume",{reason})}>{t(state.status==="locked"?"unlock":"resume")}</TournamentButton></>}
      </div><details className="mt-4"><summary>{t("audit")}</summary><div className="space-y-2 mt-3">{state.audit?.map(a=><details className="rounded-xl bg-warm p-3 text-sm" key={a.id}><summary>{new Date(a.at).toLocaleString()} · {t(a.action)} · {a.actor_name||t("registeredNameUnavailable")}</summary>{a.detail?.reason&&<p>{t("reason")}: {a.detail.reason}</p>}</details>)}</div></details></Card>}
    </>}
  </div>;
}

function GlobalTableLabels({language}) {
 const [names,setNames]=React.useState(null),[busy,setBusy]=React.useState(false),[message,setMessage]=React.useState("");
 React.useEffect(()=>{tournamentApi("/api/table-labels").then(v=>setNames(v.names)).catch(e=>setMessage(e.message));},[]);
 const t=k=>mt(language,k);
 return <details className="mt-5"><summary>{t("tables")}</summary>{names&&<div className="mt-3 grid gap-3 sm:grid-cols-3">{Array.from({length:Math.max(3,...Object.keys(names).map(Number))},(_,i)=><label key={i} className="flex items-center gap-2"><span>{i+1}</span><input className={inputStyle} value={names[i+1]||""} onChange={e=>setNames({...names,[i+1]:e.target.value})}/></label>)}</div>}
 <div className="mt-3 flex gap-2"><TournamentButton disabled={busy||!names} onClick={()=>setNames({...names,[Math.max(3,...Object.keys(names).map(Number))+1]:""})}>{t("addTable")}</TournamentButton><TournamentButton disabled={busy||!names} onClick={async()=>{if(busy)return;setBusy(true);try{setNames((await tournamentApi("/api/table-labels",{names})).names);setMessage("localSaved");}catch(e){setMessage(e.message);}finally{setBusy(false);}}}>{t("save")}</TournamentButton></div>
 {message&&<p role="status">{t(message)}</p>}</details>;
}
