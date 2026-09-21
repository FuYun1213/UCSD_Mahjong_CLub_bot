const $=id=>document.getElementById(id),winds=['east','south','west','north'];
const query=new URLSearchParams(location.search),embedded=query.get('embedded')==='1';
let language=localStorage.getItem('mahjong_lang')||'EN';
const t=(key,vars)=>MahjongI18n.t(language,key,vars);
$('table').value=query.get('table')||'';
let state=null,snapshotAt=0,draft=null,photoTask=null,previewUrl=null,busy=false,seated=false,lastResult=null,messageKey='',messageVars={};
// The host supplies its existing global account. This frame never loads or stores a session.
let globalContext={profile:null,authReady:false,entryToken:null,pendingSeat:''};
let leaving=false,seatBusy=false,seatPending='',seatMessageKey='',seatMessageVars={},tableReadSequence=0,tableLoading=false,resumeConsumed=false;
let swapRequests=[],swapDialog=null,swapBusy=false,swapClockOffset=0,swapReturnWind=null,reminderData=null,reminderLoading=false,reminderSequence=0,reminderClockOffset=0;
function parentEvent(type,extra={}){if(embedded)parent.postMessage({type,...extra},location.origin);}
function scoreUrl(params){if(embedded)params.set('embedded','1');return '/score?'+params.toString();}
function applyLanguage(value){
 language=value==='EN'?'EN':'CN';document.documentElement.lang=language==='CN'?'zh':'en';document.title=t('pTitle');
 document.querySelectorAll('[data-text]').forEach(el=>{el.textContent=t(el.dataset.text);});
 document.querySelectorAll('[data-placeholder]').forEach(el=>el.placeholder=t(el.dataset.placeholder));
 $('preview').alt=t('pPhoto');
 if(messageKey)message(messageKey,messageVars);
 seatMessage(seatMessageKey,seatMessageVars);
 if(state)renderState(state,false);else renderSeatCards();
 if(draft)renderReviewLabels();
 if(lastResult)renderResult();
 renderReminders();renderSwapUi();

}

window.addEventListener('message',event=>{
 if(event.origin!==location.origin||event.source!==parent)return;
 if(event.data?.type==='mahjong-language')applyLanguage(event.data.language);
 if(event.data?.type==='mahjong-table-changed'&&!busy&&!seatBusy){refresh();refreshReminders();}
 if(event.data?.type==='mahjong-score-context'&&event.data.table===$('table').value){
  const previousId=globalContext.profile?.id,previousReady=globalContext.authReady;
  globalContext={profile:event.data.profile||null,authReady:Boolean(event.data.authReady),entryToken:event.data.entryToken||null,pendingSeat:event.data.pendingSeat||''};
  if(previousId!==globalContext.profile?.id){tableReadSequence++;state=null;swapRequests=[];reminderData=null;reminderSequence++;hideSwapDialog();renderReminders();}
  renderSeatCards();
  if(previousId!==globalContext.profile?.id||previousReady!==globalContext.authReady){refresh().then(resumeSeatChoice);refreshReminders();}
  else resumeSeatChoice();
 }
});
if(embedded){
 document.querySelector('main>a').hidden=true;document.querySelector('h1').hidden=true;document.body.style.background='transparent';document.querySelector('main').style.padding='0';
 new ResizeObserver(()=>parentEvent('mahjong-score-height',{height:Math.ceil(document.querySelector('main').getBoundingClientRect().height)})).observe(document.querySelector('main'));
}
function taskKey(){return MahjongI18n.key();}
function message(key,vars={}){messageKey=key;messageVars=vars;$('message').textContent=t(key,vars);}
function duration(value){if(value===null||value===undefined)return t('pNoRecords');const n=Math.max(0,Math.floor(value));return String(Math.floor(n/3600)).padStart(2,'0')+':'+String(Math.floor(n/60)%60).padStart(2,'0')+':'+String(n%60).padStart(2,'0');}
async function api(url,options={}){
 let response,body;
 const {seatIntent,...requestOptions}=options;
 try{response=await fetch(url,{...requestOptions,credentials:'include'});body=await response.json();}catch{throw new Error('requestFailed');}
 if(response.status===401){if(seatIntent){requestSeatLogin(seatIntent);throw new Error('not_authenticated');}if(options.method&&options.method!=='GET'){const target=new URL(embedded?parent.location.href:location.href);if(draft)target.searchParams.set('draft_id',draft.draft_id);window.top.location.assign('/login?redirect_url='+encodeURIComponent(target.pathname+target.search+target.hash));}throw new Error('not_authenticated');}
 if(!response.ok)throw new Error(MahjongI18n.entries[body.detail?.code]?body.detail.code:'requestFailed');
 return body;
}
function renderState(data,resetClock=true){
 state=data;if(resetClock)snapshotAt=performance.now();
 $('round').textContent=t('ordinaryTable',{table:data.display_name||data.table});
 $('started').textContent=data.started_at?new Date(data.started_at).toLocaleString():t('pWaitingFour');
 $('average').textContent=duration(data.average_duration_seconds);renderSeatCards();
 tick();
}
function tick(){if(!state)return;const elapsed=state.elapsed_seconds===null?null:state.elapsed_seconds+(state.ended_at?0:Math.floor((performance.now()-snapshotAt)/1000));$('elapsed').textContent=duration(elapsed);}
function seatMessage(key,vars={}){seatMessageKey=key;seatMessageVars=vars;$('seat-message').textContent=key?t(key,vars):'';}
function ownWind(){return winds.find(wind=>globalContext.profile&&state?.players?.[wind]?.id===String(globalContext.profile.id));}
function renderSeatCards(){
 const current=ownWind(),locked=Boolean(state?.started_at&&!state?.ended_at),container=$('players');
 container.setAttribute('aria-busy',String(seatBusy));
 winds.forEach((wind,index)=>{
  const person=state?.players?.[wind],mine=Boolean(current===wind),occupied=Boolean(person),ready=Boolean(state&&globalContext.authReady);
  // Preserve each button across polling so an in-progress pointer click and keyboard focus survive.
  let button=container.querySelector('[data-seat-card="'+wind+'"]');
  if(!button){
   button=document.createElement('button');button.type='button';button.className='player';button.dataset.seatCard=wind;button.dataset.seatAction=wind;button.dataset.seat=wind;
   const title=document.createElement('strong'),name=document.createElement('span'),action=document.createElement('span');name.className='seat-name';action.className='seat-action';
   button.append(title,name,action);button.onclick=()=>chooseSeat(wind);container.append(button);
  }
  button.dataset.seatState=!ready?'unknown':mine?'current':occupied?'occupied':'empty';
  button.disabled=seatBusy||swapBusy||!ready||(occupied&&!mine&&(!current||Boolean(pendingSwap())))||(locked&&!mine);button.setAttribute('aria-pressed',String(mine));button.setAttribute('aria-busy',String(seatBusy&&seatPending===wind));
  const title=button.querySelector('strong'),name=button.querySelector('.seat-name'),action=button.querySelector('.seat-action');
  title.textContent=t('wind'+index);const playerLabel=!ready?t('pSeatLoading'):person?(person.name||t('pSeatOccupied')):t('pSeatEmpty');
  const nameSignature=JSON.stringify([playerLabel,ready&&person?.name,person?.avatar]);
  if(button._seatNameSignature!==nameSignature){
   button._seatNameSignature=nameSignature;const nameLabel=document.createElement('span');nameLabel.textContent=playerLabel;name.replaceChildren(nameLabel);
   if(ready&&person?.name)name.prepend(AccountAvatars.element({name:person.name,src:person.avatar,size:24,decorative:true}));
  }
  const key=seatBusy&&seatPending===wind?(leaving?'pSeatLeaving':'pSeatSaving'):!ready?'pSeatLoading':mine?'pSeatLeave':occupied?(current&&!locked?'swapChoose':'pSeatOccupied'):locked?'pSeatLocked':current?'pSeatMove':'pSeatJoin';
  action.textContent=t(key);button.setAttribute('aria-label',title.textContent+' · '+playerLabel+' · '+action.textContent);
 });
 const leave=$('leave-table');
 leave.disabled=seatBusy||swapBusy||busy||!current||!globalContext.authReady;
 leave.textContent=t(leaving?'pSeatLeaving':'pSeatLeaveButton');leave.setAttribute('aria-busy',String(leaving));
 $('leave-hint').textContent=t(current?(locked?'cannot_leave_started':'pSeatLeaveHint'):'pSeatNotSeated');
}
function requestSeatLogin(wind){
 if(!winds.includes(wind))return;
 if(embedded){parentEvent('mahjong-seat-login',{table:$('table').value,seat:wind});return;}
 const target=new URL('/?page=record',location.origin);target.searchParams.set('table',$('table').value);target.searchParams.set('pending_seat',wind);
 window.top.location.assign('/login?redirect_url='+encodeURIComponent(target.pathname+target.search+target.hash));
}
async function chooseSeat(wind){
 if(!winds.includes(wind)||seatBusy||swapBusy||!globalContext.authReady)return;
 if(!globalContext.profile){requestSeatLogin(wind);return;}
 if(ownWind()===wind){await leaveTable('seat_card');return;}
 if(state?.players?.[wind]){if(ownWind()&&!state.started_at&&!pendingSwap())confirmSwap(wind);else seatMessage('seat_occupied');return;}
 seatBusy=true;seatPending=wind;tableReadSequence++;seatMessage('pSeatSaving');renderSeatCards();
 try{
  const payload={seat:wind};if(state?.match_id)payload.match_id=state.match_id;if(globalContext.entryToken)payload.entry_token=globalContext.entryToken;
  const response=await api('/api/club-tables/'+encodeURIComponent($('table').value)+'/my-seat',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),seatIntent:wind});
  tableReadSequence++;renderState(response);seatMessage(response.seat_action==='unchanged'?'pSeatUnchanged':response.seat_action==='moved'?'pSeatMoved':'pSeated');
  parentEvent('mahjong-seat-changed',{table:$('table').value});refreshReminders();
 }catch(error){if(error.message!=='not_authenticated')seatMessage(error.message);}
 finally{seatBusy=false;seatPending='';renderSeatCards();}
}
async function leaveTable(source='leave_button'){
 const wind=ownWind();
 if(!wind||seatBusy||swapBusy||busy||!globalContext.authReady||!globalContext.profile)return;
 if(state?.started_at&&!state?.ended_at){seatMessage('cannot_leave_started');return;}
 const matchId=state?.match_id;
 leaving=true;seatBusy=true;seatPending=wind;tableReadSequence++;seatMessage('pSeatLeaving');renderSeatCards();
 try{
  const response=await api('/api/club-tables/'+encodeURIComponent($('table').value)+'/leave',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason:source,match_id:matchId})});
  tableReadSequence++;swapRequests=[];hideSwapDialog();renderState(response.table_state);renderSwapUi();seatMessage('pSeatLeft');
  parentEvent('mahjong-seat-changed',{table:$('table').value});refreshReminders();
 }catch(error){if(error.message!=='not_authenticated')seatMessage(error.message);}
 finally{leaving=false;seatBusy=false;seatPending='';renderSeatCards();}
}
$('leave-table').onclick=()=>leaveTable();
function resumeSeatChoice(){
 const wind=globalContext.pendingSeat;
 if(resumeConsumed||!globalContext.authReady||!globalContext.profile||!state||seatBusy||!winds.includes(wind))return;
 resumeConsumed=true;parentEvent('mahjong-seat-resume-consumed',{table:$('table').value});
 // Resuming a login is an intent to sit, never an implicit click-to-leave.
 if(ownWind()===wind){seatMessage('pSeatUnchanged');return;}
 chooseSeat(wind);
}
async function refresh(){
 if(!globalContext.authReady||!$('table').value||seatBusy||swapBusy||tableLoading)return;
 tableLoading=true;const sequence=++tableReadSequence;
 try{
  const path=globalContext.profile?'/api/tables/'+encodeURIComponent($('table').value)+'/seat-swap-requests':'/api/club-tables/'+encodeURIComponent($('table').value)+'/seat-map';
  let data;try{data=await api(path);}catch(error){if(globalContext.profile&&error.message==='fixed_tournament_seating')data={requests:[],table_state:await api('/api/tables/'+encodeURIComponent($('table').value))};else throw error;}
  if(sequence!==tableReadSequence||seatBusy||swapBusy)return;
  if(globalContext.profile){updateSwaps(data);renderState(data.table_state);}else renderState(data);resumeSeatChoice();
 }catch(error){if(sequence===tableReadSequence&&!lastResult&&error.message!=='not_authenticated')seatMessage(error.message);}
 finally{tableLoading=false;}
}
function windName(wind){return t('wind'+winds.indexOf(wind));}
function swapNow(){return Date.now()+swapClockOffset;}
function pendingSwap(){return swapRequests.find(request=>request.status==='pending'&&Date.parse(request.expires_at)>swapNow());}
function updateSwaps(data){
 if(data.server_now)swapClockOffset=Date.parse(data.server_now)-Date.now();
 if(data.requests)swapRequests=data.requests;
 else if(data.request)swapRequests=[data.request,...swapRequests.filter(request=>request.id!==data.request.id)];
 renderSwapUi();
}
function hideSwapDialog(){
 swapDialog=null;
 if($('seat-swap-dialog').open)$('seat-swap-dialog').close();
 if(winds.includes(swapReturnWind)){
  const button=$('players').querySelector('[data-seat-card="'+swapReturnWind+'"]');
  if(button&&!button.disabled)button.focus({preventScroll:true});
 }
 swapReturnWind=null;
}
function showSwapDialog(mode,request){
 const wasOpen=$('seat-swap-dialog').open;
 if(!wasOpen)swapReturnWind=$('players').contains(document.activeElement)?document.activeElement.dataset.seatCard:null;
 swapDialog={mode,request};$('swap-error').textContent='';renderSwapDialog();
 if(!wasOpen){$('seat-swap-dialog').showModal();$(mode==='incoming'?'swap-decline':'swap-back').focus({preventScroll:true});parentEvent('mahjong-seat-swap-open',{table:$('table').value});}
}
function renderSwapDialog(){
 if(!swapDialog)return;
 const {mode,request}=swapDialog,incoming=mode==='incoming';
 $('swap-title').textContent=t(incoming?'swapReceiveTitle':'swapConfirmTitle');
 $('swap-note').textContent=t(incoming?'swapReceiveNote':'swapConfirmNote',{name:request.requester.name});
 $('swap-requester-change').textContent=t('swapSeatChange',{name:request.requester.name,from:windName(request.requester.seat),to:windName(request.target.seat)});
 $('swap-target-change').textContent=t('swapSeatChange',{name:request.target.name,from:windName(request.target.seat),to:windName(request.requester.seat)});
 $('swap-countdown').textContent=incoming?t('swapCountdown',{seconds:Math.max(0,Math.ceil((Date.parse(request.expires_at)-swapNow())/1000))}):'';
 for(const id of ['swap-back','swap-send','swap-decline','swap-accept']){
  $(id).hidden=incoming?['swap-back','swap-send'].includes(id):['swap-decline','swap-accept'].includes(id);
  $(id).disabled=swapBusy;
 }
 $('seat-swap-dialog').setAttribute('aria-busy',String(swapBusy));
}
function renderSwapUi(){
 const pending=pendingSwap(),latest=swapRequests[0];
 if(pending){
  const incoming=String(pending.target.id)===String(globalContext.profile?.id);
  $('swap-status').textContent=t(incoming?'swapIncoming':'swapPending',{name:incoming?pending.requester.name:pending.target.name})+' '+t('swapCountdown',{seconds:Math.max(0,Math.ceil((Date.parse(pending.expires_at)-swapNow())/1000))});
  if(incoming&&pending.can_accept){
   if(swapDialog?.mode!=='incoming'||swapDialog.request.id!==pending.id)showSwapDialog('incoming',pending);
   else{swapDialog.request=pending;renderSwapDialog();}
  }
 }else{
  const status=latest?.status==='pending'?'expired':latest?.status;
  const keys={accepted:'swapAccepted',declined:'swapDeclined',expired:'swapExpired',cancelled:'swapCancelled',invalidated:'swapInvalidated'};
  $('swap-status').textContent=keys[status]?t(keys[status]):'';
  if(swapDialog?.mode==='incoming'&&!swapBusy)hideSwapDialog();
 }
 if(swapDialog?.mode==='compose'){
  const request=swapDialog.request;
  if(ownWind()!==request.requester.seat||state?.players?.[request.target.seat]?.id!==request.target.id||state?.started_at||pending){hideSwapDialog();}
  else{request.requester.name=state.players[request.requester.seat].name;request.target.name=state.players[request.target.seat].name;renderSwapDialog();}
 }
}
function confirmSwap(wind){
 const own=ownWind(),other=state?.players?.[wind];
 if(!own||!other||!other.id||own===wind)return;
 showSwapDialog('compose',{requester:{id:String(globalContext.profile.id),name:state.players[own].name,seat:own},target:{id:String(other.id),name:other.name,seat:wind}});
}
async function submitSwap(action){
 if(swapBusy||!swapDialog)return;
 const context=swapDialog,request=context.request;
 if(context.mode==='incoming'&&!pendingSwap()){hideSwapDialog();renderSwapUi();return;}
 swapBusy=true;tableReadSequence++;$('swap-error').textContent='';renderSwapDialog();renderSeatCards();
 try{
  const path=action==='send'?'/api/tables/'+encodeURIComponent($('table').value)+'/seat-swap-requests':'/api/seat-swap-requests/'+encodeURIComponent(request.id)+'/'+action;
  const payload=action==='send'?{target_user_id:request.target.id,match_id:state.match_id}:{};
  const data=await api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  tableReadSequence++;hideSwapDialog();updateSwaps(data);renderState(data.table_state);
  parentEvent('mahjong-seat-changed',{table:$('table').value});refreshReminders();
 }catch(error){
  if(error.message!=='not_authenticated'){
   seatMessage(error.message);$('swap-error').textContent=t(error.message);
   if(['swap_expired','swap_invalidated','swap_not_pending','swap_target_not_at_table','table_already_started','table_closed'].includes(error.message))hideSwapDialog();
  }
 }finally{swapBusy=false;renderSwapDialog();renderSeatCards();refresh();}
}
$('swap-send').onclick=()=>submitSwap('send');
$('swap-accept').onclick=()=>submitSwap('accept');
$('swap-decline').onclick=()=>submitSwap('decline');
$('swap-back').onclick=()=>{if(!swapBusy)hideSwapDialog();};
$('seat-swap-dialog').addEventListener('cancel',event=>{event.preventDefault();if(swapDialog?.mode==='compose'&&!swapBusy)hideSwapDialog();});
function reservationRange(item){const format=(month,day,time)=>t('reservationReminderTime',{month,day,time});const start=format(item.local_month,item.local_day,item.local_time);return item.end_local_time?t('reservationRangeDisplay',{start,end:format(item.end_local_month,item.end_local_day,item.end_local_time)}):start;}
function renderReminders(){
 const container=$('reservation-reminders'),items=reminderData?.reminders||[];
 const folded=new Set([...container.querySelectorAll('[data-reservation-reminder]:not([open])')].map(node=>node.dataset.reservationReminder));
 const expandedPersonal=new Set([...container.querySelectorAll('.reservation-personal[open]')].map(node=>node.closest('[data-reservation-reminder]').dataset.reservationReminder));
 const focusPersonal=Boolean(document.activeElement?.parentElement?.classList.contains('reservation-personal'));
 const focused=document.activeElement?.closest?.('[data-reservation-reminder]');
 const focusId=focused&&container.contains(document.activeElement)?focused.dataset.reservationReminder:null;
 container.replaceChildren();container.hidden=!items.length;
 if(!items.length)return;
 const heading=document.createElement('h2');heading.textContent=t('reservationReminderTitle');container.append(heading);
 for(const item of items){
  const group=document.createElement('details');group.className='reservation-reminder';group.dataset.reservationReminder=item.id;group.dataset.allSeated=String(item.all_seated);group.open=!folded.has(String(item.id));
  const summary=document.createElement('summary');summary.textContent=reservationRange(item)+' · '+t('ordinaryTable',{table:item.table_number||reminderData.table_number})+(item.all_seated?' · '+t('reservationAllSeated'):'');group.append(summary);
  const list=document.createElement('ul');
  for(const person of item.participants){
   const row=document.createElement('li');row.dataset.reservationParticipant='';row.dataset.seated=String(person.seated);row.dataset.seat=person.seat||'';
   const name=document.createElement('strong');name.textContent=person.name;
   row.append(AccountAvatars.element({name:person.name,src:person.avatar,size:24,decorative:true}),name,document.createTextNode(' · '+(person.seated?t('reservationSeated',{seat:windName(person.seat)}):t('reservationWaiting'))));list.append(row);
  }
  group.append(list);
  if(item.reservations?.length){const details=document.createElement('details');details.className='reservation-personal';details.open=expandedPersonal.has(String(item.id));const heading=document.createElement('summary');heading.textContent=t('reservationPersonalDetails');details.append(heading);for(const reservation of item.reservations){const line=document.createElement('p');line.textContent=reservationRange(reservation)+' · '+(reservation.participants||[]).map(person=>person.name).join(', ');details.append(line);}group.append(details);}
  container.append(group);
  if(focusId===String(item.id))(focusPersonal?group.querySelector('.reservation-personal > summary')||summary:summary).focus({preventScroll:true});
 }
}
async function refreshReminders(){
 if(!globalContext.authReady||!globalContext.profile||!$('table').value||reminderLoading)return;
 reminderLoading=true;const sequence=++reminderSequence;
 try{const data=await api('/api/club-tables/'+encodeURIComponent($('table').value)+'/reservation-reminders');if(sequence===reminderSequence){reminderData=data;reminderClockOffset=Date.parse(data.server_now)-Date.now();renderReminders();}}
 catch{}finally{reminderLoading=false;}
}
async function boot(){
 try{
 if(location.pathname==='/sit'&&query.get('seat')&&!seated){
  await api('/api/sit?'+new URLSearchParams({table:$('table').value,seat:query.get('seat')}),{method:'POST'});seated=true;message('pSeated');
  history.replaceState(null,'',scoreUrl(new URLSearchParams({table:$('table').value})));
 }
 await refresh();
 if(query.get('draft_id')){const data=await api('/api/score_drafts/'+encodeURIComponent(query.get('draft_id')));if(data.draft_status==='submitted')message('pAlreadySaved');else showReview(data);}
 const saved=localStorage.getItem('score-result-'+$('table').value);
 if(saved){lastResult=JSON.parse(saved);renderResult();await refreshSync();}
 }catch(error){if(error.message!=='not_authenticated')message(error.message);}
}
function unitText(data){return t(data.normalization?.multiplier===100?'pHundreds':'pFullPoints');}
function renderReviewLabels(){
 $('review-reason').textContent=t('pCheckScores')+' · '+unitText(draft);
 [...$('score-fields').children].forEach((label,i)=>label.querySelector('span').textContent=t('wind'+i)+' · '+(draft.players[winds[i]]?.name||''));
}
function showReview(data){
 draft=data;$('review').classList.remove('hidden');$('score-fields').replaceChildren();
 let saved={};try{saved=JSON.parse(localStorage.getItem('score-inputs-'+data.draft_id)||'{}');}catch{}
 winds.forEach((wind,i)=>{
 const label=document.createElement('label'),span=document.createElement('span'),input=document.createElement('input');
 input.name=wind;input.type='number';input.step='100';input.required=true;input.value=saved[wind]??data.scores[wind]??'';
 input.addEventListener('input',()=>{showTotal();localStorage.setItem('score-inputs-'+draft.draft_id,JSON.stringify(Object.fromEntries([...new FormData($('confirm'))])));});
 label.append(span,input);$('score-fields').append(label);
 });
 renderReviewLabels();showTotal();message('pCheckScores');
 history.replaceState(null,'',scoreUrl(new URLSearchParams({table:data.table,draft_id:data.draft_id})));parentEvent('mahjong-score-draft',{draft_id:data.draft_id});
}
function showTotal(){$('total').textContent=[...$('score-fields').querySelectorAll('input')].reduce((sum,input)=>sum+Number(input.value),0);}
function renderResult(){
 if(!lastResult?.result)return;
 $('result').classList.remove('hidden');
 const result=lastResult.result;
 $('result-text').textContent=unitText(lastResult)+'\n'+t('ordinaryTable',{table:result.table_name||result.table})+' · '+duration(result.duration_seconds)+'\n'+
 winds.map((wind,i)=>{const p=result.players[wind];return t('wind'+i)+' '+p.user.name+'：'+p.final_points+' '+t('pPoints')+' / '+(p.net_score>=0?'+':'')+p.net_score;}).join('\n');
 const sync=lastResult.external_sync;
 $('external-status').textContent=t('externalResult')+': '+(sync?t(sync.status):t('disabled'))+(sync?.error_code?' · '+t(MahjongI18n.entries[sync.error_code]?sync.error_code:'requestFailed'):'');
 $('retry-sync').hidden=!sync||!['failed','pending'].includes(sync.status);
 $('local-status').textContent=t('localSaved');
}
function showResponse(data){
 if(data.status==='needs_review'){showReview(data);return;}
 $('review').classList.add('hidden');if(draft)localStorage.removeItem('score-inputs-'+draft.draft_id);draft=null;
 lastResult=data;localStorage.setItem('score-result-'+data.result.table,JSON.stringify(data));renderResult();message('pSaved');
 history.replaceState(null,'',scoreUrl(new URLSearchParams({table:data.result.table})));parentEvent('mahjong-score-saved');refresh();
}
async function refreshSync(){
 const snapshot=lastResult;if(!snapshot?.result)return;
 // Cached score results retain stable IDs; refresh only their display names.
 try{
  const ids=winds.map(wind=>snapshot.result.players[wind]?.user?.id).filter(Boolean);
  const data=await api('/api/registered-users?'+new URLSearchParams({ids:ids.join(',')}));
  if(lastResult!==snapshot)return;
  const names=new Map((data.users||[]).map(user=>[String(user.id),user.name]));
  winds.forEach(wind=>{const user=snapshot.result.players[wind]?.user;if(user&&names.has(String(user.id)))user.name=names.get(String(user.id));});
 }catch{}
 const key=snapshot.external_sync?.request_id;
 if(key){try{const sync=await api('/api/external-deliveries/'+encodeURIComponent(key));if(lastResult!==snapshot)return;snapshot.external_sync=sync;}catch{}}
 if(lastResult!==snapshot)return;
 localStorage.setItem('score-result-'+snapshot.result.table,JSON.stringify(snapshot));renderResult();
}
$('retry-sync').onclick=async()=>{
 if(busy||!lastResult?.external_sync)return;busy=true;$('retry-sync').disabled=true;
 try{lastResult.external_sync=await api('/api/external-deliveries/'+lastResult.external_sync.request_id+'/retry',{method:'POST'});localStorage.setItem('score-result-'+lastResult.result.table,JSON.stringify(lastResult));renderResult();}
 catch(e){message(e.message);}finally{busy=false;$('retry-sync').disabled=false;}
};

$('load').onclick=()=>{
 if(busy)return;photoTask=null;state=null;draft=null;lastResult=null;$('review').classList.add('hidden');$('result').classList.add('hidden');$('recognize').disabled=true;
 localStorage.setItem('score-table',$('table').value);history.replaceState(null,'',scoreUrl(new URLSearchParams({table:$('table').value})));refresh();
};
$('photo').onclick=()=>{photoTask=state?{table:state.table,match_id:state.match_id,key:taskKey()}:null;};
$('photo').onchange=()=>{
 if(previewUrl)URL.revokeObjectURL(previewUrl);const file=$('photo').files[0];if(!file)return;
 if(!photoTask){message('pOpenFirst');return;}previewUrl=URL.createObjectURL(file);$('preview').src=previewUrl;$('preview').classList.remove('hidden');$('recognize').disabled=false;
};
async function shrinkPhoto(file){
 if(file.size>25*1024*1024)throw new Error('pPhotoLarge');
 const source=URL.createObjectURL(file);
 try{const img=new Image();img.src=source;await img.decode();const ratio=Math.min(1,1920/Math.max(img.naturalWidth,img.naturalHeight));
 if(ratio===1&&file.size<=2*1024*1024)return file;const canvas=document.createElement('canvas');canvas.width=Math.round(img.naturalWidth*ratio);canvas.height=Math.round(img.naturalHeight*ratio);canvas.getContext('2d').drawImage(img,0,0,canvas.width,canvas.height);
 const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.92));if(!blob)throw new Error('pPhotoFailed');return blob;}finally{URL.revokeObjectURL(source);}
}
$('recognize').onclick=async()=>{
 if(busy||!photoTask)return;busy=true;$('recognize').disabled=true;
 try{const form=new FormData();form.append('file',await shrinkPhoto($('photo').files[0]),'score.jpg');form.append('table',photoTask.table);form.append('match_id',photoTask.match_id);form.append('review_only','true');
 message('pRecognizing');showResponse(await api('/api/recognize_photo',{method:'POST',headers:{'Idempotency-Key':photoTask.key},body:form}));photoTask=null;}
 catch(e){message(e.message);}finally{busy=false;$('recognize').disabled=!photoTask;}
};
$('manual').onclick=()=>{window.top.location.assign('/manual-score'+($('table').value?'?table='+encodeURIComponent($('table').value):''));};
$('confirm').onsubmit=async event=>{
 event.preventDefault();if(busy||!draft)return;
 const scores=Object.fromEntries([...new FormData(event.target)].map(([key,value])=>[key,Number(value)]));
 if(!window.confirm(t('confirmScore')+'\n'+t('table')+' '+draft.table+'\n'+winds.map((wind,i)=>t('wind'+i)+' '+(draft.players[wind]?.name||'')+': '+scores[wind]).join('\n')))return;
 busy=true;
 try{showResponse(await api('/api/confirm_scores',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({draft_id:draft.draft_id,scores})}));}
 catch(e){message(e.message);}finally{busy=false;}
};
applyLanguage(language);setInterval(()=>{tick();renderSwapUi();if(reminderData?.reminders.some(item=>Date.parse(item.expires_at)<Date.now()+reminderClockOffset)){reminderData.reminders=reminderData.reminders.filter(item=>Date.parse(item.expires_at)>=Date.now()+reminderClockOffset);renderReminders();}},1000);setInterval(()=>{if(!seatBusy&&!swapBusy)refresh();refreshReminders();},2000);setInterval(()=>{if(!busy&&globalContext.profile)refreshSync();},10000);parentEvent('mahjong-score-ready');boot();
