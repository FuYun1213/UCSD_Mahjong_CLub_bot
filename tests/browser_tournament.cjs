const fs=require("fs"),path=require("path"),assert=require("assert");
const {chromium}=require("playwright"),babel=require("@babel/core");
const root=path.resolve(__dirname,".."),base=process.env.NFC_TEST_URL;
const compile=p=>babel.transformFileSync(path.join(root,p),{plugins:[[require("@babel/plugin-transform-react-jsx"),{runtime:"classic"}]]}).code;
(async()=>{
 const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || undefined,headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900},acceptDownloads:true});
  await require("./browser_support.cjs").prepare(page.context(),base);
  const errors=[];page.on("pageerror",e=>errors.push(e.message));page.on("dialog",d=>d.type()==="prompt"?d.accept("Browser audit reason"):d.accept());
  await page.route("https://cdn.tailwindcss.com/**",r=>r.fulfill({body:"window.tailwind={};",contentType:"application/javascript"}));
  await page.route("https://unpkg.com/react@18/**",r=>r.fulfill({path:path.join(path.dirname(require.resolve("react/package.json")),"umd/react.development.js"),contentType:"application/javascript"}));
  await page.route("https://unpkg.com/react-dom@18/**",r=>r.fulfill({path:path.join(path.dirname(require.resolve("react-dom/package.json")),"umd/react-dom.development.js"),contentType:"application/javascript"}));
  await page.route("**/table-controls.jsx?*",r=>r.fulfill({body:compile("web/table-controls.jsx"),contentType:"application/javascript"}));
  await page.route("**/app.jsx?*",r=>r.fulfill({body:compile("web/app.jsx"),contentType:"application/javascript"}));
  await page.route("**/tournament-v2.jsx?*",r=>r.fulfill({body:compile("web/tournament-v2.jsx"),contentType:"application/javascript"}));
  await page.route("**/tournament.jsx?*",r=>r.fulfill({body:compile("web/tournament.jsx"),contentType:"application/javascript"}));
  await page.route(url=>url.origin===base&&["/","/login"].includes(url.pathname),r=>r.fulfill({body:fs.readFileSync(path.join(root,"web/index.html"),"utf8").replace(/<script src="https:\/\/unpkg.com\/@babel\/standalone\/babel.min.js"><\/script>/,"").replaceAll('type="text/babel"','type="text/javascript"'),contentType:"text/html"}));
  // Verify the real login entry, failed-login state and home redirect.
  await page.goto(base+"/");
  await page.locator("header").getByRole("link",{name:"Log In",exact:true}).click();
  await page.locator('input[name="password"]').waitFor();
  await page.locator('input[name="username"]').first().fill("photo1");
  await page.locator('input[name="password"]').fill("wrong-test-password");
  await Promise.all([page.waitForResponse(r=>r.url().endsWith("/api/login")),page.getByRole("button",{name:"Log in",exact:true}).click()]);
  assert.equal(new URL(page.url()).pathname,"/login");
  await page.locator('input[name="password"]').fill("photo-test-password");
  await page.getByRole("button",{name:"Log in",exact:true}).click();
  await page.waitForURL(base+"/");
  await page.locator("header").getByRole("link",{name:"Log In",exact:true}).waitFor({state:"hidden"});
  assert.equal(await page.locator("header").getByRole("link",{name:"Log In",exact:true}).count(),0);
  try {await page.getByRole("button",{name:"Tournament Mode",exact:true}).click({timeout:8000});} catch(e){console.error("UI ERRORS",errors,"BODY",await page.locator("body").innerText());throw e;}
  await page.getByRole("textbox",{name:"Tournament Name",exact:true}).fill("Browser Cup");
  await page.getByRole("button",{name:"Create Tournament",exact:true}).click();
  await page.getByRole("heading",{name:"Browser Cup · Draft",exact:true}).waitFor();
  let tid=new URL(page.url()).searchParams.get("tournament");
  const get=async()=>{const r=await page.request.get(base+"/api/tournaments/"+tid+"/admin");assert(r.ok(),await r.text());return r.json();};
  const field=page.getByRole("combobox",{name:"Player Name",exact:true}).first();
  for(let i=1;i<=8;i++){
   await field.fill("photo"+i);
   await page.getByRole("option",{name:"photo"+i,exact:true}).click();
   await page.getByRole("button",{name:"Add Player",exact:true}).click();
   await page.waitForFunction(n=>document.querySelectorAll('[data-i18n-owned] li').length>=n,i);
  }
  await field.fill("Unsaved Name");
  await page.getByRole("button",{name:"CN",exact:true}).click();
  assert.equal(await page.getByRole("combobox",{name:"选手姓名",exact:true}).first().inputValue(),"Unsaved Name");
  await page.getByRole("button",{name:"EN",exact:true}).click();
  assert.equal(await field.inputValue(),"Unsaved Name");
  const penaltyCard=page.getByRole("heading",{name:"Penalty",exact:true}).locator("..");
  let penaltyState=await get();
  await penaltyCard.getByRole("combobox").first().fill(penaltyState.players[0].name);
  await penaltyCard.getByRole("option",{name:penaltyState.players[0].name,exact:true}).click();
  await penaltyCard.getByRole("spinbutton").fill("10");
  await penaltyCard.getByRole("textbox").fill("Browser penalty");
  await penaltyCard.getByRole("button",{name:"Add Penalty",exact:true}).click();
  await penaltyCard.getByText("Browser penalty",{exact:true}).waitFor();
  assert.equal((await get()).standings.find(p=>p.id===penaltyState.players[0].id).penalty_total,-10);
  await penaltyCard.getByRole("button",{name:"Revoke Penalty",exact:true}).click();
  await penaltyCard.getByText("Revoked",{exact:false}).waitFor();
  assert.equal((await get()).standings.find(p=>p.id===penaltyState.players[0].id).penalty_total,0);
  let binding=await get();
  for(let i=0;i<binding.players.length;i++){
   const r=await page.request.post(base+"/api/tournaments/"+tid+"/actions",{data:{action:"bind_account",data:{player_id:binding.players[i].id,account_id:"photo-user-"+(i+1),version:binding.version,request_id:"binding-"+i}}});
   assert(r.ok(),await r.text());binding=await r.json();
  }
  const timed=await page.request.post(base+"/api/tournaments/"+tid+"/actions",{data:{action:"settings",data:{settings:{time_limit_seconds:1},version:binding.version,request_id:"one-second-timer"}}});
  assert(timed.ok(),await timed.text());
  const participantContexts=[];
  for(let i=1;i<=8;i++){
    const c=await browser.newContext();assert((await c.request.post(base+"/api/login",{data:{username:"photo"+i,password:"photo-test-password"}})).ok());
    participantContexts.push(c);
  }
  const startTables=async tables=>{
    const state=await get();
    for(const table of tables){
      const before=await page.request.post(base+"/api/tournaments/"+tid+"/tables/"+table.match_id+"/start",{data:{request_id:"premature-"+table.match_id}});
      assert.equal(before.status(),409);
      for(const pid of table.seats){
        const index=Number(state.players.find(p=>p.id===pid).account_id.split("-").at(-1))-1;
        const res=await participantContexts[index].request.post(base+"/api/tournaments/"+tid+"/tables/"+table.match_id+"/check-in",{data:{request_id:"check-"+table.match_id+"-"+pid}});
        assert(res.ok(),await res.text());
      }
      const res=await page.request.post(base+"/api/tournaments/"+tid+"/tables/"+table.match_id+"/start",{data:{request_id:"start-"+table.match_id}});
      assert(res.ok(),await res.text());
    }
    await page.getByRole("button",{name:"Refresh",exact:true}).last().click();
    await page.getByText(/^(In Progress|Time is up)$/).first().waitFor();
  };
  await page.reload();
  await page.getByRole("heading",{name:"Browser Cup · Draft",exact:true}).waitFor();
  await page.getByRole("button",{name:"Start Tournament",exact:true}).click();
  await page.getByRole("button",{name:"Preview Pairings",exact:true}).click();
  await page.getByRole("button",{name:"Confirm Seats and Start Round",exact:true}).click();
  await page.locator("#tm-table-1").waitFor();
  let state=await get();
  await startTables(state.rounds[0].tables);
  await page.getByText("Time is up",{exact:true}).first().waitFor();
  for(const table of state.rounds[0].tables){
   const card=page.locator("#tm-table-"+table.number);
   const names=Object.fromEntries(state.players.map(p=>[p.id,p.name]));
   for(let i=0;i<4;i++)await card.getByRole("spinbutton",{name:names[table.seats[i]]+" Raw Points",exact:true}).fill(String([40000,30000,20000,10000][i]));
   await card.getByRole("button",{name:"Preview Score Calculation",exact:true}).click();
   await card.getByRole("button",{name:"Save Score Draft",exact:true}).click();
   await card.getByText("Score draft saved.",{exact:false}).waitFor();
  }
  await page.getByRole("button",{name:"Confirm Round Scores",exact:true}).click();
  await page.getByRole("button",{name:"Finish Swiss Stage",exact:true}).click();
  await page.getByRole("combobox",{name:"Select Finalists",exact:true}).waitFor();
  const finalists=page.getByRole("combobox",{name:"Select Finalists",exact:true});
  const finalPlayers=(await get()).swiss_standings;
  for(const person of finalPlayers){
   await finalists.fill(person.name);
   await page.getByRole("option",{name:person.name,exact:true}).click();
  }
  await page.getByRole("button",{name:"Preview Finals Tables",exact:true}).click();
  await page.getByRole("button",{name:"Confirm and Start Finals",exact:true}).click();
  await page.getByRole("heading",{name:"Browser Cup · Finals In Progress",exact:true}).waitFor();
  state=await get();assert.equal(state.finals.tables.length,2);
  await startTables(state.finals.tables);
  // The one-second fixture expires both tables and changes the aggregate version.
  // Load that authoritative version before submitting a hand.
  await page.getByText("Time is up",{exact:true}).last().waitFor();
  await page.reload();
  await page.getByRole("heading",{name:"Browser Cup · Finals In Progress",exact:true}).waitFor();
  const firstFinal=page.locator("#tm-table-1").last();
  for(const input of await firstFinal.getByRole("spinbutton").all())await input.fill("1");
  const handResponse=page.waitForResponse(r=>r.url().endsWith("/actions")&&r.request().postDataJSON()?.action==="hand");
  await firstFinal.getByRole("button",{name:"Confirm and Save Hand",exact:true}).click();
  const savedHand=await handResponse;assert(savedHand.ok(),await savedHand.text());
  await page.waitForFunction(()=>document.body.innerText.includes("Hand 1"));
  state=await get();assert.equal(state.finals.tables[0].hands.length,1);
  assert.equal(state.finals.tables[1].hands.length,0);
  const before=state.standings;
  await page.reload();
  await page.getByRole("heading",{name:"Browser Cup · Finals In Progress",exact:true}).waitFor();
  assert.deepEqual((await get()).standings,before);
  await page.setViewportSize({width:390,height:844});
  await page.getByRole("button",{name:"Finish Tournament",exact:true}).click();
  await page.getByRole("button",{name:"Lock Results",exact:true}).click();
  await page.getByRole("heading",{name:"Browser Cup · Locked",exact:true}).waitFor();
  assert.equal(await page.getByRole("button",{name:"Confirm and Save Hand",exact:true}).count(),0);
  assert.deepEqual(errors,[]);
  for(const c of participantContexts)await c.close();
  assert.deepEqual(errors,[]);
  console.log("Browser workflow passed: bilingual state, guest players, seating, score confirmation, two finals tables, PNG download, reload, lock and ordinary scoring.");
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
