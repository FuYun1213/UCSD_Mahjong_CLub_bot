
const assert=require("assert"),{chromium}=require("playwright");
const {prepare}=require("./browser_support.cjs"),base=process.env.NFC_TEST_URL;
(async()=>{
 const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || undefined,headless:true});
 try{
  const context=await browser.newContext();await prepare(context,base);
  assert((await context.request.post(base+"/api/login",{data:{username:"photo1",password:"photo-test-password"}})).ok());
  const page=await context.newPage(),errors=[];page.on("pageerror",e=>errors.push(e.message));
  await page.goto(base+"/?page=record");
  const create=page.locator("details").filter({has:page.locator("summary").filter({hasText:/^Create Table$/})}).first();
  await create.locator("summary").click();
  for(const number of [22,23]){
   await create.getByLabel("Table Number (positive integer)",{exact:true}).fill(String(number));
   await create.getByRole("button",{name:"Create Table",exact:true}).click();
   await page.waitForFunction(n=>document.querySelector('select[aria-label="Select Table"]')?.selectedOptions[0]?.textContent==="Table "+n,number);
  }
  const selector=page.getByRole("combobox",{name:"Select Table",exact:true});
  const tableId=await selector.inputValue();
  assert(tableId&&tableId!=="23");
  const tableInfo=async()=>{const response=await page.request.get(base+"/api/admin/club-tables");assert(response.ok());return (await response.json()).tables.find(t=>t.score_table_id===tableId);};
  assert.equal(await page.locator("[data-reservation-form]").count(),0);
  await page.getByRole("link",{name:"View Table Reservations",exact:true}).click();
  await page.waitForURL(url=>url.pathname==="/reservations");
  await page.getByLabel("Month",{exact:true}).fill("10");
  await page.getByLabel("Day",{exact:true}).fill("2");
  await page.getByLabel("Time",{exact:true}).fill("18:30");
  assert.equal(await page.locator('input[type="datetime-local"],input[type="date"]').count(),0);
  await page.getByLabel("Note (optional)",{exact:true}).fill("Admin can reserve");
  await page.getByRole("button",{name:"CN",exact:true}).click();
  assert.equal(await page.getByLabel("时间",{exact:true}).inputValue(),"18:30");
  assert.equal(await page.getByLabel("月",{exact:true}).inputValue(),"10");
  await page.getByRole("button",{name:"EN",exact:true}).click();
  await page.getByRole("button",{name:"Reserve This Table",exact:true}).click();
  await page.getByText("Admin can reserve",{exact:false}).waitFor();
  let info=await tableInfo();assert.equal(info.player_count,0);assert.equal(info.reservations[0].user_id,"photo-user-1");
  await page.reload();
  await page.getByText("Admin can reserve",{exact:false}).waitFor();
  assert.equal((await tableInfo()).score_table_id,tableId);
  await page.getByRole("button",{name:"Cancel Reservation",exact:true}).click();
  await page.locator("[data-reservation-id]").getByText("Cancelled",{exact:false}).waitFor();
  await page.goto(base+"/?page=admin");
  const adminTable=page.locator("details").filter({has:page.locator("summary").filter({hasText:/^Table 23 /})}).first();await adminTable.locator("summary").first().click();
  for(const [name,seat] of [["photo2","east"],["photo3","south"]]){
   await adminTable.getByRole("button",{name:"Join Table",exact:true}).click();
   await page.getByRole("tab",{name:"Seat by Registered Name",exact:true}).click();
   const search=page.getByRole("dialog").getByRole("combobox",{name:"Registered Name",exact:true});
   await search.fill("not-registered");
   await page.getByText("No registered name found.",{exact:true}).waitFor();
   assert(await page.getByRole("dialog").getByRole("button",{name:"Add Selected Player",exact:true}).isDisabled());
   await search.fill(name.toUpperCase());
   await page.getByRole("option",{name,exact:true}).click();
   await page.getByRole("dialog").getByRole("combobox",{name:"Choose a Seat",exact:true}).selectOption(seat);
   await page.getByRole("dialog").getByRole("button",{name:"Add Selected Player",exact:true}).click();
   await page.getByRole("dialog").waitFor({state:"detached"});
  }
  info=await tableInfo();
  assert.deepEqual(info.members.map(m=>m.user_id).sort(),["photo-user-2","photo-user-3"]);
  assert(info.members.every(m=>m.join_method==="registered_name"&&m.added_by_user_id==="photo-user-1"));
  assert.deepEqual(errors,[]);
  console.log("Admin reservations, inline table creation, registered-account search/selection, refresh and bilingual form retention passed.");
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
