/* Global registration and optional Discord flow; no credentials are stored in the browser. */
const v10 = (language, en, cn) => language === "CN" ? cn : en;
const registrationMessages={
  "Existing player registration uses the selected player's current name.": "已有玩家须使用所选玩家当前的姓名开通账号，不能另设新名字。",
  "This ID is already registered. Please log in or contact an administrator.": "此 ID 已注册，请登录或联系管理员。",
  "Existing ID was not found or needs administrator review.": "未找到该已有 ID，或需要管理员核实。",
  "This ID is unavailable. Please contact an administrator.": "此 ID 暂不可用，请联系管理员。",
  "This registered name is already in use.": "此注册名已被使用。",
  "This registered name is already used by another existing player.": "此注册名已被其他已有玩家使用。",
  "This is an existing ID. Use Claim Existing ID for administrator approval.": "此名称属于已有玩家，请选择“已有玩家开通账号”并提交管理员审批。",
  "Please select your existing player name from the results.": "请从搜索结果中选择自己的原玩家姓名。",
  "This name has a pending registration. Please contact an administrator.": "此名称有待审批的注册申请，请联系管理员。",
  "This ID has a pending registration. Please contact an administrator.": "此 ID 有待审批的认领申请，请联系管理员。",
  "Passwords must match.": "两次输入的密码必须一致。",
  "Password must contain 6–1024 characters.": "密码长度须为 6 至 1024 个字符。",
  "Please enter a valid registered name.": "请输入有效的注册名。",
  "Please enter a valid registered name (1–128 characters).": "请输入 1 至 128 个字符的有效注册名。",
  "Invalid registration form.": "注册信息无效，请检查后重试。",
  "Your claim was not approved. Please contact an administrator.": "认领申请未获批准，请联系管理员。",
  "Registration is paused while administrators resolve duplicate registered names.": "管理员正在处理重复注册名，注册暂时暂停。",
  "Registration recovery needs administrator review; no existing account was changed.": "注册恢复需要管理员核实，已有账号未被修改。",
  "Registration recovery needs administrator review.": "注册恢复需要管理员核实。",
  "Account directory is unavailable. Please contact an administrator.": "账号目录暂不可用，请联系管理员。",
  "Account recovery needs administrator review.": "账号恢复需要管理员核实。",
  "Only administrators can review claims.": "仅管理员可审批认领申请。",
  "An approved claim is being activated. Retry approval to finish.": "已批准的申请正在激活，请重试审批以完成操作。",
  "Discord binding is currently unavailable. You can skip it and bind later in Account Settings.": "Discord 绑定暂不可用，可以跳过并稍后在账号设置中绑定。",
  "This Discord account is already bound. Unbind it from the original account first.": "该 Discord 账号已绑定，请先在原账号中解绑。",
  "Discord authorization expired or is invalid. Please try again.": "Discord 授权已过期或无效，请重试。",
  "Please enter your username and password.": "请输入用户名和密码。",
  "Request body must be a JSON object.": "提交内容无效，请刷新后重试。"
};
const registrationErrorCodes={
  legacy_identity_conflict:{EN:"This player record is linked to another account. Ask an administrator to verify it; the original record was not changed.",CN:"这条玩家记录已有其他账号关联，请联系管理员核实；原记录未修改。"},
  existing_player_name_mismatch:{EN:"Use the selected player's current name to open the account.",CN:"请使用所选玩家当前的姓名开通账号，不能另设新名字。"}
};
function registrationMessage(language,value){const source=value?.message||value;if(registrationErrorCodes[source])return registrationErrorCodes[source][language==="CN"?"CN":"EN"];if(Object.prototype.hasOwnProperty.call(registrationMessages,source))return language==="CN"?registrationMessages[source]:source;return v10(language,"Request failed. Please try again.","请求未完成，请重试。");}

async function accountRequest(path, body) {
  const response = await fetch(path,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const result = await response.json();
  if(!response.ok)throw new Error(registrationErrorCodes[result.code]?result.code:result.message||"Request failed. Please try again.");
  return result;
}
function registrationDestination(result, bindDiscord) {
  const target=safeLoginReturn(result.redirect_url||"/");
  location.assign(bindDiscord?"/registration-complete?redirect_url="+encodeURIComponent(target):target);
}
function ExistingPlayerPicker({language,value,onChange,disabled=false}) {
  const t=(en,cn)=>v10(language,en,cn),id=React.useId(),box=React.useRef(null);
  const [query,setQuery]=React.useState(value?.name||""),[players,setPlayers]=React.useState([]),[open,setOpen]=React.useState(false),[active,setActive]=React.useState(-1);
  const [loading,setLoading]=React.useState(false),[failed,setFailed]=React.useState(false),[more,setMore]=React.useState(false),[retry,setRetry]=React.useState(0);
  React.useEffect(()=>{
    if(value&&query===value.name){setLoading(false);setFailed(false);return;}
    const controller=new AbortController();let current=true;setLoading(true);setFailed(false);setPlayers([]);setActive(-1);
    const timer=setTimeout(async()=>{try{
      const response=await fetch("/api/register/players?"+new URLSearchParams({q:query,limit:"20"}),{credentials:"same-origin",cache:"no-store",signal:controller.signal});
      if(!response.ok)throw new Error("lookup");const result=await response.json();
      if(!Array.isArray(result.players))throw new Error("lookup");
      if(current){setPlayers(result.players);setMore(Boolean(result.has_more));}
    }catch(error){if(current&&error.name!=="AbortError")setFailed(true);}finally{if(current)setLoading(false);}},180);
    return()=>{current=false;clearTimeout(timer);controller.abort();};
  },[query,value?.id,retry]);
  function choose(player){onChange(player);setQuery(player.name);setOpen(false);setActive(-1);}
  function keydown(event){
    if(event.key==="ArrowDown"||event.key==="ArrowUp"){event.preventDefault();setOpen(true);if(players.length)setActive(old=>event.key==="ArrowDown"?(old+1)%players.length:old<0?players.length-1:(old-1+players.length)%players.length);}
    else if(event.key==="Enter"&&open){event.preventDefault();if(active>=0&&players[active])choose(players[active]);}
    else if(event.key==="Escape"){event.preventDefault();setOpen(false);setActive(-1);}
    else if(event.key==="Tab")setOpen(false);
  }
  return <div data-registration-picker ref={box} onBlur={event=>{if(!box.current?.contains(event.relatedTarget))setOpen(false);}}>
    <label htmlFor={id} className="mb-1 block text-sm font-semibold text-zinc-600">{t("Find your player name","搜索已有玩家姓名")}</label>
    <input id={id} role="combobox" maxLength={128} autoComplete="off" className={inputStyle} value={query} disabled={disabled} aria-autocomplete="list" aria-expanded={open} aria-controls={id+"-list"} aria-activedescendant={open&&active>=0?id+"-option-"+active:undefined} aria-describedby={id+"-help"} onFocus={()=>setOpen(true)} onChange={event=>{setQuery(event.target.value);onChange(null);setOpen(true);setActive(-1);}} onKeyDown={keydown} placeholder={t("Type the name in the club player list","输入社团名单中的玩家姓名")}/>
    <p id={id+"-help"} className="mt-2 text-sm text-zinc-500">{t("Choose your name from the results. No player number or separate username is needed.","从搜索结果中选择自己的姓名，无需玩家编号，也无需另设用户名。")}</p>
    {open&&<div className="mt-2 rounded-xl border bg-white p-2">
      {loading&&<p role="status" className="p-2 text-sm">{t("Searching player names…","正在查找玩家姓名…")}</p>}
      {failed&&<div role="alert" className="p-2 text-sm text-red-700"><p>{t("Player names could not be loaded. Your input is saved; please retry.","暂时无法加载玩家名单，已保留输入，请重试。")}</p><button type="button" className={buttonStyle+" mt-2"} disabled={disabled} onClick={()=>{setRetry(old=>old+1);document.getElementById(id)?.focus();}}>{t("Retry search","重新搜索")}</button></div>}
      {!loading&&!failed&&players.length===0&&<p role="status" className="p-2 text-sm">{t("No available player name found. If you already have an account, log in. Otherwise try another spelling or ask an administrator.","未找到可开通账号的玩家姓名。已有账号请登录；否则可换个写法搜索，或联系管理员。")}</p>}
      <ul role="listbox" id={id+"-list"} aria-label={t("Existing player names","已有玩家姓名")} className="max-h-60 overflow-y-auto">{players.map((player,index)=><li key={player.id} role="presentation"><button id={id+"-option-"+index} role="option" aria-selected={active===index} type="button" tabIndex={-1} className={"block w-full break-words rounded-lg px-3 py-2 text-left "+(active===index?"bg-warm font-bold":"")} onMouseDown={event=>event.preventDefault()} onMouseEnter={()=>setActive(index)} onClick={()=>choose(player)}>{player.name}</button></li>)}</ul>
      {!loading&&!failed&&more&&<p className="p-2 text-sm text-zinc-500">{t("More names match. Keep typing to narrow the results.","还有更多匹配姓名，请继续输入以缩小范围。")}</p>}
    </div>}
    {value&&<p data-selected-claim-player role="status" className="mt-3 break-words rounded-xl bg-warm p-3 text-sm"><strong>{t("Login and display name: ","登录和显示名：")}{value.name}</strong></p>}
  </div>;
}
function RegistrationPage({language,session,authReady,onRefresh}) {
  const t=(en,cn)=>v10(language,en,cn),[mode,setMode]=React.useState("claim"),[player,setPlayer]=React.useState(null),[message,setMessage]=React.useState(""),[busy,setBusy]=React.useState(false),[pending,setPending]=React.useState(false);
  const [bind,setBind]=React.useState(false),[available,setAvailable]=React.useState(false),operation=React.useRef(false),resuming=React.useRef(false);
  const target=safeLoginReturn(new URLSearchParams(location.search).get("redirect_url"));
  React.useEffect(()=>{if(authReady&&session)location.replace(target);},[authReady,session]);
  React.useEffect(()=>{fetch("/api/discord/config").then(r=>r.json()).then(r=>setAvailable(r.available)).catch(()=>{});},[]);
  async function resume() {
    if(resuming.current)return;resuming.current=true;
    try {
      const result=await accountRequest("/api/register/resume",{});
      if(result.status==="approved"){onRefresh();registrationDestination(result,result.bind_discord);}
      if(result.status==="pending"||result.status==="approving")setPending(true);
      if(result.status==="rejected"){setPending(false);setMessage("Your claim was not approved. Please contact an administrator.");}
    } catch(e){setMessage(e.message);}finally{resuming.current=false;}
  }
  React.useEffect(()=>{if(authReady&&!session)resume();},[authReady]);
  React.useEffect(()=>{if(!pending)return;const timer=setInterval(resume,10000);return()=>clearInterval(timer);},[pending,language]);
  async function submit(event){
    event.preventDefault();if(operation.current)return;
    const form=event.currentTarget,body=Object.fromEntries(new FormData(form));
    if(mode==="claim"&&!player){setMessage("Please select your existing player name from the results.");return;}
    if(body.password!==body.confirm_password){setMessage("Passwords must match.");return;}
    operation.current=true;setBusy(true);setMessage("");
    try{
      const result=await accountRequest(mode==="claim"?"/api/register/claim":"/api/register",{...body,...(mode==="claim"?{player_id:player.id}:{}),bind_discord:bind,redirect_url:target});
      form.reset();
      if(result.status==="pending")setPending(true);
      else{onRefresh();registrationDestination(result,bind);}
    }catch(e){setMessage(e.message);}finally{setBusy(false);operation.current=false;}
  }
  if(authReady&&session)return null;
  return <div data-registration-page data-i18n-owned className="mx-auto max-w-xl"><Card>
    <p className="text-sm font-bold uppercase tracking-widest text-zinc-500">UCSD MAHJONG CLUB</p>
    <h1 className="my-3 text-3xl font-black">{t("Register","注册")}</h1>
    {pending?<div role="status" className="space-y-4 rounded-xl bg-warm p-5"><h2 className="text-xl font-bold">{t("Waiting for administrator approval","等待管理员审批")}</h2><p>{t("After an administrator verifies your identity, your existing player name becomes your login and display name. Your original results stay unchanged. Keep this page open, or return on this device to continue automatically.","管理员核实身份后，原玩家姓名就是你的登录名和显示名，原有成绩不会改变。保持此页面开启，或稍后用当前设备返回，系统会自动继续。")}</p><button type="button" className={buttonStyle} onClick={resume}>{t("Check status","检查状态")}</button></div>:<>
      <div role="tablist" className="my-5 grid grid-cols-2 gap-2">{[["claim","Existing Player","已有玩家开通账号"],["new","New Player","新玩家注册"]].map(([key,en,cn])=><button type="button" role="tab" disabled={busy} aria-selected={mode===key} key={key} onClick={()=>{setMode(key);setMessage("");}} className={"rounded-xl border px-3 py-3 text-sm font-bold sm:text-base "+(mode===key?"bg-navy text-white":"bg-white")}>{t(en,cn)}</button>)}</div>
      <p className="mb-5 text-sm text-zinc-600">{mode==="claim"?t("Already listed as a club player, even with no games yet? Find your name below and set a password. An administrator will verify your identity; your player record and any original results stay unchanged.","社团名单中已经有你的名字，即使还没有对局记录？请在下方选择原有姓名并设置密码。管理员核实身份后即可登录，玩家资料和原有成绩都将保留。"):t("Your name is not in the club player list yet? Create a player name for both login and display. No email or Discord account is required.","名字尚未录入社团名单？请设置一个用于登录和显示的玩家名称，无需邮箱或 Discord。")}</p>
      <form onSubmit={submit} className="grid gap-4">
        {mode==="claim"?<ExistingPlayerPicker language={language} value={player} onChange={setPlayer} disabled={busy}/>:<TournamentField label={t("Player name (for login and display)","玩家名称（用于登录和显示）")}><input name="username" required maxLength={128} autoComplete="username" disabled={busy} className={inputStyle}/></TournamentField>}
        <TournamentField label={t("Password","密码")}><input name="password" type="password" required minLength={6} maxLength={1024} autoComplete="new-password" className={inputStyle}/></TournamentField>
        <TournamentField label={t("Confirm password","确认密码")}><input name="confirm_password" type="password" required minLength={6} maxLength={1024} autoComplete="new-password" className={inputStyle}/></TournamentField>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={bind} onChange={e=>setBind(e.target.checked)}/>{t("Bind Discord Account (Optional)","绑定 Discord（可选）")}</label>
        {!available&&<p className="text-sm text-zinc-500">{t("Discord is unavailable here. You can skip it and bind later.","此环境暂未启用 Discord，可以跳过并在以后绑定。")}</p>}
        <button disabled={busy||!authReady||(mode==="claim"&&!player)} className="rounded-xl bg-navy px-4 py-3 font-bold text-white disabled:opacity-50">{busy?t("Submitting…","提交中…"):mode==="claim"?t("Submit for approval","提交审批"):t("Create account","创建账号")}</button>
      </form>
    </>}
    {message&&<p role="alert" className="mt-4 text-sm text-red-700">{registrationMessage(language,message)}</p>}
    <p className="mt-6 text-sm"><a className="underline" href={globalLoginUrl(target)}>{t("Already registered? Log In","已有账号？登录")}</a></p>
  </Card></div>;
}
function DiscordOptional({language,target="/",complete=false}) {
  const t=(en,cn)=>v10(language,en,cn),[error,setError]=React.useState(""),[busy,setBusy]=React.useState(false);
  const result=new URLSearchParams(location.search).get("discord");
  return <div data-i18n-owned className="space-y-3">
    {complete&&<><h1 className="text-2xl font-black">{t("Your account is ready","账号已就绪")}</h1><p>{t("Discord binding is optional. You can always do this later.","Discord 绑定为可选项，你可以稍后再设置。")}</p></>}
    {result&&<p role="status">{result==="bound"?t("Discord is bound.","Discord 已绑定。"):t("Discord binding did not finish. Your website account is ready to use.","Discord 绑定未完成，网站账号仍可正常使用。")}</p>}
    <button type="button" className={buttonStyle} disabled={busy} onClick={async()=>{setBusy(true);setError("");try{const r=await accountRequest("/api/discord/start",{redirect_url:target});location.assign(r.url);}catch(e){setError(e.message);setBusy(false);}}}>{t("Bind Discord Account (Optional)","绑定 Discord（可选）")}</button>
    {complete&&<a className={buttonStyle+" inline-block ml-2"} href={safeLoginReturn(target)}>{t("Skip for Now / Continue","暂时跳过 / 继续")}</a>}
    {error&&<p role="alert" className="text-sm text-amber-800">{registrationMessage(language,error)}</p>}
  </div>;
}
function ClaimAdmin({language}) {
  const t=(en,cn)=>v10(language,en,cn),[claims,setClaims]=React.useState([]),[message,setMessage]=React.useState(""),[busy,setBusy]=React.useState(false);
  const load=async()=>{try{const response=await fetch("/api/admin/account-claims");if(!response.ok)throw new Error("requestFailed");const result=await response.json();setClaims(result.claims||[]);}catch(error){setMessage(registrationMessage(language,error));}};
  React.useEffect(()=>{load().catch(()=>{});},[]);
  async function review(claim,decision){
    if(!window.confirm(t("Confirm identity verification and "+decision+" this claim?","确认已核实身份，并"+(decision==="approve"?"批准":"拒绝")+"此申请？")))return;
    setBusy(true);try{await accountRequest("/api/admin/account-claims/review",{claim_id:claim.id,decision});await load();setMessage(t("Saved","已保存"));}catch(e){setMessage(registrationMessage(language,e));}finally{setBusy(false);}
  }
  return <div data-i18n-owned className="my-5"><Card><h2 className="text-xl font-bold">{t("Existing player account requests","已有玩家账号开通审批")}</h2><p className="my-3 text-sm">{t("Verify the player's identity before approving. Rejected requests do not change the original player.","请核实申请者身份后再批准。拒绝申请不会修改原玩家资料。")}</p><button className={buttonStyle} onClick={load}>{t("Refresh","刷新")}</button>
    {claims.map(c=><div className="my-3 rounded-xl border p-4" key={c.id} data-account-claim><b>{t("Activate account for ","为此玩家开通账号：")}{c.legacy_name}</b><p className="text-sm">{({pending:t("Pending","待审批"),approving:t("Activating","激活中"),approved:t("Approved","已批准"),rejected:t("Rejected","已拒绝")})[c.status]||t("Review required","需要核实")} · {c.created_at}</p>{["pending","approving"].includes(c.status)&&<div className="mt-3 flex gap-2"><button className={buttonStyle} disabled={busy} onClick={()=>review(c,"approve")}>{t("Approve","批准")}</button><button className={buttonStyle} disabled={busy||c.status==="approving"} onClick={()=>review(c,"reject")}>{t("Reject","拒绝")}</button></div>}</div>)}{message&&<p role="status">{message}</p>}
  </Card></div>;
}
