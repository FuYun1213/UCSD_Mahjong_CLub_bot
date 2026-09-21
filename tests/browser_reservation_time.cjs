const assert=require("node:assert/strict"),{chromium}=require("playwright"),{prepare}=require("./browser_support.cjs");
const base=process.env.NFC_TEST_URL;
(async()=>{
 const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || undefined,headless:true});
 try{
  const context=await browser.newContext({timezoneId:"Asia/Tokyo"});await prepare(context,base);
  assert((await context.request.post(base+"/api/login",{data:{username:"photo1",password:"photo-test-password"}})).ok());
  const response=await context.request.post(base+"/api/admin/club-tables",{data:{number:76,request_id:"reservation-default-browser"}});
  assert(response.ok(),await response.text());const table=await response.json();
  const expected="2027-01-01T08:00:00.000+00:00";
  const page=await context.newPage(),errors=[];page.setDefaultTimeout(15000);page.on("pageerror",error=>errors.push(error.message));
  const form=page.locator("[data-reservation-form]"),field=name=>form.getByLabel(name,{exact:true});
  const url=base+"/reservations?table="+table.id;
  await page.goto(url);
  await page.waitForFunction(()=>document.querySelector('input[aria-label="Time"]')?.value==="00:00");
  assert.equal(await field("Month").inputValue(),"1");assert.equal(await field("Day").inputValue(),"1");
  assert.equal(await form.locator('input[type="date"],input[type="datetime-local"],input[aria-label*="Year"]').count(),0);
  assert((await form.innerText()).includes("America/Los_Angeles"));
  // The initial UTC default retains the next year even in an unrelated browser zone.
  const savedResponse=page.waitForResponse(r=>r.url().endsWith("/reservations")&&r.request().method()==="POST");
  await form.getByRole("button",{name:"Reserve This Table",exact:true}).click();
  const saved=await savedResponse;assert(saved.ok(),await saved.text());assert.equal((await saved.json()).scheduled_at,expected);
  assert.deepEqual(saved.request().postDataJSON().scheduled_at,expected);
  let defaults=0;page.on("request",request=>{if(request.url().endsWith("/reservation-default"))defaults++;});
  await page.getByRole("button",{name:"Edit Reservation",exact:true}).click();
  await field("Time").waitFor();assert.equal(await field("Time").inputValue(),"00:00");
  const beforeEdit=defaults;
  await field("Month").fill("9");await field("Day").fill("20");await field("Time").fill("18:45");
  assert.equal(defaults,beforeEdit);
  await form.getByRole("button",{name:"Reset to One Hour",exact:true}).click();
  const editedResponse=page.waitForResponse(r=>r.url().includes("/api/table-reservations/")&&r.request().method()==="POST");
  await form.getByRole("button",{name:"Save Reservation Changes",exact:true}).click();
  const edited=await editedResponse;assert(edited.ok(),await edited.text());assert.equal((await edited.json()).scheduled_at,"2027-09-21T01:45:00.000+00:00");
  assert.equal(edited.request().postDataJSON().scheduled_at,"2027-09-21T01:45:00.000+00:00");
  // The form remains editable across language renders and the ten-second refresh.
  await form.getByRole("button",{name:"Reserve This Table",exact:true}).waitFor();
  await field("Month").fill("10");await field("Day").fill("4");await field("Time").fill("19:30");
  await page.getByRole("button",{name:"CN",exact:true}).click();
  assert.equal(await form.getByLabel("时间",{exact:true}).inputValue(),"19:30");
  await page.getByRole("button",{name:"EN",exact:true}).click();
  await page.waitForResponse(r=>new URL(r.url()).pathname==="/api/admin/club-tables"&&r.request().method()==="GET");
  assert.equal(await field("Month").inputValue(),"10");assert.equal(await field("Day").inputValue(),"4");assert.equal(await field("Time").inputValue(),"19:30");
  await page.getByRole("button",{name:"Edit Reservation",exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('input[aria-label="Time"]')?.value==="18:45");
  assert.equal(await field("Month").inputValue(),"9");assert.equal(await field("Day").inputValue(),"20");
  // A slow server default must not overwrite even a single edited field.
  let release,requested;const gate=new Promise(resolve=>{release=resolve;}),started=new Promise(resolve=>{requested=resolve;});
  await context.route("**/reservation-default",async route=>{requested();await gate;await route.continue();});
  await page.goto(url);await requested;await field("Month").fill("8");
  const late=page.waitForResponse(r=>r.url().endsWith("/reservation-default"));release();await late;
  await page.getByRole("button",{name:"CN",exact:true}).click();await page.getByRole("button",{name:"EN",exact:true}).click();
  assert.equal(await field("Month").inputValue(),"8");assert.equal(await field("Day").inputValue(),"");assert.equal(await field("Time").inputValue(),"");
  assert.deepEqual(errors,[]);console.log("Reservation default browser passed: server timezone, cross-year save, retained edit year, no year input, refresh retention and slow-response protection.");
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
