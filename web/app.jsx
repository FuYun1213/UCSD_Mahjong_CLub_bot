const { Trophy, UserRound, ListChecks, Plus, LogIn, ScrollText, Camera } = lucideReactShim();

const logoUrl = "/assets/UCSD_mermaid_whitebg.jpg";

const navLabels = {
  EN: {
    dashboard: "Dashboard",
    ranking: "Ranking",
    record: "Game Record",
    matches: "Recent Match",
    live: "Live",
    tournament: "Tournament Mode",
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
    tournament: "比赛模式",
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
  if(path==="/login") return "account";
  if(path==="/register") return "register";
  if(path==="/registration-complete") return "registration-complete";
  if(path==="/reservations") return "reservations";
  if(path==="/manual-score") return "manual-score";
  if(query.has("tournament")) return "tournament";
  return ["dashboard","ranking","record","reservations","matches","live","tournament","account","admin","result"].includes(query.get("page")) ? query.get("page") : "dashboard";
}
function globalLoginUrl(target=location.pathname+location.search+location.hash) {
  return "/login?redirect_url="+encodeURIComponent(target);
}
function safeLoginReturn(raw) {
  try {
    if(!raw || !raw.startsWith("/") || raw.startsWith("//") || /[\\\r\n]/.test(raw)) return "/";
    const target=new URL(raw,location.origin);
    if(target.origin!==location.origin || ["/login","/register"].includes(target.pathname)) return "/";
    return target.pathname+target.search+target.hash;
  } catch {return "/";}
}
function App() {
  const [session, setSession] = React.useState(null);
  const [sessionLoaded, setSessionLoaded] = React.useState(false);
  const [profile, setProfile] = React.useState(null);
  const [players, setPlayers] = React.useState([]);
  const [yakumanOptions, setYakumanOptions] = React.useState([]);
  const [matchPlayer, setMatchPlayer] = React.useState("");
  const [tablePlayers, setTablePlayers] = React.useState("");
  const [viewQuarter, setViewQuarter] = React.useState("");
  const [profileQuarter, setProfileQuarter] = React.useState("");
  const [profilePlayer, setProfilePlayer] = React.useState("");
  const [rankingType, setRankingType] = React.useState("quarter_pt");
  const [page, updatePage] = React.useState(currentAppPage);
  const [routeVersion,setRouteVersion] = React.useState(0);
  function setPage(next) {
    const target=next==="reservations"?"/reservations":next==="manual-score"?"/manual-score":next==="account"?"/login":"/?page="+encodeURIComponent(next);
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

  async function refresh() {
    try {
      const [sessionResponse, playersResponse, dashboardResponse, yakumanResponse] = await Promise.all([
        fetch("/api/session", { cache: "no-store" }),
        fetch("/api/players", { cache: "no-store" }),
        fetch(`/api/dashboard?ranking=${encodeURIComponent(rankingType)}&match_player=${encodeURIComponent(matchPlayer)}&table_players=${encodeURIComponent(tablePlayers)}&quarter=${encodeURIComponent(viewQuarter)}&profile_quarter=${encodeURIComponent(profileQuarter)}&profile_player=${encodeURIComponent(profilePlayer)}`, { cache: "no-store" }),
        fetch("/api/yakuman-options", { cache: "no-store" }),
      ]);
      const sessionData = await sessionResponse.json();
      const playersData = await playersResponse.json();
      const dashboardData = await dashboardResponse.json();
      const yakumanData = await yakumanResponse.json();
      setSession(sessionData.user || null);
      setSessionLoaded(true);
      setProfile(sessionData.profile || null);
      setPlayers([...(playersData.players || [])].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" })));
      setDashboard(dashboardData);
      setYakumanOptions(yakumanData.options || []);
      setStatus("");
    } catch (error) {
      setStatus("Backend unavailable; showing demo data.");
    }
  }

  React.useEffect(() => {
    refresh();
  }, [rankingType, matchPlayer, tablePlayers, viewQuarter, profileQuarter, profilePlayer]);

  const effectiveMatchPlayer = dashboard?.recent_match_player || matchPlayer;
  const ranking = normalizeRanking(dashboard?.rankings, session, dashboard?.profiles) || fallbackRanking;
  const records = normalizeRecords(dashboard?.recent_games, effectiveMatchPlayer) || [];

  React.useEffect(() => {
    requestAnimationFrame(() => applyPageLanguage(language));
  }, [language, page, dashboard, profile, players, yakumanOptions, lastResult, status]);

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

  return (
    <main className="min-h-screen px-5 py-8 sm:px-8">
      <div className="mx-auto max-w-[1100px]">
        <Header session={session} authReady={sessionLoaded} memberCount={dashboard?.stats?.member_count || players.length} currentQuarter={dashboard?.stats?.view_quarter || dashboard?.stats?.current_quarter} page={page} setPage={setPage} onRefresh={refresh} language={language} setLanguage={setLanguage} />
        {status && <p className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-800">{status}</p>}

        {page === "dashboard" && (
          <>
            <CurrentChallenge language={language}/>
            <section className="grid gap-5 lg:grid-cols-2">
              <ProfileCard session={session} profile={profile} summary={dashboard?.current_user_rank} players={players} profilePlayer={profilePlayer} setProfilePlayer={setProfilePlayer} quarters={dashboard?.quarters || []} profileQuarter={profileQuarter} setProfileQuarter={setProfileQuarter} onProfile={setProfile} onRefresh={refresh} language={language} />
            </section>
            <AnnualSummaryCard summary={dashboard?.annual_summary} session={session} />
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
            tablePlayers={tablePlayers}
            setTablePlayers={setTablePlayers}
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
            <ChallengeAdmin language={language} profile={profile}/>
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
        {page === "registration-complete" && <Card><DiscordOptional complete language={language} target={new URLSearchParams(location.search).get("redirect_url")||"/"}/></Card>}
        {page === "reservations" && <ReservationPage key={routeVersion} language={language} profile={profile}/>}
        {page === "manual-score" && (new URLSearchParams(location.search).has("tournament")?<CompetitionManualScore language={language} profile={profile}/>:<ManualScorePage key={routeVersion} language={language} profile={profile} onRefresh={refresh}/>)}
        {page === "join-table" && <TableJoinPage key={routeVersion} language={language} profile={profile} authReady={sessionLoaded}/>}
        {page === "tournament" && <TournamentMode language={language} profile={profile} players={players} />}
        {page === "live" && <LiveGameCard language={language} players={players} session={session} games={dashboard?.live_games || []} onRefresh={refresh} />}
      </div>
    </main>
  );
}

function Header({ session, authReady, memberCount, currentQuarter, page, setPage, onRefresh, language, setLanguage }) {
  const labels = navLabels[language] || navLabels.EN;
  const navItems = [
    ["dashboard", labels.dashboard],
    ["ranking", labels.ranking],
    ["record", labels.record],
    ["reservations", MahjongI18n.t(language,"reservations")],
    ["matches", labels.matches],
    ["live", labels.live],
    ["tournament", labels.tournament],
    ["account", labels.account],
    ["admin", labels.admin],
  ];
  return (
    <header className="mb-9 border-b border-zinc-200 pb-7">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-center gap-4">
          <img width="64" height="64" src={logoUrl} alt={window.MahjongBrand.name+" logo"} className="h-16 w-16 rounded-xl border border-zinc-200 bg-white object-cover" />
          <div>
            <h1 className="text-3xl font-extrabold tracking-tight text-zinc-950">{window.MahjongBrand.name}</h1>
            <p className="mt-1 flex items-center gap-2 text-lg text-zinc-600">
              <span className="h-2 w-2 rounded-full bg-gold" />
              {currentQuarter || labels.currentSeason} - {memberCount || "--"} {labels.members}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3 sm:justify-end">
          <span className="text-sm font-bold text-zinc-500">{session ? `${labels.loggedIn}: ${session}` : labels.notLoggedIn}</span>
          <span data-i18n-owned>{authReady?(session?<button className="rounded-xl border border-zinc-300 px-4 py-2 text-sm font-bold" onClick={async()=>{await fetch("/api/logout",{method:"POST"});location.assign("/");}}>{MahjongI18n.t(language,"logOut")}</button>:<span className="flex gap-2"><a className="rounded-xl bg-navy px-4 py-2 text-sm font-bold text-white" href={globalLoginUrl()}>{MahjongI18n.t(language,"logIn")}</a><a className="rounded-xl border border-zinc-300 px-4 py-2 text-sm font-bold" href={"/register?redirect_url="+encodeURIComponent(new URLSearchParams(location.search).get("redirect_url")||location.pathname+location.search+location.hash)}>{v10(language,"Register","注册")}</a></span>):null}</span>
          <button
            onClick={() => {
              const next = language === "EN" ? "CN" : "EN";
              localStorage.setItem("mahjong_lang", next);
              setLanguage(next);
            }}
            className="rounded-xl border border-zinc-300 bg-white px-4 py-2 text-sm font-black hover:bg-warm"
          >
            {language === "EN" ? "CN" : "EN"}
          </button>
          <button onClick={onRefresh} className="rounded-xl border border-zinc-300 bg-white px-4 py-2 text-sm font-bold hover:bg-warm">{labels.refresh}</button>
        </div>
      </div>
      <nav className="mt-6 flex flex-wrap gap-2">
        {navItems.map(([key, label]) => (
          <button key={key} onClick={() => setPage(key)} className={`rounded-xl px-4 py-2 text-sm font-extrabold ${page === key ? "bg-navy text-white" : "border border-zinc-300 bg-white text-zinc-700 hover:bg-warm"}`}>
            {label}
          </button>
        ))}
      </nav>
    </header>
  );
}

function Card({ children, className = "", id }) {
  return (
    <article id={id} className={`overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-soft ${className}`}>
      <div className="h-1 bg-gradient-to-r from-navy via-zinc-600 to-gold" />
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
              <p className="text-sm text-zinc-600">{player.wins || "Ranked"} wins</p>
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

function GameRecords({ language, records, history, players, matchPlayer, effectiveMatchPlayer, setMatchPlayer, tablePlayers, setTablePlayers, currentQuarter, viewQuarter, quarters, setViewQuarter, recentYakuman, yakumanOptions, profile, recentMatchCount, onRefresh, onYakumanDeleted }) {
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
  const tablePlayerValues = splitPlayerFilter(tablePlayers, 4);
  // Match history is public; do not query the authenticated account directory.
  const historyPlayers = React.useMemo(() => registeredRosterOptions(players), [players]);

  function updateTablePlayer(index, value) {
    const next = [...tablePlayerValues];
    next[index] = value;
    setTablePlayers(next.some(Boolean)?next.join(" / "):"");
  }

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
          <RegisteredUserField value={matchPlayer} onChange={setMatchPlayer} language={language} options={historyPlayers} label={v10(language,"Find a Player","查询玩家姓名")}/>
          <div className="grid gap-2 sm:grid-cols-2">
            {tablePlayerValues.map((value,index)=><RegisteredUserField key={index} value={value} onChange={name=>updateTablePlayer(index,name)} language={language} options={historyPlayers} label={v10(language,`Player ${index+1}`,`玩家 ${index+1}`)}/>)}
          </div>
          <button type="button" onClick={() => { setMatchPlayer(""); setTablePlayers(""); }} className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-bold">Clear</button>
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

function AccountCard({ players, session, profile, onSession, onProfile, onRefresh, language }) {
  const [message, setMessage] = React.useState("");

  async function request(path, form) {
    setMessage("Working...");
    const payload = Object.fromEntries(new FormData(form).entries());
    const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      const error = new Error(data.message || "Request failed.");
      error.code = data.code;
      throw error;
    }
    return data;
  }

  async function submit(event) {
    event.preventDefault();
    try {
      const data = await request("/api/login", event.currentTarget);
      onSession(data.user);
      onRefresh();
      const destination = new URLSearchParams(location.search).get("redirect_url") || "";
      location.assign(safeLoginReturn(destination));
    } catch (error) {
      setMessage(error.code === "website_registration_required"
        ? MahjongI18n.t(language, "websiteRegistrationRequired")
        : error.message === "Incorrect username or password."
          ? MahjongI18n.t(language, "loginFailed")
          : error instanceof TypeError ? MahjongI18n.t(language, "loginRequestFailed") : error.message);
    }
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
      setMessage("Please enter the new password twice.");
      return;
    }
    try {
      const data = await request("/api/change-password", form);
      setMessage(data.warning || data.message);
      form.reset();
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function forgotPassword(event) {
    event.preventDefault();
    try {
      const data = await request("/api/forgot-password", event.currentTarget);
      setMessage(data.message);
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

  if (session) {
    return (
      <Card>
        <SectionTitle icon={LogIn}>Account Settings</SectionTitle>
        <div data-i18n-owned className="mb-4 rounded-xl bg-warm px-4 py-3">
          <label className="grid gap-1 text-sm font-bold text-zinc-700">{MahjongI18n.t(language,"ownRegisteredName")}<input readOnly value={profile?.name||session} className="rounded-lg border border-zinc-200 bg-white px-3 py-2"/></label>
          <p className="mt-2 text-sm text-zinc-600">{MahjongI18n.t(language,"registeredNameReadOnlyHelp")}</p>
        </div>
        <div className="mb-5 rounded-xl border border-zinc-200 bg-white px-4 py-3">
          <h3 className="text-sm font-black uppercase tracking-[0.14em] text-zinc-500">Discord binding</h3>
          {profile?.discord_id ? (
            <div className="mt-2 flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
              <p className="font-bold text-zinc-800">Bound to {profile.discord_name || MahjongI18n.t(language,"discordLinked")}</p>
              <button type="button" onClick={unbindDiscord} className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm font-black text-red-700">Unbind</button>
            </div>
          ) : (
            <p className="mt-2 text-sm font-semibold text-zinc-600">Not bound. In Discord, run <span className="font-black">/bind_web_account</span> with this web account name.</p>
          )}
        </div>
        <div className="mb-5"><DiscordOptional language={language} target="/login"/></div>
        <form onSubmit={changePassword} className="grid gap-4">
          <label className="grid gap-2 text-sm font-bold text-zinc-600">
            Current password
            <input name="old_password" type="password" required className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
          </label>
          <label className="grid gap-2 text-sm font-bold text-zinc-600">
            New password
            <input name="new_password" type="password" required className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
          </label>
          <label className="grid gap-2 text-sm font-bold text-zinc-600">
            Confirm new password
            <input name="confirm_password" type="password" required className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <button className="rounded-xl bg-navy px-4 py-3 font-bold text-white">Change password</button>
            <button type="button" onClick={logout} className="rounded-xl border border-zinc-300 bg-white px-4 py-3 font-bold">Log out</button>
          </div>
        </form>
        <p className="mt-4 min-h-5 text-sm font-semibold text-zinc-600">{message}</p>
      </Card>
    );
  }

  return (
    <Card>
      <SectionTitle icon={LogIn}>Account</SectionTitle>
      <p data-i18n-owned className="mb-4 text-sm text-zinc-600">{v10(language,"Your username is your player name. Existing players sign in with the same name shown in the player list after their account is approved.","用户名就是你的玩家名称。已有玩家开通账号并通过审批后，使用名单中原来的名字登录。")}</p>
      <form onSubmit={submit} className="grid gap-4">
        <label className="grid gap-2 text-sm font-bold text-zinc-600">
          Username
          <input name="username" required className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
        </label>
        <label className="grid gap-2 text-sm font-bold text-zinc-600">
          Password
          <input name="password" type="password" required className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
        </label>
        <div className="grid grid-cols-3 gap-3">
          <button className="rounded-xl bg-navy px-4 py-3 font-bold text-white">Log in</button>
          <a href={"/register?redirect_url="+encodeURIComponent(new URLSearchParams(location.search).get("redirect_url")||"/")} className="rounded-xl border border-zinc-300 bg-white px-4 py-3 font-bold text-center">Register</a>
          <button type="button" onClick={logout} className="rounded-xl border border-zinc-300 bg-white px-4 py-3 font-bold">Log out</button>
        </div>
      </form>
      <form onSubmit={forgotPassword} className="mt-5 grid gap-3 border-t border-zinc-200 pt-5">
        <label className="grid gap-2 text-sm font-bold text-zinc-600">
          Forgot password
          <input name="username" required placeholder="Your player name" className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
        </label>
        <button className="rounded-xl border border-zinc-300 bg-white px-4 py-3 font-bold">Message @fuyun</button>
      </form>
      <p className="mt-4 min-h-5 text-sm font-semibold text-zinc-600">{message || (session ? `Active account: ${session}` : MahjongI18n.t(language, "websiteRegistrationHelp"))}</p>
    </Card>
  );
}

function RecordGameCard({ session, profile, authReady, onRefresh, language }) {
  const frame = React.useRef(null);
  const initialDraft = React.useRef(new URLSearchParams(location.search).get("draft_id")||"");
  const [height, setHeight] = React.useState(1100);
  const [table,setTable] = React.useState(()=>new URLSearchParams(location.search).get("table") || "");
  const pendingSeat = React.useRef(new URLSearchParams(location.search).get("pending_seat")||"");
  const sendContext = () => {
    const target=frame.current?.contentWindow;if(!target)return;
    target.postMessage({type:"mahjong-language",language},location.origin);
    target.postMessage({type:"mahjong-score-context",authReady:Boolean(authReady),profile:profile?{id:String(profile.id),name:profile.name}:null,
      table,entryToken:new URLSearchParams(location.hash.slice(1)).get("entry"),pendingSeat:pendingSeat.current},location.origin);
  };
  React.useEffect(sendContext, [language,authReady,profile?.id,profile?.name,table]);
  React.useEffect(() => {
    function receive(event) {
      if (event.origin !== location.origin || event.source !== frame.current?.contentWindow) return;
      if (event.data?.type === "mahjong-score-ready") sendContext();
      if (event.data?.type === "mahjong-seat-swap-open" && event.data.table===table) {
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
  }, [onRefresh,authReady,profile?.id,profile?.name,language,table]);
  return (
    <Card className="scroll-mt-8" id="record-game">
      <SectionTitle icon={Camera}>{MahjongI18n.t(language,"photoScore")}</SectionTitle>
      <div className="mb-4 flex flex-wrap gap-3" data-i18n-owned>
        <a className={buttonStyle} href={"/manual-score"+(table?"?table="+encodeURIComponent(table):"")}>{MahjongI18n.t(language,"manualScore")}</a>
        <a className="px-2 py-2 text-sm underline" href={"/reservations"+(table?"?table="+encodeURIComponent(table):"")}>{MahjongI18n.t(language,"viewReservations")}</a>
      </div>
      <OrdinaryTables onChanged={()=>frame.current?.contentWindow?.postMessage({type:"mahjong-table-changed"},location.origin)} profile={profile} language={language} selected={table} onSelect={id=>{const url=new URL(location.href);if(id!==table){initialDraft.current="";pendingSeat.current="";url.searchParams.delete("draft_id");url.searchParams.delete("pending_seat");const fragment=new URLSearchParams(url.hash.slice(1));if(fragment.has("entry")){fragment.delete("entry");url.hash=fragment.toString();}}setTable(id);url.searchParams.set("page","record");url.searchParams.set("table",id);history.replaceState(null,"",url);}}/>
      {table&&<iframe ref={frame} onLoad={sendContext} title={MahjongI18n.t(language,"photoFrame")}
        src={"/score?embedded=1&table=" + encodeURIComponent(table)+(initialDraft.current?"&draft_id="+encodeURIComponent(initialDraft.current):"")}
        className="w-full border-0" style={{height: height + "px"}} />}
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
    event.preventDefault();
    if (!canSuperAdmin) {
      setAccountMessage("Only super admins can manage account recovery.");
      return;
    }
    const submitter = event.nativeEvent.submitter?.value || "reset";
    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form).entries());
    const endpoint = submitter === "delete" ? "/api/admin/account-delete" : "/api/admin/password-reset";
    if (submitter === "delete" && !window.confirm(`Delete account for ${payload.username || "this user"}?`)) return;
    setAccountMessage(submitter === "delete" ? "Deleting account..." : "Resetting password...");
    try {
      const response = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not update account.");
      setAccountMessage(data.message);
      form.reset();
      onRefresh();
    } catch (error) {
      setAccountMessage(error.message);
    }
  }

  async function mergePlayers(event) {
    event.preventDefault();
    if (!canAdmin) {
      setPlayerMessage("Only admins can merge players.");
      return;
    }
    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form).entries());
    if (!window.confirm(`Merge ${payload.source_name || "source"} into ${payload.target_name || "target"} and recompute every SQL game?`)) return;
    setPlayerMessage("Merging players and recomputing all games...");
    try {
      const response = await fetch("/api/admin/player-merge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Could not merge players.");
      setPlayerMessage(data.message);
      form.reset();
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
          <ClaimAdmin language={language}/>
          <RegisteredNameAdmin language={language} onRefresh={onRefresh}/>
          <form onSubmit={mergePlayers} className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
            <RegisteredUserField name="source_name" label={MahjongI18n.t(language,"registeredMergeSource")} required language={language}/>
            <RegisteredUserField name="target_name" label={MahjongI18n.t(language,"registeredMergeTarget")} required language={language}/>
            <button className="h-11 rounded-xl border border-red-200 bg-red-50 px-5 font-extrabold text-red-700">Merge + recompute</button>
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
      {canSuperAdmin && (
        <form onSubmit={manageAccount} className="mt-5 grid gap-3 border-t border-zinc-200 pt-5 md:grid-cols-[1fr_1fr_auto_auto]">
          <div className="md:col-span-4">
            <h3 className="text-xs font-extrabold uppercase tracking-[0.14em] text-zinc-500">Account recovery (super admin only)</h3>
            <p className="mt-2 text-sm font-semibold text-zinc-500">Passwords are hashed, so they cannot be viewed. Reset a password or delete a registered web account here.</p>
          </div>
          <RegisteredUserField name="username" label={MahjongI18n.t(language,"registeredName")} required language={language}/>
          <input name="new_password" type="password" placeholder="New password for reset" className="h-11 rounded-xl border border-zinc-200 px-3 text-zinc-950" />
          <button name="action" value="reset" className="h-11 rounded-xl border border-zinc-300 bg-white px-5 font-bold">Reset password</button>
          <button name="action" value="delete" className="h-11 rounded-xl border border-red-200 bg-red-50 px-5 font-extrabold text-red-700">Delete account</button>
          <p className="md:col-span-4 min-h-5 text-sm font-semibold text-zinc-600">{accountMessage}</p>
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
                <button disabled={!canUse} onClick={() => revert(row.game_id)} className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm font-extrabold text-red-700 disabled:cursor-not-allowed disabled:opacity-40">Revert game</button>
              </div>
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
  return text;
}

function normalizeName(value) {
  return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function splitPlayerFilter(value, size = 4) {
  const parts = String(value || "").split(/[,/]/).map((name) => name.trim()).slice(0, size);
  while (parts.length < size) parts.push("");
  return parts;
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
