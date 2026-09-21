const assert=require("assert"),{chromium}=require("playwright");
const {prepare}=require("./browser_support.cjs"),base=process.env.NFC_TEST_URL;
(async()=>{
 const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || undefined,headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1280,height:900}});await prepare(context,base);
  assert((await context.request.post(base+"/api/login",{data:{username:"photo1",password:"photo-test-password"}})).ok());
  const createdResponse=await context.request.post(base+"/api/admin/club-tables",{data:{number:75,request_id:"registered-browser-table"}});
  assert(createdResponse.ok(),await createdResponse.text());const table=await createdResponse.json();
  const page=await context.newPage(),errors=[],queries=[];page.setDefaultTimeout(15000);page.on("pageerror",error=>errors.push(error.message));
  page.on("request",request=>{const url=new URL(request.url());if(url.pathname==="/api/registered-users")queries.push(url.searchParams);});
  await page.goto(base+"/reservations?table="+table.id);
  await page.getByLabel("Month",{exact:true}).fill("10");await page.getByLabel("Day",{exact:true}).fill("8");await page.getByLabel("Time",{exact:true}).fill("18:00");
  await page.getByRole("button",{name:"Add Another Participant",exact:true}).click();
  let input=page.getByRole("combobox",{name:"Participant 2 Registered Name",exact:true});
  await input.fill("unknown-free-text");await page.getByText("No registered name found.",{exact:true}).waitFor();
  assert(await page.getByRole("button",{name:"Reserve This Table",exact:true}).isDisabled());
  assert.equal(await input.evaluate(element=>element.checkValidity()),false);
  await input.fill("g");await input.fill("gu");await input.fill("gue");await input.fill("guest");
  await page.getByRole("option",{name:"guest01",exact:true}).waitFor();
  assert.equal(queries.filter(query=>query.get("q")==="g"||query.get("q")==="gu"||query.get("q")==="gue").length,0);
  assert.equal(await page.locator("[role=listbox]").getByRole("option").count(),10);
  assert(queries.every(query=>query.get("limit")==="10"));
  await page.getByRole("button",{name:"More Results",exact:true}).click();
  await page.getByRole("option",{name:"guest20",exact:true}).waitFor();
  assert(queries.some(query=>query.get("cursor")));
  assert(!(await page.locator("body").innerText()).includes("private-account-"));
  await input.press("ArrowDown");await input.press("Enter");
  assert.equal(await input.inputValue(),"guest02");
  assert.equal(await input.evaluate(element=>element.checkValidity()),true);
  await page.getByRole("button",{name:"CN",exact:true}).click();
  assert.equal(await page.getByRole("combobox",{name:"参与者 2 注册名",exact:true}).inputValue(),"guest02");
  await page.getByRole("button",{name:"EN",exact:true}).click();
  await input.fill("guest02 changed");assert(await page.getByRole("button",{name:"Reserve This Table",exact:true}).isDisabled());
  let failed=false;
  await page.route("**/api/registered-users?*",async route=>{
   const url=new URL(route.request().url());if(url.searchParams.get("q")==="guest"&&!failed){failed=true;await route.fulfill({status:500,json:{detail:{code:"private-account-SECRET",message:"database accounts.secret"}}});}else await route.continue();
  });
  await input.fill("guest");await page.getByText("Search is unavailable. Please retry.",{exact:true}).waitFor();
  assert(!(await page.locator("body").innerText()).includes("private-account-SECRET"));
  await page.getByRole("button",{name:"Retry Search",exact:true}).click();await page.getByRole("option",{name:"guest01",exact:true}).click();
  await page.getByRole("button",{name:"Participant 2 Registered Name · Clear Selection",exact:true}).click();
  assert.equal(await input.inputValue(),"");assert(await page.getByRole("button",{name:"Reserve This Table",exact:true}).isDisabled());
  await input.fill(" ＰＨＯＴＯ２ ");await page.getByRole("option",{name:"photo2",exact:true}).click();
  const [savedResponse]=await Promise.all([
   page.waitForResponse(response=>response.request().method()==="POST"&&response.url().endsWith("/reservations")),
   page.getByRole("button",{name:"Reserve This Table",exact:true}).click(),
  ]);
  assert(savedResponse.ok(),await savedResponse.text());const savedReservation=await savedResponse.json();
  assert.deepEqual(savedReservation.participants.map(person=>person.id||person.user_id).sort(),["photo-user-1","photo-user-2"]);
  const reservationRow=page.locator('[data-reservation-id="'+savedReservation.id+'"]');await reservationRow.waitFor();
  assert((await reservationRow.innerText()).includes("photo1"));assert((await reservationRow.innerText()).includes("photo2"));
  assert.equal(await reservationRow.locator('[data-account-avatar]').count(),2);
  assert(!(await page.locator("body").innerText()).includes("photo-user-"));
  await page.goto(base+"/?page=record&table="+table.score_table_id);
  const ordinary=page.frameLocator("#record-game iframe");
  await ordinary.locator('[data-seat-card="east"][data-seat-state="empty"]').waitFor();
  assert.equal(await page.locator("[data-main-seat-button],[data-table-member-controls],[data-table-seats]").count(),0);
  assert.equal(await ordinary.locator("#seat-buttons,#seating").count(),0);
  await page.setViewportSize({width:390,height:844});assert.equal(await ordinary.locator("[data-seat-card]").count(),4);
  await ordinary.locator('[data-seat-card="east"]').click();
  await ordinary.locator('[data-seat-card="east"][data-seat-state="current"]').waitFor();
  await page.goto(base+"/?page=admin");
  const adminTable=page.locator("details").filter({has:page.locator("summary").filter({hasText:/^Table 75 /})}).first();
  await adminTable.locator("summary").first().click();
  await adminTable.getByRole("button",{name:"Join Table",exact:true}).click();
  await page.getByRole("tab",{name:"Seat by Registered Name",exact:true}).click();
  input=page.getByRole("dialog").getByRole("combobox",{name:"Registered Name",exact:true});await input.fill("photo2");
  assert(await page.getByRole("dialog").getByRole("button",{name:"Add Selected Player",exact:true}).isDisabled());
  await page.getByRole("option",{name:"photo2",exact:true}).click();await page.getByRole("dialog").getByRole("combobox",{name:"Choose a Seat",exact:true}).selectOption("south");
  const added=page.waitForResponse(response=>response.url().endsWith("/players")&&response.request().method()==="POST");
  await page.getByRole("dialog").getByRole("button",{name:"Add Selected Player",exact:true}).click();assert((await added).ok());await page.getByRole("dialog").waitFor({state:"detached"});
  const state=await(await context.request.get(base+"/api/club-tables/"+table.id)).json(),member=state.members.find(p=>p.user_id==="photo-user-2");
  assert.equal(member.join_method,"registered_name");assert.equal(member.added_by_user_id,"photo-user-1");assert.equal(member.seat,"south");
  assert(!(await adminTable.locator("[data-table-member-controls]").innerText()).includes("photo-user-"));
  assert((await context.request.post(base+"/api/club-tables/"+table.id+"/leave",{data:{}})).ok());
  // The same picker can restrict historical tournament rosters without fetching all accounts.
  await page.evaluate(()=>{
   const mount=document.createElement("div");mount.id="combobox-contract";document.body.append(mount);
   const options=Array.from({length:24},(_,i)=>({id:"legacy-private-"+(i+1),name:"Legacy "+(i+1)}));
   function Contract(){const [value,setValue]=React.useState(null);return React.createElement("form",null,React.createElement(window.RegisteredUserCombobox,{value,onChange:setValue,language:"EN",label:"Legacy Player",options,allowedIds:["legacy-private-20","legacy-private-21"],excludeIds:["legacy-private-21"],required:true}));}
   ReactDOM.createRoot(mount).render(React.createElement(Contract));
  });
  const legacy=page.getByRole("combobox",{name:"Legacy Player",exact:true});await legacy.fill("legacy");
  await page.getByRole("option",{name:"Legacy 20",exact:true}).waitFor();assert.equal(await page.locator("[role=listbox]").getByRole("option").count(),1);
  await legacy.press("Enter");assert.equal(await legacy.inputValue(),"Legacy 20");assert.equal(await legacy.evaluate(element=>element.checkValidity()),true);
  await legacy.fill("Legacy 999");assert.equal(await legacy.evaluate(element=>element.checkValidity()),false);
  // Local historical rosters use Python-compatible name folding without changing IDs.
  await page.evaluate(()=>{
   const mount=document.createElement("div");mount.id="casefold-contract";document.body.append(mount);
   const options=[{id:"MiXeD-Straße-Ｉ-ı",name:"Straße"},{id:"CAPS-STRASSE",name:"STRASSE"},{id:"ASCII-I",name:"I"},{id:"Dotless-ı",name:"ı"}];
   function Contract(){const [value,setValue]=React.useState(null);return React.createElement(RegisteredUserCombobox,{value,onChange:person=>{setValue(person);window.casefoldSelected=person;},language:"EN",label:"Casefold Player",options,required:true});}
   ReactDOM.createRoot(mount).render(React.createElement(Contract));
  });
  const casefold=page.locator("#casefold-contract"),foldInput=casefold.getByRole("combobox");
  await foldInput.fill("STRASSE");await casefold.getByRole("option",{name:"Straße",exact:true}).waitFor();
  assert.equal(await casefold.getByRole("option").count(),2);await casefold.getByRole("option",{name:"Straße",exact:true}).click();
  assert.deepEqual(await page.evaluate(()=>window.casefoldSelected),{id:"MiXeD-Straße-Ｉ-ı",name:"Straße"});
  await foldInput.fill("straße");await casefold.getByRole("option",{name:"STRASSE",exact:true}).click();
  assert.deepEqual(await page.evaluate(()=>window.casefoldSelected),{id:"CAPS-STRASSE",name:"STRASSE"});
  await foldInput.fill("I");await casefold.getByRole("option",{name:"I",exact:true}).waitFor();
  assert.equal(await casefold.getByRole("option",{name:"ı",exact:true}).count(),0);
  await foldInput.fill("ı");await casefold.getByRole("option",{name:"ı",exact:true}).click();
  assert.equal(await page.evaluate(()=>window.casefoldSelected.id),"Dotless-ı");
  assert(!(await casefold.innerText()).includes("MiXeD-Straße-Ｉ-ı"));
  // Tournament adapters keep actual roster IDs and respect cleared local selections.
  await page.evaluate(()=>{
   const mount=document.createElement("div");mount.id="tournament-contract";document.body.append(mount);
   const players=[{id:"old-roster-a",name:"Roster A",account_id:"photo-user-1"},{id:"old-roster-b",name:"Roster B"},{id:"old-roster-c",name:"Roster C"},{id:"old-roster-d",name:"Roster D"}];
   const tables=[{number:1,seats:players.map(p=>p.id)}],standings=players.map((p,i)=>({...p,rank:i+1,score:30-i*10,round_score:0,game_score:0,penalty_total:0,completed_rounds:1}));
   const initial={id:"browser-adapter-contract",players,standings,status:"running",settings:{qualifying_rank:2,min_unit:.1,advance_on_tie:true},rounds:[],penalties:[]};
   localStorage.setItem("tm-penalty-"+initial.id,JSON.stringify({player_id:"removed-private-roster",amount:"10",reason:"Old draft",match_id:""}));
   window.bindingCalls=[];window.penaltyCalls=[];window.confirmedRoster=null;
   function Contract(){const [state,setState]=React.useState(initial);
    window.renameContractBinding=name=>setState(old=>({...old,players:old.players.map(p=>p.id==="old-roster-a"?{...p,name}:p)}));
    const bind=async(action,data)=>{window.bindingCalls.push({action,data});setState(old=>({...old,players:old.players.map(p=>p.id===data.player_id?{...p,account_id:data.account_id}:p)}));return true;};
    return React.createElement("div",null,
      React.createElement("div",{id:"seating-adapter-contract"},React.createElement(TournamentSeating,{tables,state,language:"EN",disabled:false,onConfirm:seats=>{window.confirmedRoster=seats;}})),
      React.createElement("div",{id:"ranking-adapter-contract"},React.createElement(TournamentRankings,{state,language:"EN"})),
      React.createElement("div",{id:"binding-adapter-contract"},React.createElement(TournamentAccountBindings,{state,language:"EN",busy:false,run:bind})),
      React.createElement("div",{id:"penalty-adapter-contract"},React.createElement(TournamentPenalties,{state,language:"EN",busy:false,canAdmin:true,run:async(action,data)=>{window.penaltyCalls.push({action,data});return true;}})));
   }
   ReactDOM.createRoot(mount).render(React.createElement(Contract));
  });
  const seating=page.locator("#seating-adapter-contract");
  await seating.getByRole("button",{name:"Seat 1-1 · Clear Selection",exact:true}).click();
  await seating.getByRole("button",{name:"Seat 1-2 · Clear Selection",exact:true}).click();
  assert.equal(await seating.getByRole("combobox",{name:"Seat 1-1",exact:true}).inputValue(),"");
  assert.equal(await seating.getByRole("combobox",{name:"Seat 1-2",exact:true}).inputValue(),"");
  assert.equal(await seating.getByRole("combobox",{name:"Seat 1-3",exact:true}).inputValue(),"Roster C");
  assert(await seating.getByRole("button").last().isDisabled());
  for(const [wind,name] of [[1,"Roster A"],[2,"Roster B"]]){await seating.getByRole("combobox",{name:"Seat 1-"+wind,exact:true}).fill(name);await seating.getByRole("option",{name,exact:true}).click();}
  await seating.getByRole("button").last().click();assert.deepEqual(await page.evaluate(()=>window.confirmedRoster),[["old-roster-a","old-roster-b","old-roster-c","old-roster-d"]]);
  const ranking=page.locator("#ranking-adapter-contract"),compare=ranking.getByRole("combobox").first(),target=ranking.getByRole("combobox").last();
  await compare.fill("Roster A");await ranking.getByRole("option",{name:"Roster A",exact:true}).click();
  await compare.fill("No fallback please");assert.equal(await compare.inputValue(),"No fallback please");
  assert.equal(await compare.evaluate(element=>element.checkValidity()),false);
  await ranking.getByRole("button",{name:"Player Name · Clear Selection",exact:true}).click();assert.equal(await compare.inputValue(),"");
  await target.fill("Roster B");await ranking.getByRole("option",{name:"Roster B",exact:true}).click();
  await ranking.getByRole("button").last().click();assert.equal(await target.inputValue(),"");
  const binding=page.locator("#binding-adapter-contract");await binding.locator("summary").click();
  let account=binding.getByRole("combobox",{name:"Roster A",exact:true});
  await binding.getByRole("button",{name:"Roster A · Clear Selection",exact:true}).click();assert.equal(await account.inputValue(),"");
  assert.equal(await binding.getByText("Selected",{exact:true}).count(),0);assert.deepEqual(await page.evaluate(()=>window.bindingCalls),[]);
  await account.fill("Unselected account");assert.equal(await account.evaluate(element=>element.checkValidity()),false);assert.deepEqual(await page.evaluate(()=>window.bindingCalls),[]);
  await account.fill("photo2");await binding.getByRole("option",{name:"photo2",exact:true}).click();
  assert.equal(await account.inputValue(),"photo2");assert.deepEqual(await page.evaluate(()=>window.bindingCalls),[{action:"bind_account",data:{player_id:"old-roster-a",account_id:"photo-user-2"}}]);
  await page.evaluate(()=>window.renameContractBinding("Renamed Roster A"));account=binding.getByRole("combobox",{name:"Renamed Roster A",exact:true});
  await page.waitForFunction(()=>document.querySelector('#binding-adapter-contract input[role="combobox"]').value==="Renamed Roster A");
  assert.equal(await account.inputValue(),"Renamed Roster A");
  await binding.getByRole("button",{name:"Renamed Roster A · Clear Selection",exact:true}).click();
  await page.evaluate(()=>window.renameContractBinding("Renamed Again"));account=binding.getByRole("combobox",{name:"Renamed Again",exact:true});
  assert.equal(await account.inputValue(),"");assert.equal(await binding.getByText("Selected",{exact:true}).count(),0);
  await account.fill("Different typed account");assert.equal(await binding.getByText("Selected",{exact:true}).count(),0);assert.equal((await page.evaluate(()=>window.bindingCalls)).length,1);
  const penalty=page.locator("#penalty-adapter-contract"),addPenalty=penalty.getByRole("button",{name:"Add Penalty",exact:true});
  assert(await addPenalty.isDisabled());await penalty.getByRole("combobox").first().fill("Roster B");await penalty.getByRole("option",{name:"Roster B",exact:true}).click();
  assert(!await addPenalty.isDisabled());await addPenalty.click();
  const penalties=await page.evaluate(()=>window.penaltyCalls);assert.equal(penalties.length,1);assert.equal(penalties[0].data.player_id,"old-roster-b");
  // Unknown server error codes and delivery request IDs never become rendered text.
  const secret="private-UUID-9c5736b1-559f-44f8-9421-90e6437b5794";
  for(const [kind,body] of Object.entries({detail:{detail:{code:secret,message:secret}},top:{code:secret,message:secret},validation:{detail:[{msg:secret,input:secret}]}})){
   await page.route("**/api/privacy-probe-"+kind,route=>route.fulfill({status:500,json:body}));
   const message=await page.evaluate(async path=>{try{await tournamentApi(path);return "unexpected success";}catch(error){return error.message;}},"/api/privacy-probe-"+kind);
   assert.equal(message,"requestFailed");assert(!message.includes(secret));
  }
  await page.evaluate(secret=>{
   const mount=document.createElement("div");mount.id="privacy-error-contract";document.body.append(mount);
   function Failure(){const [error,setError]=React.useState("");React.useEffect(()=>{tournamentApi("/api/privacy-probe-detail").catch(e=>setError(e.message));},[]);
    return React.createElement("div",null,React.createElement("p",{id:"safe-api-error"},error),React.createElement(DeliveryStatus,{language:"EN",delivery:{status:"failed",request_id:secret,error_code:secret}}));}
   ReactDOM.createRoot(mount).render(React.createElement(Failure));
  },secret);
  await page.locator("#safe-api-error").getByText("requestFailed",{exact:true}).waitFor();
  assert(!(await page.locator("body").innerText()).includes(secret));
  assert.deepEqual(errors,[]);
  console.log("Registered picker passed: debounce, pagination, NFKC, keyboard/mouse, required selection, invalidation, clear, language retention, retry privacy, restricted roster, four self-seat cards, administrator by-name seating and existing leave API.");
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
