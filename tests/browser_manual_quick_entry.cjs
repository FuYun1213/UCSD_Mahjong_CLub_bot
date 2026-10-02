const assert=require('assert'),path=require('path'),fs=require('fs'),{chromium}=require('playwright');
const {prepare}=require('./browser_support.cjs'),base=process.env.NFC_TEST_URL;
(async()=>{
 const browser=await chromium.launch({...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{}),headless:true});
 const out=path.resolve('docs/manual-quick-entry-20261001');fs.mkdirSync(out,{recursive:true});
 try{
  const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  await prepare(context,base);
  await context.addInitScript(()=>{
   localStorage.setItem('mahjong_lang','CN');
   const viewport=new EventTarget();Object.assign(viewport,{width:390,height:844,offsetLeft:0,offsetTop:0});
   Object.defineProperty(window,'visualViewport',{value:viewport,configurable:true});
   window.setKeyboardViewport=(width,height,offsetTop=0)=>{
    Object.assign(viewport,{width,height,offsetTop});viewport.dispatchEvent(new Event('resize'));viewport.dispatchEvent(new Event('scroll'));
   };
  });
  const page=await context.newPage(),errors=[],uploads=[];page.setDefaultTimeout(15000);
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.url().endsWith('/api/manual-score/upload'))uploads.push(r.postDataJSON());});
  assert((await context.request.post(base+'/api/login',{data:{username:'photo8',password:'photo-test-password'}})).ok());
  await page.goto(base+'/manual-score');await page.locator('.manual-command-form').waitFor();
  const input=page.locator('#manual-command-input'),dock=page.locator('.manual-composer-dock');
  assert.equal(await dock.locator('input').count(),1);assert.equal(await dock.locator('[data-quick-field]').count(),8);
  await input.tap();
  await page.evaluate(()=>{
   window.originalCommandInput=document.querySelector('#manual-command-input');window.commandBlurCount=0;
   originalCommandInput.addEventListener('blur',()=>window.commandBlurCount++);setKeyboardViewport(390,490);
  });
  async function focused(field){
   await page.waitForFunction(key=>document.querySelector('.manual-composer-dock').dataset.activeField===key&&document.activeElement===window.originalCommandInput,field);
   assert(await input.evaluate(el=>el===window.originalCommandInput),'The same input must survive field changes');
  }
  async function geometry(bottom){
   await page.waitForFunction(edge=>Math.abs(document.querySelector('.manual-composer-dock').getBoundingClientRect().bottom-edge)<2,bottom);
   const rect=await dock.boundingBox();assert(rect.y>=0);assert(rect.x>=0);assert(rect.width<=await page.evaluate(()=>innerWidth));
  }
  async function suggestionsFit(){
   const menu=await dock.locator('[data-registered-options]').boundingBox(),bar=await dock.boundingBox();
   assert(menu.y>=await page.evaluate(()=>visualViewport.offsetTop)-1,'Suggestions must stay above the keyboard and inside the visible viewport');
   assert(menu.y+menu.height<=bar.y,'Suggestions must not cover field navigation');
  }
  await focused('players.east');await geometry(490);
  await input.fill('pho');await page.locator('[data-quick-field="players.south"]').tap();await focused('players.south');
  await input.fill('ph');await page.locator('[data-quick-field="players.east"]').tap();await focused('players.east');
  assert.equal(await input.inputValue(),'pho','Partially typed searches are retained per field');
  await input.evaluate(el=>el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,isComposing:true})));
  await focused('players.east');
  for(const [wind,index,points] of [['east',1,'35000'],['south',2,'28000'],['west',3,'43000'],['north',4,'6000']]){
   await focused('players.'+wind);await input.fill('photo'+index);
   await page.getByRole('option',{name:'photo'+index,exact:true}).waitFor();await suggestionsFit();
   await page.getByRole('option',{name:'photo'+index,exact:true}).tap();await focused('scores.'+wind);
   await input.fill(points);
   if(wind==='north'){
    await dock.getByRole('button',{name:'切换正负分',exact:true}).tap();assert.equal(await input.inputValue(),'-6000');
   }else await input.press('Enter');
  }
  assert.equal(await page.evaluate(()=>window.commandBlurCount),0,'Touch shortcuts and name selections must keep the keyboard focus');
  assert((await page.getByTestId('manual-score-totals').innerText()).includes('100000'));
  assert.equal(uploads.length,0,'Next never submits a score');
  await page.evaluate(()=>setKeyboardViewport(390,465,25));await geometry(490);
  await page.screenshot({path:path.join(out,'keyboard-edge-390.png')});
  await page.setViewportSize({width:320,height:700});await page.evaluate(()=>setKeyboardViewport(320,390));await geometry(390);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'320px page must fit');
  for(const field of ['scores.east','players.north','scores.north']){
   await page.locator('[data-quick-field="'+field+'"]').tap();await focused(field);
  }
  await page.setViewportSize({width:640,height:360});await page.evaluate(()=>setKeyboardViewport(640,210));await geometry(210);
  assert.equal(await dock.getAttribute('data-compact'),'true');
  await page.locator('[data-quick-field="players.west"]').scrollIntoViewIfNeeded();await page.locator('[data-quick-field="players.west"]').tap();await focused('players.west');
  await input.fill('photo');await page.getByRole('option',{name:'photo3',exact:true}).waitFor();await suggestionsFit();await page.getByRole('option',{name:'photo3',exact:true}).tap();await focused('scores.west');
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>setKeyboardViewport(390,490));await geometry(490);
  await dock.getByRole('button',{name:'完成',exact:true}).tap();
  await page.waitForFunction(()=>document.activeElement!==window.originalCommandInput);
  await page.evaluate(()=>setKeyboardViewport(390,844));
  await page.getByRole('button',{name:'普通表单',exact:true}).tap();
  assert.equal(await page.getByLabel('北风 分数',{exact:true}).inputValue(),'-6000');
  await page.getByRole('button',{name:'快捷输入',exact:true}).tap();
  await page.reload();await page.locator('.manual-command-form').waitFor();
  await page.waitForFunction(()=>document.querySelector('[data-quick-field="scores.north"] strong')?.textContent==='-6000');
  await page.evaluate(()=>{window.originalCommandInput=document.querySelector('#manual-command-input');});
  await page.locator('[data-quick-field="scores.north"]').tap();assert.equal(await input.inputValue(),'-6000');
  await dock.getByRole('button',{name:'完成',exact:true}).tap();
  // Missing fields focus the first error once; editing it must not jump to the next error.
  await page.locator('[data-quick-field="players.east"]').tap();
  await dock.getByRole('button',{name:'东风 注册名 · 清除选择',exact:true}).tap();
  await page.locator('[data-quick-field="players.south"]').tap();
  await dock.getByRole('button',{name:'南风 注册名 · 清除选择',exact:true}).tap();
  await dock.getByRole('button',{name:'完成',exact:true}).tap();
  await page.getByRole('button',{name:'上传',exact:true}).tap();await focused('players.east');
  await input.fill('photo1');await focused('players.east');
  await page.getByRole('option',{name:'photo1',exact:true}).tap();await focused('scores.east');
  await input.press('Enter');await focused('players.south');await input.fill('photo2');
  await page.getByRole('option',{name:'photo2',exact:true}).tap();await focused('scores.south');
  await dock.getByRole('button',{name:'完成',exact:true}).tap();assert.equal(uploads.length,0);
  await page.getByRole('button',{name:'上传',exact:true}).tap();await page.getByText('成绩保存成功',{exact:true}).waitFor();
  assert.equal(uploads.length,1);assert.deepEqual(Object.values(uploads[0].players),[1,2,3,4].map(i=>'photo-user-'+i));
  assert.deepEqual(Object.values(uploads[0].scores),[35000,28000,43000,-6000]);assert.equal(uploads[0].table_id,null);
  assert.deepEqual(errors,[]);
  console.log('Mobile touch switching retained one focused input; viewport resize/scroll, partial searches, auto-advance, negative points, narrow/landscape layout, validation, draft restore and one submission passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
