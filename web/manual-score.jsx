/* Registered names are display values; every relation uses its stable account key. */
const manualWinds = ["east", "south", "west", "north"];
async function manualScoreApi(url, body) {
  let response, data;
  try {
    response=await fetch(url,{credentials:"same-origin",cache:"no-store",...(body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})});
    data=await response.json();
  } catch {throw Object.assign(new Error("requestFailed"),{fieldErrors:{}});}
  if(response.status===401) {location.assign(globalLoginUrl());throw new Error("not_authenticated");}
  if(!response.ok) throw Object.assign(new Error(data.detail?.code||"requestFailed"),{fieldErrors:data.detail?.field_errors||{},totals:data.detail?.score_totals,status:response.status});
  return data;
}
function ManualScorePage({language,profile,onRefresh}) {
  const t=(k,vars)=>MahjongI18n.t(language,k,vars), safeMessage=k=>t(MahjongI18n.entries[k]?k:"requestFailed");
  const table=new URLSearchParams(location.search).get("table")||"";
  const storageKey=profile?"manual-score-upload-v6:"+profile.id+":"+table:null;
  const emptyForm=()=>({played_at:"",players:Object.fromEntries(manualWinds.map(w=>[w,null])),scores:Object.fromEntries(manualWinds.map(w=>[w,""]))});
  const [form,setForm]=React.useState(emptyForm),[context,setContext]=React.useState(null),[errors,setErrors]=React.useState({});
  const [message,setMessage]=React.useState(""),[busy,setBusy]=React.useState(false),[result,setResult]=React.useState(null);
  const [uncertain,setUncertain]=React.useState(false),[loadedKey,setLoadedKey]=React.useState(null);
  const attempt=React.useRef(null),pending=React.useRef(false),formRef=React.useRef(form),resultRef=React.useRef(result);
  formRef.current=form;resultRef.current=result;
  const inputClass="w-full min-w-0 rounded-xl border border-zinc-300 bg-white px-3 py-2";
  function remember(nextAttempt=attempt.current,nextResult=resultRef.current,nextForm=formRef.current) {
    attempt.current=nextAttempt;
    if(storageKey)sessionStorage.setItem(storageKey,JSON.stringify({form:nextForm,attempt:nextAttempt,result:nextResult}));
  }
  React.useEffect(()=>{
    let active=true,saved=null;
    setContext(null);setErrors({});setMessage("");setLoadedKey(null);
    try{saved=storageKey?JSON.parse(sessionStorage.getItem(storageKey)):null;}catch{}
    const restored=saved?.form?.players&&saved?.form?.scores?saved.form:emptyForm();
    setForm(restored);setResult(saved?.result||null);attempt.current=saved?.attempt||null;setUncertain(Boolean(saved?.attempt?.uncertain));
    if(!profile)return;
    manualScoreApi("/api/manual-score/context"+(table?"?table="+encodeURIComponent(table):"")).then(async data=>{
      if(!active)return;setContext(data);
      const players=Object.fromEntries(manualWinds.map(w=>[w,restored.players[w]||data.players[w]||null]));
      const ids=[...new Set(Object.values(players).filter(Boolean).map(p=>p.id))];
      if(ids.length){
        try{
          const found=await manualScoreApi("/api/registered-users?ids="+encodeURIComponent(ids.join(",")));
          const byId=new Map(found.users.map(p=>[String(p.id),p]));
          for(const wind of manualWinds)if(players[wind])players[wind]=byId.get(String(players[wind].id))||null;
          if(saved?.result&&active)setResult({...saved.result,result:{...saved.result.result,players:Object.fromEntries(manualWinds.map(w=>{
            const item=saved.result.result.players[w],person=byId.get(String(item.user.id));
            return [w,{...item,user:person||item.user}];
          }))}});
        }catch(e){if(active)setMessage(e.message);}
      }
      if(active){setForm({...restored,players,played_at:restored.played_at||data.played_at_default});setLoadedKey(storageKey);}
    }).catch(e=>{if(active)setMessage(e.message);});
    return()=>{active=false;};
  },[table,profile?.id]);
  React.useEffect(()=>{if(storageKey&&loadedKey===storageKey)remember();},[form,storageKey,loadedKey]);
  function edit(kind,wind,value) {
    if(uncertain||busy)return;
    setForm(old=>({...old,[kind]:{...old[kind],[wind]:value}}));
    setErrors(old=>{const next={...old};delete next[kind+"."+wind];delete next.scores;return next;});setMessage("");
  }
  const rules=context?.score_rules;
  function scoreValue(raw) {
    const text=String(raw).trim(),value=Number(text);
    return /^-?\d+$/.test(text)&&Number.isSafeInteger(value)&&rules&&Math.abs(value)<=rules.max_absolute&&value%rules.step===0?value:null;
  }
  const numbers=manualWinds.map(w=>scoreValue(form.scores[w])),allNumbers=numbers.every(n=>n!==null);
  const total=allNumbers?numbers.reduce((a,b)=>a+b,0):null,difference=total!==null&&rules?total-rules.expected_total:null;
  async function upload(event) {
    event.preventDefault();if(pending.current||(!rules&&!uncertain))return;
    const fieldErrors={},seen=new Map(),players={},scores={};
    for(const wind of manualWinds){
      const player=form.players[wind];
      if(!player?.id)fieldErrors["players."+wind]="manualSelectionRequired";
      else {
        const key=String(player.id);players[wind]=key;
        if(seen.has(key)){fieldErrors["players."+wind]="manualDuplicateSelection";fieldErrors["players."+seen.get(key)]="manualDuplicateSelection";}seen.set(key,wind);
      }
      const value=scoreValue(form.scores[wind]);
      if(value===null)fieldErrors["scores."+wind]="manualScoreRuleError";
      else scores[wind]=value;
    }
    if(!form.played_at)fieldErrors.played_at="invalid_played_at";
    if(allNumbers&&difference!==0)fieldErrors.scores="invalid_score_total";
    setErrors(fieldErrors);
    // After an uncertain response, retry the exact saved payload even when a
    // selected account has since changed or been disabled. The server owns it.
    if(!uncertain&&Object.keys(fieldErrors).length)return;
    const body={table_id:context?.table_id||table||null,players,scores,played_at:form.played_at};
    const signature=JSON.stringify(body);
    let next=attempt.current;
    if(!uncertain&&next?.signature!==signature)next={signature,body,request_id:MahjongI18n.key()};
    if(!next)return;
    pending.current=true;setBusy(true);setMessage("");setUncertain(true);
    remember({...next,uncertain:true});
    try{
      const data=await manualScoreApi("/api/manual-score/upload",{...next.body,request_id:next.request_id});
      setResult(data);setUncertain(false);remember({...next,uncertain:false},data);onRefresh?.();
    }catch(e){
      setMessage(e.message);setErrors(e.fieldErrors||{});
      if(e.status>=400&&e.status<500&&![401,408,429].includes(e.status)){setUncertain(false);remember({...next,uncertain:false});}
    }finally{pending.current=false;setBusy(false);}
  }
  async function retry() {
    if(pending.current||!result?.draft_id)return;
    pending.current=true;setBusy(true);setMessage("");
    try{
      const data=await manualScoreApi("/api/manual-score/drafts/"+encodeURIComponent(result.draft_id)+"/retry",{});
      setResult(data);remember(attempt.current,data);onRefresh?.();
    }catch(e){setMessage(e.message);}finally{pending.current=false;setBusy(false);}
  }
  function recordAnother() {
    if(busy||uncertain||!result?.local_saved)return;
    // Only an acknowledged local save can be replaced. The next page load
    // obtains the current table roster and creates a fresh request identity.
    if(storageKey)sessionStorage.removeItem(storageKey);
    attempt.current=null;
    location.reload();
  }
  const externalStatus=result?.external_sync?.status;
  const externalLabel=externalStatus==="success"?"manualExternalSuccess":externalStatus==="disabled"||!externalStatus?"manualExternalDisabled":externalStatus==="failed"||externalStatus==="unsupported"||externalStatus==="manual_review"?"manualExternalFailed":"manualExternalPending";
  const retryNeeded=result&&(result.status==="pending"||["failed","pending","sending"].includes(externalStatus));
  return <div data-i18n-owned><Card>
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-bold">{t("manualScore")}</h2>
      <a href={"/?page=record"+(table?"&table="+encodeURIComponent(context?.table||table):"")} className="text-sm underline">{t("manualBack")}</a></div>
    {table&&context?.table_name&&<p className="mb-3 text-sm">{t("table")} · {context.table_name}</p>}
    <p className="mb-4 text-sm text-zinc-600">{t("manualUploadHelp")}</p>
    {!result&&<form onSubmit={upload} noValidate>
      <label className="mb-4 block text-sm font-bold">{t("competitionPlayedAt")} ({context?.timezone||"America/Los_Angeles"})<input aria-label={t("competitionPlayedAt")} type="datetime-local" className={inputClass} value={form.played_at||""} disabled={busy||uncertain} onChange={e=>setForm(old=>({...old,played_at:e.target.value}))}/><span className="block font-normal text-zinc-600">{t("competitionPlayedAtHelp")}</span>{errors.played_at&&<span className="text-red-700">{t(errors.played_at)}</span>}</label>
      <div className="space-y-4">{manualWinds.map((wind,index)=><fieldset key={wind} className="rounded-xl border border-zinc-200 p-3" data-wind={wind}>
        <legend className="px-2 font-bold">{t("wind"+index)}</legend>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="min-w-0 text-sm font-semibold"><RegisteredUserCombobox language={language} value={form.players[wind]} onChange={person=>edit("players",wind,person)} disabled={busy||uncertain} label={t("wind"+index)+" "+t("manualRegisteredName")} inputId={"manual-player-"+wind} required error={errors["players."+wind]?(MahjongI18n.entries[errors["players."+wind]]?errors["players."+wind]:"requestFailed"):""}/></div>
          <label className="min-w-0 text-sm font-semibold"><span className="mb-1 block">{t("manualPoints")}</span>
            <input className={inputClass} type="text" inputMode="numeric" aria-label={t("wind"+index)+" "+t("manualPoints")} aria-describedby={"score-error-"+wind} aria-invalid={Boolean(errors["scores."+wind])} value={form.scores[wind]} onChange={e=>edit("scores",wind,e.target.value)} disabled={busy||uncertain}/>
            <span id={"score-error-"+wind} role={errors["scores."+wind]?"alert":undefined} className="mt-1 block text-red-700">{errors["scores."+wind]?safeMessage(errors["scores."+wind]):""}</span>
          </label>
        </div>
      </fieldset>)}</div>
      {rules&&<div className="mt-4 rounded-xl bg-warm p-3" aria-live="polite" data-testid="manual-score-totals">
        <p>{t("manualCurrentTotal")}: {total===null?"—":total}</p><p>{t("manualExpectedTotal")}: {rules.expected_total}</p><p>{t("manualTotalDifference")}: {difference===null?"—":difference>0?"+"+difference:difference}</p>
        <p className="mt-1 text-sm">{t("manualScoreRule",{step:rules.step,maximum:rules.max_absolute})}</p>
      </div>}
      <button className={buttonStyle+" mt-5"} disabled={busy||(!rules&&!uncertain)||!profile}>{t(busy?"manualWorking":"manualUpload")}</button>
    </form>}
    {uncertain&&!result&&<p role="status" className="mt-3 text-sm">{t("manualUploadUncertain")}</p>}
    {result&&<section role="status" className="rounded-xl bg-emerald-50 p-4">
      <h3 className="font-bold text-emerald-900">{t("manualSaved")}</h3>
      {manualWinds.map((wind,index)=>{const p=result.result.players[wind];return <p key={wind}>{t("wind"+index)} · {p.user.name||form.players[wind]?.name} · {p.final_points} {t("pPoints")}</p>;})}
      <p className="mt-2 text-sm">{t("manualLocalSaved")}</p>
      {result.status==="pending"&&<p className="mt-2 text-sm">{t("manualSyncPending")}</p>}
      <p className={externalLabel==="manualExternalFailed"?"mt-2 text-red-700":"mt-2 text-sm"}>{t(externalLabel)}</p>
      {externalLabel==="manualExternalFailed"&&<p className="mt-1 text-sm">{t("manualExternalRetryHelp")}</p>}
      {retryNeeded&&<button className={buttonStyle+" mt-3"} disabled={busy} onClick={retry}>{t(busy?"manualWorking":"manualRetryUpload")}</button>}
      {result.local_saved&&<button className={buttonStyle+" mt-3 ml-3"} disabled={busy||uncertain} onClick={recordAnother}>{t("manualRecordAnother")}</button>}
    </section>}
    {["players","scores"].map(key=>errors[key]&&<p key={key} role="alert" className="mt-3 text-red-700">{safeMessage(errors[key])}</p>)}
    {message&&<p role="alert" className="mt-4 whitespace-pre-wrap text-red-700">{safeMessage(message)}</p>}
  </Card></div>;
}
