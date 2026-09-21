
const fs=require("fs"),path=require("path"),assert=require("assert"),{chromium,request}=require("playwright");
const {prepare,root}=require("./browser_support.cjs"),base=process.env.NFC_TEST_URL;
const cases=JSON.parse(fs.readFileSync(path.join(__dirname,"fixtures/displays/expected.json"),"utf8"));
(async()=>{
 const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || undefined,headless:true}),clients=[];
 try{
  for(let i=1;i<=4;i++){
   const c=await request.newContext({baseURL:base});
   assert((await c.post("/api/login",{data:{username:"photo"+i,password:"photo-test-password"}})).ok());clients.push(c);
  }
  const context=await browser.newContext({viewport:{width:390,height:844}});await prepare(context,base);
  await context.request.post(base+"/api/login",{data:{username:"photo2",password:"photo-test-password"}});
  const page=await context.newPage(),errors=[];page.on("pageerror",e=>errors.push(e.message));page.on("dialog",d=>d.accept());
  await page.goto(base+"/");await page.evaluate(()=>localStorage.setItem("mahjong_lang","CN"));
  for(let index=0;index<cases.length;index++){
   const table="browser-"+index,fixture=cases[index];
   for(const [i,seat]of [[0,"east"],[1,"south"],[2,"west"],[3,"north"]])
    assert((await clients[i].post("/api/sit?table="+table+"&seat="+seat)).ok());
   await page.goto(base+"/?page=record&table="+table);
   const frame=page.frameLocator("#record-game iframe");
   await frame.locator("#players").getByText("photo2",{exact:true}).waitFor();
   assert.equal(await frame.locator("#players .player").count(),4);
   assert.equal(await frame.locator("#language").count(),0);assert.equal(await frame.locator("#qr-download").count(),0);
   const chooser=page.waitForEvent("filechooser");await frame.locator("#photo").click();
   await(await chooser).setFiles(path.join(__dirname,"fixtures/displays",fixture.file));
   await frame.getByRole("button",{name:"识别并核对",exact:true}).click();
   await frame.locator("#review").waitFor({state:"visible"});
   const inputs=await frame.locator("#score-fields input").evaluateAll(nodes=>nodes.map(n=>n.value));
   await page.getByRole("button",{name:"EN",exact:true}).click();
   assert.deepEqual(await frame.locator("#score-fields input").evaluateAll(nodes=>nodes.map(n=>n.value)),inputs);
   await page.getByRole("button",{name:"CN",exact:true}).click();
   await frame.getByRole("button",{name:"确认并结算",exact:true}).click();
   await frame.getByText("结算完成，座位已清空",{exact:true}).waitFor();
   const output=await frame.locator("#result-text").innerText();assert(!/Round [0-9]|第.*轮/.test(output));
   for(const value of Object.values(fixture.scores))assert(output.includes("："+Number(value)*fixture.multiplier+" 点"),output);
   assert(output.includes(fixture.multiplier===100?"×100":"完整点数"));
   assert(await page.frames().find(f=>f.url().includes("/score?")).evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }
  // Keep all four real OCR fixtures unchanged; simulate only a later name
  // directory refresh for the already saved final result.
  const finalTable="browser-"+(cases.length-1),photoFrame=page.frames().find(f=>f.url().includes("/score?"));
  const cachedBefore=await photoFrame.evaluate(table=>JSON.parse(localStorage.getItem("score-result-"+table)),finalTable);
  let nameRefreshes=0;
  await context.route("**/api/registered-users?*",async route=>{
   const url=new URL(route.request().url());if(!url.searchParams.has("ids"))return route.continue();
   const response=await route.fetch();assert(response.ok());const data=await response.json();
   data.users=data.users.map(user=>user.id==="photo-user-1"?{...user,name:"photo1 renamed"}:user);nameRefreshes++;
   await route.fulfill({response,json:data});
  });
  await photoFrame.evaluate(()=>refreshSync());
  assert((await page.frameLocator("#record-game iframe").locator("#result-text").innerText()).includes("photo1 renamed"));
  const cachedAfter=await photoFrame.evaluate(table=>JSON.parse(localStorage.getItem("score-result-"+table)),finalTable);
  assert.equal(cachedAfter.result.players.east.user.id,cachedBefore.result.players.east.user.id);
  assert.equal(cachedAfter.result.players.east.user.name,"photo1 renamed");
  assert.deepEqual(Object.values(cachedAfter.result.players).map(p=>p.final_points),Object.values(cachedBefore.result.players).map(p=>p.final_points));
  assert.equal(cachedAfter.result.match_id,cachedBefore.result.match_id);
  await photoFrame.evaluate(table=>{
   const cached=JSON.parse(localStorage.getItem("score-result-"+table));cached.result.players.east.user.name="stale cached name";
   localStorage.setItem("score-result-"+table,JSON.stringify(cached));
  },finalTable);
  await page.reload();
  await page.frameLocator("#record-game iframe").getByText(/photo1 renamed/).waitFor();
  const refreshedText=await page.frameLocator("#record-game iframe").locator("#result-text").innerText();
  assert(!refreshedText.includes("stale cached name")&&!refreshedText.includes("photo-user-"));
  assert(nameRefreshes>=2);
  const reduced=await page.frames().find(f=>f.url().includes("/score?")).evaluate(async()=>{
   const c=document.createElement("canvas");c.width=3000;c.height=2000;c.getContext("2d").fillRect(0,0,3000,2000);
   const b=await new Promise(r=>c.toBlob(r,"image/png")),resized=await shrinkPhoto(new File([b],"large.png",{type:"image/png"})),image=await createImageBitmap(resized);
   return [image.width,image.height,resized.type];
  });
  assert.deepEqual(reduced,[1920,1280,"image/jpeg"]);assert.deepEqual(errors,[]);
  console.log("Four real photo fixtures passed: camera, OCR, review, global language without data loss, settlement, refreshed registered names in cached results, ordinary page without rounds, and mobile width.");
 }finally{for(const c of clients)await c.dispose();await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
