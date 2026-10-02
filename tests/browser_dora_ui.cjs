const assert=require("assert"),path=require("path"),fs=require("fs"),{chromium}=require("playwright");
const {prepare}=require("./browser_support.cjs"),base=process.env.NFC_TEST_URL;
(async()=>{
 const browser=await chromium.launch({...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{}),headless:true});
 const out=path.resolve("docs/dora-ui-20261001");fs.mkdirSync(out,{recursive:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1050},hasTouch:true});await prepare(context,base);
  await context.addInitScript(()=>localStorage.setItem("mahjong_lang","CN"));
  const page=await context.newPage(),errors=[],uploads=[];page.setDefaultTimeout(15000);
  page.on("pageerror",e=>errors.push(e.message));page.on("request",r=>{if(r.url().endsWith("/api/manual-score/upload"))uploads.push(r.postDataJSON());});
  page.on("dialog",dialog=>dialog.accept());
  assert((await context.request.post(base+"/api/login",{data:{username:"photo8",password:"photo-test-password"}})).ok());
  const tableId=(await(await context.request.get(base+"/api/club-tables")).json()).tables.find(t=>t.score_table_id==="web").id;
  await page.goto(base+"/");const table=page.locator('[data-club-table="'+tableId+'"]');await table.waitFor();
  assert(await page.locator('.club-personal-details').evaluate(el=>el.open),'Home stats should be expanded on arrival');
  assert.equal(await page.locator('.club-table-manage').count(),0);
  assert.equal(await page.locator('.club-live-tables [data-table-member-controls]').count(),0);
  assert(await page.locator('.club-sidebar img').evaluate(img=>img.complete&&img.naturalWidth>0));
  await page.screenshot({path:path.join(out,"lobby-desktop.png"),fullPage:false});
  let releaseJoin;const pendingJoin=new Promise(resolve=>releaseJoin=resolve),seatWrites=[];
  await page.route('**/api/club-tables/'+tableId+'/my-seat',async route=>{
   seatWrites.push(route.request().postDataJSON());if(seatWrites.length===1)await pendingJoin;await route.continue();
  });
  await table.locator('[data-lobby-join-seat="east"]').click();
  await page.waitForFunction(id=>Array.from(document.querySelectorAll('[data-club-table="'+id+'"] [data-lobby-join-seat]')).every(button=>button.disabled),tableId);
  await table.locator('[data-lobby-join-seat="east"]').evaluate(button=>button.click());
  assert.equal(seatWrites.length,1,'Repeated clicks must not send duplicate seat requests');releaseJoin();
  await table.locator('[data-table-seat="east"][data-seat-state="occupied"]').getByText('photo8',{exact:true}).waitFor();
  let roster=await(await context.request.get(base+"/api/club-tables/"+tableId)).json();
  assert.equal(roster.player_count,1);assert.equal(roster.members[0].user_id,'photo-user-8');assert.equal(roster.members[0].seat,'east');
  assert.equal(await page.getByRole('dialog').count(),0,'An empty seat should join without a separate dialog');
  await page.setViewportSize({width:390,height:844});
  await table.locator('[data-lobby-join-seat="west"]').tap();
  await table.locator('[data-table-seat="west"][data-seat-state="occupied"]').getByText('photo8',{exact:true}).waitFor();
  roster=await(await context.request.get(base+'/api/club-tables/'+tableId)).json();
  assert.equal(roster.player_count,1);assert.equal(roster.members[0].seat,'west');
  // A seat claimed after the last poll must be rejected and refreshed, retaining our own seat.
  const other=await browser.newContext();
  assert((await other.request.post(base+'/api/login',{data:{username:'photo1',password:'photo-test-password'}})).ok());
  assert((await other.request.put(base+'/api/club-tables/'+tableId+'/my-seat',{data:{seat:'south',match_id:roster.current_match_id}})).ok());
  await table.locator('[data-lobby-join-seat="south"]').tap();
  await table.locator('[data-table-seat="south"][data-seat-state="occupied"]').getByText('photo1',{exact:true}).waitFor();
  await table.getByRole('status').waitFor();
  roster=await(await context.request.get(base+'/api/club-tables/'+tableId)).json();
  assert.equal(roster.members.find(m=>m.user_id==='photo-user-8').seat,'west');assert.equal(roster.player_count,2);
  const otherTable=(await(await context.request.get(base+'/api/club-tables')).json()).tables.find(t=>t.id!==tableId&&!t.tournament_id&&!t.started_at);
  const otherCard=page.locator('[data-club-table="'+otherTable.id+'"]');await otherCard.locator('[data-lobby-join-seat="east"]').tap();await otherCard.getByRole('status').waitFor();
  assert(!(await(await context.request.get(base+'/api/club-tables/'+otherTable.id)).json()).members.some(m=>m.user_id==='photo-user-8'));
  assert((await other.request.post(base+'/api/club-tables/'+tableId+'/leave',{data:{}})).ok());await other.close();
  assert((await context.request.post(base+'/api/club-tables/'+tableId+'/leave',{data:{}})).ok());
  await page.reload();await table.waitFor();assert(await page.locator('.club-personal-details').evaluate(el=>el.open));
  for(const width of [320,390,768]){
   await page.setViewportSize({width,height:844});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),"Lobby overflow at "+width);
  }
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,"lobby-mobile.png"),fullPage:false});
  await page.getByRole("button",{name:"手动登分",exact:true}).click();await page.locator(".manual-command-form").waitFor();
  assert.equal(await page.locator(".manual-composer-dock input").count(),1);
  assert.equal(await page.locator("[data-quick-field]").count(),8);
  await page.getByRole("button",{name:"普通表单",exact:true}).click();
  assert.equal(await page.locator("fieldset input").count(),8);
  assert.equal(await page.locator('input[type="file"]').count(),0);
  const winds=["东风","南风","西风","北风"],scores=["35000","28000","43000","-6000"];
  for(let i=0;i<4;i++){
   await page.getByRole("combobox",{name:winds[i]+" 注册名",exact:true}).fill("photo"+(i+1));
   await page.getByRole("option",{name:"photo"+(i+1),exact:true}).click();
   await page.getByLabel(winds[i]+" 分数",{exact:true}).fill(scores[i]);
  }
  await page.getByRole("button",{name:"普通表单",exact:true}).click();
  assert.equal(await page.getByLabel("北风 分数",{exact:true}).inputValue(),"-6000");
  await page.getByRole("button",{name:"快捷输入",exact:true}).click();
  assert.equal(await page.locator("#manual-command-input").inputValue(),"photo1");
  await page.getByRole("button",{name:"普通表单",exact:true}).click();
  await page.getByLabel("北风 分数",{exact:true}).fill("-5900");await page.getByRole("button",{name:"上传",exact:true}).click();
  assert.equal(uploads.length,0);assert((await page.getByTestId("manual-score-totals").innerText()).includes("+100"));
  await page.getByLabel("北风 分数",{exact:true}).fill("-6000");
  for(const width of [320,390,768,1440]){
   await page.setViewportSize({width,height:1050});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),"Score overflow at "+width);
  }
  await page.setViewportSize({width:390,height:844});await page.locator(".mobile-tabbar").waitFor();await page.getByRole("button",{name:"快捷输入",exact:true}).click();await page.screenshot({path:path.join(out,"manual-template-mobile.png"),fullPage:true});
  await page.getByRole("button",{name:"上传",exact:true}).click();await page.getByText("成绩保存成功",{exact:true}).waitFor();
  assert.equal(uploads.length,1);assert.equal(uploads[0].table_id,null);assert.deepEqual(Object.values(uploads[0].players),["photo-user-1","photo-user-2","photo-user-3","photo-user-4"]);
  await page.screenshot({path:path.join(out,"manual-saved-mobile.png"),fullPage:false});
  assert.deepEqual(errors,[]);console.log("Default-expanded home stats, direct desktop/mobile vacant-seat joins, safe seat moves, repeated-click protection, occupied/other-table rejection, no folded member controls, score entry and one standalone submission passed.");
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
