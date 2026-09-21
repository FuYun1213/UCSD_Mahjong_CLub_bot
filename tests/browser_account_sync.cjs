const {chromium}=require("playwright"), assert=require("assert");
const {prepare}=require("./browser_support.cjs");
(async()=>{
 const base=process.env.NFC_TEST_URL;
 const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || undefined,headless:true});
 try{
  const context=await browser.newContext(); await prepare(context,base);
  const page=await context.newPage();const errors=[];page.on("pageerror",e=>errors.push(e.message));
  await page.goto(base+"/login");
  await page.locator('input[name="username"]').first().fill("Existing Player");
  await page.locator('input[name="password"]').fill("test-password");
  const firstLogin=page.waitForResponse(response=>response.url().endsWith("/api/login")&&response.request().method()==="POST");
  await page.getByRole("button",{name:"Log in",exact:true}).click();
  const guidance=await (await firstLogin).json();assert.equal(guidance.code,"website_registration_required",JSON.stringify(guidance));
  await page.getByText("This player has no website account yet.",{exact:false}).first().waitFor();
  await page.goto(base+"/register");
  assert.equal(await page.getByRole("tab",{name:"Existing Player",exact:true}).getAttribute("aria-selected"),"true");
  assert.equal(await page.locator("input[name=username],input[name=legacy_id]").count(),0);
  await page.getByRole("combobox",{name:"Find your player name",exact:true}).fill("Existing Player");
  await page.getByRole("option",{name:"Existing Player",exact:true}).click();
  await page.getByLabel("Password",{exact:true}).fill("test-password");
  await page.getByLabel("Confirm password",{exact:true}).fill("test-password");
  await page.getByRole("button",{name:"Submit for approval"}).click();
  await page.getByRole("heading",{name:"Waiting for administrator approval"}).waitFor();
  const admin=await browser.newContext();
  await admin.request.post(base+"/api/login",{data:{username:"ReviewAdmin",password:"test-password"}});
  const claims=await admin.request.get(base+"/api/admin/account-claims").then(r=>r.json());
  const approved=await admin.request.post(base+"/api/admin/account-claims/review",{data:{claim_id:claims.claims[0].id,decision:"approve"}});assert(approved.ok(),await approved.text());
  await page.getByRole("button",{name:"Check status"}).click();
  await page.waitForURL(base+"/");
  assert.equal((await (await context.request.get(base+"/api/session")).json()).user,"Existing Player");
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({discordIdSetupGuidance:true,sameNameRegistration:true,browserLogin:true,pageErrors:0}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
