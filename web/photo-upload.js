/* Phone photo preparation. No photo leaves this device before normalization. */
(function(global){
'use strict';
const MAX_INPUT_BYTES=100*1024*1024,MAX_OUTPUT_BYTES=2*1024*1024,MAX_EDGE=1920;
let decoderLoading;
function deadline(promise,ms=120000){
 return new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('pPhotoFailed')),ms);
  promise.then(value=>{clearTimeout(timer);resolve(value);},error=>{clearTimeout(timer);reject(error);});});
}
async function format(file){
 const b=new Uint8Array(await file.slice(0,64).arrayBuffer());
 const ascii=(start,end)=>String.fromCharCode(...b.slice(start,end));
 if(b[0]===255&&b[1]===216&&b[2]===255)return 'jpeg';
 if(ascii(1,4)==='PNG'&&b[0]===137)return 'png';
 if(ascii(0,4)==='RIFF'&&ascii(8,12)==='WEBP')return 'webp';
 if(ascii(4,8)==='ftyp'&&/(heic|heix|hevc|hevx|mif1|msf1)/.test(ascii(8,64)))return 'heic';
 throw new Error('pPhotoFormat');
}
function loadHeicDecoder(){
 if(global.HeicTo)return Promise.resolve(global.HeicTo);
 if(!decoderLoading){decoderLoading=new Promise((resolve,reject)=>{
  const script=document.createElement('script');script.src='/vendor/heic-to-1.5.2.js';script.async=true;
  script.onload=()=>global.HeicTo?resolve(global.HeicTo):reject(new Error('pPhotoFailed'));
  script.onerror=()=>{script.remove();reject(new Error('pPhotoFailed'));};document.head.append(script);
 }).catch(error=>{decoderLoading=null;throw error;});}
 return decoderLoading;
}
async function nativeImage(file){
 // Browser codecs apply EXIF orientation before pixels reach the canvas.
 if(global.createImageBitmap){try{return await createImageBitmap(file,{imageOrientation:'from-image'});}catch{}}
 const url=URL.createObjectURL(file),img=new Image();
 try{img.src=url;await img.decode();return img;}finally{URL.revokeObjectURL(url);}
}
async function prepare(file){
 if(!file||!file.size)throw new Error('pPhotoFormat');
 if(file.size>MAX_INPUT_BYTES)throw new Error('pPhotoLarge');
 const kind=await format(file);let img,canvas;
 try{
  try{img=await deadline(nativeImage(file),30000);}catch(error){
   if(kind!=='heic')throw error;
   const decode=await deadline(loadHeicDecoder());
   img=await deadline(decode({blob:file,type:'bitmap'}));
  }
  const width=img.naturalWidth||img.width,height=img.naturalHeight||img.height;
  if(!width||!height)throw new Error('pPhotoFailed');
  // Keep already small supported images lossless. HEIC always becomes JPEG.
  if(kind!=='heic'&&Math.max(width,height)<=MAX_EDGE&&file.size<=MAX_OUTPUT_BYTES)return file;
  canvas=document.createElement('canvas');
  let edge=MAX_EDGE;
  while(edge>=960){
   const ratio=Math.min(1,edge/Math.max(width,height));
   canvas.width=Math.max(1,Math.round(width*ratio));canvas.height=Math.max(1,Math.round(height*ratio));
   const ctx=canvas.getContext('2d');if(!ctx)throw new Error('pPhotoFailed');
   ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);
   ctx.drawImage(img,0,0,canvas.width,canvas.height);
   for(const quality of [.92,.85,.78,.70]){
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',quality));
    if(!blob||!blob.size)throw new Error('pPhotoFailed');
    if(blob.size<=MAX_OUTPUT_BYTES)return new File([blob],'score.jpg',{type:'image/jpeg'});
   }
   edge=Math.floor(edge*.8);
  }
  throw new Error('pPhotoCompressFailed');
 }catch(error){
  if(/^pPhoto/.test(error?.message||''))throw error;
  throw new Error('pPhotoFailed');
 }finally{img?.close?.();if(canvas){canvas.width=1;canvas.height=1;}}
}
global.PhotoUpload={prepare,MAX_INPUT_BYTES,MAX_OUTPUT_BYTES,MAX_EDGE};
})(window);
