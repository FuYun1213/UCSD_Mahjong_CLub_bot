const v10 = (language, en, cn) => language === "CN" ? cn : en;
﻿const { Trophy, UserRound, ListChecks, Plus, LogIn, ScrollText, Camera } = lucideReactShim();

const logoUrl = "/assets/UCSD_mermaid_whitebg.jpg";

const navLabels = {
  EN: {
    dashboard: "Dashboard",
    ranking: "Ranking",
    record: "Game Record",
    matches: "Recent Match",
    live: "Live",
    tournament: "Competitions",
    account: "Account",
    admin: "Admin",
    refresh: "Refresh",
    loggedIn: "Logged in as",
    notLoggedIn: "Not logged in",
    currentSeason: "Current Season",
    members: "members",
  },
  CN: {
    dashboard: "主页",
    ranking: "排行榜",
    record: "登分",
    matches: "最近对局",
    live: "实时对局",
    tournament: "比赛",
    account: "账号",
    admin: "管理",
    refresh: "刷新",
    loggedIn: "已登录",
    notLoggedIn: "未登录",
    currentSeason: "当前学期",
    members: "名成员",
  },
};

const cnTextMap = {
  "Dashboard": "主页",
  "Ranking": "排行榜",
  "Game Record": "登分",
  "Recent Match": "最近对局",
  "Live": "实时对局",
  "Account": "账号",
  "Admin": "管理",
  "Refresh": "刷新",
  "Current Season": "当前学期",
  "Current quarter": "当前学期",
  "Total games": "总数据",
  "Quarter Games": "季度对局数",
  "Total Games": "总对局数",
  "games": "对局",
  "View player": "查看玩家",
  "Data scope": "数据范围",
  "Key Metrics": "关键指标",
  "MMR rank": "MMR 排名",
  "PT rank": "PT 排名",
  "Games": "对局数",
  "Yakuman": "役满",
  "Avg place": "平均顺位",
  "Top 2 rate": "连对率",
  "Avoid 4th": "避四率",
  "Highest score": "最高点数",
  "Ability Radar": "能力雷达",
  "Recent Yakuman": "最近役满",
  "Placement Distribution": "顺位分布",
  "Record Trend": "战绩变化",
  "Season Ranking": "赛季排名",
  "Most Yakuman": "役满最多",
  "Showing": "显示",
  "players": "名玩家",
  "Ranked": "已排名",
  "wins": "胜场",
  "you": "你",
  "Annual Summary": "年度总结",
  "Log in to see your bilingual year recap.": "登录后查看中英双语年度总结。",
  "View": "查看",
  "Hide": "收起",
  "Recent matches": "最近对局",
  "View quarter": "查看学期",
  "Table player search": "同桌玩家检索",
  "Search": "搜索",
  "Clear": "清空",
  "Date": "日期",
  "Opponents": "同桌玩家",
  "Result": "顺位",
  "MMR": "MMR",
  "PT": "PT",
  "Log new game": "登记新对局",
  "Match Management": "对局管理",
  "10 matches per page": "每页 10 局",
  "Add yakuman": "添加役满",
  "Revert game": "撤回对局",
  "Add yakuman to this match": "给这局补充役满",
  "No SQL game rows found for this view.": "这个筛选下没有找到对局。",
  "Previous": "上一页",
  "Next": "下一页",
  "Quarter": "学期",
  "Change quarter": "切换学期",
  "Undo quarter": "撤回学期切换",
  "Player data tools (admin only)": "玩家数据工具（仅管理员）",
  "Create player": "新增玩家",
  "Rename": "改名",
  "Merge + recompute": "合并并重算",
  "Set icon": "设置图标",
  "Role management (super admin only)": "权限管理（仅超级管理员）",
  "Update role": "更新权限",
  "Account recovery (super admin only)": "账号恢复（仅超级管理员）",
  "Reset password": "重置密码",
  "Delete account": "删除账号",
  "Recent Admin Changes": "最近管理更改",
  "Revert action": "撤回操作",
  "Not reversible": "不可撤回",
  "No admin changes found.": "没有管理更改记录。",
  "Live Game Recorder": "实时对局记录",
  "Start from 25000": "25000 开局",
  "Record hand": "记录一手",
  "Game Result": "对局结果",
  "No recorded result yet.": "还没有记录结果。",
  "Revert this record": "撤回这条记录",
  "Sign in": "登录",
  "Register": "注册",
  "Change password": "修改密码",
  "Forgot password": "忘记密码",
  "Bind Discord": "绑定 Discord",
  "Unbind Discord": "解除 Discord 绑定",
  "Password": "密码",
  "New password": "新密码",
  "Confirm password": "确认密码",
  "Username": "用户名",
  "Record game": "提交对局",
  "Yakuman winner": "役满玩家",
  "Winner": "和牌者",
  "Deal in": "放铳者",
  "Other player": "其他同桌玩家",
  "Photo note": "照片备注",
};

function translateText(language, value) {
  if (language !== "CN") return value;
  const text = String(value || "");
  const trimmed = text.trim();
  if (!trimmed) return value;
  if (cnTextMap[trimmed]) return text.replace(trimmed, cnTextMap[trimmed]);
  let translated = trimmed
    .replace(/^Logged in as (.+)$/i, "已登录：$1")
    .replace(/^(.+) members$/i, "$1 名成员")
    .replace(/^Showing (\d+) players$/i, "显示 $1 名玩家")
    .replace(/^Page (\d+) \/ (\d+)$/i, "第 $1 / $2 页")
    .replace(/^No yakuman in this scope\.$/i, "这个范围内没有役满。")
    .replace(/^Not enough games for a trend chart\.$/i, "对局数不足，暂时无法生成趋势图。")
    .replace(/^Type a player name$/i, "输入玩家名")
    .replace(/^Choose a player$/i, "选择玩家");
  return text.replace(trimmed, translated);
}

function applyPageLanguage(language) {
  const root = document.getElementById("root");
  if (!root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => {
    if (node.parentElement?.closest("[data-i18n-owned]")) return;
    const next = translateText(language, node.nodeValue);
    if (next !== node.nodeValue) node.nodeValue = next;
  });
  root.querySelectorAll("input[placeholder], textarea[placeholder]").forEach((node) => {
    const next = translateText(language, node.getAttribute("placeholder"));
    node.setAttribute("placeholder", next);
  });
}

const rankingLabels = {
  quarter_pt: "Quarter PT",
  quarter_mmr: "Quarter MMR",
  total_mmr: "Total MMR",
  total_pt: "Total PT",
  quarter_games: "Quarter Games",
  total_games: "Total Games",
  history_highest_mmr: "History Highest MMR",
};

const fallbackRanking = [
  { rank: 1, initials: "LK", name: "Luna Kim", wins: 18, value: "+2,140", leader: true },
  { rank: 2, initials: "RC", name: "Ryan Chen", wins: 15, value: "+1,870" },
  { rank: 3, initials: "MN", name: "Maya Nguyen", wins: 14, value: "+1,620" },
  { rank: 4, initials: "WZ", name: "Wei Zhang", wins: 12, value: "+840", you: true },
  { rank: 5, initials: "JL", name: "Jamie Liu", wins: 10, value: "+610" },
];

const fallbackRecords = [
  { date: "May 22", opponents: "LK / RC / JL", result: "1st", mmr: "+320", pt: "+86" },
  { date: "May 19", opponents: "MN / JL / TW", result: "2nd", mmr: "+80", pt: "+21" },
  { date: "May 15", opponents: "RC / MN / JL", result: "4th", mmr: "-210", pt: "-54" },
  { date: "May 12", opponents: "LK / TW / SB", result: "1st", mmr: "+450", pt: "+112" },
  { date: "May 8", opponents: "RC / SB / TW", result: "3rd", mmr: "-40", pt: "-8" },
];

function currentAppPage() {
  const path=location.pathname, query=new URLSearchParams(location.search);
  if (/^\/(join|join-table)\//.test(path)) return "join-table";
  if(path.startsWith("/challenges/")) return "challenge";
  if(path==="/login"||path==="/account") return "account";
  if(["/admin","/record","/ranking","/tournament"].includes(path))return path.slice(1);
  if(path.startsWith("/tournaments/"))return "tournament";
  if(path.startsWith("/tables/"))return "record";
  if(path==="/register") return "register";
  if(path==="/registration-complete") return "registration-complete";
  if(path==="/reservations") return "reservations";
  if(path==="/manual-score") return "manual-score";
  if(query.has("tournament")) return "tournament";
  return ["dashboard","ranking","record","reservations","matches","live","tournament","account","admin","result"].includes(query.get("page")) ? query.get("page") : "dashboard";
}
function safeLoginReturn(raw) {
  try {
    if(typeof raw!=="string"||raw.length>2000||!raw.startsWith("/"))return "/";
    let decoded=raw;
    for(let i=0;i<4;i++){
      if(decoded.startsWith("//")||/[\\\x00-\x1f\x7f]/.test(decoded))return "/";
      const target=new URL(decoded,location.origin);
      if(target.origin!==location.origin||["/login","/register"].includes(target.pathname.replace(/\/+$/,"").toLowerCase()))return "/";
      const next=decodeURIComponent(decoded);if(next===decoded)return raw;decoded=next;
    }
  } catch {}
  return "/";
}
function loginReturnTarget() {
  const query=new URLSearchParams(location.search);
  const target=safeLoginReturn(query.get("returnTo")??query.get("redirect_url"));
  // HTTP redirects cannot see fragments. Browsers carry them to /login.
  return safeLoginReturn(target+(!target.includes("#")&&location.hash&&location.hash!=="#reset-password"?location.hash:""));
}
function globalLoginUrl(target=location.pathname+location.search+location.hash) {
  return "/login?returnTo="+encodeURIComponent(safeLoginReturn(target));
}

function App() {
  const [session, setSession] = React.useState(null);
  const [sessionLoaded, setSessionLoaded] = React.useState(false);
  const [profile, setProfile] = React.useState(null);
  const [players, setPlayers] = React.useState([]);
  const [yakumanOptions, setYakumanOptions] = React.useState([]);
  const [matchPlayer, setMatchPlayer] = React.useState("");
  const [viewQuarter, setViewQuarter] = React.useState("");
  const [profileQuarter, setProfileQuarter] = React.useState("");
  const [profilePlayer, setProfilePlayer] = React.useState("");
  const [rankingType, setRankingType] = React.useState("quarter_pt");
  const [page, updatePage] = React.useState(currentAppPage);
  const [routeVersion,setRouteVersion] = React.useState(0);
  function setPage(next) {
    const target=appPageUrl(next);
    history.pushState(null,"",target);updatePage(next);setRouteVersion(v=>v+1);
  }
  React.useEffect(()=>{
    const restore=()=>{updatePage(currentAppPage());setRouteVersion(v=>v+1);};
    addEventListener("popstate",restore);return()=>removeEventListener("popstate",restore);
  },[]);
  const [language, setLanguage] = React.useState(() => localStorage.getItem("mahjong_lang") || "EN");
  const [lastResult, setLastResult] = React.useState(null);
  const [dashboard, setDashboard] = React.useState(null);
  const [status, setStatus] = React.useState("");

  const loadSequence=React.useRef(0),authRequest=React.useRef(null),dataAbort=React.useRef(null);
  const [refreshVersion,setRefreshVersion]=React.useState(0),[assetsReady,setAssetsReady]=React.useState("");
  async function refresh() {
    if(!authRequest.current)authRequest.current=(async()=>{
      const response=await fetch("/api/session",{cache:"no-store"});
      if(!response.ok)throw new Error("sessionUnavailable");
      const data=await response.json();if(data.error)throw new Error("sessionUnavailable");return data;
    })().finally(()=>{authRequest.current=null;});
    try {
      const data=await authRequest.current;
      setSession(data.user||null);setProfile(data.profile||null);setSessionLoaded(true);setStatus("");
      setRefreshVersion(v=>v+1);
    } catch {setStatus(language==="CN"?"暂时无法连接，请重试。":"Could not connect. Please retry.");}
  }
  React.useEffect(()=>{refresh();return()=>dataAbort.current?.abort();},[]);
  React.useEffect(()=>{
    let active=true;
    Promise.resolve(window.MahjongAssets?.load(page)).then(()=>{if(active)setAssetsReady(page);})
      .catch(()=>{if(active)setStatus(language==="CN"?"页面加载失败，请刷新。":"Page could not load. Please refresh.");});
    return()=>{active=false;};
  },[page]);
  React.useEffect(()=>{
    if(!sessionLoaded||!session)return;
    const sequence=++loadSequence.current,controller=new AbortController();dataAbort.current?.abort();dataAbort.current=controller;
    const get=url=>fetch(url,{cache:"no-store",signal:controller.signal}).then(r=>{if(!r.ok)throw new Error("requestFailed");return r.json();});
    const work=[];
    if(["dashboard","ranking","matches","admin","live"].includes(page))work.push(
      get(`/api/dashboard?ranking=${encodeURIComponent(rankingType)}&match_player=${encodeURIComponent(matchPlayer)}&quarter=${encodeURIComponent(viewQuarter)}&profile_quarter=${encodeURIComponent(profileQuarter)}&profile_player=${encodeURIComponent(profilePlayer)}`)
        .then(data=>{if(sequence===loadSequence.current)setDashboard(data);}));
    if(page==="admin")work.push(get("/api/yakuman-options").then(data=>{if(sequence===loadSequence.current)setYakumanOptions(data.options||[]);}));
    Promise.all(work).catch(()=>{if(!controller.signal.aborted)setStatus(language==="CN"?"暂时无法连接，请重试。":"Could not connect. Please retry.");});
    return()=>controller.abort();
  },[sessionLoaded,session,page,refreshVersion,rankingType,matchPlayer,viewQuarter,profileQuarter,profilePlayer]);

  const effectiveMatchPlayer = dashboard?.recent_match_player || matchPlayer;
  const ranking = normalizeRanking(dashboard?.rankings, session, dashboard?.profiles) || fallbackRanking;
  const records = normalizeRecords(dashboard?.recent_games, effectiveMatchPlayer) || [];

  React.useEffect(() => {
    requestAnimationFrame(() => applyPageLanguage(language));
  }, [language, page, dashboard, profile, players, yakumanOptions, lastResult, status]);

  React.useEffect(()=>{
    if(sessionLoaded&&!session&&!["/login","/register","/auth/callback","/discord/callback"].includes(location.pathname))location.replace(globalLoginUrl());
    if(sessionLoaded&&session&&["/login","/register"].includes(location.pathname))location.replace("/");
  },[page,sessionLoaded,session]);

  function removeYakumanFromDashboard(yakumanId, responseData = {}) {
    const idNumber = Number(yakumanId);
    setDashboard((current) => {
      if (!current) return current;
      const next = { ...current };
      next.recent_yakuman = Array.isArray(responseData.recent_yakuman)
        ? responseData.recent_yakuman
        : (current.recent_yakuman || []).filter((item) => Number(item.id) !== idNumber);
      if (Array.isArray(responseData.yakuman_leaders)) {
        next.yakuman_leaders = responseData.yakuman_leaders;
      }
      if (Array.isArray(responseData.recent_yakuman)) {
        next.yakuman_error = "";
      }
      next.stats = {
        ...(current.stats || {}),
        recent_yakuman: next.recent_yakuman.length,
      };
      return next;
    });
  }

  const publicAuth=["/login","/register","/auth/callback","/discord/callback"].includes(location.pathname);
  if(!sessionLoaded||(!session&&!publicAuth)||(session&&["/login","/register"].includes(location.pathname)))return <div data-i18n-owned className="auth-loading" role="status">{status||(language==="CN"?"正在检查登录状态…":"Checking your session…")}{status&&<button className="navigation-link" onClick={refresh}>{language==="CN"?"重试":"Retry"}</button>}</div>;
  if(page==="admin"&&!profile?.is_admin)return <div data-i18n-owned className="auth-loading" role="alert">{language==="CN"?"需要管理员权限。":"Administrator access required."}<a href="/">{language==="CN"?"返回主页":"Home"}</a></div>;
  if(assetsReady!==page)return <div className="auth-loading" role="status">{status||(language==="CN"?"正在加载…":"Loading…")}</div>;
  return (
    <main className={"app-shell min-h-screen "+(session?"club-member-shell":"club-public-shell")}>
      <div className="club-page-container">
        <Header session={session} profile={profile} authReady={sessionLoaded} memberCount={dashboard?.stats?.member_count || players.length} currentQuarter={dashboard?.stats?.view_quarter || dashboard?.stats?.current_quarter} page={page} setPage={setPage} onRefresh={refresh} language={language} setLanguage={setLanguage} />
        {profile?.is_admin&&profile?.has_password===false&&<section role="status" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"><span><strong>{v10(language,"You are an administrator. Please register a password.","你是管理员，请注册密码。")}</strong> {v10(language,"Set it in Account Settings while this administrator session is active.","请在此管理员会话有效时到账号设置中注册。")}</span><button type="button" className="rounded-lg bg-navy px-3 py-2 font-bold text-white" onClick={()=>setPage("account")}>{v10(language,"Set password","设置密码")}</button></section>}
        {status && <p className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-800">{status}</p>}

        {page === "dashboard" && (
          <>
            <ClubLobby language={language} profile={profile} dashboard={dashboard} onNavigate={setPage}/>
            <details open className="club-personal-details"><summary>{language==="CN"?"我的成绩与社团活动":"My stats & club activities"}</summary>
            <CurrentChallenge language={language}/><section className="grid gap-5 lg:grid-cols-2">
              <ProfileCard session={session} profile={profile} summary={dashboard?.current_user_rank} players={players} profilePlayer={profilePlayer} setProfilePlayer={setProfilePlayer} quarters={dashboard?.quarters || []} profileQuarter={profileQuarter} setProfileQuarter={setProfileQuarter} onProfile={setProfile} onRefresh={refresh} language={language} />
            </section>
            <AnnualSummaryCard summary={dashboard?.annual_summary} session={session} />
            </details>
          </>
        )}

        {page === "ranking" && (
          <RankingCard ranking={ranking} rankingType={rankingType} setRankingType={setRankingType} options={dashboard?.ranking_options} yakumanLeaders={dashboard?.yakuman_leaders || []} recentYakuman={dashboard?.recent_yakuman || []} profile={profile} onYakumanDeleted={removeYakumanFromDashboard} onRefresh={refresh} />
        )}

        {page === "record" && (
          <>
            <RecordGameCard key={routeVersion} profile={profile} authReady={sessionLoaded} language={language} players={players} yakumanOptions={yakumanOptions} session={session} onRefresh={refresh} onRecorded={(result) => { setLastResult(result); setPage("result"); }} />
            {lastResult && <GameResultPanel result={lastResult} session={session} profile={profile} onRevert={async (actionId) => {
              const response = await fetch("/api/revert", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action_id: actionId }) });
              const data = await response.json();
              if (!response.ok || !data.ok) throw new Error(data.message || "Could not revert.");
              setLastResult(data.result);
              refresh();
              return data;
            }} />}
          </>
        )}

        {page === "result" && <GameResultPanel result={lastResult} session={session} profile={profile} onRevert={async (actionId) => {
          const response = await fetch("/api/revert", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action_id: actionId }) });
          const data = await response.json();
          if (!response.ok || !data.ok) throw new Error(data.message || "Could not revert.");
          setLastResult(data.result);
          refresh();
          return data;
        }} />}

        {page === "matches" && (
          <GameRecords
            language={language}
            records={records}
            history={dashboard?.quarter_pt_history || []}
            players={players}
            matchPlayer={matchPlayer}
            effectiveMatchPlayer={effectiveMatchPlayer}
            setMatchPlayer={setMatchPlayer}
            currentQuarter={dashboard?.stats?.view_quarter || dashboard?.stats?.current_quarter}
            viewQuarter={dashboard?.stats?.view_quarter || viewQuarter}
            quarters={dashboard?.quarters || []}
            setViewQuarter={setViewQuarter}
            recentYakuman={dashboard?.recent_yakuman || []}
            yakumanOptions={yakumanOptions}
            profile={profile}
            recentMatchCount={dashboard?.recent_match_count}
            onRefresh={refresh}
            onYakumanDeleted={removeYakumanFromDashboard}
          />
        )}

        {page === "account" && <AccountCard language={language} players={players} session={session} profile={profile} onSession={setSession} onProfile={setProfile} onRefresh={refresh} />}

        {page === "admin" && (
          <>
            <DiscordScoringControl language={language}/>
            <AdminTables language={language} profile={profile} /><ExternalApiSettings language={language} profile={profile} />
            <QuarterControlCard
              language={language}
              session={session}
              profile={profile}
              players={players}
              yakumanOptions={yakumanOptions}
              recentYakuman={dashboard?.recent_yakuman || []}
              currentQuarter={dashboard?.stats?.current_quarter}
              setViewQuarter={setViewQuarter}
              onRefresh={refresh}
              onYakumanDeleted={removeYakumanFromDashboard}
            />
            <MatchManagementPanel language={language} players={players} yakumanOptions={yakumanOptions} session={session} profile={profile} onRefresh={refresh} onYakumanDeleted={removeYakumanFromDashboard} onReverted={(result) => { setLastResult(result); setPage("result"); refresh(); }} />
            <AdminActionsPanel session={session} profile={profile} onRefresh={refresh} onYakumanChanged={removeYakumanFromDashboard} />
          </>
        )}

        {page === "challenge" && <CurrentChallenge language={language} full/>}
        {page === "register" && <RegistrationPage language={language} session={session} authReady={sessionLoaded} onRefresh={refresh}/>}
        {page === "registration-complete" && <Card><DiscordOptional complete language={language} target={loginReturnTarget()}/></Card>}
        {page === "reservations" && <ReservationPage key={routeVersion} language={language} profile={profile}/>}
        {page === "manual-score" && (new URLSearchParams(location.search).has("tournament")?<CompetitionManualScore language={language} profile={profile}/>:<ManualScorePage key={routeVersion} language={language} profile={profile} onRefresh={refresh}/>)}
        {page === "join-table" && <TableJoinPage key={routeVersion} language={language} profile={profile} authReady={sessionLoaded}/>}
        {page === "tournament" && <TournamentMode language={language} profile={profile} players={players} />}
        {page === "live" && <LiveGameCard language={language} players={players} session={session} games={dashboard?.live_games || []} onRefresh={refresh} />}
      </div>
    </main>
  );
}


function Card({ children, className = "", id }) {
  return (
    <article id={id} className={`club-card overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-soft ${className}`}>
      <div className="p-7">{children}</div>
    </article>
  );
}

function SectionTitle({ icon: Icon, children, action }) {
  return (
    <div className="mb-6 flex items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <Icon className="h-5 w-5 text-zinc-600" />
        <h2 className="text-sm font-extrabold uppercase tracking-[0.18em] text-zinc-700">{children}</h2>
      </div>
      {action}
    </div>
  );
}

function Avatar({ name, src, size = "lg", leader = false }) {
  const small=size==="sm",sizeClass=small?"h-11 w-11 text-sm":"h-20 w-20 text-2xl";
  return <AccountAvatars.Avatar name={name} src={src} size={small?44:80} className={`${sizeClass} shrink-0 rounded-full border-[3px] ${leader?"border-gold bg-navy text-gold":"border-zinc-200 bg-warm text-zinc-700"} font-black`}/>;
}

function PlayerName({ name, icon, className = "" }) {
  return (
    <span className={`inline-flex min-w-0 items-center gap-1.5 ${className}`}>
      <span className="truncate">{name}</span>
      {icon?.image && <img src={icon.image} alt="" className="h-5 w-5 shrink-0 rounded-full object-cover" />}
      {!icon?.image && icon?.label && <span className="shrink-0 rounded-full bg-warm px-1.5 py-0.5 text-[10px] font-black text-navy">{icon.label}</span>}
    </span>
  );
}

function ProfileCard({ session, profile, summary, players, profilePlayer, setProfilePlayer, quarters, profileQuarter, setProfileQuarter, onProfile, onRefresh, language }) {
  const [message, setMessage] = React.useState("");
  const displayName = summary?.name || session || "Wei Zhang";
  const avatar = summary?.avatar || profile?.avatar || "";
  const personal = summary?.personal_data || null;
  const isOwnProfile = !profilePlayer || normalizeName(profilePlayer) === normalizeName(session || "");
  const rankScope = profileQuarter === "__total__" ? "Total" : "Quarter";
  const text = profileText(language);

  async function uploadAvatar(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!["image/jpeg", "image/png"].includes(file.type)) {
      setMessage("Please upload a JPG or PNG image.");
      return;
    }
    if (!session) {
      setMessage("Log in before setting an avatar.");
      return;
    }
    try {
      setMessage("Preparing avatar...");
      const avatarData = await fileToCompressedDataUrl(file, 650 * 1024);
      const response = await fetch("/api/profile/avatar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ avatar: avatarData }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not save avatar.");
      onProfile(data.profile);
      setMessage("Avatar updated.");
      onRefresh();
    } catch (error) {
      setMessage(error.message || "Could not upload avatar.");
    }
  }

  return (
    <section className="lg:col-span-2">
      <div className="mb-5 flex flex-col gap-3 rounded-2xl border border-zinc-200 bg-white p-4 shadow-soft sm:flex-row sm:items-end">
        <div className="flex-1"><RegisteredUserField value={profilePlayer} onChange={setProfilePlayer} language={language} label={text.viewPlayer}/></div>
        <label className="grid gap-1 text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">
          {text.dataScope}
          <select
            value={profileQuarter}
            onChange={(event) => setProfileQuarter(event.target.value)}
            className="h-11 rounded-xl border border-zinc-200 bg-white px-3 text-sm font-bold normal-case tracking-normal text-zinc-950"
          >
            <option value="">Current quarter</option>
            {(quarters || []).map((quarter) => <option key={quarter} value={quarter}>{quarter}</option>)}
            <option value="__total__">Total games</option>
          </select>
        </label>
      </div>

      <div className="grid gap-5 xl:grid-cols-[0.95fr_1.1fr]">
        <Card>
          <div className="flex flex-col gap-6 sm:flex-row sm:items-center">
            <label className={`relative ${isOwnProfile ? "cursor-pointer" : ""}`}>
              <div className="grid h-40 w-40 place-items-center rounded-full border-[3px] border-zinc-500 bg-cyan-100 text-6xl font-black text-teal-600">
                <AccountAvatars.Avatar name={displayName} src={avatar} size={154} className="h-full w-full rounded-full object-cover"/>
              </div>
              {isOwnProfile && (
                <>
                  <span className="absolute bottom-2 right-2 grid h-9 w-9 place-items-center rounded-full bg-navy text-white shadow">
                    <Camera className="h-4 w-4" />
                  </span>
                  <input type="file" accept="image/jpeg,image/png" onChange={uploadAvatar} className="sr-only" />
                </>
              )}
            </label>
            <div className="min-w-0 flex-1">
              <div className="mb-3 flex flex-wrap gap-2">
                <span className="rounded-lg bg-teal-600 px-4 py-2 text-lg font-black text-white">{personal?.mmr_value || summary?.total_mmr?.value || "--"} MMR</span>
                <span className="rounded-lg bg-teal-600 px-4 py-2 text-lg font-black text-white">{personal?.scope || "Current quarter"}</span>
              </div>
              <h2 className="truncate text-4xl font-black tracking-tight text-zinc-800"><PlayerName name={displayName} icon={summary?.icon || profile?.icon} /></h2>
              <div className="mt-8 grid grid-cols-2 gap-4 text-sm font-bold text-zinc-600 md:grid-cols-4">
                <ProfileRank label={`${rankScope} ${text.mmrRank}`} value={personal?.mmr_rank ? `#${personal.mmr_rank} / ${personal.mmr_rank_total || "--"}` : "--"} />
                <ProfileRank label={`${rankScope} ${text.ptRank}`} value={personal?.pt_rank ? `#${personal.pt_rank} / ${personal.pt_rank_total || "--"}` : "--"} />
                <ProfileRank label={text.games} value={personal?.selected_game_count || summary?.games_played || "--"} />
                <ProfileRank label={text.yakuman} value={personal?.yakuman_count || 0} />
              </div>
              {message && <p className="mt-3 text-sm font-semibold text-zinc-600">{message}</p>}
            </div>
          </div>
        </Card>

        <Card>
          <SectionTitle icon={ListChecks}>{text.keyMetrics}</SectionTitle>
          <div className="grid gap-4 md:grid-cols-3">
            <MetricBar label="MMR" value={personal?.mmr_value || "--"} note={personal?.mmr_rank ? `#${personal.mmr_rank}` : ""} percent={radarValue(personal?.radar, "mmr", 0)} />
            <MetricBar label="PT" value={formatSigned(personal?.pt_value)} note={personal?.pt_rank ? `#${personal.pt_rank}` : ""} percent={radarValue(personal?.radar, "pt_efficiency", 1)} />
            <MetricBar label={text.avgPlace} value={personal?.avg_place || "--"} percent={radarValue(personal?.radar, "placement", 2)} />
            <MetricBar label={text.top2} value={personal?.top2_rate !== undefined ? `${personal.top2_rate}%` : "--"} percent={Number(personal?.top2_rate || 0)} />
            <MetricBar label={text.avoid4} value={personal?.avoid_last_rate !== undefined ? `${personal.avoid_last_rate}%` : "--"} percent={Number(personal?.avoid_last_rate || 0)} />
            <MetricBar label={text.highScore} value={formatInteger(personal?.highest_point)} percent={100} />
          </div>
        </Card>

        <Card>
          <SectionTitle icon={Trophy}>{text.radar}</SectionTitle>
          <RadarChart data={personal?.radar || {}} />
          <div className="mt-5 border-t border-zinc-200 pt-4">
            <h3 className="text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">{text.recentYakuman}</h3>
            <div className="mt-3 grid gap-2">
              {(personal?.yakuman_records || []).slice(-5).reverse().map((item, index) => (
                <div key={`${item.time}-${index}`} className="rounded-lg bg-warm px-3 py-2 text-sm font-bold">
                  <span>{formatSheetDate(item.time)} - {(item.names || [item.yakuman]).join(", ")}</span>
                </div>
              ))}
              {!(personal?.yakuman_records || []).length && <p className="text-sm font-semibold text-zinc-500">No yakuman in this scope.</p>}
            </div>
          </div>
        </Card>

        <Card>
          <SectionTitle icon={ListChecks}>{text.placementDist}</SectionTitle>
          <PlacementDonut counts={personal?.placement_counts || {}} total={personal?.selected_game_count || 0} />
        </Card>

        <Card className="xl:col-span-2">
          <SectionTitle icon={ScrollText}>{text.trend}</SectionTitle>
          <TrendChart history={personal?.history || []} />
        </Card>
      </div>
    </section>
  );
}

function ProfileRank({ label, value }) {
  return (
    <div>
      <span className="block text-zinc-500">{label}</span>
      <strong className="mt-1 block text-xl text-zinc-900">{value}</strong>
    </div>
  );
}

function profileText(language) {
  if (language === "CN") {
    return {
      viewPlayer: "查看玩家",
      dataScope: "数据范围",
      mmrRank: "MMR 排名",
      ptRank: "PT 排名",
      games: "对局数",
      yakuman: "役满",
      keyMetrics: "关键指标",
      avgPlace: "平均顺位",
      top2: "连对率",
      avoid4: "避四率",
      highScore: "最高点",
      radar: "能力雷达",
      recentYakuman: "最近役满",
      placementDist: "顺位分布",
      trend: "战绩变化",
    };
  }
  return {
    viewPlayer: "View player",
    dataScope: "Data scope",
    mmrRank: "MMR rank",
    ptRank: "PT rank",
    games: "Games",
    yakuman: "Yakuman",
    keyMetrics: "Key Metrics",
    avgPlace: "Avg place",
    top2: "Top 2 rate",
    avoid4: "Avoid 4th",
    highScore: "Highest score",
    radar: "Ability Radar",
    recentYakuman: "Recent Yakuman",
    placementDist: "Placement Distribution",
    trend: "Record Trend",
  };
}

function MetricBar({ label, value, note = "", percent = 0 }) {
  const width = Math.max(4, Math.min(100, Number(percent) || 0));
  return (
    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-extrabold text-zinc-500">{label}</span>
        {note && <span className="text-sm font-black text-red-500">{note}</span>}
      </div>
      <strong className="mt-3 block text-2xl font-black text-zinc-950">{value}</strong>
      <div className="mt-3 h-2 rounded-full bg-teal-100">
        <div className="h-full rounded-full bg-teal-500" style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function RadarChart({ data }) {
  const rawValues = Object.values(data || {});
  const labels = [
    ["Strength", radarValue(data, "mmr", 0, 60)],
    ["PT efficiency", radarValue(data, "pt_efficiency", 1, 55)],
    ["Placement", radarValue(data, "placement", 2, 55)],
    ["Attack", radarValue(data, "attack", 3, rawValues[3] ?? 45)],
    ["Defense", radarValue(data, "defense", 4, rawValues[4] ?? 60)],
    ["Recent form", radarValue(data, "recent", 5, rawValues[5] ?? 50)],
  ];
  const size = 310;
  const center = size / 2;
  const radius = 92;
  const points = labels.map(([, value], index) => {
    const angle = (-Math.PI / 2) + (index * Math.PI * 2) / labels.length;
    const normalized = Number(value || 0) <= 1 ? Number(value || 0) * 100 : Number(value || 0);
    const ratio = Math.max(0, Math.min(1, normalized / 100));
    return [center + Math.cos(angle) * radius * ratio, center + Math.sin(angle) * radius * ratio];
  });
  const grid = [0.33, 0.66, 1].map((ratio) => labels.map((entry, index) => {
    const angle = (-Math.PI / 2) + (index * Math.PI * 2) / labels.length;
    return `${center + Math.cos(angle) * radius * ratio},${center + Math.sin(angle) * radius * ratio}`;
  }).join(" "));
  return (
    <div className="flex justify-center">
      <svg viewBox={`0 0 ${size} ${size}`} className="h-[320px] max-w-full">
        {grid.map((polygon, index) => <polygon key={index} points={polygon} fill="none" stroke="#dbeafe" strokeWidth="1" />)}
        {labels.map(([label], index) => {
          const angle = (-Math.PI / 2) + (index * Math.PI * 2) / labels.length;
          const x = center + Math.cos(angle) * (radius + 46);
          const y = center + Math.sin(angle) * (radius + 34);
          return <text key={label} x={x} y={y} textAnchor="middle" className="fill-slate-600 text-[11px] font-bold">{label}</text>;
        })}
        <polygon points={points.map((point) => point.join(",")).join(" ")} fill="rgba(59,130,246,0.35)" stroke="#4f6fca" strokeWidth="3" />
        {points.map(([x, y], index) => <circle key={index} cx={x} cy={y} r="4" fill="#4f6fca" stroke="white" strokeWidth="2" />)}
      </svg>
    </div>
  );
}

function PlacementDonut({ counts, total }) {
  const values = ["1st", "2nd", "3rd", "4th"].map((key) => Number(counts?.[key] || 0));
  const sum = Number(total || values.reduce((a, b) => a + b, 0)) || 0;
  const colors = ["#5b73d1", "#8bc76d", "#ffd15c", "#f25b62"];
  let cumulative = 0;
  const gradient = values.map((value, index) => {
    const start = sum ? (cumulative / sum) * 100 : 0;
    cumulative += value;
    const end = sum ? (cumulative / sum) * 100 : 0;
    return `${colors[index]} ${start}% ${end}%`;
  }).join(", ");
  return (
    <div className="grid gap-6 md:grid-cols-[1fr_1fr] md:items-center">
      <div className="mx-auto grid h-56 w-56 place-items-center rounded-full" style={{ background: `conic-gradient(${gradient || "#e5e7eb 0 100%"})` }}>
        <div className="grid h-32 w-32 place-items-center rounded-full bg-white text-center">
          <strong className="block text-4xl font-black">{sum}</strong>
          <span className="text-sm font-bold text-zinc-500">Total games</span>
        </div>
      </div>
      <div className="grid gap-3">
        {["1st", "2nd", "3rd", "4th"].map((label, index) => (
          <div key={label} className="flex items-center justify-between text-sm font-bold">
            <span className="flex items-center gap-2"><span className="h-3 w-3 rounded" style={{ background: colors[index] }} />{label}</span>
            <span>{values[index]} · {sum ? Math.round((values[index] / sum) * 1000) / 10 : 0}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TrendChart({ history }) {
  const rows = Array.isArray(history) ? history : [];
  if (rows.length < 2) {
    return <div className="grid h-48 place-items-center rounded-xl border border-dashed border-zinc-300 bg-warm text-sm font-semibold text-zinc-500">Not enough games for a trend chart.</div>;
  }
  const width = 900;
  const height = 240;
  const pad = 28;
  const values = rows.map((row) => Number(row.cumulative_pt || 0));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = rows.map((row, index) => {
    const x = pad + (index / Math.max(1, rows.length - 1)) * (width - pad * 2);
    const y = height - pad - ((Number(row.cumulative_pt || 0) - min) / span) * (height - pad * 2);
    return { x, y, row };
  });
  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="min-w-[760px]">
        <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="#d4d4d8" />
        <line x1={pad} y1={pad} x2={pad} y2={height - pad} stroke="#d4d4d8" />
        <polyline points={points.map((point) => `${point.x},${point.y}`).join(" ")} fill="none" stroke="#14b8a6" strokeWidth="4" strokeLinecap="round" />
        {points.map((point, index) => (
          <g key={index}>
            <circle cx={point.x} cy={point.y} r="4" fill={Number(point.row.pt_delta || 0) >= 0 ? "#16a34a" : "#dc2626"} />
            <title>{`${formatSheetDate(point.row.date)} · ${ordinal(point.row.placement)} · ${formatSigned(point.row.pt_delta)} PT · total ${formatSigned(point.row.cumulative_pt)}`}</title>
          </g>
        ))}
      </svg>
    </div>
  );
}

function Stat({ value, label }) {
  return (
    <div className="rounded-xl bg-warm px-4 py-4 text-center">
      <strong className="block text-2xl font-black leading-none">{value}</strong>
      <span className="mt-2 block text-sm text-zinc-600">{label}</span>
    </div>
  );
}

function RankingCard({ ranking, rankingType, setRankingType, options, yakumanLeaders, recentYakuman, profile, onYakumanDeleted, onRefresh }) {
  const rankingOptions = options?.length ? options : Object.entries(rankingLabels).map(([value, label]) => ({ value, label }));
  const canDeleteYakuman = Boolean(profile?.is_admin || profile?.is_super_admin);

  async function deleteRecentYakuman(item) {
    if (!canDeleteYakuman || !item.id) return;
    if (!window.confirm(`Delete all matching records for ${item.winner} - ${item.yakuman} on ${item.date}?`)) return;
    const response = await fetch("/api/admin/yakuman-hard-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        played_at: item.date,
        winner: item.winner,
        yakuman: item.yakuman,
      }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      window.alert(data.message || "Could not delete yakuman.");
      return;
    }
    onYakumanDeleted?.(item.id, data);
    await onRefresh?.();
  }

  return (
    <Card className="min-h-[440px]">
      <SectionTitle
        icon={Trophy}
        action={
          <select value={rankingType} onChange={(event) => setRankingType(event.target.value)} className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm font-bold">
            {rankingOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        }
      >
        Season Ranking
      </SectionTitle>
      <div className="overflow-y-auto pr-2 divide-y divide-zinc-200" style={{ maxHeight: "360px" }}>
        {ranking.map((player) => (
          <div key={`${player.rank}-${player.name}`} className="grid grid-cols-[32px_48px_minmax(0,1fr)_110px] items-center gap-3 py-3">
            <div className={`text-lg font-black ${player.rank === 1 ? "text-gold" : "text-zinc-500"}`}>{player.rank}</div>
            <Avatar name={player.name} src={player.avatar} size="sm" leader={player.rank === 1} />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <PlayerName name={player.name} icon={player.icon} className="text-lg font-semibold" />
                {player.you && <span className="rounded-full bg-navy px-2 py-0.5 text-xs font-extrabold text-gold">you</span>}
              </div>
              <p className="text-sm text-zinc-600">{player.wins ?? 0} wins{player.games != null && <> · {player.games} games</>}</p>
            </div>
            <div className="text-right">
              <strong className="block text-lg font-black">{player.value}</strong>
              <span className="text-sm text-zinc-600">{rankingLabels[rankingType] || player.label || "pts"}</span>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-4 text-right text-xs font-bold uppercase tracking-[0.14em] text-zinc-400">
        Showing {ranking.length} players
      </p>
      <div className="mt-5 grid gap-4 border-t border-zinc-200 pt-5 md:grid-cols-2">
        <div>
          <h3 className="text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">Most Yakuman</h3>
          <div className="mt-3 grid gap-2">
            {(yakumanLeaders || []).slice(0, 5).map((item) => (
              <div key={item.name} className="flex items-center justify-between rounded-lg bg-warm px-3 py-2 text-sm font-bold">
                <span>{item.rank}. {item.name}</span>
                <span>{item.yakuman_count}</span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h3 className="text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">Recent Yakuman</h3>
          <div className="mt-3 grid gap-2">
            {(recentYakuman || []).slice(0, 5).map((item, index) => (
              <div key={`${item.date}-${item.winner}-${index}`} className="rounded-lg bg-warm px-3 py-2 text-sm">
                <div className="flex items-start justify-between gap-2">
                  <span><strong>{item.winner}</strong> - {item.yakuman}</span>
                  {canDeleteYakuman && item.id && (
                    <button type="button" onClick={() => deleteRecentYakuman(item)} className="rounded-md border border-red-200 bg-red-50 px-2 py-0.5 text-[11px] font-black text-red-700">Delete</button>
                  )}
                </div>
                <p className="text-xs font-semibold text-zinc-500">{item.date}</p>
                {item.updated_at && item.updated_at !== item.date && (
                  <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-zinc-400">Updated {formatSheetDate(item.updated_at)}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

function AnnualSummaryCard({ summary, session }) {
  const [open, setOpen] = React.useState(false);
  const [selectedYear, setSelectedYear] = React.useState(summary?.school_year || "");
  const [data, setData] = React.useState(summary || null);
  const [message, setMessage] = React.useState("");

  React.useEffect(() => {
    setData(summary || null);
    setSelectedYear(summary?.school_year || "");
  }, [summary?.school_year]);

  async function loadYear(year) {
    setSelectedYear(year);
    if (!year) return;
    try {
      const response = await fetch(`/api/annual-summary?year=${encodeURIComponent(year)}`, { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.message || "Could not load annual summary.");
      setData(payload.summary);
      setMessage("");
    } catch (error) {
      setMessage(error.message);
    }
  }

  if (!session) {
    return (
      <Card className="mt-5">
        <SectionTitle icon={ScrollText}>Annual Summary</SectionTitle>
        <p className="text-sm font-semibold text-zinc-600">Log in to see your bilingual year recap.</p>
      </Card>
    );
  }
  const active = data || summary;
  const items = active?.items || [];
  return (
    <Card className="mt-5">
      <SectionTitle
        icon={ScrollText}
        action={
          <button type="button" onClick={() => setOpen((value) => !value)} className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-bold">
            {open ? "Hide" : "View"}
          </button>
        }
      >
        Annual Summary
      </SectionTitle>
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <h3 className="text-2xl font-black">{active?.school_year || "School year"} · {active?.name || session}</h3>
          <p className="mt-1 text-sm font-semibold text-zinc-500">{active?.games || 0} games from Fall through Spring</p>
        </div>
        <select
          value={selectedYear}
          onChange={(event) => loadYear(event.target.value)}
          className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm font-bold"
        >
          {(active?.years || []).map((year) => <option key={year} value={year}>{year}</option>)}
        </select>
      </div>
      {message && <p className="mt-3 text-sm font-semibold text-red-600">{message}</p>}
      {open && (
        <div className="mt-5 grid gap-3 md:grid-cols-2">
          {items.map((item) => (
            <div key={item.key} className="rounded-xl border border-zinc-200 bg-warm p-4">
              <div className="flex items-baseline justify-between gap-3">
                <h4 className="text-sm font-black text-zinc-950">{item.title_en || item.title_cn}</h4>
                <span className="text-xs font-extrabold uppercase tracking-[0.12em] text-zinc-400">{item.title_en}</span>
              </div>
              <p className="mt-2 text-lg font-black text-navy">{item.value}</p>
              <p className="mt-2 text-sm font-semibold text-zinc-600">{item.comment_en || item.comment_cn}</p>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function GameRecords({ language, records, history, matchPlayer, effectiveMatchPlayer, setMatchPlayer, currentQuarter, viewQuarter, quarters, setViewQuarter, recentYakuman, yakumanOptions, profile, recentMatchCount, onRefresh, onYakumanDeleted }) {
  const [yakumanMessage, setYakumanMessage] = React.useState("");
  const [deletedYakumanIds, setDeletedYakumanIds] = React.useState([]);
  const [editingYakumanId, setEditingYakumanId] = React.useState(null);
  const noMatchText = matchPlayer
    ? v10(language, `No matches found for ${effectiveMatchPlayer || matchPlayer} in this quarter.`, `本赛季没有找到 ${effectiveMatchPlayer || matchPlayer} 的对局。`)
    : v10(language, "No recent matches in this quarter.", "本赛季暂无最近对局。");
  const normalizedPlayer = normalizeName(effectiveMatchPlayer || matchPlayer || "");
  const yakumanRows = (recentYakuman || []).filter((item) => {
    if (deletedYakumanIds.includes(item.id)) return false;
    if (!normalizedPlayer) return true;
    const winner = normalizeName(item.winner || "");
    const tablePlayers = (item.players || []).map((name) => normalizeName(name));
    return winner === normalizedPlayer || tablePlayers.includes(normalizedPlayer);
  });
  const canDeleteYakuman = Boolean(profile?.is_admin || profile?.is_super_admin);
  // Match history is public; do not query the authenticated account directory.

  async function deleteYakuman(item) {
    if (!canDeleteYakuman || !item.id) return;
    if (!window.confirm(`Delete ${item.winner}'s ${item.yakuman} yakuman record?`)) return;
    try {
      setYakumanMessage("Deleting yakuman...");
      const response = await fetch("/api/admin/yakuman-delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yakuman_id: item.id }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not delete yakuman.");
      setYakumanMessage(data.message);
      setDeletedYakumanIds((current) => [...current, item.id]);
      onYakumanDeleted?.(item.id, data);
      await onRefresh();
    } catch (error) {
      setYakumanMessage(error.message);
    }
  }

  async function editYakuman(event, item) {
    event.preventDefault();
    if (!canDeleteYakuman || !item.id) return;
    const form = event.currentTarget;
    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());
    payload.yakuman_id = item.id;
    try {
      setYakumanMessage("Updating yakuman...");
      const response = await fetch("/api/admin/yakuman-update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not update yakuman.");
      setYakumanMessage(data.message);
      setEditingYakumanId(null);
      onYakumanDeleted?.(item.id, data);
      await onRefresh?.();
    } catch (error) {
      setYakumanMessage(error.message);
    }
  }

  async function uploadYakumanPhoto(item, event) {
    const file = event.target.files?.[0];
    if (!file || !item.id) return;
    if (!["image/jpeg", "image/png"].includes(file.type)) {
      setYakumanMessage("Please upload a JPG or PNG photo.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setYakumanMessage("Yakuman photo must be 10MB or smaller.");
      return;
    }
    try {
      setYakumanMessage("Uploading photo...");
      const photoData = await fileToDataUrl(file);
      const caption = window.prompt("Photo caption", item.photo_caption || "") || "";
      const response = await fetch("/api/admin/yakuman-photo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yakuman_id: item.id, photo_data: photoData, photo_caption: caption }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not upload photo.");
      setYakumanMessage(data.message);
      event.target.value = "";
      onRefresh();
    } catch (error) {
      setYakumanMessage(error.message);
    }
  }

  return (
    <Card className="mt-5">
      <div className="mb-5 flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
        <div>
          <SectionTitle icon={ListChecks}>Recent Match</SectionTitle>
          <p className="-mt-4 text-sm font-semibold text-zinc-500">
            {effectiveMatchPlayer ? `${effectiveMatchPlayer} - ${currentQuarter || "Current quarter"}` : v10(language,"All players","全部玩家")}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <label className="grid gap-1 text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">
            View quarter
            <select
              value={viewQuarter || currentQuarter || ""}
              onChange={(event) => setViewQuarter(event.target.value)}
              className="w-44 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm font-bold normal-case tracking-normal text-zinc-900"
            >
              {(quarters?.length ? quarters : [currentQuarter]).filter(Boolean).map((quarter) => (
                <option key={quarter} value={quarter}>{quarter}</option>
              ))}
            </select>
          </label>
          <RegisteredUserField value={matchPlayer} onChange={setMatchPlayer} language={language} searchUrl="/api/history-players" label={v10(language,"Find a Player","查询玩家姓名")}/>
          <button type="button" onClick={() => setMatchPlayer("")} className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-bold">Clear</button>
        </div>
      </div>

      <QuarterPtChart points={history || []} player={effectiveMatchPlayer || matchPlayer} quarter={currentQuarter} />

      <div className="mt-6 max-h-[520px] overflow-auto pr-2">
        <table className="w-full min-w-[720px] text-left">
          <thead>
            <tr className="border-b border-zinc-200 text-sm font-extrabold text-zinc-700">
              <th className="sticky top-0 bg-white pb-3">Date</th>
              <th className="sticky top-0 bg-white pb-3">Opponents</th>
              <th className="sticky top-0 bg-white pb-3">Result</th>
              <th className="sticky top-0 bg-white pb-3">MMR</th>
              <th className="sticky top-0 bg-white pb-3">PT</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-200">
            {records.length ? records.map((record) => (
              <tr key={`${record.date}-${record.mmr}-${record.opponents}`} className="text-zinc-700">
                <td className="py-4 font-medium">{record.date}</td>
                <td className="py-4">{record.opponents}</td>
                <td className="py-4"><ResultBadge result={record.result} /></td>
                <td className={`py-4 font-black ${record.mmr_value === undefined ? "text-zinc-950" : deltaClass(record.mmr_value)}`}>{record.mmr}</td>
                <td className={`py-4 font-black ${record.pt_value === undefined ? "text-zinc-950" : deltaClass(record.pt_value)}`}>{record.pt}</td>
              </tr>
            )) : (
              <tr>
                <td className="py-6 text-zinc-500" colSpan="5">
                  {noMatchText}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-right text-xs font-bold uppercase tracking-[0.14em] text-zinc-400">
        Showing {records.length} matches{recentMatchCount ? ` from ${recentMatchCount}` : ""}
      </p>

      <div className="mt-6 border-t border-zinc-200 pt-5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h3 className="text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">Yakuman</h3>
          <span className="text-xs font-bold text-zinc-400">{yakumanRows.length} records</span>
        </div>
        {yakumanMessage && <p className="mb-3 text-sm font-semibold text-zinc-600">{yakumanMessage}</p>}
        <div className="max-h-[260px] overflow-auto pr-2">
          {yakumanRows.length ? (
            <div className="grid gap-2">
              {yakumanRows.map((item, index) => (
                <div key={item.id || `${item.date}-${item.winner}-${item.yakuman}-${index}`} className="rounded-xl border border-zinc-200 bg-warm px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-black text-zinc-900">{item.winner} <span className="text-gold">{item.yakuman}</span></p>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-bold text-zinc-500">{formatSheetDate(item.date)}</p>
                      {canDeleteYakuman && item.id && (
                        <>
                          <label className="cursor-pointer rounded-lg border border-zinc-300 bg-white px-2 py-1 text-xs font-extrabold text-zinc-700">
                            Photo
                            <input type="file" accept="image/jpeg,image/png" onChange={(event) => uploadYakumanPhoto(item, event)} className="sr-only" />
                          </label>
                          <button type="button" onClick={() => setEditingYakumanId(editingYakumanId === item.id ? null : item.id)} className="rounded-lg border border-zinc-300 bg-white px-2 py-1 text-xs font-extrabold text-zinc-700">Edit</button>
                          <button type="button" onClick={() => deleteYakuman(item)} className="rounded-lg border border-red-200 bg-red-50 px-2 py-1 text-xs font-extrabold text-red-700">Delete</button>
                        </>
                      )}
                    </div>
                  </div>
                  {item.deal_in && <p className="mt-1 text-sm font-semibold text-red-700">Deal-in: {item.deal_in}</p>}
                  {(item.players || []).length > 0 && <p className="mt-1 text-sm font-semibold text-zinc-500">{item.players.join(" / ")}</p>}
                  <p className="mt-1 text-xs font-bold uppercase tracking-[0.12em] text-zinc-400">
                    SQL #{item.id}{item.game_id ? ` - Game #${item.game_id}` : ""}{item.source ? ` - ${item.source}` : ""}
                  </p>
                  {item.note && <p className="mt-1 text-sm font-semibold text-zinc-600">{item.note}</p>}
                  {editingYakumanId === item.id && (
                    <form onSubmit={(event) => editYakuman(event, item)} className="mt-3 grid gap-3 rounded-xl border border-zinc-200 bg-white p-3">
                      <div className="grid gap-3 md:grid-cols-2">
                        <label className="grid gap-1 text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">
                          Date
                          <input name="played_at" defaultValue={item.date || ""} className="h-10 rounded-lg border border-zinc-200 px-3 text-sm font-bold normal-case tracking-normal text-zinc-950" />
                        </label>
                        <RegisteredUserField name="winner" defaultValue={item.winner||""} required language={language} label={MahjongI18n.t(language,"registeredWinner")} options={registeredRosterOptions([...(item.players||[]),item.winner,item.deal_in])}/>
                        <label className="grid gap-1 text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">
                          Yakuman
                          <select name="yakuman" defaultValue={item.yakuman || ""} required className="h-10 rounded-lg border border-zinc-200 px-3 text-sm font-bold normal-case tracking-normal text-zinc-950">
                            <option value="">Choose yakuman</option>
                            {(yakumanOptions || []).map((name) => <option key={name} value={name}>{name}</option>)}
                          </select>
                        </label>
                        <RegisteredUserField name="deal_in" defaultValue={item.deal_in||""} language={language} label={MahjongI18n.t(language,"registeredDealIn")} options={registeredRosterOptions([...(item.players||[]),item.winner,item.deal_in])}/>
                        <label className="grid gap-1 text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">
                          Game ID
                          <input name="game_id" defaultValue={item.game_id || ""} placeholder="Blank for standalone" className="h-10 rounded-lg border border-zinc-200 px-3 text-sm font-bold normal-case tracking-normal text-zinc-950" />
                        </label>
                        <label className="grid gap-1 text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">
                          Note
                          <input name="note" defaultValue={item.note || ""} className="h-10 rounded-lg border border-zinc-200 px-3 text-sm font-bold normal-case tracking-normal text-zinc-950" />
                        </label>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <button className="rounded-lg bg-navy px-3 py-2 text-sm font-bold text-white">Save edit</button>
                        <button type="button" onClick={() => setEditingYakumanId(null)} className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-bold">Cancel</button>
                      </div>
                    </form>
                  )}
                  {item.photo_url && (
                    <figure className="mt-3 overflow-hidden rounded-xl border border-zinc-200 bg-white">
                      <img src={item.photo_url} alt={`${item.winner} yakuman`} className="max-h-72 w-full object-cover" />
                      {item.photo_caption && <figcaption className="px-3 py-2 text-sm font-semibold text-zinc-600">{item.photo_caption}</figcaption>}
                    </figure>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm font-semibold text-zinc-500">No yakuman records found for this view.</p>
          )}
        </div>
      </div>
    </Card>
  );
}

function QuarterPtChart({ points, player, quarter }) {
  const [hoverIndex, setHoverIndex] = React.useState(null);
  const width = 900;
  const height = 260;
  const pad = 34;
  const values = points.map((point) => Number(point.quarter_pt || 0));
  const minValue = values.length ? Math.min(...values, 0) : 0;
  const maxValue = values.length ? Math.max(...values, 0) : 0;
  const span = Math.max(1, maxValue - minValue);
  const xFor = (index) => points.length <= 1 ? pad : pad + (index / (points.length - 1)) * (width - pad * 2);
  const yFor = (value) => height - pad - ((value - minValue) / span) * (height - pad * 2);
  const path = points.map((point, index) => `${index ? "L" : "M"} ${xFor(index)} ${yFor(Number(point.quarter_pt || 0))}`).join(" ");
  const hovered = hoverIndex === null ? null : points[hoverIndex];

  return (
    <div className="rounded-xl border border-zinc-200 bg-warm/60 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-extrabold uppercase tracking-[0.14em] text-zinc-700">Quarter PT Change</h3>
          <p className="mt-1 text-sm font-semibold text-zinc-500">{player || "Player"} - {quarter || "Current quarter"}</p>
        </div>
        <strong className="text-lg font-black text-zinc-900">{values.length ? formatDelta(values[values.length - 1]) : "--"}</strong>
      </div>
      {points.length ? (
        <div className="relative overflow-x-auto">
          <svg viewBox={`0 0 ${width} ${height}`} className="min-w-[760px]">
            <line x1={pad} x2={width - pad} y1={yFor(0)} y2={yFor(0)} stroke="#d4d4d8" strokeDasharray="4 5" />
            <path d={path} fill="none" stroke="#14213d" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
            {points.map((point, index) => (
              <circle
                key={point.game_id || index}
                cx={xFor(index)}
                cy={yFor(Number(point.quarter_pt || 0))}
                r={hoverIndex === index ? 6 : 4}
                fill={point.pt_delta >= 0 ? "#c9972b" : "#b91c1c"}
                stroke="#fff"
                strokeWidth="2"
                onMouseEnter={() => setHoverIndex(index)}
                onMouseLeave={() => setHoverIndex(null)}
              />
            ))}
          </svg>
          {hovered && (
            <div className="mt-3 rounded-xl border border-zinc-200 bg-white px-4 py-3 text-sm font-semibold text-zinc-700 shadow-soft">
              <div className="flex flex-wrap gap-x-5 gap-y-1">
                <span>{formatSheetDate(hovered.date)}</span>
                <span>{ordinal(hovered.placement)}</span>
                <span>{formatDelta(hovered.pt_delta)} this match</span>
                <span>{formatDelta(hovered.quarter_pt)} quarter total</span>
              </div>
              <p className="mt-1 text-zinc-500">vs {(hovered.opponents || []).join(" / ") || "Unknown"}</p>
            </div>
          )}
        </div>
      ) : (
        <div className="grid h-36 place-items-center rounded-xl border border-dashed border-zinc-300 bg-white text-sm font-semibold text-zinc-500">
          No quarter PT history for this player.
        </div>
      )}
    </div>
  );
}

function recoveryError(language, error) {
  const messages = {
    invalid_reset_code: ["The reset code is invalid or expired. Ask an administrator for a new code.", "重置码错误或已失效，请向管理员领取新码。"],
    invalid_reset_password: ["Password must contain 6–1024 characters.", "密码长度须为 6–1024 个字符。"],
    reset_password_mismatch: ["Please enter the new password twice.", "两次输入的新密码不一致。"],
    reset_notification_failed: ["Could not notify the administrator. Please try again later.", "暂时无法通知管理员，请稍后重试。"],
    reset_name_required: ["Please enter your player name.", "请输入你的玩家名称。"],
    stale_reset_account: ["This player's name changed. Select the player again.", "玩家名称已变更，请重新选择。"],
    admin_password_reset_disabled: ["Administrators can only generate a reset code. Refresh this page.", "管理员只能生成重置码，请刷新页面。"],
    request_denied: ["Permission denied or too many requests. Administrator accounts require a super admin.", "无操作权限或请求过于频繁；管理员账号须由超级管理员生成重置码。"]
  };
  const pair=messages[error.code];
  return pair?v10(language,...pair):error instanceof TypeError?v10(language,"Request failed. Please retry.","请求失败，请重试。"):error.message;
}

function PasswordRecovery({language}) {
  const [busy,setBusy]=React.useState(""),[notice,setNotice]=React.useState(null),pending=React.useRef(false);
  const t=(en,cn)=>v10(language,en,cn);
  async function send(event,kind) {
    event.preventDefault();if(pending.current)return;
    const form=event.currentTarget,body=Object.fromEntries(new FormData(form));
    if(kind==="redeem"&&body.new_password!==body.confirm_password){setNotice({error:{code:"reset_password_mismatch"}});return;}
    pending.current=true;setBusy(kind);setNotice(null);
    try {
      const response=await fetch(kind==="request"?"/api/forgot-password":"/api/reset-password",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
      const data=await response.json();if(!response.ok||!data.ok)throw Object.assign(new Error(data.message||"Request failed."),{code:data.code});
      setNotice({kind});if(kind==="redeem")form.reset();
    }catch(error){setNotice({error});}finally{pending.current=false;setBusy("");}
  }
  React.useEffect(()=>{if(location.hash==="#reset-password")document.getElementById("reset-password")?.scrollIntoView();},[]);
  return <section id="reset-password" data-password-recovery data-i18n-owned className="mt-5 scroll-mt-28 border-t border-zinc-200 pt-5">
    <h3 className="font-black">{t("Forgot password","忘记密码")}</h3>
    <p className="my-2 text-sm text-zinc-600">{t("Request a reset code from an administrator, then set your new password below.","先申请并向管理员领取重置码，再在下面自行设置新密码。")}</p>
    <form data-reset-request onSubmit={e=>send(e,"request")} className="grid gap-3">
      <fieldset disabled={Boolean(busy)} className="grid gap-3">
        <label className="grid gap-1 text-sm font-semibold">{t("Player name","玩家名称")}<input name="username" autoComplete="username" required maxLength={128} className={inputStyle}/></label>
        <button className={buttonStyle}>{busy==="request"?t("Sending…","正在发送…"):t("Request reset code","申请重置码")}</button>
      </fieldset>
    </form>
    <form data-reset-redeem onSubmit={e=>send(e,"redeem")} className="mt-5 grid gap-3 rounded-xl border border-zinc-200 p-4">
      <h4 className="font-bold">{t("Already have a code?","已有重置码？")}</h4>
      <fieldset disabled={Boolean(busy)} className="grid gap-3">
        <label className="grid gap-1 text-sm font-semibold">{t("Player name","玩家名称")}<input name="username" autoComplete="username" required maxLength={128} className={inputStyle}/></label>
        <label className="grid gap-1 text-sm font-semibold">{t("Reset code","重置码")}<input name="reset_code" autoComplete="one-time-code" autoCapitalize="characters" spellCheck={false} required maxLength={64} placeholder="XXXX-XXXX-XXXX" className={inputStyle}/></label>
        <label className="grid gap-1 text-sm font-semibold">{t("New password","新密码")}<input name="new_password" type="password" autoComplete="new-password" required minLength={6} maxLength={1024} className={inputStyle}/></label>
        <label className="grid gap-1 text-sm font-semibold">{t("Confirm new password","确认新密码")}<input name="confirm_password" type="password" autoComplete="new-password" required minLength={6} maxLength={1024} className={inputStyle}/></label>
        <button className={buttonStyle}>{busy==="redeem"?t("Updating…","正在更新…"):t("Set my new password","设置我的新密码")}</button>
      </fieldset>
      <p className="text-xs text-zinc-500">{t("Codes expire after 30 minutes and can only be used once.","重置码 30 分钟内有效，仅可使用一次。")}</p>
    </form>
    {notice&&<p className="mt-3 text-sm font-semibold" role={notice.error?"alert":"status"}>{notice.error?recoveryError(language,notice.error):notice.kind==="redeem"?t("Password updated. Log in with your new password.","密码已更新，请使用新密码登录。"):t("If this player has an active website account, an administrator has been notified. Ask them for your reset code.","若该玩家已开通可用的网站账号，申请已通知管理员，请向管理员领取重置码。")}</p>}
  </section>;
}

function AdminPasswordSetup({language}) {
  const t=(en,cn)=>v10(language,en,cn),[busy,setBusy]=React.useState(false),[message,setMessage]=React.useState("");
  if(location.hash!=="#admin-password-setup")return null;
  async function submit(event){
    event.preventDefault();if(busy)return;
    const form=event.currentTarget,body=Object.fromEntries(new FormData(form));
    if(body.new_password!==body.confirm_password){setMessage(t("Passwords must match.","两次输入的密码不一致。"));return;}
    setBusy(true);setMessage("");
    try{
      const response=await fetch("/api/admin/password-setup",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
      const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.message||t("Could not set the password.","暂时无法设置密码。"));
      location.assign("/");
    }catch(error){setMessage(error.message||t("Could not set the password.","暂时无法设置密码。"));setBusy(false);}
  }
  return <section data-admin-password-setup className="mb-5 rounded-xl border border-amber-200 bg-amber-50 p-4" aria-labelledby="admin-password-setup-title">
    <h2 id="admin-password-setup-title" className="text-lg font-black">{t("Set administrator password","设置管理员密码")}</h2>
    <p className="my-2 text-sm text-zinc-700">{t("Discord verified this administrator account. Choose a password to finish and sign in.","Discord 已验证此管理员账号。设置密码后即可完成并登录。")}</p>
    <form onSubmit={submit} className="grid gap-3">
      <label className="grid gap-1 text-sm font-semibold">{t("New password","新密码")}<input name="new_password" type="password" autoComplete="new-password" required minLength={6} maxLength={1024} className={inputStyle}/></label>
      <label className="grid gap-1 text-sm font-semibold">{t("Confirm password","确认密码")}<input name="confirm_password" type="password" autoComplete="new-password" required minLength={6} maxLength={1024} className={inputStyle}/></label>
      <button disabled={busy} className="rounded-xl bg-navy px-4 py-3 font-bold text-white disabled:opacity-50">{busy?t("Saving…","正在保存……"):t("Set password and sign in","设置密码并登录")}</button>
    </form>
    {message&&<p role="alert" className="mt-3 text-sm text-red-700">{message}</p>}
  </section>;
}

function DiscordScoringControl({language}) {
  const [paused,setPaused]=React.useState(null),[busy,setBusy]=React.useState(false),[notice,setNotice]=React.useState("");
  React.useEffect(()=>{let active=true;
    fetch("/api/admin/discord-score",{cache:"no-store"}).then(async response=>{const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.message||"Could not load Discord scoring status.");return data;})
      .then(data=>{if(active)setPaused(data.paused);}).catch(error=>{if(active)setNotice(error.message);});
    return()=>{active=false;};
  },[]);
  const change=async()=>{if(busy||paused===null)return;setBusy(true);setNotice("");
    try{const response=await fetch("/api/admin/discord-score",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({paused:!paused})});
      const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.message||"Could not update Discord scoring.");
      setPaused(data.paused);setNotice(v10(language,"Discord scoring setting saved.","Discord 登分设置已保存。"));
    }catch(error){setNotice(error.message);}finally{setBusy(false);}
  };
  return <Card id="discord-score-control"><h2 className="text-lg font-black">{v10(language,"Discord scoring","Discord 登分")}</h2>
    <p className="mt-2 text-sm text-zinc-600">{v10(language,"Pause score submission through the Discord /record_game command. Website scoring at doramj.org stays available.","暂停 Discord /record_game 命令登分。doramj.org 网页登分仍可使用。")}</p>
    <p className="mt-3 font-semibold" role="status">{paused===null?v10(language,"Loading status…","正在读取状态……"):paused?v10(language,"Discord scoring is paused.","Discord 登分已暂停。") :v10(language,"Discord scoring is available.","Discord 登分可用。")}</p>
    <button type="button" disabled={paused===null||busy} onClick={change} className="mt-3 rounded-xl bg-navy px-5 py-3 font-bold text-white disabled:opacity-50">{busy?v10(language,"Saving…","正在保存……"):paused?v10(language,"Resume Discord scoring","恢复 Discord 登分"):v10(language,"Pause Discord scoring","暂停 Discord 登分")}</button>
    {notice&&<p className="mt-2 text-sm" role="alert">{notice}</p>}
  </Card>;
}


function PasswordResetAdmin({language}) {
  const [person,setPerson]=React.useState(null),[issued,setIssued]=React.useState(null),[busy,setBusy]=React.useState(false),[error,setError]=React.useState(null),[copied,setCopied]=React.useState(false),pending=React.useRef(false);
  const t=(en,cn)=>v10(language,en,cn);
  React.useEffect(()=>{
    const id=new URLSearchParams(location.search).get("recovery_user");if(!id)return;
    const controller=new AbortController();
    (async()=>{try{
      const response=await fetch("/api/registered-users?ids="+encodeURIComponent(id),{cache:"no-store",signal:controller.signal});
      if(!response.ok)throw new Error(t("Could not load the requested player. Select them below.","无法加载申请玩家，请在下方重新选择。"));
      const data=await response.json();if(!data.users?.length)throw new Error(t("This account is unavailable.","该账号目前不可用。"));
      setPerson(data.users[0]);requestAnimationFrame(()=>document.getElementById("account-recovery")?.scrollIntoView());
    }catch(err){if(!controller.signal.aborted)setError(err);}})();
    return()=>controller.abort();
  },[]);
  async function issue(event){
    event.preventDefault();if(pending.current||!person)return;
    pending.current=true;setBusy(true);setIssued(null);setError(null);setCopied(false);
    try{
      const response=await fetch("/api/admin/password-reset",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:person.name,user_id:person.id})});
      const data=await response.json();if(!response.ok||!data.ok)throw Object.assign(new Error(data.message||"Request failed."),{code:data.code});
      setIssued(data);
    }catch(err){setError(err);}finally{pending.current=false;setBusy(false);}
  }
  return <section id="account-recovery" data-reset-admin data-i18n-owned className="mt-5 scroll-mt-28 border-t border-zinc-200 pt-5">
    <h3 className="font-black">{t("Password reset code","密码重置码")}</h3>
    <p className="my-2 text-sm text-zinc-600">{t("Verify the player's identity, then give them a code. The player chooses their own new password. Generating a new code invalidates the previous one.","核实玩家身份后生成重置码并交给本人。新密码由玩家自行设置；重新生成会使旧码失效。")}</p>
    <form onSubmit={issue} className="grid gap-3">
      <RegisteredUserCombobox value={person} onChange={p=>{setPerson(p);setIssued(null);setError(null);setCopied(false);}} language={language} label={MahjongI18n.t(language,"registeredName")} required disabled={busy}/>
      <input type="hidden" name="username" value={person?.name||""}/>
      <button className={buttonStyle} disabled={busy||!person}>{busy?t("Generating…","正在生成…"):t("Generate reset code","生成重置码")}</button>
    </form>
    {error&&<p className="mt-3 text-sm text-red-700" role="alert">{recoveryError(language,error)}</p>}
    {issued&&<div data-issued-reset className="mt-4 grid gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
      <p className="font-bold">{issued.target}</p>
      <label className="grid gap-1 text-sm font-semibold">{t("Reset code","重置码")}<input readOnly value={issued.reset_code} onFocus={e=>e.target.select()} className={inputStyle+" font-mono tracking-wider"}/></label>
      <p className="text-sm">{t("Expires at","失效时间")}: {new Date(issued.expires_at*1000).toLocaleString(language==="CN"?"zh-CN":"en-US")}</p>
      <p className="text-sm">{t("This code is shown only here. Share it privately with the player.","重置码仅在此处显示，请私下交给该玩家。")}</p>
      <button type="button" className={buttonStyle} onClick={async()=>{try{await navigator.clipboard.writeText(issued.reset_code);setCopied(true);}catch{setError(new Error(t("Select and copy the code manually.","请选中重置码手动复制。")));}}}>{copied?t("Copied","已复制"):t("Copy code","复制重置码")}</button>
      <a className="break-all text-sm underline" href="/login#reset-password">{t("User reset page","玩家重置密码页面")}: {location.origin}/login#reset-password</a>
    </div>}
  </section>;
}

function playerPickerCopy(language, recordedOnly=false) {
  return {
    registeredNameSelected:v10(language,"Player selected","已选择玩家"),
    registeredNameClear:v10(language,"Clear selection","清除选择"),
    registeredNameLoading:v10(language,"Searching players…","正在搜索玩家……"),
    registeredNameNone:recordedOnly
      ?v10(language,"No matching player with a recorded game was found.","未找到有对局记录的匹配玩家。")
      :v10(language,"No matching historical player was found.","未找到匹配的历史玩家。"),
    registeredNameSearchFailed:v10(language,"Player search is unavailable. Please retry.","玩家搜索暂不可用，请重试。"),
    registeredNameRetry:v10(language,"Retry search","重试搜索"),
    registeredNameMore:v10(language,"More results","更多结果"),
    registeredNameSelectRequired:v10(language,"Select a player from the suggestions.","请从候选列表中选择玩家。"),
  };
}

function AccountCard({ players, session, profile, onSession, onProfile, onRefresh, language }) {
  const [message, setMessage] = React.useState("");
  const [loginBusy,setLoginBusy]=React.useState(false);
  const [memberQuery,setMemberQuery]=React.useState("");
  const [memberChoices,setMemberChoices]=React.useState([]);
  const [memberLoading,setMemberLoading]=React.useState(false);
  const [memberSearchError,setMemberSearchError]=React.useState(false);
  const [adminUsername,setAdminUsername]=React.useState("");
  const hasPassword=profile?.has_password!==false;

  React.useEffect(()=>{
    const query=memberQuery.trim();
    if(session||!query){setMemberChoices([]);setMemberLoading(false);setMemberSearchError(false);return;}
    const controller=new AbortController();let current=true;
    setMemberChoices([]);setMemberLoading(true);setMemberSearchError(false);
    const timer=setTimeout(async()=>{
      try {
        const response=await fetch("/api/login-players?"+new URLSearchParams({q:query,limit:"20"}),{cache:"no-store",signal:controller.signal});
        if(!response.ok)throw new Error("search");
        const result=await response.json();
        if(current)setMemberChoices(Array.isArray(result.users)?result.users:[]);
      } catch(error) {
        if(current&&error.name!=="AbortError"){setMemberChoices([]);setMemberSearchError(true);}
      } finally {if(current)setMemberLoading(false);}
    },180);
    return()=>{current=false;clearTimeout(timer);controller.abort();};
  },[session,memberQuery]);

  async function request(path, source) {
    setMessage(v10(language,"Working…","正在处理……"));
    const fields=source?.tagName==="FORM"?Object.fromEntries(new FormData(source).entries()):{...(source||{})};
    const payload = {...fields,returnTo:loginReturnTarget()};
    const response = await fetch(path, { method: "POST", credentials:"same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      const error = new Error(data.message || "Request failed.");
      error.code = data.code;
      throw error;
    }
    return data;
  }

  function showLoginError(error) {
    setMessage(error.code === "admin_password_setup_required"
      ? v10(language,"You are an administrator. Please register a password. Use the Discord verification button below.","你是管理员，请注册密码。请使用下方 Discord 验证按钮设置。")
      : error.code === "website_registration_required"
        ? MahjongI18n.t(language, "websiteRegistrationRequired")
        : error.code === "password_required"
          ? v10(language,"Choose your name above to sign in without a password.","请在上方选择自己的姓名，无需密码即可登录。")
        : error.message === "Incorrect username or password."
          ? MahjongI18n.t(language, "loginFailed")
          : error instanceof TypeError ? MahjongI18n.t(language, "loginRequestFailed") : error.message);
  }

  async function submit(event) {
    event.preventDefault();
    if(loginBusy)return;
    setLoginBusy(true);
    try {
      const data = await request("/api/login", event.currentTarget);
      location.assign(safeLoginReturn(data.redirect_url||loginReturnTarget()));
    } catch (error) {showLoginError(error);}
    finally {setLoginBusy(false);}
  }

  async function chooseMember(player) {
    if(loginBusy)return;
    setLoginBusy(true);setMessage("");
    try {
      const data=await request("/api/login",{player_id:player.id});
      location.assign(safeLoginReturn(data.redirect_url||loginReturnTarget()));
    } catch(error) {showLoginError(error);}
    finally {setLoginBusy(false);}
  }

  async function startAdminPasswordSetup() {
    if(loginBusy)return;
    if(!adminUsername.trim()){
      setMessage(v10(language,"Enter your administrator username first.","请先输入管理员用户名。"));
      return;
    }
    setLoginBusy(true);setMessage(v10(language,"Opening Discord verification…","正在打开 Discord 验证……"));
    try{
      const response=await fetch("/api/admin/password-setup/start",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:adminUsername.trim()})});
      const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.message||"Could not start password setup.");
      location.assign(data.url);
    }catch(error){setMessage(error.message||v10(language,"Could not start password setup.","无法开始密码设置。"));setLoginBusy(false);}
  }

  async function logout() {
    await fetch("/api/logout", { method: "POST" });
    onSession(null);
    onProfile(null);
    setMessage("Logged out.");
    onRefresh();
  }

  async function changePassword(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    if (formData.get("new_password") !== formData.get("confirm_password")) {
      setMessage(v10(language,"Please enter the new password twice.","请重复输入相同的新密码。"));
      return;
    }
    try {
      const data = await request("/api/change-password", form);
      setMessage(data.warning || data.message || v10(language,"Password saved.","密码已保存。"));
      form.reset();
      onRefresh();
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function unbindDiscord() {
    try {
      setMessage("Unbinding Discord...");
      const response = await fetch("/api/profile/discord-unbind", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not unbind Discord.");
      onProfile(data.profile);
      setMessage(data.message || "Discord account unbound.");
      onRefresh();
    } catch (error) {
      setMessage(error.message);
    }
  }

  if (session && profile?.session_mode === "member") {
    return <Card><div data-i18n-owned>
      <SectionTitle icon={LogIn}>{v10(language,"Member selected","已选择成员")}</SectionTitle>
      <p className="mb-4 rounded-xl bg-warm px-4 py-3">{v10(language,"Using the club member profile for","当前使用成员资料：")} <strong>{profile?.name||session}</strong></p>
      <p className="mb-4 text-sm text-zinc-600">{v10(language,"You can switch members at any time. No password or administrator approval is needed for an existing player.","随时可以切换成员。已有玩家无需密码，也无需管理员审批。")}</p>
      <div className="flex flex-wrap gap-3"><a href="/reservations" className="rounded-xl bg-navy px-4 py-3 font-bold text-white">{v10(language,"Reserve a table","预约桌子")}</a><button type="button" onClick={logout} className="rounded-xl border border-zinc-300 bg-white px-4 py-3 font-bold">{v10(language,"Switch member / Log out","切换成员 / 退出登录")}</button></div>
      <p className="mt-4 min-h-5 text-sm font-semibold text-zinc-600" role="status">{message}</p>
    </div></Card>;
  }

  if (session) {
    return (
      <Card>
        <div data-i18n-owned>
          <SectionTitle icon={LogIn}>{v10(language,"Account Settings","账号设置")}</SectionTitle>
          <div className="mb-4 rounded-xl bg-warm px-4 py-3">
            <label className="grid gap-1 text-sm font-bold text-zinc-700">{MahjongI18n.t(language,"ownRegisteredName")}<input readOnly value={profile?.name||session} className="rounded-lg border border-zinc-200 bg-white px-3 py-2"/></label>
            <p className="mt-2 text-sm text-zinc-600">{MahjongI18n.t(language,"registeredNameReadOnlyHelp")}</p>
          </div>
          <div id="discord-binding" className="mb-5 rounded-xl border border-zinc-200 bg-white px-4 py-3">
            <h3 className="text-sm font-black uppercase tracking-[0.14em] text-zinc-500">{v10(language,"Discord binding","Discord 绑定")}</h3>
            {profile?.discord_id ? (
              <div className="mt-2 flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
                <p className="font-bold text-zinc-800">{v10(language,"Bound to","已绑定至")} {profile.discord_name || MahjongI18n.t(language,"discordLinked")}</p>
                <button type="button" onClick={unbindDiscord} className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm font-black text-red-700">{v10(language,"Unbind","解除绑定")}</button>
              </div>
            ) : (
              <p className="mt-2 text-sm font-semibold text-zinc-600">{v10(language,"Not bound. In Discord, run","尚未绑定。请在 Discord 中运行")} <span className="font-black">/bind_web_account</span> {v10(language,"with this player name.","并使用当前玩家名称。")}</p>
            )}
          </div>
          <div className="mb-5"><DiscordOptional language={language} target="/account#discord-binding"/></div>
          <form onSubmit={changePassword} className="grid gap-4">
            <p className="text-sm text-zinc-600">{hasPassword
              ?v10(language,"Use this password for future sign-ins. Your player ID and match history remain linked to this account.","后续可使用此密码登录；玩家 ID 和历史成绩仍与此账号关联。")
              :v10(language,"A password is optional. Existing members can sign in by selecting their name.","密码为可选项。已有成员可直接选择姓名登录。")}</p>
            {hasPassword&&<label className="grid gap-2 text-sm font-bold text-zinc-600">
              {v10(language,"Current password","当前密码")}
              <input name="old_password" type="password" required autoComplete="current-password" className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
            </label>}
            <label className="grid gap-2 text-sm font-bold text-zinc-600">
              {v10(language,hasPassword?"New password":"Set a password",hasPassword?"新密码":"设置密码")}
              <input name="new_password" type="password" required minLength={6} maxLength={1024} autoComplete="new-password" className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
            </label>
            <label className="grid gap-2 text-sm font-bold text-zinc-600">
              {v10(language,"Confirm new password","确认新密码")}
              <input name="confirm_password" type="password" required minLength={6} maxLength={1024} autoComplete="new-password" className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button className="rounded-xl bg-navy px-4 py-3 font-bold text-white">{v10(language,hasPassword?"Change password":"Set password",hasPassword?"修改密码":"设置密码")}</button>
              <button type="button" onClick={logout} className="rounded-xl border border-zinc-300 bg-white px-4 py-3 font-bold">{v10(language,"Log out","退出登录")}</button>
            </div>
          </form>
          <p className="mt-4 min-h-5 text-sm font-semibold text-zinc-600" role="status">{message}</p>
        </div>
      </Card>
    );
  }

  return <Card><div data-i18n-owned>
    <SectionTitle icon={LogIn}>{v10(language,"Choose a member","选择成员")}</SectionTitle>
    <p className="mb-4 text-sm text-zinc-600">{v10(language,"Search the club list by player name or ID. Select a member to continue; existing members do not need a password or administrator approval.","按玩家姓名或 ID 搜索俱乐部名单。选择成员即可进入；已有成员无需密码或管理员审批。")}</p>
    <label className="grid gap-2 text-sm font-bold text-zinc-600">{v10(language,"Player name or ID","玩家姓名或 ID")}
      <input value={memberQuery} onChange={event=>setMemberQuery(event.target.value)} autoComplete="off" role="combobox" aria-expanded={Boolean(memberQuery.trim())} aria-controls="member-login-results" className="h-12 rounded-xl border border-zinc-200 px-3 text-zinc-950" placeholder={v10(language,"Type a name or player ID","输入姓名或玩家 ID")}/>
    </label>
    {memberQuery.trim()&&<div className="mt-2 rounded-xl border border-zinc-200 bg-white p-2" id="member-login-results">
      {memberLoading&&<p className="p-2 text-sm" role="status">{v10(language,"Searching members…","正在搜索成员……")}</p>}
      {memberSearchError&&<p className="p-2 text-sm text-red-700" role="alert">{v10(language,"Member search is unavailable. Please retry.","成员搜索暂不可用，请重试。")}</p>}
      {!memberLoading&&!memberSearchError&&!memberChoices.length&&<p className="p-2 text-sm text-zinc-600" role="status">{v10(language,"No matching member found.","没有找到匹配成员。")}</p>}
      <ul className="max-h-64 overflow-y-auto" role="listbox">{memberChoices.map(player=><li key={player.id}><button type="button" disabled={loginBusy} onClick={()=>chooseMember(player)} className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-3 text-left hover:bg-warm disabled:opacity-50"><span className="break-words font-bold">{player.name}</span><span className="shrink-0 text-xs text-zinc-500">ID {player.display_id}</span></button></li>)}</ul>
    </div>}
    <a href={"/register?returnTo="+encodeURIComponent(loginReturnTarget())} className="mt-4 inline-block rounded-xl border border-zinc-300 bg-white px-4 py-3 text-center font-bold">{v10(language,"New member? Register","新成员？注册")}</a>
    <details open={location.hash==="#admin-password-setup"} className="mt-5 rounded-xl border border-zinc-200 bg-zinc-50 p-4">
      <summary className="cursor-pointer font-bold text-zinc-700">{v10(language,"Administrator entrance","管理员入口")}</summary>
      <p className="mb-4 mt-3 text-sm text-zinc-600">{v10(language,"Administrators sign in separately with their username and password.","管理员请在此使用独立的用户名和密码登录。")}</p>
      <form onSubmit={submit} className="grid gap-4">
        <label className="grid gap-2 text-sm font-bold text-zinc-600">{v10(language,"Administrator username","管理员用户名")}<input name="username" value={adminUsername} onChange={e=>setAdminUsername(e.target.value)} autoComplete="username" required disabled={loginBusy} className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950"/></label>
        <label className="grid gap-2 text-sm font-bold text-zinc-600">{v10(language,"Password","密码")}<input name="password" type="password" autoComplete="current-password" disabled={loginBusy} className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950"/></label>
        <button disabled={loginBusy} className="rounded-xl bg-navy px-4 py-3 font-bold text-white disabled:opacity-50">{loginBusy?v10(language,"Signing in…","正在登录……"):v10(language,"Administrator sign in","管理员登录")}</button>
      </form>
      <button type="button" disabled={loginBusy} onClick={startAdminPasswordSetup} className="mt-3 w-full rounded-xl border border-zinc-300 bg-white px-4 py-3 text-sm font-bold disabled:opacity-50">{v10(language,"No password yet? Verify Discord and set one","还没有密码？验证 Discord 后即可设置")}</button>
      <AdminPasswordSetup language={language}/>
      <PasswordRecovery language={language}/>
    </details>
    <p className="mt-4 min-h-5 text-sm font-semibold text-zinc-600" role="status">{message}</p>
  </div></Card>;
}

function RecordGameCard({ session, profile, authReady, onRefresh, language }) {
  const frame = React.useRef(null);
  const initialDraft = React.useRef(new URLSearchParams(location.search).get("draft_id")||"");
  const [height, setHeight] = React.useState(1100);
  const [reviewOpen,setReviewOpen] = React.useState(false);
  const [table,setTable] = React.useState("");
  const requestedTable=React.useRef(new URLSearchParams(location.search).get("table")??(location.pathname.startsWith("/tables/")?location.pathname.split("/")[2]:null));
  const entryToken=React.useRef(new URLSearchParams(location.hash.slice(1)).get("entry"));
  const pendingSeat = React.useRef(new URLSearchParams(location.search).get("pending_seat")||"");
  const autoSelectFull=React.useRef(!initialDraft.current&&!pendingSeat.current&&!entryToken.current&&!location.pathname.startsWith("/tables/")&&!new URLSearchParams(location.search).has("match_id"));
  const sendContext = () => {
    const target=frame.current?.contentWindow;if(!target)return;
    target.postMessage({type:"mahjong-language",language},location.origin);
    target.postMessage({type:"mahjong-score-context",authReady:Boolean(authReady),profile:profile?{id:String(profile.id),name:profile.name}:null,
      table,entryToken:new URLSearchParams(location.hash.slice(1)).get("entry"),pendingSeat:pendingSeat.current},location.origin);
  };
  React.useEffect(sendContext, [language,authReady,profile?.id,profile?.name,table]);
  React.useLayoutEffect(()=>{
    if(!reviewOpen)return;
    const previous=document.body.style.overflow;
    document.body.style.overflow="hidden";
    frame.current?.contentWindow?.postMessage({type:"mahjong-score-review-ready"},location.origin);
    return ()=>{document.body.style.overflow=previous;};
  },[reviewOpen,table]);
  React.useEffect(() => {
    function receive(event) {
      if (event.origin !== location.origin || event.source !== frame.current?.contentWindow) return;
      if (event.data?.type === "mahjong-score-ready") sendContext();
      if (event.data?.type === "mahjong-score-review" && event.data.table===table) {
        setReviewOpen(Boolean(event.data.open));
        // Repeated recognition can update an already open correction dialog.
        if(event.data.open&&reviewOpen)frame.current?.contentWindow?.postMessage({type:"mahjong-score-review-ready"},location.origin);
      }
      if (["mahjong-seat-swap-open","mahjong-seat-action-open"].includes(event.data?.type) && event.data.table===table) {
        const top=frame.current.getBoundingClientRect().top+window.scrollY;
        window.scrollTo({top:Math.max(0,top-112),behavior:"instant"});
      }
      if (event.data?.type === "mahjong-seat-login" && event.data.table===table && ["east","south","west","north"].includes(event.data.seat)) {
        const url=new URL(location.href);url.searchParams.set("pending_seat",event.data.seat);url.searchParams.set("table",table);
        location.assign(globalLoginUrl(url.pathname+url.search+url.hash));
      }
      if (event.data?.type === "mahjong-seat-resume-consumed" && event.data.table===table) {
        pendingSeat.current="";const url=new URL(location.href);url.searchParams.delete("pending_seat");history.replaceState(null,"",url);
      }
      if (event.data?.type === "mahjong-score-height" && Number.isFinite(event.data.height)) {
        setHeight(Math.max(500, Math.min(10000, event.data.height + 12)));
      }
      if (event.data?.type === "mahjong-score-draft" || event.data?.type === "mahjong-score-saved") {
        const url=new URL(location.href);
        if(event.data.draft_id)url.searchParams.set("draft_id",event.data.draft_id);else url.searchParams.delete("draft_id");
        history.replaceState(null,"",url);
      }
      if (event.data?.type === "mahjong-score-saved") onRefresh();
    }
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [onRefresh,authReady,profile?.id,profile?.name,language,table,reviewOpen]);
  return (
    <Card className="scroll-mt-8" id="record-game">
      <SectionTitle icon={Camera}>{MahjongI18n.t(language,"photoScore")}</SectionTitle>
      <div className="mb-4 flex flex-wrap gap-3" data-i18n-owned>
        <a className={buttonStyle} href={"/manual-score"+(table?"?table="+encodeURIComponent(table):"")}>{MahjongI18n.t(language,"manualScore")}</a>
        {table&&<a className="px-2 py-2 text-sm underline" href={"/reservations?table="+encodeURIComponent(table)}>{MahjongI18n.t(language,"viewReservations")}</a>}
      </div>
      <ScoringTableStatus profile={profile} language={language} requestedTable={requestedTable.current} entryToken={entryToken.current} autoSelectFull={autoSelectFull.current}
        onChanged={()=>frame.current?.contentWindow?.postMessage({type:"mahjong-table-changed"},location.origin)}
        onResolved={id=>{if(id!==table){const url=new URL(location.href);if(id)url.searchParams.set("table",id);else url.searchParams.delete("table");if(table){initialDraft.current="";pendingSeat.current="";url.searchParams.delete("draft_id");url.searchParams.delete("pending_seat");}history.replaceState(null,"",url);setTable(id);}}}/>

      {table&&<div style={{height:height+"px"}}><iframe ref={frame} onLoad={sendContext} title={MahjongI18n.t(language,"photoFrame")}
        key={table} src={"/score?embedded=1&table=" + encodeURIComponent(table)+(initialDraft.current?"&draft_id="+encodeURIComponent(initialDraft.current):"")}
        className="w-full border-0" style={reviewOpen?{position:"fixed",inset:0,zIndex:1000,width:"100vw",height:"100dvh"}:{height:height+"px"}} /></div>}
    </Card>
  );
}

function QuarterControlCard({ language, session, profile, players, yakumanOptions, recentYakuman, currentQuarter, setViewQuarter, onRefresh, onYakumanDeleted }) {
  const [message, setMessage] = React.useState("");
  const [roleMessage, setRoleMessage] = React.useState("");
  const [accountMessage, setAccountMessage] = React.useState("");
  const [playerMessage, setPlayerMessage] = React.useState("");
  const [yakumanMessage, setYakumanMessage] = React.useState("");
  const [yakumanCandidates, setYakumanCandidates] = React.useState([]);
  const [mergeSource,setMergeSource]=React.useState(null);
  const [mergeTarget,setMergeTarget]=React.useState(null);
  const canAdmin = Boolean(profile?.is_admin);
  const canSuperAdmin = Boolean(profile?.is_super_admin);

  async function submit(event) {
    event.preventDefault();
    if (!session) {
      setMessage("Log in before changing quarter.");
      return;
    }
    if (!canAdmin) {
      setMessage("Only admins can change quarter.");
      return;
    }
    const action = event.nativeEvent.submitter?.value || "next";
    const prompt = action === "undo"
      ? "Restore the previous quarter?"
      : `Change quarter from ${currentQuarter || "current"} to the next quarter?`;
    if (!window.confirm(prompt)) return;
    const payload = { action };
    setMessage(action === "undo" ? "Restoring quarter..." : "Changing quarter...");
    try {
      const response = await fetch("/api/quarter", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not update quarter.");
      setViewQuarter(data.quarter);
      setMessage(data.warning || data.message);
      onRefresh();
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function updateRole(event) {
    event.preventDefault();
    if (!canSuperAdmin) {
      setRoleMessage("Only super admins can update roles.");
      return;
    }
    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form).entries());
    setRoleMessage("Updating role...");
    try {
      const response = await fetch("/api/admin/role", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not update role.");
      setRoleMessage(data.message);
      onRefresh();
    } catch (error) {
      setRoleMessage(error.message);
    }
  }

  async function manageAccount(event) {
    event.preventDefault();if(!canSuperAdmin)return;
    const form=event.currentTarget,payload=Object.fromEntries(new FormData(form));
    if(!window.confirm(`Delete account for ${payload.username||"this user"}?`))return;
    setAccountMessage("Deleting account...");
    try{
      const response=await fetch("/api/admin/account-delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
      const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.message||"Could not delete account.");
      setAccountMessage(data.message);form.reset();onRefresh();
    }catch(error){setAccountMessage(error.message);}
  }

  async function mergePlayers(event) {
    event.preventDefault();
    if (!canAdmin) {
      setPlayerMessage("Only admins can merge players.");
      return;
    }
    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form).entries());
    if(!mergeSource||!mergeTarget||!payload.source_player_id||!payload.target_player_id){
      setPlayerMessage(v10(language,"Select both historical players from the search results.","请从搜索结果中选择要合并的两个历史玩家。"));
      return;
    }
    if(String(payload.source_player_id)===String(payload.target_player_id)){
      setPlayerMessage(v10(language,"Choose two different player IDs.","请选择两个不同的玩家 ID。"));
      return;
    }
    const describe=person=>`${person.name} (ID ${person.display_id||v10(language,"unavailable","不可用")})`;
    const prompt=v10(language,
      `Merge ${describe(mergeSource)} into ${describe(mergeTarget)} and recompute every SQL game?`,
      `确认将 ${describe(mergeSource)} 合并到 ${describe(mergeTarget)}，并重新计算所有对局吗？`);
    if (!window.confirm(prompt)) return;
    setPlayerMessage(v10(language,"Merging players and recomputing all games…","正在合并玩家并重新计算所有对局……"));
    try {
      const response = await fetch("/api/admin/player-merge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not merge players.");
      setPlayerMessage(data.message);
      form.reset();
      setMergeSource(null);setMergeTarget(null);
      onRefresh();
    } catch (error) {
      setPlayerMessage(error.message);
    }
  }

  async function setPlayerIcon(event) {
    event.preventDefault();
    if (!canAdmin) {
      setPlayerMessage("Only admins can set player icons.");
      return;
    }
    const form = event.currentTarget;
    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());
    try {
      const iconFile = formData.get("icon_file");
      if (iconFile && iconFile.size) {
        if (!["image/jpeg", "image/png"].includes(iconFile.type)) throw new Error("Please upload a JPG or PNG icon.");
        if (iconFile.size > 1024 * 1024) throw new Error("Icon image must be 1MB or smaller.");
        payload.icon_image = await fileToDataUrl(iconFile);
      }
      delete payload.icon_file;
      setPlayerMessage("Updating icon...");
      const response = await fetch("/api/admin/player-icon", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not update icon.");
      setPlayerMessage(data.message);
      form.reset();
      onRefresh();
    } catch (error) {
      setPlayerMessage(error.message);
    }
  }

  async function createPlayer(event) {
    event.preventDefault();
    if (!canAdmin) {
      setPlayerMessage("Only admins can create players.");
      return;
    }
    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form).entries());
    setPlayerMessage("Creating player...");
    try {
      const response = await fetch("/api/admin/player-create", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not create player.");
      setPlayerMessage(data.message);
      form.reset();
      onRefresh();
    } catch (error) {
      setPlayerMessage(error.message);
    }
  }

  async function findYakumanMatches(event) {
    const form = event.currentTarget.form;
    const formData = new FormData(form);
    const names = [formData.get("winner"), formData.get("deal_in"), ...formData.getAll("other_players")].filter(Boolean);
    if (names.length < 2) {
      setYakumanMessage("Enter at least two table players to search matches.");
      return;
    }
    setYakumanMessage("Searching matching games...");
    try {
      const response = await fetch(`/api/match-candidates?players=${encodeURIComponent(names.join("/"))}&played_at=${encodeURIComponent(formData.get("played_at") || "")}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not search matches.");
      setYakumanCandidates(data.matches || []);
      setYakumanMessage((data.matches || []).length ? "Choose a matching game below." : "No matching games found.");
    } catch (error) {
      setYakumanMessage(error.message);
    }
  }

  async function addYakuman(event) {
    event.preventDefault();
    if (!canAdmin) {
      setYakumanMessage("Only admins can add yakuman records.");
      return;
    }
    const form = event.currentTarget;
    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());
    payload.yakuman_names = formData.getAll("yakuman_names");
    payload.other_players = formData.getAll("other_players").filter(Boolean);
    payload.attach_latest_game = formData.get("attach_latest_game") ? "1" : "";
    setYakumanMessage("Adding yakuman...");
    try {
      const photoFile = formData.get("photo");
      if (photoFile && photoFile.size) {
        if (!["image/jpeg", "image/png"].includes(photoFile.type)) throw new Error("Please upload a JPG or PNG yakuman photo.");
        if (photoFile.size > 10 * 1024 * 1024) throw new Error("Yakuman photo must be 10MB or smaller.");
        payload.photo_data = await fileToDataUrl(photoFile);
      }
      delete payload.photo;
      const response = await fetch("/api/admin/yakuman", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not add yakuman.");
      setYakumanMessage(data.message);
      form.reset();
      setYakumanCandidates([]);
      onRefresh();
    } catch (error) {
      setYakumanMessage(error.message);
    }
  }

  async function deleteYakuman(event) {
    event.preventDefault();
    if (!canAdmin) {
      setYakumanMessage("Only admins can revert yakuman records.");
      return;
    }
    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form).entries());
    if (!payload.yakuman_id) {
      setYakumanMessage("Choose a yakuman record to revert.");
      return;
    }
    if (!window.confirm("Revert this yakuman record?")) return;
    try {
      setYakumanMessage("Reverting yakuman...");
      const response = await fetch("/api/admin/yakuman-delete", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not revert yakuman.");
      setYakumanMessage(data.message);
      form.reset();
      onYakumanDeleted?.(payload.yakuman_id, data);
      await onRefresh();
    } catch (error) {
      setYakumanMessage(error.message);
    }
  }

  return (
    <Card className="mt-5">
      <SectionTitle icon={ScrollText}>Quarter</SectionTitle>
      {canAdmin && (
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-[1fr_auto_auto] md:items-end">
          <div className="rounded-xl border border-zinc-200 bg-warm px-4 py-3">
            <p className="text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">Current quarter</p>
            <p className="mt-1 text-lg font-black text-zinc-900">{currentQuarter || "Not set"}</p>
          </div>
          <button name="action" value="next" className="h-11 rounded-xl bg-navy px-6 font-bold text-white">Change quarter</button>
          <button name="action" value="undo" className="h-11 rounded-xl border border-zinc-300 bg-white px-5 font-bold">Undo quarter</button>
        </form>
      )}
      <p className="mt-4 min-h-5 text-sm font-semibold text-zinc-600">{message}</p>
      {canAdmin && (
        <div className="mt-5 grid gap-5 border-t border-zinc-200 pt-5">
          <h3 className="text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">Player data tools (admin only)</h3>
          <form onSubmit={createPlayer} className="grid gap-3 md:grid-cols-[1fr_auto]">
            <input name="player_name" placeholder="New player name" required className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
            <button className="h-11 rounded-xl border border-zinc-300 bg-white px-5 font-bold">Create player</button>
          </form>
          <RegisteredNameAdmin language={language} onRefresh={onRefresh}/>
          <form onSubmit={mergePlayers} data-i18n-owned className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
            <RegisteredUserField idName="source_player_id" label={v10(language,"Player ID to merge","要合并的玩家 ID")} required language={language}
              searchUrl="/api/history-players" placeholder={v10(language,"Search name or player ID…","搜索姓名或玩家 ID……")}
              copy={playerPickerCopy(language)} onSelected={setMergeSource} excludeIds={mergeTarget?[mergeTarget.id]:[]}/>
            <RegisteredUserField idName="target_player_id" label={v10(language,"Player ID to keep","要保留的玩家 ID")} required language={language}
              searchUrl="/api/history-players" placeholder={v10(language,"Search name or player ID…","搜索姓名或玩家 ID……")}
              copy={playerPickerCopy(language)} onSelected={setMergeTarget} excludeIds={mergeSource?[mergeSource.id]:[]}/>
            <button disabled={!mergeSource||!mergeTarget} className="h-11 rounded-xl border border-red-200 bg-red-50 px-5 font-extrabold text-red-700 disabled:opacity-40">{v10(language,"Merge + recompute","合并并重算")}</button>
          </form>
          <form onSubmit={setPlayerIcon} className="grid gap-3 md:grid-cols-[1fr_160px_1fr_auto]">
            <RegisteredUserField name="username" label={MahjongI18n.t(language,"registeredName")} required language={language}/>
            <input name="icon_label" placeholder="Icon text" maxLength="12" className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
            <input name="icon_file" type="file" accept="image/jpeg,image/png" className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-zinc-950" />
            <button className="h-11 rounded-xl border border-zinc-300 bg-white px-5 font-bold">Set icon</button>
          </form>
          <p className="min-h-5 text-sm font-semibold text-zinc-600">{playerMessage}</p>
        </div>
      )}
      {canSuperAdmin && (
        <form onSubmit={updateRole} className="mt-5 grid gap-3 border-t border-zinc-200 pt-5 md:grid-cols-[1fr_180px_auto]">
          <h3 className="md:col-span-3 text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">Role management (super admin only)</h3>
          <RegisteredUserField name="username" label={MahjongI18n.t(language,"registeredName")} required language={language}/>
          <select name="role" defaultValue="admin" className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950">
            <option value="admin">Admin</option>
            <option value="super_admin">Super admin</option>
            <option value="user">User</option>
          </select>
          <button className="h-11 rounded-xl border border-zinc-300 bg-white px-5 font-bold">Update role</button>
          <p className="md:col-span-3 min-h-5 text-sm font-semibold text-zinc-600">{roleMessage}</p>
        </form>
      )}
      {canAdmin && <PasswordResetAdmin language={language}/>}
      {canSuperAdmin && (
        <form onSubmit={manageAccount} className="mt-5 grid gap-3 border-t border-zinc-200 pt-5 md:grid-cols-[1fr_auto]">
          <h3 data-i18n-owned className="md:col-span-2 text-sm font-bold">{v10(language,"Delete web account (super admin only)","删除网站账号（仅超级管理员）")}</h3>
          <RegisteredUserField name="username" label={MahjongI18n.t(language,"registeredName")} required language={language}/>
          <button className="h-11 rounded-xl border border-red-200 bg-red-50 px-5 font-extrabold text-red-700">Delete account</button>
          <p className="md:col-span-2 min-h-5 text-sm font-semibold text-zinc-600">{accountMessage}</p>
        </form>
      )}
    </Card>
  );
}

function MiniStat({ value, label }) {
  return (
    <div className="rounded-lg bg-white px-3 py-3">
      <strong className="block text-base font-black text-zinc-900">{value}</strong>
      <span className="mt-1 block text-xs font-bold text-zinc-500">{label}</span>
    </div>
  );
}

function GameResultPanel({ result, session, profile, onRevert }) {
  const [message, setMessage] = React.useState("");
  if (!result) {
    return (
      <Card>
        <SectionTitle icon={ScrollText}>Game Result</SectionTitle>
        <p className="text-sm font-semibold text-zinc-500">No recorded result yet.</p>
      </Card>
    );
  }
  const canRevert = Boolean(session && result.action_id && (profile?.is_admin || profile?.is_super_admin));

  async function revert() {
    try {
      setMessage("Reverting...");
      const data = await onRevert(result.action_id);
      setMessage(data.warning || data.message || "Reverted.");
    } catch (error) {
      setMessage(error.message);
    }
  }

  return (
    <Card className="mt-5">
      <SectionTitle icon={Trophy}>{result.title || "Game Result"}</SectionTitle>
      <div className="grid gap-3">
        {(result.players || []).map((player, index) => (
          <div key={`${player.name}-${index}`} className="grid gap-3 rounded-xl border border-zinc-200 bg-warm px-4 py-4 md:grid-cols-[64px_minmax(0,1fr)_1fr_1fr] md:items-center">
            <div className="text-3xl">{player.emoji || resultEmoji(player.rank || index + 1)}</div>
            <div className="min-w-0">
              <div className="truncate text-lg font-black">{ordinal(player.rank || index + 1)} {player.name}</div>
              {player.score !== undefined && <p className="text-sm font-semibold text-zinc-500">{player.score} pts</p>}
            </div>
            <div>
              <p className="text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">MMR</p>
              <p className="text-lg font-black">{formatNumber(player.mmr)} <span className={deltaClass(player.mmr_delta)}>{formatDelta(player.mmr_delta)}</span></p>
              {player.mmr_rank && <p className="text-sm font-semibold text-zinc-500">#{player.mmr_rank} {rankMoveText(player.mmr_rank_change)}</p>}
            </div>
            <div>
              <p className="text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">Quarter PT</p>
              <p className="text-lg font-black">{formatNumber(player.pt)} <span className={deltaClass(player.pt_delta)}>{formatDelta(player.pt_delta)}</span></p>
              {player.pt_rank && <p className="text-sm font-semibold text-zinc-500">#{player.pt_rank} {rankMoveText(player.pt_rank_change)}</p>}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        {canRevert && <button onClick={revert} className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm font-extrabold text-red-700">Revert this record</button>}
        <p className="text-sm font-semibold text-zinc-600">{message}</p>
      </div>
    </Card>
  );
}

function MatchManagementPanel({ language, players, yakumanOptions, session, profile, onRefresh, onYakumanDeleted, onReverted }) {
  const [message, setMessage] = React.useState("");
  const [rows, setRows] = React.useState([]);
  const [page, setPage] = React.useState(1);
  const [pages, setPages] = React.useState(1);
  const [dateFilter, setDateFilter] = React.useState("");
  const [playerFilters, setPlayerFilters] = React.useState(["", "", "", ""]);
  const [openGameId, setOpenGameId] = React.useState(null);
  const canUse = Boolean(session && (profile?.is_admin || profile?.is_super_admin));

  async function load(nextPage = page, nextDate = dateFilter, nextPlayers = playerFilters) {
    if (!canUse) return;
    try {
      const playerQuery = (nextPlayers || []).filter(Boolean).join(" / ");
      const response = await fetch(`/api/admin/matches?page=${encodeURIComponent(nextPage)}&date=${encodeURIComponent(nextDate)}&players=${encodeURIComponent(playerQuery)}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not load matches.");
      setRows(data.rows || []);
      setPage(data.page || nextPage);
      setPages(data.pages || 1);
      setMessage("");
    } catch (error) {
      setMessage(error.message);
    }
  }

  React.useEffect(() => {
    load(1, dateFilter, playerFilters);
  }, [session, profile?.is_admin, profile?.is_super_admin]);

  async function revert(gameId) {
    if (!canUse) {
      setMessage("Only admins can revert game rows.");
      return;
    }
    if (!window.confirm(`Revert SQL game #${gameId}? This will recalculate later games.`)) return;
    try {
      setMessage("Reverting...");
      const response = await fetch("/api/revert", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ game_id: gameId }) });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not revert.");
      setMessage(data.warning || data.message);
      await load(page, dateFilter, playerFilters);
      onReverted(data.result);
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function addYakuman(event, row) {
    event.preventDefault();
    if (!canUse) {
      setMessage("Only admins can add yakuman records.");
      return;
    }
    const form = event.currentTarget;
    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());
    payload.game_id = row.game_id;
    payload.played_at = row.date;
    payload.yakuman_names = formData.getAll("yakuman_names");
    payload.other_players = (row.players || []).map((player) => player.name).filter((name) => name !== payload.winner && name !== payload.deal_in);
    try {
      const photoFile = formData.get("photo");
      if (photoFile && photoFile.size) {
        if (!["image/jpeg", "image/png"].includes(photoFile.type)) throw new Error("Please upload a JPG or PNG yakuman photo.");
        if (photoFile.size > 10 * 1024 * 1024) throw new Error("Yakuman photo must be 10MB or smaller.");
        payload.photo_data = await fileToDataUrl(photoFile);
      }
      delete payload.photo;
      setMessage(`Adding yakuman to game #${row.game_id}...`);
      const response = await fetch("/api/admin/yakuman", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not add yakuman.");
      setMessage(data.message);
      form.reset();
      setOpenGameId(null);
      onYakumanDeleted?.(null, data);
      await load(page, dateFilter, playerFilters);
      await onRefresh?.();
    } catch (error) {
      setMessage(error.message);
    }
  }

  function applyDateFilter(event) {
    event.preventDefault();
    setPage(1);
    load(1, dateFilter, playerFilters);
  }

  function updatePlayerFilter(index, value) {
    const next = [...playerFilters];
    next[index] = value;
    setPlayerFilters(next);
  }

  return (
    <Card className="mt-5">
      <SectionTitle icon={ListChecks}>Match Management</SectionTitle>
      <form onSubmit={applyDateFilter} className="mb-4 grid gap-3 md:grid-cols-[220px_1fr_auto_auto] md:items-end">
        <label className="grid gap-2 text-sm font-bold text-zinc-600">
          Search date
          <input type="date" value={dateFilter} onChange={(event) => setDateFilter(event.target.value)} className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
        </label>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {playerFilters.map((value,index)=><RegisteredUserField key={index} value={value} onChange={name=>updatePlayerFilter(index,name)} language={language} label={MahjongI18n.t(language,"registeredFilterPlayer",{number:index+1})}/>)}
        </div>
        <button className="h-11 rounded-xl border border-zinc-300 bg-white px-5 font-bold">Search</button>
        <button type="button" onClick={() => { const empty = ["", "", "", ""]; setDateFilter(""); setPlayerFilters(empty); setPage(1); load(1, "", empty); }} className="h-11 rounded-xl border border-zinc-300 bg-white px-5 font-bold">Clear</button>
        <p className="text-sm font-semibold text-zinc-500 md:col-span-4 md:text-right">10 matches per page</p>
      </form>
      <div className="grid gap-3">
        {rows.length ? rows.map((row) => {
          const names = (row.players || []).map((player) => player.name).join(" / ");
          const scores = (row.players || []).map((player) => player.score).join(" / ");
          return (
            <div key={row.id || row.game_id} className="rounded-xl border border-zinc-200 px-4 py-3">
              <div className="grid gap-3 md:grid-cols-[1fr_auto_auto] md:items-center">
                <div>
                  <p className="font-bold text-zinc-900">{formatSheetDate(row.date)} - {names}</p>
                  <p className="text-sm font-semibold text-zinc-500">
                    Scores: {scores || "unknown"} - SQL #{row.game_id}{row.sheet_row ? ` - Sheet row ${row.sheet_row}` : ""}{row.quarter ? ` - ${row.quarter}` : ""}
                  </p>
                  {(row.yakuman || []).length > 0 && (
                    <p className="mt-1 text-sm font-bold text-gold">
                      Yakuman: {(row.yakuman || []).map((item) => `${item.winner} ${item.yakuman}`).join(" / ")}
                    </p>
                  )}
                  {row.created_by && <p className="text-xs font-bold uppercase tracking-[0.14em] text-zinc-400">by {row.created_by}</p>}
                </div>
                <button disabled={!canUse} onClick={() => setOpenGameId(openGameId === row.game_id ? null : row.game_id)} className="rounded-xl border border-zinc-300 bg-white px-4 py-2 text-sm font-extrabold disabled:cursor-not-allowed disabled:opacity-40">Add yakuman</button>
                <button disabled={!canUse || row.can_revert === false} onClick={() => revert(row.game_id)} className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm font-extrabold text-red-700 disabled:cursor-not-allowed disabled:opacity-40">Revert game</button>
              </div>
              {row.can_revert === false && <p className="mt-2 text-sm text-zinc-600">NFC scores require a coordinated correction and cannot be reverted here.</p>}
              {openGameId === row.game_id && (
                <form onSubmit={(event) => addYakuman(event, row)} className="mt-4 grid gap-3 rounded-xl border border-zinc-200 bg-warm p-4">
                  <div className="grid gap-3 md:grid-cols-3">
                    <RegisteredUserField name="winner" required language={language} label={MahjongI18n.t(language,"registeredWinner")} options={registeredRosterOptions(row.players)}/>
                    <RegisteredUserField name="deal_in" language={language} label={MahjongI18n.t(language,"registeredDealIn")} options={registeredRosterOptions(row.players)}/>
                    <label className="grid gap-2 text-sm font-bold text-zinc-600">
                      Note
                      <input name="note" placeholder="Optional note" className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
                    </label>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {(yakumanOptions || []).map((name) => (
                      <label key={name} className="flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-sm font-bold text-zinc-700">
                        <input type="checkbox" name="yakuman_names" value={name} />
                        {name}
                      </label>
                    ))}
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <input name="photo" type="file" accept="image/jpeg,image/png" className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-zinc-950" />
                    <input name="photo_caption" placeholder="Photo caption" className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
                  </div>
                  <button className="h-11 rounded-xl bg-navy px-5 font-bold text-white">Add yakuman to this match</button>
                </form>
              )}
            </div>
          );
        }) : (
          <p className="text-sm font-semibold text-zinc-500">No SQL game rows found for this view.</p>
        )}
      </div>
      <div className="mt-4 flex items-center justify-between gap-3">
        <button disabled={!canUse || page <= 1} onClick={() => { const next = Math.max(1, page - 1); setPage(next); load(next, dateFilter, playerFilters); }} className="rounded-xl border border-zinc-300 bg-white px-4 py-2 text-sm font-bold disabled:opacity-40">Previous</button>
        <span className="text-sm font-bold text-zinc-500">Page {page} / {pages}</span>
        <button disabled={!canUse || page >= pages} onClick={() => { const next = Math.min(pages, page + 1); setPage(next); load(next, dateFilter, playerFilters); }} className="rounded-xl border border-zinc-300 bg-white px-4 py-2 text-sm font-bold disabled:opacity-40">Next</button>
      </div>
      <p className="mt-4 min-h-5 text-sm font-semibold text-zinc-600">{message}</p>
    </Card>
  );
}

function AdminActionsPanel({ session, profile, onRefresh, onYakumanChanged }) {
  const [actions, setActions] = React.useState([]);
  const [message, setMessage] = React.useState("");
  const canUse = Boolean(session && (profile?.is_admin || profile?.is_super_admin));

  async function load() {
    if (!canUse) return;
    try {
      const response = await fetch("/api/admin/actions?limit=30", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not load admin actions.");
      setActions(data.actions || []);
      setMessage("");
    } catch (error) {
      setMessage(error.message);
    }
  }

  React.useEffect(() => {
    load();
  }, [session, profile?.is_admin, profile?.is_super_admin]);

  async function revertAction(action) {
    if (!action.can_revert) return;
    if (!window.confirm(`Revert admin action: ${action.summary || action.action_type}?`)) return;
    try {
      setMessage("Reverting admin action...");
      const response = await fetch("/api/admin/action-revert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action_id: action.id }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not revert admin action.");
      setActions(data.actions || []);
      setMessage(data.message);
      onYakumanChanged?.(null, data);
      await onRefresh?.();
    } catch (error) {
      setMessage(error.message);
    }
  }

  return (
    <Card className="mt-5">
      <SectionTitle icon={ScrollText}>Recent Admin Changes</SectionTitle>
      <div className="grid max-h-[520px] gap-3 overflow-auto pr-2">
        {actions.length ? actions.map((action) => (
          <div key={action.id} className="grid gap-3 rounded-xl border border-zinc-200 px-4 py-3 md:grid-cols-[1fr_auto] md:items-center">
            <div>
              <p className="font-bold text-zinc-900">{action.summary || action.action_type}</p>
              <p className="text-sm font-semibold text-zinc-500">
                {formatSheetDate(action.created_at)} - {action.user_name || "system"} - {action.action_type}
                {action.reverted_at ? ` - reverted ${formatSheetDate(action.reverted_at)}` : ""}
              </p>
            </div>
            <button disabled={!action.can_revert} onClick={() => revertAction(action)} className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm font-extrabold text-red-700 disabled:cursor-not-allowed disabled:opacity-40">
              {action.can_revert ? "Revert action" : "Not reversible"}
            </button>
          </div>
        )) : (
          <p className="text-sm font-semibold text-zinc-500">No admin changes found.</p>
        )}
      </div>
      <p className="mt-4 min-h-5 text-sm font-semibold text-zinc-600">{message}</p>
    </Card>
  );
}

function LiveGameCard({ language, players, session, games, onRefresh }) {
  const [message, setMessage] = React.useState(""),[gameId,setGameId]=React.useState("");
  const selectedGame=(games||[]).find(game=>String(game.id)===gameId);
  const gameRoster=registeredRosterOptions(selectedGame?[selectedGame.player1,selectedGame.player2,selectedGame.player3,selectedGame.player4]:[]);

  async function post(path, form) {
    const payload = Object.fromEntries(new FormData(form).entries());
    if (path === "/api/live-hands") payload.dealer_tenpai = form.elements.dealer_tenpai?.checked ? "1" : "";
    const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.message || "Request failed.");
    return data;
  }

  async function start(event) {
    event.preventDefault();
    if (!session) return setMessage("Log in before starting a live game.");
    try {
      const data = await post("/api/live-games", event.currentTarget);
      setMessage(`Started live game #${data.game.id}.`);
      onRefresh();
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function hand(event) {
    event.preventDefault();
    if (!session) return setMessage("Log in before recording a hand.");
    try {
      const data = await post("/api/live-hands", event.currentTarget);
      setMessage(`Recorded hand for game #${data.game.id}.`);
      onRefresh();
    } catch (error) {
      setMessage(error.message);
    }
  }

  return (
    <Card className="mt-5">
      <SectionTitle icon={ScrollText}>Live Game Recorder</SectionTitle>
      <form onSubmit={start} className="grid gap-3 md:grid-cols-4">
        {[1,2,3,4].map(index=><RegisteredUserField key={index} name={`player${index}`} required language={language} label={MahjongI18n.t(language,"registeredFilterPlayer",{number:index})}/>)}
        <button className="h-11 rounded-xl bg-navy font-bold text-white md:col-span-4">Start from 25000</button>
      </form>

      <form onSubmit={hand} className="mt-6 grid gap-3 md:grid-cols-3">
        <select name="game_id" value={gameId} onChange={event=>setGameId(event.target.value)} required className="h-11 rounded-xl border border-zinc-200 px-3">
          <option value="">Active game</option>
          {games.map((game) => <option key={game.id} value={game.id}>#{game.id} {game.player1} / {game.player2} / {game.player3} / {game.player4}</option>)}
        </select>
        <select name="hand_type" className="h-11 rounded-xl border border-zinc-200 px-3">
          <option value="win">Win</option>
          <option value="draw">Exhaustive draw</option>
        </select>
        <input name="honba" type="number" min="0" step="1" placeholder="Honba" className="h-11 rounded-xl border border-zinc-200 px-3" />
        <RegisteredUserField key={"winner-"+gameId} name="winner" language={language} label={MahjongI18n.t(language,"registeredWinner")} options={gameRoster} disabled={!selectedGame}/>
        <RegisteredUserField key={"deal_in-"+gameId} name="deal_in" language={language} label={MahjongI18n.t(language,"registeredDealIn")} options={gameRoster} disabled={!selectedGame}/>
        <input name="win_points" type="number" step="100" placeholder="Win points" className="h-11 rounded-xl border border-zinc-200 px-3" />
        <input name="deal_in_points" type="number" step="100" placeholder="Deal-in points" className="h-11 rounded-xl border border-zinc-200 px-3" />
        <input name="yaku" placeholder="Yaku / notes" className="h-11 rounded-xl border border-zinc-200 px-3" />
        <label className="flex h-11 items-center gap-2 rounded-xl border border-zinc-200 px-3 text-sm font-bold text-zinc-600">
          <input name="dealer_tenpai" type="checkbox" value="1" />
          Dealer tenpai
        </label>
        <button className="h-11 rounded-xl bg-navy font-bold text-white md:col-span-3">Record hand</button>
      </form>
      <p className="mt-4 text-sm font-semibold text-zinc-600">{message}</p>
    </Card>
  );
}

function ResultBadge({ result }) {
  const classes = { "1st": "bg-green-100 text-green-800", "2nd": "bg-yellow-100 text-yellow-800", "3rd": "bg-zinc-100 text-zinc-700", "4th": "bg-red-100 text-red-800" };
  return <span className={`rounded-full px-3 py-1 text-sm font-black ${classes[result] || classes["3rd"]}`}>{result}</span>;
}

function Tile({ children }) {
  return <span className="grid h-11 w-9 place-items-center rounded-lg border border-zinc-300 bg-warm text-xs font-black shadow-sm">{children}</span>;
}

function normalizeRanking(rows, session, profiles) {
  if (!rows?.length) return null;
  return rows.map((row) => {
    const profile = profiles?.[row.name] || {};
    return {
      ...row,
      initials: initials(row.name),
      you: session && row.name === session,
      value: row.value || row.mmr || row.pts,
      avatar: row.avatar || profile.avatar || "",
      icon: row.icon || profile.icon || null,
    };
  });
}

function normalizeRecords(games, session) {
  if (!games?.length) return null;
  const normalizedSession = normalizeName(session);
  const tableSearch = !normalizedSession || normalizedSession.includes("/");
  const sourceGames = tableSearch ? games : games.filter((game) => (game.players || []).some((player) => normalizeName(player.name) === normalizedSession));

  return sourceGames.map((game) => {
    const players = game.players || [];
    if (tableSearch) {
      const ordered = [...players].sort((a, b) => Number(a.placement || 9) - Number(b.placement || 9));
      return {
        date: formatSheetDate(game.date || game.created_at),
        opponents: ordered.map((player) => `${player.name} ${player.score}`).join(" / "),
        result: "Table",
        mmr: ordered.map((player) => `${player.name}: ${formatDelta(player.delta)}`).join(" / "),
        pt: ordered.map((player) => `${player.name}: ${formatDelta(player.pt_delta)}`).join(" / "),
      };
    }
    let index = players.findIndex((player) => normalizeName(player.name) === normalizedSession);
    if (index < 0) return null;
    const target = players[index] || {};
    const opponents = players.filter((_, playerIndex) => playerIndex !== index).map((player) => player.name).join(" / ");
    const mmr = target.delta || target.score || "";
    const pt = target.pt_delta || "";
    const targetScore = Number(target.score);
    const resultRank = Number.isFinite(targetScore)
      ? 1 + players.filter((player) => Number(player.score) > targetScore).length
      : index + 1;
    return {
      date: formatSheetDate(game.date || game.created_at),
      opponents,
      result: ordinal(resultRank),
      mmr: formatDelta(mmr),
      pt: pt === "" ? "-" : formatDelta(pt),
      mmr_value: Number(mmr),
      pt_value: pt === "" ? undefined : Number(pt),
    };
  }).filter(Boolean);
}

function formatSheetDate(value) {
  if (!value) return "Recent";
  const text = String(value).trim();
  // Game timestamps are stored with an explicit offset (usually UTC). Render
  // them consistently in the club's Pacific time, regardless of browser locale.
  if (/[zZ]|[+-]\d{2}:?\d{2}$/.test(text)) {
    const date = new Date(text);
    if (!Number.isNaN(date.getTime())) {
      const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
        timeZone: "America/Los_Angeles", year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23", timeZoneName: "short",
      }).formatToParts(date).map((part) => [part.type, part.value]));
      return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second} ${parts.timeZoneName}`;
    }
  }
  return text;
}

function normalizeName(value) {
  return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function formatShortDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recent";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function formatDelta(value) {
  if (value === "" || value === undefined || value === null) return "-";
  const number = Number(value);
  const text = Number.isFinite(number) && !Number.isInteger(number)
    ? Math.abs(number).toFixed(4).replace(/0+$/, "").replace(/\.$/, "")
    : String(Math.abs(number));
  if (number > 0) return `\u{1F53A}${text}`;
  if (number < 0) return `\u{1F53B}${text}`;
  return "0";
}

function formatSigned(value) {
  if (value === "" || value === undefined || value === null) return "--";
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  const rounded = Math.round(number * 10) / 10;
  return `${rounded > 0 ? "+" : ""}${rounded}`;
}

function formatInteger(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return value ?? "--";
  return String(Math.round(number));
}

function radarPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(100, number));
}

function radarValue(radar, key, index, fallback = 0) {
  const direct = radar?.[key];
  const values = Object.values(radar || {});
  const value = direct !== undefined ? direct : values[index];
  const number = Number(value !== undefined ? value : fallback);
  if (!Number.isFinite(number)) return fallback;
  return number <= 1 ? number * 100 : Math.max(0, Math.min(100, number));
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return value ?? "-";
  return Number.isInteger(number) ? String(number) : number.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function deltaClass(value) {
  const number = Number(value);
  if (number > 0) return "text-green-700";
  if (number < 0) return "text-red-700";
  return "text-zinc-500";
}

function rankMoveText(value) {
  const number = Number(value || 0);
  if (number > 0) return `\u{1F53A}${number}`;
  if (number < 0) return `\u{1F53B}${Math.abs(number)}`;
  return "\u2796";
}

function resultEmoji(rank) {
  return ["\u{1F436}", "\u{1F948}", "\u{1F949}", "\u{1FAA6}"][rank - 1] || "\u{1F004}";
}


function ordinal(value) {
  return ["1st", "2nd", "3rd", "4th"][value - 1] || `${value}`;
}

function bestRankText(summary) {
  if (!summary) return "";
  const ranks = ["quarter_pt", "quarter_mmr", "total_mmr", "total_pt", "history_highest_mmr"]
    .map((key) => summary[key]?.rank)
    .filter(Boolean);
  return ranks.length ? `#${Math.min(...ranks)}` : "";
}

function initials(name) {
  return String(name || "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || "")
    .join("") || "--";
}

function fileToCompressedDataUrl(file, maxBytes) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      let width = image.width;
      let height = image.height;
      let quality = 0.86;
      const canvas = document.createElement("canvas");
      const context = canvas.getContext("2d");
      for (let attempt = 0; attempt < 12; attempt += 1) {
        canvas.width = Math.max(64, Math.round(width));
        canvas.height = Math.max(64, Math.round(height));
        context.clearRect(0, 0, canvas.width, canvas.height);
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        const dataUrl = canvas.toDataURL("image/jpeg", quality);
        if (dataUrl.length * 0.75 <= maxBytes || canvas.width <= 128 || canvas.height <= 128) {
          resolve(dataUrl);
          return;
        }
        width *= 0.82;
        height *= 0.82;
        quality = Math.max(0.62, quality - 0.06);
      }
      resolve(canvas.toDataURL("image/jpeg", 0.7));
    };
    image.onerror = () => reject(new Error("Could not read that image."));
    fileToDataUrl(file).then((url) => { image.src = url; }).catch(reject);
  });
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function lucideReactShim() {
  const icon = (path) =>
    function Icon({ className = "" }) {
      return <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{path}</svg>;
    };

  return {
    Trophy: icon(<><path d="M8 21h8" /><path d="M12 17v4" /><path d="M7 4h10v4a5 5 0 0 1-10 0V4Z" /><path d="M5 5H3v3a4 4 0 0 0 4 4" /><path d="M19 5h2v3a4 4 0 0 1-4 4" /></>),
    UserRound: icon(<><circle cx="12" cy="8" r="5" /><path d="M20 21a8 8 0 0 0-16 0" /></>),
    ListChecks: icon(<><path d="m3 17 2 2 4-4" /><path d="m3 7 2 2 4-4" /><path d="M13 6h8" /><path d="M13 12h8" /><path d="M13 18h8" /></>),
    Plus: icon(<><path d="M5 12h14" /><path d="M12 5v14" /></>),
    LogIn: icon(<><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" /><path d="m10 17 5-5-5-5" /><path d="M15 12H3" /></>),
    ScrollText: icon(<><path d="M8 21h12a2 2 0 0 0 2-2v-1H10v1a2 2 0 1 1-4 0V5a2 2 0 1 1 4 0v13" /><path d="M19 18V5a2 2 0 0 0-2-2H8" /></>),
    Camera: icon(<><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3Z" /><circle cx="12" cy="13" r="3" /></>),
  };
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);


