/* Local preview only. Bundle the existing app without browser CDN dependencies. */
const fs=require('fs'),path=require('path'),cp=require('child_process');
const root=path.resolve(__dirname,'..'),modules=path.dirname(path.dirname(require.resolve('react/package.json')));
const babel=require(path.join(modules,'@babel/core'));
const out=path.join(root,'.local_challenge_v11/assets');fs.mkdirSync(out,{recursive:true});
for(const file of fs.readdirSync(path.join(root,'web')).filter(f=>f.endsWith('.jsx'))){
 const result=babel.transformFileSync(path.join(root,'web',file),{plugins:[[require(path.join(modules,'@babel/plugin-transform-react-jsx')),{runtime:'classic'}]]});
 fs.writeFileSync(path.join(out,file),result.code);
}
for(const [pkg,file] of [['react','react.development.js'],['react-dom','react-dom.development.js']])fs.copyFileSync(path.join(modules,pkg,'umd',file),path.join(out,file));
fs.writeFileSync(path.join(out,'input.css'),'@tailwind base;\n@tailwind components;\n@tailwind utilities;\n');
fs.writeFileSync(path.join(out,'tailwind.cjs'),'module.exports='+JSON.stringify({content:[path.join(root,'web/*.jsx').replaceAll('\\','/')],theme:{extend:{colors:{navy:'#14213d',gold:'#c9972b',paper:'#faf9f5',warm:'#f7f5ef'},boxShadow:{soft:'0 18px 45px rgba(20,33,61,.08)'}}}}));
cp.execFileSync(process.execPath,[path.join(modules,'tailwindcss/lib/cli.js'),'-c',path.join(out,'tailwind.cjs'),'-i',path.join(out,'input.css'),'-o',path.join(out,'styles.css'),'--minify'],{stdio:'inherit'});
let html=fs.readFileSync(path.join(root,'web/index.html'),'utf8');
html=html.replace('<script src="https://cdn.tailwindcss.com"></script>','<link rel="stylesheet" href="/preview-assets/styles.css"><script>window.tailwind={};</script>')
 .replace('https://unpkg.com/react@18/umd/react.development.js','/preview-assets/react.development.js')
 .replace('https://unpkg.com/react-dom@18/umd/react-dom.development.js','/preview-assets/react-dom.development.js')
 .replace('<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>','')
 .replaceAll('type="text/babel"','type="text/javascript"');
fs.writeFileSync(path.join(out,'index.html'),html);
console.log('Local preview assets ready.');
