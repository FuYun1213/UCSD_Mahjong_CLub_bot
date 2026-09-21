const assert=require('assert'),{chromium}=require('playwright'),{prepare}=require('./browser_support.cjs');
const base=process.env.NFC_TEST_URL,tid=process.env.V10_TID;
(async()=>{const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || undefined,headless:true});try{
 const context=await browser.newContext();await prepare(context,base);
 const login=await context.request.post(base+'/api/login',{data:{username:'photo1',password:'photo-test-password'}});assert(login.ok());
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 await page.goto(base+'/manual-score?tournament='+tid);
 for(let i=0;i<4;i++){
  await page.getByRole('combobox').nth(i).fill('photo'+(i+1));
  await page.getByRole('option',{name:'photo'+(i+1),exact:true}).click();
  await page.getByRole('spinbutton').nth(i).fill(String([40000,30000,20000,10000][i]));
 }
 await page.getByRole('button',{name:'Preview calculation',exact:true}).click();
 let interrupted=false,requestId;
 await page.route('**/api/tournaments/'+tid+'/actions',async route=>{
  const body=route.request().postDataJSON();
  if(body.action==='manual_game'&&!interrupted){
   interrupted=true;requestId=body.data.request_id;
   const committed=await route.fetch();assert(committed.ok(),await committed.text());await route.abort('connectionreset');
  }else{assert.equal(body.data.request_id,requestId);await route.continue();}
 });
 await page.getByRole('button',{name:'Confirm and save game',exact:true}).click();
 await page.getByRole('status').last().waitFor();
 assert(interrupted);assert(await page.getByRole('spinbutton').first().isDisabled());
 const get=async()=>(await context.request.get(base+'/api/tournaments/'+tid+'/admin')).json();
 assert.equal((await get()).rounds.length,1);
 await page.reload();await page.getByText('An earlier save needs confirmation.',{exact:false}).waitFor();
 assert.equal(await page.getByRole('spinbutton').first().inputValue(),'40000');assert(await page.getByRole('spinbutton').first().isDisabled());
 await page.getByRole('button',{name:'Preview calculation',exact:true}).click();
 await page.getByRole('button',{name:'Confirm and save game',exact:true}).click();
 await page.getByText('Confirmed game saved. Standings are updated.',{exact:true}).waitFor();
 const state=await get();assert.equal(state.rounds.length,1);assert.equal(state.standings.find(p=>p.name==='photo1').score,7);
 assert.equal(await page.evaluate(()=>Object.keys(sessionStorage).filter(k=>k.startsWith('tournament-manual-pending:')).length),0);
 assert.deepEqual(errors,[]);console.log('PASS: server commit followed by lost response, disabled edits, reload recovery, same request ID, exactly one game');
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
