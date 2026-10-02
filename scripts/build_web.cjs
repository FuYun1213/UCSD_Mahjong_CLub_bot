/* Reproducible production assets. No browser compiler or third-party runtime CDN. */
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const root=path.resolve(__dirname,'..');
const modules=process.env.WEB_BUILD_MODULES||(fs.existsSync(path.join(__dirname,'web-build/node_modules'))?path.join(__dirname,'web-build/node_modules'):path.join(root,'.venv-api/browser-tests/node_modules'));
const dependency=name=>require(path.join(modules,name));
const babel=dependency('@babel/core'),jsx=dependency('@babel/plugin-transform-react-jsx');
const target=process.env.WEB_BUILD_OUTPUT||path.join(root,'web');
const brand=require(path.join(root,'web/brand.js'));
const favicon='/assets/dora-club-icon.png?v=20260922';
const escapeHtml=value=>value.replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const footer=`<footer class="club-footer" data-club-footer aria-label="Disclaimer" lang="en"><p>${escapeHtml(brand.disclaimer)}</p></footer>`;
const footerCss=fs.readFileSync(path.join(root,'web/footer.css'),'utf8');
const output=path.join(target,'dist');fs.mkdirSync(output,{recursive:true});
for(const folder of ['assets','vendor'])if(target!==path.join(root,'web')&&fs.existsSync(path.join(root,'web',folder)))fs.cpSync(path.join(root,'web',folder),path.join(target,folder),{recursive:true});
for(const file of fs.readdirSync(path.join(root,'web')).filter(f=>/\.(js|css)$/.test(f)))if(target!==path.join(root,'web'))fs.copyFileSync(path.join(root,'web',file),path.join(target,file));
const assets={},sizes={};
function emit(name,content,ext='js'){
 const hash=crypto.createHash('sha256').update(content).digest('hex').slice(0,16);
 const file=`${name}.${hash}.${ext}`;fs.writeFileSync(path.join(output,file),content);
 assets[name]='/dist/'+file;sizes[name]=Buffer.byteLength(content);return assets[name];
}
function compile(code){return babel.transformSync(code,{plugins:[[jsx,{runtime:'classic'}]],comments:false,compact:true}).code;}
const chunks={common:[],admin:[],ranking:[],tables:[],tournaments:[],challenge:[]};
const adminApp=new Set(['PasswordResetAdmin','QuarterControlCard','MatchManagementPanel','AdminActionsPanel','DiscordScoringControl']);
const adminTables=new Set(['AdminTableToken','AdminTableCard','AdminTables','CreateClubTable']);
const commonTournament=new Set(['TournamentButton','TournamentField','useTournamentDraft','tournamentApi']);
let boot='';
for(const file of ['tournament','table-controls','competition','registered-admin','app']){
 const source=fs.readFileSync(path.join(root,'web',file+'.jsx'),'utf8');
 const ast=babel.parseSync(source,{plugins:[[jsx,{runtime:'classic'}]]});
 for(const node of ast.program.body){
  const text=source.slice(node.start,node.end),name=node.id?.name;
  if(file==='app'&&text.startsWith('ReactDOM.createRoot')){boot=text;continue;}
  let group='common';
  if(file==='app'&&adminApp.has(name))group='admin';
  if(file==='app'&&name==='RankingCard')group='ranking';
  if(file==='tournament'&&node.type==='FunctionDeclaration'&&!commonTournament.has(name))group='tournaments';
  if(file==='table-controls')group=adminTables.has(name)?'admin':'tables';
  if(file==='registered-admin')group=name==='RegisteredNameAdmin'?'admin':'common';
  if(file==='competition')group='challenge';
  chunks[group].push(text);
 }
}
// The declaration-only chunks can load after common; components execute on demand.
for(const [name,code] of Object.entries(chunks))emit(name,compile(code.join('\n')));
for(const name of ['registered-user-combobox','navigation','registration-v10','tournament-v2','tournament-v10','manual-score'])
 emit(name,compile(fs.readFileSync(path.join(root,'web',name+'.jsx'),'utf8')));
for(const name of ['brand','i18n','competition-i18n','table-v5-i18n','seat-card-i18n','seat-swap-i18n','reservation-time','reservation-v9-i18n','account-avatar','registered-v6-i18n','manual-v6-i18n'])
 emit(name,fs.readFileSync(path.join(root,'web',name+'.js'),'utf8'));
emit('react',fs.readFileSync(path.join(modules,'react/umd/react.production.min.js')));
emit('react-dom',fs.readFileSync(path.join(modules,'react-dom/umd/react-dom.production.min.js')));
const routes={dashboard:['tables','challenge'],challenge:['challenge'],ranking:['ranking'],record:['tables'],reservations:['tables'],
 'join-table':['tables'],tournament:['tables','tournaments','tournament-v2','tournament-v10','challenge'],
 'manual-score':['tables','tournaments','tournament-v2','tournament-v10','manual-score'],
 account:['registration-v10'],register:['registration-v10'],'registration-complete':['registration-v10'],
 admin:['tables','tournaments','tournament-v2','tournament-v10','registration-v10','admin']};
emit('loader',`window.MahjongAssets=(()=>{const assets=${JSON.stringify(assets)},routes=${JSON.stringify(routes)},loaded=new Map();function script(name){if(!loaded.has(name)){loaded.set(name,new Promise((resolve,reject)=>{const s=document.createElement('script');s.src=assets[name];s.onload=resolve;s.onerror=()=>{loaded.delete(name);s.remove();reject(new Error('assetUnavailable'));};document.head.append(s);}));}return loaded.get(name);}return {async load(page){for(const name of routes[page]||[])await script(name);}};})();`);
emit('boot',compile(boot));
(async()=>{
 const css=(await dependency('postcss')([dependency('tailwindcss')({content:[path.join(root,'web/*.{html,jsx,js}')],theme:{extend:{colors:{navy:'#425b3d',gold:'#a2a76f',paper:'#f7f9f2',warm:'#eff3e8'},fontFamily:{sans:['Inter','ui-sans-serif','system-ui','sans-serif']},boxShadow:{soft:'0 18px 45px rgba(20,33,61,.08)'}}}})]).process('@tailwind base;@tailwind components;@tailwind utilities;',{from:undefined})).css;
 emit('style',css+'\n'+fs.readFileSync(path.join(root,'web/styles.css'),'utf8')+'\n'+footerCss,'css');
 const initial=['brand','react','react-dom','i18n','competition-i18n','table-v5-i18n','seat-card-i18n','seat-swap-i18n','reservation-time','reservation-v9-i18n','account-avatar','registered-v6-i18n','manual-v6-i18n','registered-user-combobox','navigation','loader','common','boot'];
 emit('initial',initial.map(name=>fs.readFileSync(path.join(target,assets[name]),'utf8')).join('\n;\n'));
 const html=`<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><meta name="theme-color" content="#425b3d"><title>${escapeHtml(brand.name)}</title><meta property="og:site_name" data-club-brand content="${escapeHtml(brand.name)}"><meta property="og:title" data-club-brand content="${escapeHtml(brand.name)}"><link rel="icon" type="image/png" href="${favicon}"><link rel="apple-touch-icon" href="${favicon}"><link rel="stylesheet" href="${assets.style}"></head><body class="bg-paper text-zinc-900 antialiased"><div id="root"></div>${footer}<script defer src="${assets.initial}"></script></body></html>\n`;
 fs.writeFileSync(path.join(target,'index.html'),html);
 fs.writeFileSync(path.join(target,'footer.html'),`<style>${footerCss}</style>${footer}\n`);
 // Isolated builds keep both generated shells inside their requested output directory.
 const scoreSource=path.join(root,'mahjong_api/static/score.html');
 const scoreTarget=process.env.WEB_BUILD_SCORE_OUTPUT||(path.resolve(target)===path.join(root,'web')?scoreSource:path.join(target,'score.html'));
 const scoreTemplate=fs.readFileSync(scoreSource,'utf8');
 for(const marker of ['/* club-footer-style:start */','/* club-footer-style:end */','<!-- club-footer:start -->','<!-- club-footer:end -->'])
  if(scoreTemplate.split(marker).length!==2)throw new Error('Expected exactly one footer build marker: '+marker);
 const scoreHtml=scoreTemplate
  .replace(/\/\* club-footer-style:start \*\/[\s\S]*?\/\* club-footer-style:end \*\//,`/* club-footer-style:start */\n${footerCss}/* club-footer-style:end */`)
  .replace(/<!-- club-footer:start -->[\s\S]*?<!-- club-footer:end -->/,`<!-- club-footer:start -->${footer}<!-- club-footer:end -->`);
 fs.mkdirSync(path.dirname(scoreTarget),{recursive:true});fs.writeFileSync(scoreTarget,scoreHtml);
 fs.writeFileSync(path.join(output,'manifest.json'),JSON.stringify({assets,sizes,initialBytes:initial.reduce((n,k)=>n+sizes[k],0),routes},null,2));
 console.log(JSON.stringify({initialBytes:initial.reduce((n,k)=>n+sizes[k],0),sizes},null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
