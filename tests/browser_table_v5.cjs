const assert=require("assert"),fs=require("fs"),{chromium}=require("playwright");
const {prepare}=require("./browser_support.cjs"),base=process.env.NFC_TEST_URL;
(async()=>{
 const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || undefined,headless:true});let diagnosticPage;const errors=[];
 try{
  const admin=await browser.newContext({acceptDownloads:true}),member=await browser.newContext(),other=await browser.newContext();
  for(const context of [admin,member,other])await prepare(context,base);
  const login=async(context,id)=>assert((await context.request.post(base+"/api/login",{data:{username:"photo"+id,password:"photo-test-password"}})).ok());
  await login(admin,1);const page=await admin.newPage(),user=await member.newPage(),conflict=await other.newPage();
  diagnosticPage=page;
  for(const p of [page,user,conflict]){p.setDefaultTimeout(15000);p.on("pageerror",e=>errors.push(e.message));p.on("dialog",dialog=>dialog.accept());}
  const post=async(path,data,context=admin)=>{const response=await context.request.post(base+path,{data});assert(response.ok(),await response.text());return response.json();};
  const created=await post("/api/admin/club-tables",{number:52,request_id:"table-browser-v5"});
  const info=async()=>(await(await admin.request.get(base+"/api/admin/club-tables")).json()).tables.find(t=>t.id===created.id);
  await page.goto(base+"/?page=record&table="+encodeURIComponent(created.score_table_id));
  await page.getByRole("combobox",{name:"Select Table",exact:true}).waitFor();
  assert.equal(await page.locator("[data-reservation-form]").count(),0);
  assert.equal(await page.locator('#record-game input[type="password"]').count(),0);
  await page.getByRole("link",{name:"View Table Reservations",exact:true}).click();
  await page.waitForURL(url=>url.pathname==="/reservations");
  await page.getByLabel("Month",{exact:true}).fill("10");await page.getByLabel("Day",{exact:true}).fill("4");await page.getByLabel("Time",{exact:true}).fill("18:30");
  assert.equal(await page.locator('input[type="datetime-local"],input[type="date"]').count(),0);
  // Participants are selected by registered name and IDs stay out of the UI.
  for(const [number,name] of [[2,"photo2"],[3,"photo3"]]){
   await page.getByRole("button",{name:"Add Another Participant",exact:true}).click();
   await page.getByRole("combobox",{name:"Participant "+number+" Registered Name",exact:true}).fill(name);
   await page.getByRole("option",{name,exact:true}).click();
  }
  assert.equal(await page.locator('[data-reservation-form] [data-registered-user-combobox]').count(),3);
  assert(!(await page.locator('[data-reservation-form]').innerText()).includes("photo-user-"));
  await page.getByLabel("Note (optional)",{exact:true}).fill("Reservation with three people");
  await page.getByRole("button",{name:"CN",exact:true}).click();
  assert.equal(await page.getByLabel("月",{exact:true}).inputValue(),"10");assert.equal(await page.getByLabel("时间",{exact:true}).inputValue(),"18:30");
  assert.equal(await page.getByRole("combobox",{name:"参与者 2 注册名",exact:true}).inputValue(),"photo2");
  await page.getByRole("button",{name:"EN",exact:true}).click();
  const reservationResponse=page.waitForResponse(r=>r.url().endsWith("/reservations")&&r.request().method()==="POST");
  await page.getByRole("button",{name:"Reserve This Table",exact:true}).click();
  const reserved=await reservationResponse;assert(reserved.ok(),await reserved.text());
  await page.getByText("Reservation with three people",{exact:false}).waitFor();
  let table=await info(),reservation=table.reservations[0];assert.equal(table.player_count,0);assert.equal(reservation.participants.length,3);
  assert(reservation.participants.every(p=>!Object.prototype.hasOwnProperty.call(p,"seat")));
  const originalYear=new Date(reservation.scheduled_at).getUTCFullYear();
  await page.reload();await page.getByText("Reservation with three people",{exact:false}).waitFor();assert.equal(new URL(page.url()).pathname,"/reservations");
  await page.getByRole("button",{name:"Edit Reservation",exact:true}).click();
  await page.getByLabel("Note (optional)",{exact:true}).fill("Edited reservation");
  await page.getByRole("button",{name:"Save Reservation Changes",exact:true}).click();await page.getByText("Edited reservation",{exact:false}).waitFor();
  assert.equal(new Date((await info()).reservations[0].scheduled_at).getUTCFullYear(),originalYear);
  await page.getByRole("link",{name:"Back to Scoring",exact:true}).click();await page.waitForURL(url=>url.searchParams.get("page")==="record");await page.goBack();await page.getByText("Edited reservation",{exact:false}).waitFor();
  await login(member,2);await user.goto(base+"/reservations?table="+created.id);await user.getByText("Edited reservation",{exact:false}).waitFor();
  assert.equal(await user.getByRole("button",{name:"Edit Reservation",exact:true}).count(),0);assert.equal(await user.getByRole("button",{name:"Cancel Reservation",exact:true}).count(),0);
  // Every management item has an independent preview, link, PNG download and revoke action.
  await page.goto(base+"/?page=admin");
  const card=page.locator("details").filter({has:page.locator("summary").filter({hasText:/^Table 52 /})}).first();await card.locator("summary").first().click();
  const links={};for(const seat of ["entry","east","south","west","north"]){
   const token=card.locator('[data-table-token="'+seat+'"]');await token.getByRole("button",{name:"Create QR Code",exact:true}).click();await token.getByRole("img").waitFor();
   links[seat]=await token.locator('input[readonly]').inputValue();
   const downloadEvent=page.waitForEvent("download");await token.getByRole("button",{name:"Download QR Code",exact:true}).click();const download=await downloadEvent;
   assert.equal(download.suggestedFilename(),"table-52-"+seat+".png");assert(fs.readFileSync(await download.path()).subarray(1,4).equals(Buffer.from("PNG")));
   assert.equal(await token.getByRole("button",{name:"Copy Link",exact:true}).count(),1);
  }
  assert.equal(new Set(Object.values(links)).size,5);
  // Creating another table from a landing QR clears the old trusted entry token.
  await page.goto(links.entry);await page.waitForURL(url=>url.searchParams.get("page")==="record");
  assert(new URLSearchParams(new URL(page.url()).hash.slice(1)).has("entry"));
  const inlineCreate=page.locator("details").filter({has:page.locator("summary").filter({hasText:/^Create Table$/})}).first();
  await inlineCreate.locator("summary").click();await inlineCreate.getByLabel("Table Number (positive integer)",{exact:true}).fill("53");
  await inlineCreate.getByRole("button",{name:"Create Table",exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('select[aria-label="Select Table"]')?.selectedOptions[0]?.textContent==="Table 53");
  assert(!new URLSearchParams(new URL(page.url()).hash.slice(1)).has("entry"));
  const selectedScoreId=await page.getByRole("combobox",{name:"Select Table",exact:true}).inputValue();
  await page.waitForFunction(id=>document.querySelector('#record-game iframe')?.contentDocument?.querySelector('#table')?.value===id,selectedScoreId);
  const newSeat=page.frameLocator("#record-game iframe").locator('[data-seat-card="south"][data-seat-state="empty"]');await newSeat.waitFor();
  // A poll that finishes between pointer-down and pointer-up must preserve the real button and its click.
  await newSeat.scrollIntoViewIfNeeded();const heldButton=await newSeat.elementHandle(),seatBounds=await newSeat.boundingBox(),seatWrites=[];
  const trackSeatWrite=request=>{if(request.method()==="PUT"&&request.url().endsWith("/my-seat"))seatWrites.push(request);};page.on("request",trackSeatWrite);
  await page.mouse.move(seatBounds.x+seatBounds.width/2,seatBounds.y+seatBounds.height/2);await page.mouse.down();
  const polled=page.waitForResponse(response=>response.request().method()==="GET"&&response.url().includes(encodeURIComponent(selectedScoreId))&&response.url().endsWith("/seat-swap-requests"));
  await page.evaluate(()=>document.querySelector('#record-game iframe').contentWindow.postMessage({type:"mahjong-table-changed"},location.origin));
  const pollResponse=await polled;assert(pollResponse.ok());await pollResponse.finished();
  await heldButton.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert(await heldButton.evaluate(button=>button.isConnected),"Polling replaced a seat button while the pointer was held down");
  const [newJoin]=await Promise.all([page.waitForResponse(r=>r.request().method()==="PUT"&&r.url().endsWith("/my-seat")),page.mouse.up()]);assert(newJoin.ok(),await newJoin.text());assert(!newJoin.request().postDataJSON().entry_token);
  assert.equal(seatWrites.length,1);page.off("request",trackSeatWrite);
  await page.frameLocator("#record-game iframe").locator('[data-seat-card="south"][data-seat-state="current"]').waitFor();
  const createdNext=(await(await admin.request.get(base+"/api/admin/club-tables")).json()).tables.find(t=>t.number===53);
  assert.equal(createdNext.members[0].user_id,"photo-user-1");assert.equal(createdNext.members[0].join_method,"seat_card");
  assert.equal((await info()).player_count,0);
  await page.goto(base+"/?page=admin");await card.locator("summary").first().click();
  await user.goto(links.entry);await user.waitForURL(url=>url.searchParams.get("page")==="record");await user.frameLocator("#record-game iframe").locator("[data-seat-card]").first().waitFor();assert.equal((await info()).player_count,0);
  // Logged-out table entry shows all four seats without a local login panel or joining.
  await conflict.goto(links.entry);await conflict.locator("[data-table-seats]").waitFor();assert.equal(await conflict.locator('[data-table-seats] li').count(),4);assert.equal((await info()).player_count,0);
  // Browsing the entry QR did not seat anyone; choosing a seat records its trusted source.
  assert.equal(new URLSearchParams(new URL(user.url()).hash.slice(1)).get("entry"),new URL(links.entry).pathname.split("/").at(-1));
  await user.frameLocator("#record-game iframe").locator('[data-seat-card="north"][data-seat-state="empty"]').click();
  await user.frameLocator("#record-game iframe").locator('[data-seat-card="north"][data-seat-state="current"]').waitFor();
  const entryMember=(await info()).members.find(p=>p.user_id==="photo-user-2");assert.equal(entryMember.seat,"north");assert.equal(entryMember.join_method,"qr_entry");
  assert.equal(await user.locator("[data-main-seat-button],[data-table-member-controls]").count(),0);
  assert((await member.request.post(base+"/api/club-tables/"+created.id+"/leave",{data:{}})).ok());
  assert.equal((await info()).player_count,0);
  await user.goto(links.east+"?seat=north");await user.waitForURL(url=>url.searchParams.get("page")==="record");await user.frameLocator("#record-game iframe").locator('[data-seat-card="east"][data-seat-state="current"]').waitFor();
  assert.equal((await info()).members.find(p=>p.user_id==="photo-user-2").seat,"east");
  await user.goto(links.east);await user.waitForURL(url=>url.searchParams.get("page")==="record");assert.equal((await info()).player_count,1);
  await user.goto(links.south);await user.getByText("You already occupy another seat at this table.",{exact:true}).waitFor();assert.equal((await info()).player_count,1);
  await login(other,3);await conflict.goto(links.east);await conflict.getByText("This seat is occupied. Choose another empty seat.",{exact:true}).waitFor();assert.equal((await info()).members[0].user_id,"photo-user-2");
  const before=await info();await card.locator('[data-table-token="north"]').getByRole("button",{name:"Regenerate QR Code",exact:true}).click();
  await page.waitForFunction(old=>document.querySelector('[data-table-token="north"] input[readonly]')?.value!==old,links.north);
  const after=await info();for(const seat of [null,"east","south","west"]){assert.equal(after.tokens.find(t=>t.channel==="qr"&&t.seat===seat&&!t.revoked_at).id,before.tokens.find(t=>t.channel==="qr"&&t.seat===seat&&!t.revoked_at).id);}
  await card.locator('[data-table-token="west"]').getByRole("button",{name:"Revoke Link",exact:true}).click();await card.locator('[data-table-token="west"]').getByRole("img").waitFor({state:"detached"});
  await conflict.goto(links.west);await conflict.getByText("This entry is no longer valid. Reopen the table entry.",{exact:false}).waitFor();
  // A seat scan without a session returns through the one global login page to the bound wind.
  await other.request.post(base+"/api/logout");await conflict.goto(links.south+"?seat=west");await conflict.waitForURL(url=>url.pathname==="/login");
  assert(new URL(conflict.url()).searchParams.get("redirect_url").includes(new URL(links.south).pathname));
  await conflict.locator('input[name="username"]').first().fill("photo4");await conflict.locator('input[name="password"]').fill("photo-test-password");await conflict.getByRole("button",{name:"Log in",exact:true}).click();
  await conflict.waitForURL(url=>url.searchParams.get("page")==="record");await conflict.frameLocator("#record-game iframe").locator('[data-seat-card="south"][data-seat-state="current"]').waitFor();
  assert.equal((await info()).members.find(p=>p.user_id==="photo-user-4").seat,"south");
  // Tournament entry requires an explicit check-in and resolves its wind on the server.
  let cup=await post("/api/tournaments",{name:"Entry QR Browser Cup",request_id:"entry-browser-cup"});let sequence=0;
  const action=async(action,data={})=>{cup=await post("/api/tournaments/"+cup.id+"/actions",{action,data:{...data,version:cup.version,request_id:"entry-cup-"+(++sequence)}});return cup;};
  for(const number of [5,6,7,8]){await action("player",{registered_user_id:"photo-user-"+number});const player=cup.players.find(p=>p.name==="photo"+number);await action("bind_account",{player_id:player.id,account_id:"photo-user-"+number});}
  await action("start");await action("pair");await action("confirm_seats");
  const match=cup.rounds.at(-1).tables[0],tournamentEntry=await post("/api/admin/club-tables/"+match.table_id+"/tokens",{channel:"qr",purpose:"table_landing",request_id:"entry-browser-token"});
  const tournamentContext=await browser.newContext();await prepare(tournamentContext,base);await login(tournamentContext,5);
  const tournamentPage=await tournamentContext.newPage();tournamentPage.on("pageerror",error=>errors.push(error.message));tournamentPage.on("dialog",dialog=>dialog.accept());
  await tournamentPage.goto(base+tournamentEntry.path);await tournamentPage.waitForURL(url=>url.searchParams.get("tournament")===cup.id);
  const tournamentInfo=async()=>(await(await admin.request.get(base+"/api/admin/club-tables")).json()).tables.find(t=>t.id===match.table_id);
  assert.equal((await tournamentInfo()).player_count,0);
  await tournamentPage.getByRole("button",{name:"Check In",exact:true}).click();await tournamentPage.getByRole("button",{name:"Checked In",exact:true}).waitFor();
  const joined=(await tournamentInfo()).members.find(member=>member.user_id==="photo-user-5");assert(joined);assert.equal(joined.join_method,"qr_entry");assert(["east","south","west","north"].includes(joined.seat));
  assert.deepEqual(errors,[]);console.log("V5 browser passed: separate yearless reservations, participants, permissions, language retention, five independent QR downloads, safe landing, explicit seats, conflicts, idempotent scans and global login return.");
 }catch(error){
  if(diagnosticPage&&!diagnosticPage.isClosed())console.error("V5 page diagnostic",JSON.stringify({errors,url:diagnosticPage.url(),body:(await diagnosticPage.locator("body").innerText()).slice(0,4500),summaries:await diagnosticPage.locator("summary").allTextContents(),frames:diagnosticPage.frames().map(frame=>frame.url())}));
  throw error;
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
