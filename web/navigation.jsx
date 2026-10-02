/* One ordered, permission-aware menu for desktop and mobile. */
const navigationItems = [
  {key:"dashboard",text:["Club lobby","今日大厅"]}, {key:"reservations",text:["Reservations","预约与队列"]},
  {key:"record",text:["Tables & scoring","牌桌与登分"]}, {key:"matches",text:["Game history","对局记录"]},
  {key:"ranking",label:"ranking"}, {key:"live",label:"live"},
  {key:"tournament",label:"tournament"}, {key:"account",label:"account"},
  {key:"discord",text:["Discord binding","Discord 绑定"],href:"/account#discord-binding"},
  {key:"admin",label:"admin",admin:true}, {key:"logout",text:["Log out","退出登录"],action:"logout"},
];
function ClubNavIcon({name}) {
  const paths={dashboard:"M3 10 12 3l9 7v10H3z M9 20v-7h6v7",reservations:"M3 6h18v15H3z M7 3v6 M17 3v6 M3 11h18",record:"M4 4h16v16H4z M8 8h8v8H8z",matches:"M3 11a9 9 0 1 1 2 7 M3 4v7h7 M12 7v5l3 2",ranking:"M8 3h8v7a4 4 0 0 1-8 0z M8 5H4v3a4 4 0 0 0 4 4 M16 5h4v3a4 4 0 0 1-4 4 M12 14v7 M8 21h8",account:"M4 21v-3a5 5 0 0 1 5-5h6a5 5 0 0 1 5 5v3 M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8",logout:"M9 4H4v16h5 M9 12h12 M17 8l4 4-4 4",admin:"M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z",tournament:"M5 21V3 M5 3c5-4 9 4 15 0v10c-6 4-10-4-15 0",live:"M3 12h4l3-8 4 16 3-8h4",discord:"M4 5h16v12H9l-5 4z"};
  return <svg className="club-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]||paths.account}/></svg>;
}
function appPageUrl(page) {
  return {account:"/account",reservations:"/reservations","manual-score":"/manual-score"}[page]||"/?page="+encodeURIComponent(page);
}
function useMobileNavigation() {
  const [mobile,setMobile]=React.useState(()=>matchMedia("(max-width: 767px)").matches);
  React.useEffect(()=>{const media=matchMedia("(max-width: 767px)"),change=()=>setMobile(media.matches);media.addEventListener("change",change);return()=>media.removeEventListener("change",change);},[]);
  return mobile;
}
function NavigationLinks({profile,page,language,onNavigate,onClose,exclude=[]}) {
  const labels=navLabels[language]||navLabels.EN;
  return navigationItems.filter(item=>!exclude.includes(item.key)&&(!item.admin||profile?.is_admin)).map(item=>{
    const label=item.text?item.text[language==="CN"?1:0]:labels[item.label];
    const selected=item.key===page&&!(page==="account"&&location.hash==="#discord-binding")||item.key==="discord"&&page==="account"&&location.hash==="#discord-binding";
    const props={className:"navigation-link", "data-navigation-item":item.key,"aria-current":selected?"page":undefined};
    if(item.action)return <button {...props} key={item.key} type="button" onClick={async()=>{
      onClose?.();const response=await fetch("/api/logout",{method:"POST"});if(response.ok)location.assign("/login");
    }}><ClubNavIcon name={item.key}/><span>{label}</span></button>;
    if(!item.href)return <button {...props} key={item.key} type="button" onClick={()=>{onClose?.();onNavigate(item.key);}}><ClubNavIcon name={item.key}/><span>{label}</span></button>;
    return <a {...props} key={item.key} href={item.href||appPageUrl(item.key)} onClick={event=>{
      if(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
      onClose?.();if(!item.href){event.preventDefault();onNavigate(item.key);}
    }}><ClubNavIcon name={item.key}/><span>{label}</span></a>;
  });
}
function MobileNavigation({trigger,language,children,onClose}) {
  const dialog=React.useRef(null),close=React.useRef(onClose);close.current=onClose;
  React.useEffect(()=>{
    const node=dialog.current,body=document.body,top=window.scrollY;
    const previous={overflow:body.style.overflow,position:body.style.position,top:body.style.top,width:body.style.width};
    node.showModal();Object.assign(body.style,{overflow:"hidden",position:"fixed",top:-top+"px",width:"100%"});
    node.querySelector("button")?.focus();
    return()=>{node.close();Object.assign(body.style,previous);window.scrollTo(0,top);trigger.current?.focus({preventScroll:true});};
  },[]);
  return <dialog ref={dialog} id="mobile-navigation" className="mobile-navigation mobile-more-sheet" aria-label={language==="CN"?"更多功能":"More options"}
    onCancel={event=>{event.preventDefault();close.current();}} onClick={event=>{
      if(event.target!==event.currentTarget)return;const box=event.currentTarget.getBoundingClientRect();
      if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)close.current();
    }}>
    <div className="drawer-heading"><strong>{window.MahjongBrand.name}</strong><button className="navigation-icon" type="button" aria-label={language==="CN"?"关闭":"Close"} onClick={onClose}>×</button></div>
    {children}
  </dialog>;
}
const mobilePrimary=[
  {key:"dashboard",en:"Lobby",cn:"大厅"},
  {key:"reservations",en:"Reserve",cn:"预约"},
  {key:"record",en:"Tables",cn:"牌桌"},
  {key:"matches",en:"History",cn:"记录"},
  {key:"ranking",en:"Ranking",cn:"排行"},
];
function Header({session,profile,authReady,memberCount,currentQuarter,page,setPage,onRefresh,language,setLanguage}) {
  const mobile=useMobileNavigation(),[open,setOpen]=React.useState(false),trigger=React.useRef(null);
  const labels=navLabels[language]||navLabels.EN;
  React.useEffect(()=>setOpen(false),[page,mobile]);
  const languageControl=<button type="button" className="navigation-link" title={language==="CN"?"切换语言":"Change language"} onClick={()=>{
    const next=language==="EN"?"CN":"EN";localStorage.setItem("mahjong_lang",next);setLanguage(next);
  }}>{language==="EN"?"CN":"EN"}</button>;
  const refreshControl=<button type="button" className="navigation-link" onClick={()=>{setOpen(false);onRefresh();}}>{labels.refresh}</button>;
  const links=<NavigationLinks profile={profile} page={page} language={language} onNavigate={setPage} onClose={()=>setOpen(false)} exclude={mobilePrimary.map(item=>item.key)}/>;
  const activePrimary=["result","manual-score","join-table"].includes(page)?"record":page;
  const item=navigationItems.find(item=>item.key===activePrimary);
  const pageTitle=item?.text?item.text[language==="CN"?1:0]:labels[item?.label]||(language==="CN"?"社团活动":"Club activities");
  const brand=<a className="club-wordmark" href="/" aria-label={window.MahjongBrand.name}><img src="/assets/dora-club-icon.png" width="58" height="58" alt={language==="CN"?"DORA 社团标志":"DORA club logo"}/><span>DORA</span></a>;
  return <>
    {!mobile&&session&&<aside className="club-sidebar" data-i18n-owned aria-label={language==="CN"?"社团导航":"Club navigation"}>
      {brand}<p className="club-brand-description">Mahjong Club<br/>at UC San Diego</p><p className="club-eyebrow">YOUR CLUB, YOUR TABLE.</p>
      <nav aria-label={language==="CN"?"主导航":"Main navigation"} data-desktop-navigation><NavigationLinks profile={profile} page={page} language={language} onNavigate={setPage}/></nav>
      <div className="club-sidebar-foot"><p className="club-eyebrow">A SEAT AT THE TABLE.</p><p>{language==="CN"?<>四个人，一张桌。<br/>下一局，在这里相遇。</>:<>Four players, one table.<br/>Your next game starts here.</>}</p>
        <a href="/account" className="club-sidebar-profile"><AccountAvatars.Avatar name={session} src={profile?.avatar} size={34}/><span><strong>{session}</strong><small>{language==="CN"?"账号与社团身份":"Account & membership"}</small></span></a>
      </div>
    </aside>}
    <header data-i18n-owned className={"app-header club-topbar "+(mobile?"app-header-mobile":"app-header-desktop")}>
      {mobile||!session?brand:<div className="club-breadcrumb"><span>DORA {language==="CN"?"俱乐部":"Club"}</span><span>/</span><strong>{pageTitle}</strong></div>}
      <div className="club-topbar-tools">{!mobile&&<>{languageControl}{session&&refreshControl}</>}
        {mobile&&session&&<button ref={trigger} data-menu-trigger type="button" className="club-profile-menu" aria-label={language==="CN"?"更多功能与账号":"More options & account"} aria-expanded={open} aria-controls="mobile-navigation" onClick={()=>setOpen(true)}><AccountAvatars.Avatar name={session} src={profile?.avatar} size={34}/><span aria-hidden="true">☰</span></button>}
        {mobile&&!session&&languageControl}
      </div>
      {!session&&authReady&&!(["/login","/register"].includes(location.pathname))&&<div className="auth-links"><a href={globalLoginUrl(loginReturnTarget())}>{language==="CN"?"登录":"Log In"}</a><a href={"/register?returnTo="+encodeURIComponent(loginReturnTarget())}>{language==="CN"?"注册":"Register"}</a></div>}
    </header>
    {mobile&&session&&<nav className="mobile-tabbar" aria-label={language==="CN"?"主导航":"Main navigation"}>
      {mobilePrimary.map(item=><button key={item.key} type="button" className="mobile-tab" aria-current={activePrimary===item.key?"page":undefined} onClick={()=>setPage(item.key)}>
        <ClubNavIcon name={item.key}/><span>{language==="CN"?item.cn:item.en}</span>
      </button>)}
    </nav>}
    {mobile&&session&&open&&<MobileNavigation trigger={trigger} language={language} onClose={()=>setOpen(false)}>
      <p className="drawer-account">{labels.loggedIn}: {session}</p>
      <nav aria-label={language==="CN"?"其他页面":"Other pages"} data-mobile-navigation>{links}</nav>
      <div className="drawer-tools">{languageControl}{refreshControl}</div>
      <p className="drawer-account">{currentQuarter||labels.currentSeason} · {memberCount||"—"} {labels.members}</p>
    </MobileNavigation>}
  </>;
}
