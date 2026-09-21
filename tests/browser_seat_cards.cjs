/* Four in-place self-seating cards against isolated real website/API servers. */
const assert=require("assert"),fs=require("fs"),path=require("path"),{chromium}=require("playwright");
const {prepare,root}=require("./browser_support.cjs"),base=process.env.NFC_TEST_URL;
const winds=["east","south","west","north"],checks=[];
(async()=>{
 const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || undefined,headless:true});
 try{
  const admin=await browser.newContext(),actor=await browser.newContext({viewport:{width:1280,height:1000}}),peer=await browser.newContext(),guest=await browser.newContext({viewport:{width:390,height:844}});
  for(const context of [actor,guest])await prepare(context,base);
  async function login(context,number){const r=await context.request.post(base+"/api/login",{data:{username:"photo"+number,password:"photo-test-password"}});assert(r.ok(),await r.text());}
  await login(admin,1);await login(actor,2);await login(peer,3);
  const page=await actor.newPage(),anonymous=await guest.newPage(),errors=[],dialogs=[],seatRequests=[];
  for(const p of [page,anonymous]){p.setDefaultTimeout(15000);p.on("pageerror",e=>errors.push(e.message));p.on("dialog",async d=>{dialogs.push(d.message());await d.dismiss();});p.on("request",r=>{if(r.method()==="PUT"&&r.url().endsWith("/my-seat"))seatRequests.push({url:r.url(),body:r.postDataJSON()});});}
  const check=name=>{checks.push(name);console.log("PASS: "+name);};
  const frame=p=>p.frameLocator("#record-game iframe"),card=(p,wind)=>frame(p).locator('[data-seat-card="'+wind+'"]');
  async function actualFrame(p){return (await p.locator("#record-game iframe").elementHandle()).contentFrame();}
  async function open(p,table){await p.goto(base+"/?page=record&table="+encodeURIComponent(table));await frame(p).locator("#players [data-seat-card]").first().waitFor();}
  async function state(p,wind,value){const f=await actualFrame(p);await f.waitForFunction(({wind,value})=>document.querySelector('[data-seat-card="'+wind+'"]')?.dataset.seatState===value,{wind,value});}
  async function tableInfo(scoreId){const r=await admin.request.get(base+"/api/admin/club-tables");assert(r.ok());return (await r.json()).tables.find(t=>t.score_table_id===scoreId);}
  async function seat(context,table,wind){const r=await context.request.put(base+"/api/club-tables/"+encodeURIComponent(table)+"/my-seat",{data:{seat:wind}});assert(r.ok(),await r.text());return r.json();}
  async function noExtraUI(p){assert.equal(await p.locator('[data-main-seat-button],[data-table-member-controls],[data-table-seats],[role="dialog"]').count(),0);assert.equal(await frame(p).locator('#seating,#seat-buttons,input[type="password"],input[name="username"],#login-form').count(),0);assert.equal(await frame(p).locator("#players [data-seat-card]").count(),4);}

  await open(page,"web");await state(page,"east","empty");await noExtraUI(page);
  assert.deepEqual(await frame(page).locator("#players [data-seat-card]").evaluateAll(nodes=>nodes.map(n=>n.dataset.seatCard)),winds);
  for(const wind of winds){assert.equal(await card(page,wind).evaluate(el=>el.tagName),"BUTTON");assert((await card(page,wind).getAttribute("aria-label"))||(await card(page,wind).innerText()));}
  check("only four ESWN seat cards remain; no upper member cards, seating button, dialog or local login");
  assert((await frame(page).locator("#photo").count())===1);assert.equal((await tableInfo("web")).player_count,0);
  check("viewing the ordinary photo page does not seat a player");

  // Native button keyboard activation must use the actual self-seat API.
  await card(page,"east").focus();const enterResponse=page.waitForResponse(r=>r.request().method()==="PUT"&&r.url().endsWith("/my-seat"));
  await card(page,"east").press("Enter");assert((await enterResponse).ok());await state(page,"east","current");
  let info=await tableInfo("web");assert.equal(info.player_count,1);assert.equal(info.members[0].user_id,"photo-user-2");assert.equal(info.members[0].seat,"east");
  assert((await card(page,"east").innerText()).includes("photo2"));assert(!(await frame(page).locator("#players").innerText()).includes("photo-user-"));
  check("Enter claims East using the current account and shows its registered name without an internal ID");
  const left=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith("/leave"));
  await card(page,"east").press("Enter");assert((await left).ok());await state(page,"east","empty");
  assert.equal((await tableInfo("web")).player_count,0);assert(await frame(page).locator("#leave-table").isDisabled());
  assert((await frame(page).locator("#seat-message").innerText()).includes("left the table"));
  await card(page,"east").click();await state(page,"east","current");
  check("activating the current seat leaves immediately and clears the membership; an empty card can rejoin");
  const leaveEndpoint="**/api/club-tables/*/leave";
  const failLeave=async route=>{await route.fulfill({status:503,json:{detail:{code:"requestFailed"}}});await page.unroute(leaveEndpoint,failLeave);};
  await page.route(leaveEndpoint,failLeave);await frame(page).locator("#leave-table").click();
  await frame(page).locator("#seat-message").filter({hasText:/Request did not complete/}).waitFor();
  await state(page,"east","current");assert(!await frame(page).locator("#leave-table").isDisabled());assert.equal((await tableInfo("web")).player_count,1);
  check("a failed leave keeps the displayed player and restores both leave controls");
  let releaseLeave,enterLeave;const leaveGate=new Promise(r=>releaseLeave=r),leaveEntered=new Promise(r=>enterLeave=r);let leaveCalls=0;
  const delayLeave=async route=>{leaveCalls++;enterLeave();await leaveGate;await route.continue();};
  await page.route(leaveEndpoint,delayLeave);await frame(page).locator("#leave-table").press("Space");await leaveEntered;
  assert(await frame(page).locator("#leave-table").isDisabled());assert(await card(page,"east").isDisabled());
  await card(page,"east").evaluate(el=>{el.click();el.click();});assert.equal(leaveCalls,1);
  const leftByButton=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith("/leave"));releaseLeave();assert((await leftByButton).ok());await page.unroute(leaveEndpoint,delayLeave);
  await state(page,"east","empty");assert.equal((await tableInfo("web")).player_count,0);
  await card(page,"east").click();await state(page,"east","current");
  check("Space on the lower leave button sends one request, disables repeat actions, and refreshes all seats");

  await card(page,"south").focus();await card(page,"south").press("Space");await state(page,"south","current");await state(page,"east","empty");
  info=await tableInfo("web");assert.equal(info.player_count,1);assert.equal(info.members[0].seat,"south");
  assert(!(await card(page,"east").innerText()).includes("photo2"));assert((await card(page,"south").innerText()).includes("photo2"));
  check("Space moves East to South atomically, clearing the old card and retaining one member");
  await card(page,"east").focus();await card(page,"east").press("Tab");
  const focus=await(await actualFrame(page)).evaluate(()=>document.activeElement?.dataset.seatCard);
  assert(focus&&winds.includes(focus)&&focus!=="east","Tab must reach another seat control");
  check("seat cards participate in keyboard Tab navigation");

  await seat(peer,"web","west");await page.reload();await state(page,"west","occupied");
  assert(!await card(page,"west").isDisabled());assert((await card(page,"west").innerText()).includes("photo3"));
  const occupiedRequests=seatRequests.length;await card(page,"west").click();
  await frame(page).locator("#seat-swap-dialog[open]").waitFor();
  await frame(page).locator("#swap-back").click();
  assert.equal(await frame(page).locator("#seat-swap-dialog[open]").count(),0);
  assert.equal(seatRequests.length,occupiedRequests);assert.equal((await tableInfo("web")).members.find(p=>p.seat==="west").user_id,"photo-user-3");
  check("occupied cards show the registered name and only offer a consent request without overwriting a seat");

  await open(page,"A");await state(page,"east","empty");
  const denied=page.waitForResponse(r=>r.request().method()==="PUT"&&r.url().endsWith("/my-seat"));await card(page,"east").click();
  assert.equal((await denied).status(),409);
  await frame(page).locator("#seat-message").filter({hasText:/another|other|另一|其他/}).waitFor();
  assert.equal((await tableInfo("A")).player_count,0);assert.equal((await tableInfo("web")).members.find(p=>p.user_id==="photo-user-2").seat,"south");assert.deepEqual(dialogs,[]);
  check("a cross-table attempt reports an inline error without moving the existing membership or opening a dialog");

  await open(page,"web");await state(page,"south","current");
  const endpoint="**/api/club-tables/*/my-seat";
  const fail=async route=>{await route.fulfill({status:503,json:{detail:{code:"private-player-SECRET",message:"database internals"}}});await page.unroute(endpoint,fail);};
  await page.route(endpoint,fail);await card(page,"east").click();
  await frame(page).locator("#seat-message").filter({hasText:/Request did not complete|请求未完成/}).waitFor();
  await state(page,"south","current");assert.equal((await tableInfo("web")).members.find(p=>p.user_id==="photo-user-2").seat,"south");
  assert(!(await frame(page).locator("body").innerText()).includes("private-player-SECRET"));
  assert(!await card(page,"east").isDisabled());assert(!await card(page,"north").isDisabled());
  check("failed requests retain the original member, show a safe inline error and restore available buttons");

  let release,entered;const gate=new Promise(resolve=>{release=resolve;}),intercepted=new Promise(resolve=>{entered=resolve;});let delayedCalls=0;
  const delay=async route=>{delayedCalls++;entered();await gate;await route.continue();};
  await page.route(endpoint,delay);await card(page,"east").click();await intercepted;
  assert(await card(page,"east").isDisabled());assert.equal(await card(page,"east").getAttribute("aria-busy"),"true");
  assert(await frame(page).locator("#players [data-seat-card]").evaluateAll(nodes=>nodes.every(node=>node.disabled)));
  await card(page,"east").evaluate(el=>{el.click();el.click();});assert.equal(delayedCalls,1);
  const moved=page.waitForResponse(r=>r.request().method()==="PUT"&&r.url().endsWith("/my-seat"));release();assert((await moved).ok());await page.unroute(endpoint,delay);
  await state(page,"east","current");await state(page,"south","empty");assert.equal((await tableInfo("web")).player_count,2);
  check("loading disables repeat input and sends exactly one request before restoring all seat states");

  // The server must also reject an occupancy race from a stale card view.
  await seat(peer,"web","north"); // peer leaves West atomically, taking North.
  assert.equal(await card(page,"north").getAttribute("data-seat-state"),"empty");
  const raced=page.waitForResponse(r=>r.request().method()==="PUT"&&r.url().endsWith("/my-seat"));await card(page,"north").click();assert.equal((await raced).status(),409);
  await frame(page).locator("#seat-message").filter({hasText:/occupied|占用/}).waitFor();
  info=await tableInfo("web");assert.equal(info.members.find(p=>p.user_id==="photo-user-2").seat,"east");assert.equal(info.members.find(p=>p.user_id==="photo-user-3").seat,"north");
  check("a stale empty card cannot displace a member who claimed that seat first");
  await state(page,"west","empty");await card(page,"west").click();await state(page,"west","current");await state(page,"east","empty");
  assert.equal((await tableInfo("web")).members.find(p=>p.user_id==="photo-user-2").seat,"west");
  await card(page,"east").click();await state(page,"east","current");await state(page,"west","empty");
  check("the West card also moves the current player and can return to East without duplicate membership");

  await open(anonymous,"B");await state(anonymous,"north","empty");await noExtraUI(anonymous);
  const publicMap=await guest.request.get(base+"/api/club-tables/web/seat-map");assert(publicMap.ok());const publicBody=await publicMap.json();
  assert(!JSON.stringify(publicBody).includes("photo-user-")&&!JSON.stringify(publicBody).includes("photo2")&&!JSON.stringify(publicBody).includes("photo3"));
  assert(publicBody.players.east?.occupied&&publicBody.players.north?.occupied);
  check("anonymous users can see four cards while seat-map reveals only occupancy");
  await card(anonymous,"north").click();await anonymous.waitForURL(url=>url.pathname==="/login");
  const redirect=new URL(new URL(anonymous.url()).searchParams.get("redirect_url"),base);
  assert.equal(redirect.searchParams.get("table"),"B");assert.equal(redirect.searchParams.get("pending_seat"),"north");
  assert.equal(await anonymous.locator('input[type="password"]').count(),1);
  await anonymous.locator('input[name="username"]').first().fill("photo4");await anonymous.locator('input[name="password"]').fill("photo-test-password");
  await anonymous.getByRole("button",{name:"Log in",exact:true}).click();await anonymous.waitForURL(url=>url.searchParams.get("page")==="record");
  await state(anonymous,"north","current");assert((await card(anonymous,"north").innerText()).includes("photo4"));
  assert.equal((await tableInfo("B")).members.find(p=>p.user_id==="photo-user-4").seat,"north");
  assert(!new URL(anonymous.url()).searchParams.has("pending_seat"));
  await anonymous.goto(base+"/?page=record&table=B&pending_seat=north");await state(anonymous,"north","current");
  await anonymous.waitForURL(url=>!url.searchParams.has("pending_seat"));assert.equal((await tableInfo("B")).player_count,1);
  await anonymous.reload();await state(anonymous,"north","current");assert.equal((await tableInfo("B")).player_count,1);
  check("global login retains table and selected wind, automatically resumes once, and does not duplicate on reload");

  await page.reload();await state(page,"east","current");
  await page.getByRole("button",{name:"CN",exact:true}).click();assert((await card(page,"east").innerText()).includes("photo2"));
  await page.getByRole("button",{name:"EN",exact:true}).click();assert.equal(await frame(page).locator("#players [data-seat-card]").count(),4);
  check("global language changes preserve the current player and seat selection");
  const output=path.join(root,".local_seat_cards");fs.mkdirSync(output,{recursive:true});
  await page.screenshot({path:path.join(output,"fixture-desktop.png"),fullPage:true});
  await page.setViewportSize({width:390,height:844});await noExtraUI(page);
  const dimensions=await page.evaluate(()=>({width:innerWidth,content:document.documentElement.scrollWidth}));assert(dimensions.content<=dimensions.width+1);
  const geometry=await frame(page).locator("#players [data-seat-card]").evaluateAll(nodes=>nodes.map(node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,width:r.width};}));
  assert.equal(geometry[0].y,geometry[1].y);assert.equal(geometry[2].y,geometry[3].y);assert(geometry[2].y>geometry[0].y);assert.equal(geometry[0].x,geometry[2].x);
  const frameWidth=await frame(page).locator("body").evaluate(()=>({width:innerWidth,content:document.documentElement.scrollWidth}));assert(frameWidth.content<=frameWidth.width+1);
  await page.screenshot({path:path.join(output,"fixture-mobile.png"),fullPage:true});
  check("390px layout retains exactly four touchable cards in two rows without horizontal overflow");
  assert.deepEqual(dialogs,[]);assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,"browser-test.json"),JSON.stringify({passed:true,checks,errors,dialogs,seat_requests:seatRequests.length,screenshot_note:"Isolated fixture; desktop.png and mobile.png are reserved for real-CDN preview captures."},null,2));
  console.log("Seat cards passed: "+checks.length+" browser checks, no local authentication or duplicate membership.");
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
