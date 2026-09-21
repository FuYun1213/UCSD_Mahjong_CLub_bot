const assert=require("assert"),{chromium}=require("playwright");
const {prepare}=require("./browser_support.cjs"),base=process.env.NFC_TEST_URL;
(async()=>{
 const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || undefined,headless:true});
 try {
  const context=await browser.newContext({viewport:{width:390,height:844}});await prepare(context,base);
  const page=await context.newPage(),errors=[],apiCalls=[],uploadedRequests=[];
  page.on("pageerror",e=>errors.push(e.message));page.on("request",r=>{if(r.url().includes("/api/"))apiCalls.push(r.url());if(r.url().endsWith("/api/manual-score/upload"))uploadedRequests.push(r.postDataJSON());});
  await page.goto(base+"/?page=record");
  assert.equal(await page.locator('#record-game input[type="password"]').count(),0);
  await page.getByRole("link",{name:"Manual Score",exact:true}).click();
  await page.waitForURL("**/manual-score");
  assert.equal(await page.locator('fieldset input').count(),8);
  assert.equal(await page.locator('input[type="file"]').count(),0);
  assert.deepEqual(await page.locator('fieldset input').evaluateAll(nodes=>nodes.map(n=>n.value)),Array(8).fill(""));
  assert((await context.request.post(base+"/api/login",{data:{username:"photo1",password:"photo-test-password"}})).ok());
  await page.reload();
  const winds=["East","South","West","North"];
  async function selectPlayer(index,name,keyboard=false){
   const input=page.getByRole("combobox",{name:winds[index]+" Registered Name",exact:true});
   await input.fill("");await input.fill(name);
   const option=page.getByRole("option",{name,exact:true});await option.waitFor();
   assert(!(await page.getByRole("listbox").innerText()).includes("photo-user-"));
   if(keyboard)await input.press("Enter");else await option.click();
  }
  async function fill(names=["photo1","photo2","photo3","photo4"],scores=["25000","25000","25000","25000"]){
   for(let i=0;i<4;i++){
    await selectPlayer(i,names[i],i===0);
    await page.getByLabel(winds[i]+" Score",{exact:true}).fill(scores[i]);
   }
  }
  await fill(["photo1","photo1","photo3","photo4"]);
  assert.equal(await page.getByRole("button",{name:/Review Players|检查|Confirm and Save/}).count(),0);
  await page.getByRole("button",{name:"Upload",exact:true}).click();
  // Upload schedules validation state; wait for both wind errors before counting.
  await page.getByText("Choose a different registered user for each wind.",{exact:true}).nth(1).waitFor();
  assert((await page.getByText("Choose a different registered user for each wind.",{exact:true}).count())>=2);
  await fill(undefined,["25.5","25000","25000","25000"]);
  await page.getByRole("button",{name:"Upload",exact:true}).click();
  await page.getByText("Enter an integer score that follows the scoring rules below.",{exact:true}).waitFor();
  await page.getByRole("combobox",{name:"East Registered Name",exact:true}).fill("does not exist");
  await page.getByText("No registered name found.",{exact:true}).waitFor();
  await page.getByRole("button",{name:"Upload",exact:true}).click();
  await page.getByText("Select a registered user from the suggestions.",{exact:true}).waitFor();
  await fill(undefined,["25100","25000","25000","25000"]);
  const beforeWrongTotal=apiCalls.filter(url=>url.endsWith("/api/manual-score/upload")).length;
  await page.getByRole("button",{name:"Upload",exact:true}).click();
  const totals=await page.getByTestId("manual-score-totals").innerText();
  assert(totals.includes("100100")&&totals.includes("100000")&&totals.includes("+100"));
  assert.equal(apiCalls.filter(url=>url.endsWith("/api/manual-score/upload")).length,beforeWrongTotal);
  await page.getByLabel("East Score",{exact:true}).fill("25000");
  await page.getByRole("button",{name:"CN",exact:true}).click();
  assert.equal(await page.getByRole("combobox",{name:"东风 注册名",exact:true}).inputValue(),"photo1");
  await page.getByRole("button",{name:"上传",exact:true}).waitFor();
  await page.getByRole("button",{name:"EN",exact:true}).click();
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#manual-player-east')?.value==='photo1');
  assert.equal(await page.getByLabel("North Score",{exact:true}).inputValue(),"25000");
  assert(!(await page.locator("body").innerText()).includes("photo-user-"));
  const loseAcknowledgement=async route=>{
    const reply=await route.fetch();assert(reply.ok());await route.abort("failed");await page.unroute("**/api/manual-score/upload",loseAcknowledgement);
  };
  await page.route("**/api/manual-score/upload",loseAcknowledgement);
  await page.getByRole("button",{name:"Upload",exact:true}).click();
  await page.getByText("Request did not complete. Check your connection and retry.",{exact:true}).waitFor();
  assert(await page.getByRole("combobox",{name:"East Registered Name",exact:true}).isDisabled());
  await page.reload();await page.getByRole("button",{name:"Upload",exact:true}).waitFor();
  await page.getByRole("button",{name:"Upload",exact:true}).click();
  await page.getByText("Score Saved Successfully",{exact:true}).waitFor();
  await page.getByText("Saved locally.",{exact:true}).waitFor();
  await page.getByText("External upload failed. Your local score is preserved.",{exact:true}).waitFor();
  await page.getByRole("button",{name:"Retry Upload",exact:true}).click();
  await page.getByText("External upload succeeded.",{exact:true}).waitFor();
  assert(!apiCalls.some(url=>url.includes("recognize_photo")||url.endsWith("/api/manual-score/preview")||url.endsWith("/api/manual-score/confirm")));
  const overflow=await page.evaluate(()=>[...document.querySelectorAll("body *")].filter(el=>el.getBoundingClientRect().right>innerWidth+1).slice(0,10).map(el=>[el.tagName,el.className,el.getBoundingClientRect().right]));assert.deepEqual(overflow,[]);
  assert(!(await page.locator("body").innerText()).includes("photo-user-"));
  // A confirmed score can be followed by another game with a fresh request.
  await page.getByRole("button",{name:"Record Another Game",exact:true}).click();
  await page.getByRole("combobox",{name:"East Registered Name",exact:true}).waitFor();
  assert.deepEqual(await page.locator('fieldset input').evaluateAll(nodes=>nodes.map(n=>n.value)),Array(8).fill(""));
  await fill(undefined,["35000","25000","25000","15000"]);
  await page.getByRole("button",{name:"Upload",exact:true}).click();
  await page.getByText("Score Saved Successfully",{exact:true}).waitFor();
  await page.getByText("External upload succeeded.",{exact:true}).waitFor();
  assert.equal(new Set(uploadedRequests.map(body=>body.request_id)).size,2);
  // Existing table partial roster must prefill by wind, not array order.
  assert((await context.request.post(base+"/api/sit?table=web&seat=west")).ok());
  await page.goto(base+"/manual-score?table=web");
  await page.waitForFunction(()=>document.querySelector('#manual-player-west')?.value==='photo1');
  assert.equal(await page.getByRole("combobox",{name:"East Registered Name",exact:true}).inputValue(),"");
  assert.equal(await page.getByLabel("West Score",{exact:true}).inputValue(),"");
  await context.request.post(base+"/api/logout");await page.reload();
  await page.getByRole("link",{name:"Log In",exact:true}).click();
  assert(new URL(page.url()).searchParams.get("redirect_url").includes("/manual-score?table=web"));
  await page.locator('form input[name="username"]').first().fill("photo1");
  await page.locator('form input[name="password"]').first().fill("photo-test-password");
  await page.getByRole("button",{name:"Log in",exact:true}).click();
  await page.waitForURL("**/manual-score?table=web");
  // A photo draft belongs to its original table and must not follow a table switch.
  for(const [id,seat] of [[2,"east"],[3,"south"],[4,"north"]]){
    const peer=await browser.newContext();
    assert((await peer.request.post(base+"/api/login",{data:{username:"photo"+id,password:"photo-test-password"}})).ok());
    assert((await peer.request.post(base+"/api/sit?table=web&seat="+seat)).ok());await peer.close();
  }
  const draftResponse=await context.request.post(base+"/api/submit_scores",{headers:{"Idempotency-Key":"photo-draft-switch"},data:{table:"web",scores:{bottom:"",right:"",top:"",left:""}}});
  assert(draftResponse.ok(),await draftResponse.text());const photoDraft=await draftResponse.json();
  await page.goto(base+"/?page=record&table=web&draft_id="+photoDraft.draft_id);
  await page.frameLocator("#record-game iframe").locator("#review").waitFor({state:"visible"});
  await page.getByRole("combobox",{name:"Select Table",exact:true}).selectOption("1");
  await page.waitForFunction(()=>document.querySelector("#record-game iframe")?.src.includes("table=1"));
  assert(!new URL(page.url()).searchParams.has("draft_id"));
  assert(!(await page.locator("#record-game iframe").getAttribute("src")).includes("draft_id"));
  assert.deepEqual(errors,[]);
  console.log("Manual upload: registered-name suggestions, client/server rule validation, single-action saving, lost-response recovery, local preservation and external retry, language, wind prefill, mobile and no OCR passed.");
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
