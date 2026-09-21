/* Shared registered-user adapters keep legacy name-based form payloads compatible. */
function registeredRosterOptions(roster) {
  const rows=(roster||[]).map(p=>typeof p==="string"?{name:p}:p).filter(p=>p?.name);
  return [...new Map(rows.map(p=>[p.name,{id:String(p.user_id||p.account_id||p.id||"historical:"+p.name),name:p.name}])).values()];
}
function RegisteredUserField({name,label,defaultValue="",value,required=false,language,options,onSelected,onChange,excludeIds,disabled=false}) {
  const lang=language||localStorage.getItem("mahjong_lang")||"EN",initial=value===undefined?defaultValue:value;
  const [person,setPerson]=React.useState(()=>options?.find(p=>p.name===initial)||null),hidden=React.useRef(null),selection=React.useRef(null);
  selection.current=person;
  const optionsSignature=options?JSON.stringify(options.map(p=>[p.id,p.name])):"";
  React.useEffect(()=>{
    let active=true;
    if(!initial){setPerson(null);return;}
    if(selection.current?.name===initial)return;
    if(options){setPerson(options.find(p=>p.name===initial)||null);return;}
    (async()=>{let cursor=null;do{const query=new URLSearchParams({q:initial,limit:25});if(cursor)query.set("cursor",cursor);
      const result=await tournamentApi("/api/registered-users?"+query);if(!active)return;
      const found=(result.users||[]).find(p=>p.name===initial);if(found){setPerson(found);return;}cursor=result.next_cursor;
    }while(cursor);setPerson(null);})().catch(()=>{});
    return()=>{active=false;};
  },[initial,optionsSignature]);
  React.useEffect(()=>{const form=hidden.current?.form;if(!form)return;const reset=()=>{setPerson(null);onSelected?.(null);onChange?.("");};form.addEventListener("reset",reset);return()=>form.removeEventListener("reset",reset);},[]);
  return <div data-i18n-owned><RegisteredUserCombobox value={person} onChange={p=>{setPerson(p);onSelected?.(p);onChange?.(p?.name||"");}} label={label||MahjongI18n.t(lang,"registeredName")} language={lang} options={options} excludeIds={excludeIds} required={required} disabled={disabled}/><input ref={hidden} type="hidden" name={name} value={person?.name||""}/></div>;
}
function RegisteredNameAdmin({language,onRefresh}) {
  const t=(key,values)=>MahjongI18n.t(language,key,values),pending=React.useRef(false);
  const [person,setPerson]=React.useState(null),[next,setNext]=React.useState(""),[reason,setReason]=React.useState(""),[busy,setBusy]=React.useState(false),[notice,setNotice]=React.useState(""),[report,setReport]=React.useState(null);
  const load=()=>tournamentApi("/api/admin/registered-name-conflicts").then(setReport).catch(()=>setNotice(t("registeredAdminCheckFailed")));
  React.useEffect(()=>{load();},[]);
  const select=person=>{setPerson(person);setNext("");setReason("");setNotice("");};
  const save=async event=>{event.preventDefault();if(pending.current||!person||!next.trim())return;
    if(!window.confirm(t("registeredAdminConfirm",{before:person.name,after:next.trim()})))return;
    pending.current=true;setBusy(true);setNotice("");try{
      await tournamentApi("/api/admin/registered-name",{user_id:person.id,expected_name:person.name,new_name:next,reason,confirm:true});
      select(null);setNotice(t("registeredAdminSaved"));await load();onRefresh?.();
    }catch(error){const messages={registered_name_taken:t("registeredAdminTaken"),name_taken:t("registeredAdminTaken"),stale_name:t("registeredAdminStale"),admin_required:t("registeredAdminOnly")};setNotice(messages[error.message]||t("registeredAdminFailed"));}finally{pending.current=false;setBusy(false);}};
  return <section data-i18n-owned data-registered-name-admin className="rounded-xl border border-zinc-200 p-4">
    <h3 className="mb-3 font-bold">{t("registeredAdminTitle")}</h3>
    <form onSubmit={save} className="grid gap-3 md:grid-cols-2"><RegisteredUserCombobox value={person} onChange={select} label={t("registeredAdminSelect")} language={language} disabled={busy} required/>
      <label className="grid gap-1 text-sm font-semibold">{t("registeredAdminNew")}<input className={inputStyle} value={next} onChange={e=>setNext(e.target.value)} required maxLength={128} disabled={busy}/></label>
      <label className="grid gap-1 text-sm font-semibold md:col-span-2">{t("registeredAdminReason")}<input className={inputStyle} value={reason} onChange={e=>setReason(e.target.value)} maxLength={500} disabled={busy}/></label>
      <button className={buttonStyle} disabled={busy||!person||!next.trim()}>{t("registeredAdminSave")}</button></form>
    {notice&&<p className="my-3" role="status">{notice}</p>}
    {report&&<div className="mt-4"><p>{report.unique_index_ready?t("registeredAdminUnique"):t("registeredAdminResolve")}</p>
      {(report.conflicts||[]).map((group,index)=><div className="mt-2 rounded-lg border p-3" key={index}><p className="font-bold">{t("registeredAdminDuplicate")}: {group.normalized_name}</p>{group.names.map((p,i)=><button type="button" className={buttonStyle+" mr-2 mt-2"} key={p.id} onClick={()=>select(p)}>{p.name} · {t("registeredAdminAccount")} {i+1}</button>)}</div>)}
      {(report.invalid||[]).map((p,i)=><button type="button" className={buttonStyle} key={p.id||i} onClick={()=>select(p)}>{p.name||t("registeredAdminEmpty")} · {i+1}</button>)}
      <button type="button" className="mt-3 underline" onClick={load}>{t("registeredAdminCheck")}</button></div>}
  </section>;
}
