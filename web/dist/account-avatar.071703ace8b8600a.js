/* Read-only display of the existing account avatar; never changes its source priority. */
(function(root){
  "use strict";
  const failedSources=new Set();
  function initials(name){return String(name||"").trim().split(/\s+/u).slice(0,2).map(part=>Array.from(part)[0]||"").join("").toUpperCase()||"MJ";}
  function safeSource(value){
    const source=typeof value==="string"?value:"";
    return /^(?:data:image\/(?:png|jpeg|webp);base64,|https:\/\/|\/(?!\/))/i.test(source)?source:"";
  }
  function style(size){return {display:"inline-flex",alignItems:"center",justifyContent:"center",flexShrink:0,
    width:size,height:size,borderRadius:"50%",overflow:"hidden",verticalAlign:"middle",background:"#f0f2ef",color:"#284f40",
    fontSize:Math.max(10,Math.round(size*.36)),fontWeight:700};}
  function element({name,src,size=28,decorative=false}={}){
    const holder=document.createElement("span"),source=safeSource(src);
    Object.assign(holder.style,style(size),{width:size+"px",height:size+"px",fontSize:Math.max(10,Math.round(size*.36))+"px"});
    holder.className="account-avatar";holder.dataset.accountAvatar="";
    if(decorative)holder.setAttribute("aria-hidden","true");else{holder.setAttribute("role","img");holder.setAttribute("aria-label",String(name||"")+" avatar");}
    holder.textContent=initials(name);holder.dataset.avatarState="fallback";
    if(source&&!failedSources.has(source)){
      const image=document.createElement("img");image.alt="";image.src=source;image.style.cssText="width:100%;height:100%;object-fit:cover";
      image.referrerPolicy="no-referrer";image.onload=()=>{holder.dataset.avatarState="image";};
      image.onerror=()=>{failedSources.add(source);holder.replaceChildren(document.createTextNode(initials(name)));holder.dataset.avatarState="fallback";};
      holder.replaceChildren(image);
    }
    return holder;
  }
  function Avatar({name,src,size=28,className="",decorative=false}){
    const source=safeSource(src),[failed,setFailed]=root.React.useState(false);
    root.React.useEffect(()=>setFailed(false),[source]);
    const hasImage=source&&!failed&&!failedSources.has(source);
    return root.React.createElement("span",{className:"account-avatar "+className,style:style(size),"data-account-avatar":"",
      "data-avatar-state":hasImage?"image":"fallback",role:decorative?undefined:"img","aria-label":decorative?undefined:String(name||"")+" avatar","aria-hidden":decorative?true:undefined},
      hasImage?root.React.createElement("img",{src:source,alt:"",referrerPolicy:"no-referrer",style:{width:"100%",height:"100%",objectFit:"cover"},onError:()=>{failedSources.add(source);setFailed(true);}}):initials(name));
  }
  root.AccountAvatars={Avatar,element,initials,safeSource};
  if(typeof module!=="undefined"&&module.exports)module.exports=root.AccountAvatars;
})(typeof window!=="undefined"?window:globalThis);
