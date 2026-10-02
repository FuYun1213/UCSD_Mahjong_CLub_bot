const assert=require('assert'),fs=require('fs'),path=require('path'),{chromium}=require('playwright');
const {prepare}=require('./browser_support.cjs'),base=process.env.NFC_TEST_URL;
(async()=>{
 const browser=await chromium.launch({...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{}),headless:true});
 const output=path.resolve('docs/seat-actions-20261002');fs.mkdirSync(output,{recursive:true});
 try{
  assert(base.startsWith('http://127.0.0.1:'));
  const visitor=await browser.newContext({viewport:{width:390,height:844},hasTouch:true}),a=await browser.newContext({viewport:{width:390,height:844},hasTouch:true}),b=await browser.newContext({viewport:{width:390,height:844},hasTouch:true}),publicContext=await browser.newContext();
  const errors=[];
  for(const context of [visitor,a,b,publicContext]){await prepare(context,base);await context.addInitScript(()=>localStorage.setItem('mahjong_lang','CN'));}
  async function login(context,n){const r=await context.request.post(base+'/api/login',{data:{username:'photo'+n,password:'photo-test-password'}});assert(r.ok(),await r.text());}
  await login(visitor,8);await login(a,1);await login(b,2);
  const p=await visitor.newPage(),pa=await a.newPage(),pb=await b.newPage(),publicPage=await publicContext.newPage();
  for(const page of [p,pa,pb,publicPage]){page.setDefaultTimeout(20000);page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());}
  const list=await(await a.request.get(base+'/api/club-tables')).json(),id=list.tables.find(t=>t.score_table_id==='web').id;
  const card=page=>page.locator('[data-club-table="'+id+'"]'),frame=page=>page.frameLocator('#record-game iframe');
  async function seat(context,wind){const r=await context.request.put(base+'/api/club-tables/'+id+'/my-seat',{data:{seat:wind}});assert(r.ok(),await r.text());}
  async function home(page){await page.goto(base+'/');await card(page).waitFor();}
  async function scoring(page){await page.goto(base+'/?page=record&table=web');await frame(page).locator('#players [data-seat-card]').first().waitFor();}
  async function roster(){return (await(await a.request.get(base+'/api/club-tables/'+id)).json());}
  async function occupied(page,wind,name){await card(page).locator('[data-table-seat="'+wind+'"][data-seat-state="occupied"]').getByText(name,{exact:true}).waitFor();}
  await publicPage.goto(base+'/login');await publicPage.getByRole('combobox',{name:'玩家姓名或 ID',exact:true}).waitFor();
  assert.equal(await publicPage.locator('a[href="/player-history"]').count(),0);
  await publicPage.goto(base+'/register');await publicPage.locator('[data-registration-page]').waitFor();
  assert(!(await publicPage.locator('body').innerText()).includes('此环境暂未启用 Discord'));
  assert.equal(await publicPage.locator('[data-registration-picker]').count(),0);
  await seat(a,'east');await seat(b,'south');await home(p);
  assert(!(await p.locator('body').innerText()).includes('预约你的下一局，也可以帮同伴登分'));
  await card(p).locator('[data-lobby-seat-action="east"]').tap();
  let modal=p.getByRole('dialog');await modal.waitFor();assert(await modal.locator('[data-lobby-swap]').isDisabled());assert(!await modal.locator('[data-lobby-remove]').isDisabled());
  await p.screenshot({path:path.join(output,'outsider-seat-actions-mobile.png'),fullPage:false});
  await modal.locator('[data-lobby-remove]').tap();await modal.waitFor({state:'hidden'});await card(p).locator('[data-lobby-join-seat="east"]').waitFor();
  assert.equal((await roster()).player_count,1);
  await scoring(p);await frame(p).locator('#seat-section').waitFor();
  assert(await frame(p).locator('#score-target-section').evaluate(el=>Boolean(el.compareDocumentPosition(document.querySelector('#seat-section'))&Node.DOCUMENT_POSITION_FOLLOWING)));
  assert.equal(await frame(p).locator('#actual-finish,#actual-finish-details,#record-finish').count(),0);
  await frame(p).locator('[data-seat-card="south"]').tap();await frame(p).locator('#seat-action-dialog[open]').waitFor();
  assert(await frame(p).locator('#seat-action-swap').isDisabled());assert(!await frame(p).locator('#seat-action-remove').isDisabled());
  await frame(p).locator('#seat-action-remove').tap();await frame(p).locator('[data-seat-card="south"][data-seat-state="empty"]').waitFor();assert.equal((await roster()).player_count,0);
  await p.screenshot({path:path.join(output,'final-score-above-seats-mobile.png'),fullPage:true});
  await seat(a,'east');await seat(b,'south');await home(pa);await scoring(pb);
  await occupied(pa,'south','photo2');await card(pa).locator('[data-lobby-seat-action="south"]').tap();
  modal=pa.getByRole('dialog');await modal.locator('[data-lobby-swap]').tap();await modal.getByRole('button',{name:'发送请求',exact:true}).tap();
  await modal.waitFor({state:'hidden'});await frame(pb).locator('#seat-swap-dialog[open]').waitFor();
  assert.equal((await roster()).members.find(m=>m.user_id==='photo-user-1').seat,'east','Sending must not swap before consent');
  await frame(pb).locator('#swap-accept').tap();await frame(pb).locator('[data-seat-card="east"][data-seat-state="current"]').waitFor();await occupied(pa,'east','photo2');await occupied(pa,'south','photo1');
  // Send back from the scoring page and reject on the homepage first.
  async function sendBack(){await frame(pb).locator('[data-seat-card="south"]').tap();await frame(pb).locator('#seat-action-swap').tap();await frame(pb).locator('#swap-send').tap();await card(pa).getByRole('button',{name:'收到换座请求',exact:true}).waitFor();await card(pa).getByRole('button',{name:'收到换座请求',exact:true}).tap();await pa.getByRole('dialog').waitFor();}
  await sendBack();await pa.getByRole('dialog').getByRole('button',{name:'拒绝',exact:true}).tap();await pa.getByRole('dialog').waitFor({state:'hidden'});await frame(pb).locator('#swap-status').filter({hasText:'已被拒绝'}).waitFor();
  assert.equal((await roster()).members.find(m=>m.user_id==='photo-user-1').seat,'south');
  await sendBack();assert.equal(await pa.getByRole('dialog').getByRole('alert').count(),0,'A new request must not display the previous rejection');await pa.screenshot({path:path.join(output,'swap-incoming-mobile.png'),fullPage:false});
  await pa.getByRole('dialog').getByRole('button',{name:'同意换座',exact:true}).tap();await occupied(pa,'east','photo1');await frame(pb).locator('[data-seat-card="south"][data-seat-state="current"]').waitFor();
  // A game in progress retains the existing cancellation and score protections.
  const c=await browser.newContext(),d=await browser.newContext();await login(c,3);await login(d,4);await seat(c,'west');await seat(d,'north');await home(p);
  await card(p).locator('[data-lobby-seat-action="east"]').tap();assert(await p.getByRole('dialog').locator('[data-lobby-remove]').isDisabled());
  const denied=await visitor.request.post(base+'/api/club-tables/'+id+'/seats/photo-user-1/remove',{data:{match_id:(await roster()).current_match_id,seat:'east'}});assert.equal(denied.status(),409);
  await p.getByRole('dialog').getByRole('button',{name:'关闭',exact:true}).tap();await home(pa);await card(pa).locator('[data-lobby-seat-action="east"]').tap();await card(pa).locator('[data-lobby-join-seat="east"]').waitFor();assert.equal((await roster()).player_count,0);
  await card(pa).locator('[data-lobby-join-seat="north"]').tap();await occupied(pa,'north','photo1');await card(pa).locator('[data-lobby-seat-action="north"]').tap();await card(pa).locator('[data-lobby-join-seat="north"]').waitFor();assert.equal((await roster()).player_count,0);
  for(const width of [320,390,768]){await pa.setViewportSize({width,height:844});assert(await pa.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  const newAccount=await publicContext.request.post(base+'/api/register',{data:{username:'Fresh Mobile Member'}});assert(newAccount.ok(),await newAccount.text());assert((await(await publicContext.request.get(base+'/api/session')).json()).user);
  assert.deepEqual(errors,[]);
  console.log('Homepage and scoring-page swaps synchronize in both directions with consent and rejection; outsiders remove players on both pages; started-game safety, cancellation, own-seat leaving, mobile layout, reordered scoring, removed entry points, existing login and new registration passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
