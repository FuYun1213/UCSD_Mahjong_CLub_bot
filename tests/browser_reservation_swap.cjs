/* Real two-context consent flow; only the temporary fixture accounts and clock are writable. */
const assert=require('assert'),fs=require('fs'),path=require('path'),{chromium}=require('playwright');
const {prepare,root}=require('./browser_support.cjs');
const base=process.env.NFC_TEST_URL,checks=[],output=path.join(root,'.local_seat_cards','v9');fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || undefined,headless:true});
 try{
  assert(base.startsWith('http://127.0.0.1:'));assert(process.env.SWAP_TEST_CLOCK&&process.env.SWAP_TEST_ACCOUNTS);
  const admin=await browser.newContext(),requester=await browser.newContext({viewport:{width:1280,height:960}}),target=await browser.newContext({viewport:{width:390,height:844}}),visitor=await browser.newContext();
  for(const context of [requester,target,visitor])await prepare(context,base);
  async function login(context,number){const response=await context.request.post(base+'/api/login',{data:{username:'photo'+number,password:'photo-test-password'}});assert(response.ok(),await response.text());}
  await login(admin,1);await login(requester,2);await login(target,3);await login(visitor,4);
  const a=await requester.newPage(),b=await target.newPage(),c=await visitor.newPage(),errors=[];
  for(const page of [a,b,c]){page.setDefaultTimeout(15000);page.on('pageerror',error=>errors.push(error.message));}
  const frame=page=>page.frameLocator('#record-game iframe'),card=(page,wind)=>frame(page).locator('[data-seat-card="'+wind+'"]');
  const dialog=page=>frame(page).locator('#seat-swap-dialog');
  async function actualFrame(page){return (await page.locator('#record-game iframe').elementHandle()).contentFrame();}
  async function open(page,table='web'){await page.goto(base+'/?page=record&table='+encodeURIComponent(table));await card(page,'east').waitFor();}
  async function state(page,wind,value){await (await actualFrame(page)).waitForFunction(({wind,value})=>document.querySelector('[data-seat-card="'+wind+'"]')?.dataset.seatState===value,{wind,value});}
  async function seat(context,wind){const response=await context.request.put(base+'/api/club-tables/web/my-seat',{data:{seat:wind}});assert(response.ok(),await response.text());}
  async function table(){const response=await admin.request.get(base+'/api/tables/web');assert(response.ok(),await response.text());return response.json();}
  async function reminderSeat(page,name,wind){await frame(page).locator('[data-reservation-reminder="browser-near"] [data-reservation-participant]').filter({hasText:name}).and(frame(page).locator('[data-seat="'+wind+'"]')).waitFor();}
  async function send(){await card(a,(await table()).seats.east==='photo-user-3'?'east':'south').click();await dialog(a).waitFor({state:'visible'});await frame(a).locator('#swap-send').click();await dialog(a).waitFor({state:'hidden'});await dialog(b).waitFor({state:'visible'});}
  const check=text=>{checks.push(text);console.log('PASS: '+text);};

  await open(a);await state(a,'east','empty');
  const reminders=frame(a).locator('#reservation-reminders');await reminders.waitFor({state:'visible'});
  await frame(a).locator('[data-reservation-reminder="browser-next"]').waitFor();
  assert.equal(await frame(a).locator('[data-reservation-reminder]').count(),2);
  assert.deepEqual(await frame(a).locator('[data-reservation-reminder]').evaluateAll(nodes=>nodes.map(node=>node.dataset.reservationReminder)),['browser-near','browser-next']);
  const reminderText=await reminders.innerText();assert(reminderText.includes('photo2')&&reminderText.includes('photo3')&&reminderText.includes('photo4'));
  assert(!reminderText.includes('old snapshot')&&!reminderText.includes('photo-user-')&&!reminderText.includes('photo5')&&!reminderText.includes('photo6')&&!reminderText.includes('photo7'));
  assert(await reminders.evaluate(node=>Boolean(node.nextElementSibling?.querySelector('#players'))));
  check('only active reservations within one hour appear above the lower table; groups use current registered names without IDs');
  await frame(a).locator('[data-reservation-reminder="browser-near"] > summary').click();
  await a.waitForTimeout(2200);assert.equal(await frame(a).locator('[data-reservation-reminder="browser-near"]').getAttribute('open'),null);
  await frame(a).locator('[data-reservation-reminder="browser-near"] > summary').click();
  check('reservation details remain collapsed across background refreshes');

  await card(a,'east').click();await state(a,'east','current');await seat(target,'south');
  await open(b);await state(b,'south','current');await state(a,'south','occupied');
  await frame(a).locator('[data-reservation-reminder="browser-near"][data-all-seated="true"]').waitFor();
  await reminderSeat(a,'photo2','east');await reminderSeat(a,'photo3','south');
  assert.equal(await frame(a).locator('[data-reservation-reminder="browser-next"] [data-seated="false"]').count(),1);
  await a.screenshot({path:path.join(output,'fixture-reminders.png'),fullPage:true});
  check('joining updates participant winds and All Seated while unrelated participants remain waiting');
  const readPath='**/api/tables/web/seat-swap-requests';let releaseOld,oldReadReady;
  const oldGate=new Promise(resolve=>{releaseOld=resolve;}),oldReady=new Promise(resolve=>{oldReadReady=resolve;});
  const holdOld=async route=>{const snapshot=await route.fetch();oldReadReady();await oldGate;await route.fulfill({response:snapshot});};
  await a.route(readPath,holdOld);await oldReady;
  await card(a,'west').click();await state(a,'west','current');
  const oldResponse=a.waitForResponse(response=>response.url().endsWith('/api/tables/web/seat-swap-requests'));releaseOld();await oldResponse;await a.unroute(readPath);
  await state(a,'west','current');assert.equal(await card(a,'east').getAttribute('data-seat-state'),'empty');
  await card(a,'east').click();await state(a,'east','current');
  check('a delayed table read cannot roll back a newer successful seat change');
  await open(c);await state(c,'east','occupied');assert(await card(c,'east').isDisabled());
  check('a user who has not joined cannot request a swap from an occupied card');

  await card(a,'south').focus();await card(a,'south').press('Enter');await dialog(a).waitFor({state:'visible'});
  const confirmation=await dialog(a).innerText();assert(confirmation.includes('photo2')&&confirmation.includes('photo3')&&confirmation.includes('East')&&confirmation.includes('South'));
  assert(!confirmation.includes('photo-user-'));await a.screenshot({path:path.join(output,'fixture-swap-confirm.png'),fullPage:true});
  await frame(a).locator('#swap-back').click();await dialog(a).waitFor({state:'hidden'});
  assert.equal((await table()).seats.east,'photo-user-2');assert.equal((await table()).seats.south,'photo-user-3');
  check('keyboard opens a named before/after confirmation; cancelling leaves both seats unchanged');
  await send();assert(await card(a,'south').isDisabled());
  assert.equal((await table()).seats.east,'photo-user-2');assert.equal((await table()).seats.south,'photo-user-3');
  await frame(b).locator('#swap-decline').click();await dialog(b).waitFor({state:'hidden'});
  await frame(a).locator('#swap-status').filter({hasText:/declined/i}).waitFor();
  assert.equal((await table()).seats.east,'photo-user-2');assert.equal((await table()).seats.south,'photo-user-3');
  check('pending blocks duplicate requests and recipient refusal changes neither seat');

  await send();
  const accounts=JSON.parse(fs.readFileSync(process.env.SWAP_TEST_ACCOUNTS,'utf8'));accounts.users.photo3.name='North Star';fs.writeFileSync(process.env.SWAP_TEST_ACCOUNTS,JSON.stringify(accounts));
  await frame(a).locator('#reservation-reminders').filter({hasText:'North Star'}).waitFor();
  await frame(b).locator('#swap-target-change').filter({hasText:'North Star'}).waitFor();
  assert(!(await frame(b).locator('#seat-swap-dialog').innerText()).includes('photo-user-'));
  const mobile=await dialog(b).evaluate(node=>({width:node.getBoundingClientRect().width,right:node.getBoundingClientRect().right,viewport:innerWidth}));assert(mobile.width<=mobile.viewport&&mobile.right<=mobile.viewport);
  await b.screenshot({path:path.join(output,'fixture-swap-incoming-mobile.png'),fullPage:true});
  await frame(b).locator('#swap-accept').press('Enter');await dialog(b).waitFor({state:'hidden'});
  await state(a,'south','current');await state(b,'east','current');await reminderSeat(a,'photo2','south');await reminderSeat(b,'North Star','east');
  const accepted=await table();assert.equal(accepted.seats.east,'photo-user-3');assert.equal(accepted.seats.south,'photo-user-2');
  assert.equal(Object.values(accepted.seats).filter(Boolean).length,2);
  await a.screenshot({path:path.join(output,'fixture-swap-accepted.png'),fullPage:true});
  check('only the recipient acceptance atomically swaps two seats; live names and reservation winds refresh in both sessions on mobile and keyboard');

  await send();fs.writeFileSync(process.env.SWAP_TEST_CLOCK,'61');
  await dialog(b).waitFor({state:'hidden'});await frame(a).locator('#swap-status').filter({hasText:/expired/i}).waitFor();
  assert.equal((await table()).seats.east,'photo-user-3');assert.equal((await table()).seats.south,'photo-user-2');
  check('server expiry automatically closes the recipient prompt without swapping seats');

  await send();await card(a,'west').click();await state(a,'west','current');await dialog(b).waitFor({state:'hidden'});
  await frame(b).locator('#swap-status').filter({hasText:/no longer valid/i}).waitFor();await reminderSeat(a,'photo2','west');
  check('moving to an empty seat invalidates the pending request and updates reminder attendance');
  await card(a,'east').click();await frame(a).locator('#swap-send').click();await dialog(b).waitFor({state:'visible'});
  await seat(visitor,'south');const fourth=await browser.newContext();await login(fourth,5);await seat(fourth,'north');
  await dialog(b).waitFor({state:'hidden'});await frame(b).locator('#swap-status').filter({hasText:/no longer valid/i}).waitFor();
  await a.waitForTimeout(2200);assert(await card(a,'east').isDisabled());assert((await table()).started_at);
  check('starting the game invalidates pending requests and disables further swaps');

  const cancel=await admin.request.post(base+'/api/table-reservations/browser-next',{data:{status:'cancelled',version:1,request_id:'browser-cancel-next'}});assert(cancel.ok(),await cancel.text());
  await frame(a).locator('[data-reservation-reminder="browser-next"]').waitFor({state:'detached'});
  const slowPath='**/api/tables/A/seat-swap-requests';let slowReads=0;await c.route(slowPath,async route=>{slowReads++;await new Promise(resolve=>setTimeout(resolve,2600));await route.continue();});
  await open(c,'A');await state(c,'east','empty');assert.equal(slowReads,1,'polling must reuse an in-flight read rather than starving slow responses');await c.unroute(slowPath);assert(await frame(c).locator('#reservation-reminders').isHidden());
  check('cancellation removes its reminder; empty tables hide the area, and a slow table response is not starved by faster polling');
  await a.getByRole('button',{name:'CN',exact:true}).click();await frame(a).locator('#reservation-reminders').filter({hasText:'全部已入座'}).waitFor();
  await a.getByRole('button',{name:'EN',exact:true}).click();assert.equal(await frame(a).locator('#players [data-seat-card]').count(),4);
  assert.equal(await a.locator('[data-table-member-controls],[data-main-seat-button]').count(),0);assert.equal(await frame(a).locator('input[type="password"],#login-form').count(),0);
  assert.deepEqual(errors,[]);check('global language keeps the same live seats and reminders without restoring the old member modal or a second login');
  await a.screenshot({path:path.join(output,'fixture-desktop.png'),fullPage:true});await b.screenshot({path:path.join(output,'fixture-mobile.png'),fullPage:true});
  fs.writeFileSync(path.join(output,'browser-test.json'),JSON.stringify({passed:true,checks,errors},null,2));
  console.log('Reservation and consent swap passed: '+checks.length+' checks.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
