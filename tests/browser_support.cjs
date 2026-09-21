
const fs=require("fs"),path=require("path"),assert=require("assert"),babel=require("@babel/core");
const root=path.resolve(__dirname,"..");
async function prepare(context,base){
 await context.route("https://cdn.tailwindcss.com/**",r=>r.fulfill({body:"window.tailwind={};",contentType:"application/javascript"}));
 for(const [name,file] of [["react","react.development.js"],["react-dom","react-dom.development.js"]])
  await context.route("https://unpkg.com/"+name+"@18/**",r=>r.fulfill({path:path.join(path.dirname(require.resolve(name+"/package.json")),"umd",file),contentType:"application/javascript"}));
 for(const file of ["registered-user-combobox","registered-admin","app","tournament","tournament-v2","table-controls","manual-score","registration-v10","tournament-v10","competition"])
  await context.route("**/"+file+".jsx?*",r=>r.fulfill({body:babel.transformFileSync(path.join(root,"web/"+file+".jsx"),{plugins:[[require("@babel/plugin-transform-react-jsx"),{runtime:"classic"}]]}).code,contentType:"application/javascript"}));
 await context.route(url=>url.origin===base&&(["/","/login","/register","/registration-complete","/reservations","/manual-score"].includes(url.pathname)||url.pathname.startsWith("/challenges/")||url.pathname.startsWith("/join-table/")||url.pathname.startsWith("/join/")),async r=>{
  const response=await r.fetch();assert(response.ok());
  await r.fulfill({body:(await response.text()).replace(/<script src="https:\/\/unpkg.com\/@babel\/standalone\/babel.min.js"><\/script>/,"").replaceAll('type="text/babel"','type="text/javascript"'),contentType:"text/html"});
 });
 await context.route("**/api/dashboard*",r=>r.fulfill({json:{stats:{member_count:8},rankings:[],recent_yakuman:[]}}));
 await context.route("**/api/players",r=>r.fulfill({json:{players:Array.from({length:8},(_,i)=>"photo"+(i+1))}}));
}
module.exports={prepare,root};
