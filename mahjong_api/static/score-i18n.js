Object.assign(MahjongI18n.entries,{
flowFinalScore:['终局登分','Final Score'],flowScoreTarget:['登分对局','Game to Score'],flowCurrentGame:['当前对局','Current game'],flowPendingGame:['上一局待登分','Previous game awaiting scores'],flowNoGame:['当前没有可操作的对局。','No active game to manage.'],flowAllLastStatus:['本局已标记 All Last，下一批可准备入座。','All Last recorded. The next group may prepare.'],flowAllLastSaved:['All Last 已记录。','All Last saved.'],flowCancelGame:['取消对局','Cancel Game'],flowCancelGameHint:['开局后、成绩提交前，桌上玩家可以取消本局并重新入座。','Seated players can cancel an unscored game and reseat before scores are submitted.'],flowCancelGameConfirm:['确认停止并取消这场尚未提交成绩的对局？四个座位将清空，预约局数会恢复。','Stop and cancel this game before scores are submitted? All four seats will clear and reservation game counts will be restored.'],flowCancelGameSaved:['对局已取消，四个座位已清空。','Game canceled. All four seats are clear.'],flowCancelling:['正在取消对局…','Canceling game…'],seatActionTitle:['座位操作','Seat actions'],seatActionSwap:['请求交换座位','Request seat swap'],seatActionRemove:['让对方下桌','Remove player from table'],seatActionRemoved:['玩家已下桌。','Player removed from the table.'],seatActionConfirm:['确认让 {name} 从 {seat} 位下桌？','Remove {name} from the {seat} seat?'],seatActionStartedPending:['对局进行中，暂不能让他人下桌；如需取消本局，请使用“取消对局”。','The game is in progress. To cancel it, use Cancel Game.'],seatActionJoinFirst:['请先在这张桌子入座。','Take a seat at this table first.'],pRecognize:['重新识别','Recognize Again'],pReview:['核对识别结果','Check Recognized Scores'],pReviewNote:['系统已自动识别点数。请检查或修改四家的完整点数；确认提交后成绩将锁定。','Scores were recognized automatically. Check or edit all four scores before submitting; submitted scores are locked.'],pCheckScores:['识别完成，已进入登分。请核对四家分数后确认提交，无需管理员审核。','Recognition is ready. Check all four scores and confirm submission. No administrator approval is needed.']
});
Object.assign(MahjongI18n.entries,{
 pSelectPhoto:['选择照片识别','Choose Photo to Recognize'],
 pSelectPhotoAgain:['重新选择照片识别','Choose Photo to Recognize Again'],
 pReview:['修正分数','Correct Scores'],
 pReviewNote:['识别或分数校验出现异常，本局尚未登分。请按照片修正完整点数，或重新识别。','Recognition or score validation found a problem. This game has not been saved. Correct the full scores from the photo or recognize again.'],
 pCheckScores:['识别或分数校验出现异常，请修正后提交。','Recognition or score validation found a problem. Correct the scores and submit.'],
 pCloseReview:['稍后处理','Review Later'],
 pRawDetails:['查看原始读数与单位','View original readings and units'],
 pReviewValid:['总分和分数步长正确，可以提交。','The total and score increments are valid. You can submit.'],
 pIssueLeadingDigit:['{position}按百点显示读取时，首位无法确定为负号、0 或 1，请按照片修正。','For the hundreds display at {position}, the first character could not be confirmed as a minus sign, 0 or 1. Correct it from the photo.'],
 pOcrNote:['自动区分完整点数与百点显示（例如 300 → 30000）。识别和校验通过后自动登分；仅在异常时弹出修正窗口。','Full points and hundreds are detected automatically (for example, 300 → 30,000). Valid results are saved automatically. A correction window opens only when a problem is found.']
});
const $=id=>document.getElementById(id),winds=['east','south','west','north'];
const query=new URLSearchParams(location.search),embedded=query.get('embedded')==='1';
let language=localStorage.getItem('mahjong_lang')||'EN';
const t=(key,vars)=>MahjongI18n.t(language,key,vars);
$('table').value=query.get('table')||'';
let state=null,snapshotAt=0,draft=null,photoTask=null,previewUrl=null,busy=false,seated=false,lastResult=null,messageKey='',messageVars={};
let reviewPending=false;
// The host supplies its existing global account. This frame never loads or stores a session.
let globalContext={profile:null,authReady:false,entryToken:null,pendingSeat:''};
let leaving=false,seatBusy=false,seatPending='',seatMessageKey='',seatMessageVars={},tableReadSequence=0,tableLoading=false,resumeConsumed=false;
let swapRequests=[],swapDialog=null,swapBusy=false,swapClockOffset=0,swapReturnWind=null,reminderData=null,reminderLoading=false,reminderSequence=0,reminderClockOffset=0;
let flowState=null,flowLoadedAt=0,flowLoading=false,scoreTargetId=query.get("match_id")||"",seatActionWind=null;
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
 if(draft){renderReviewLabels();renderOcrReadout(draft);showTotal();}
 if(lastResult)renderResult();
 renderReminders();renderSwapUi();renderFlow();renderPhotoControls();
 
}

window.addEventListener('message',event=>{
 if(event.origin!==location.origin||event.source!==parent)return;
 if(event.data?.type==='mahjong-language')applyLanguage(event.data.language);
 if(event.data?.type==='mahjong-score-review-ready'&&reviewPending&&draft){reviewPending=false;displayReview();}
 if(event.data?.type==='mahjong-table-changed'&&!busy&&!seatBusy){refresh();}
 if(event.data?.type==='mahjong-score-context'&&event.data.table===$('table').value){
  const previousId=globalContext.profile?.id,previousReady=globalContext.authReady;
  globalContext={profile:event.data.profile||null,authReady:Boolean(event.data.authReady),entryToken:event.data.entryToken||null,pendingSeat:event.data.pendingSeat||''};
  if(previousId!==globalContext.profile?.id){tableReadSequence++;state=null;swapRequests=[];reminderData=null;reminderSequence++;flowState=null;scoreTargetId="";hideSwapDialog();renderReminders();renderFlow();}
  renderSeatCards();
  if(previousId!==globalContext.profile?.id||previousReady!==globalContext.authReady){refresh().then(resumeSeatChoice);}
  else resumeSeatChoice();
 }
});
if(embedded){
 document.querySelector('main>a').hidden=true;document.querySelector('h1').hidden=true;document.body.style.background='transparent';document.querySelector('main').style.padding='0';
 new ResizeObserver(()=>parentEvent('mahjong-score-height',{height:Math.ceil(document.querySelector('main').getBoundingClientRect().height)})).observe(document.querySelector('main'));
}
function taskKey(){return MahjongI18n.key();}
function message(key,vars={}){messageKey=key;messageVars=vars;$('message').textContent=t(key,vars);$('review-message').textContent=!draft||key==='pCheckScores'?'':t(key,vars);}
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
 if(seatActionWind&&(!data.players?.[seatActionWind]||data.players[seatActionWind].id!==$("seat-action-dialog").dataset.targetId))hideSeatAction();
 $('round').textContent=t('ordinaryTable',{table:data.display_name||data.table});
 $('started').textContent=data.started_at?new Date(data.started_at).toLocaleString():t('pWaitingFour');
 $('average').textContent=duration(data.average_duration_seconds);renderSeatCards();renderPhotoViewpoint();
 tick();
}
function tick(){if(!state)return;const elapsed=state.elapsed_seconds===null?null:state.elapsed_seconds+(state.ended_at?0:Math.floor((performance.now()-snapshotAt)/1000));$('elapsed').textContent=duration(elapsed);}
function seatMessage(key,vars={}){seatMessageKey=key;seatMessageVars=vars;$('seat-message').textContent=key?t(key,vars):'';}
function ownWind(){return winds.find(wind=>globalContext.profile&&state?.players?.[wind]?.id===String(globalContext.profile.id));}
function renderSeatCards(){
 const current=ownWind(),locked=Boolean(state?.started_at),container=$('players');
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
  button.disabled=seatBusy||swapBusy||!ready||(locked&&!occupied&&!mine);button.setAttribute('aria-pressed',String(mine));button.setAttribute('aria-busy',String(seatBusy&&seatPending===wind));
  const title=button.querySelector('strong'),name=button.querySelector('.seat-name'),action=button.querySelector('.seat-action');
  title.textContent=t('wind'+index);const playerLabel=!ready?t('pSeatLoading'):person?(person.name||t('pSeatOccupied')):t('pSeatEmpty');
  const nameSignature=JSON.stringify([playerLabel,ready&&person?.name,person?.avatar]);
  if(button._seatNameSignature!==nameSignature){
   button._seatNameSignature=nameSignature;const nameLabel=document.createElement('span');nameLabel.textContent=playerLabel;name.replaceChildren(nameLabel);
   if(ready&&person?.name)name.prepend(AccountAvatars.element({name:person.name,src:person.avatar,size:24,decorative:true}));
  }
  const key=seatBusy&&seatPending===wind?(leaving?'pSeatLeaving':'pSeatSaving'):!ready?'pSeatLoading':mine?(locked?'flowCancelGame':'pSeatLeave'):occupied?'seatActionTitle':locked?'pSeatLocked':current?'pSeatMove':'pSeatJoin';
  action.textContent=t(key);button.setAttribute('aria-label',title.textContent+' · '+playerLabel+' · '+action.textContent);
 });
 const leave=$('leave-table');
 leave.disabled=seatBusy||swapBusy||busy||!current||!globalContext.authReady;
 leave.textContent=t(leaving?(locked?'flowCancelling':'pSeatLeaving'):(locked?'flowCancelGame':'pSeatLeaveButton'));leave.setAttribute('aria-busy',String(leaving));
 $('leave-hint').textContent=t(current?(locked?'flowCancelGameHint':'pSeatLeaveHint'):'pSeatNotSeated');
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
 if(state?.players?.[wind]){showSeatAction(wind);return;}
 seatBusy=true;seatPending=wind;tableReadSequence++;seatMessage('pSeatSaving');renderSeatCards();
 try{
  const payload={seat:wind};if(state?.match_id)payload.match_id=state.match_id;if(globalContext.entryToken)payload.entry_token=globalContext.entryToken;
  const response=await api('/api/club-tables/'+encodeURIComponent($('table').value)+'/my-seat',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),seatIntent:wind});
  tableReadSequence++;renderState(response);seatMessage(response.seat_action==='unchanged'?'pSeatUnchanged':response.seat_action==='moved'?'pSeatMoved':'pSeated');
  parentEvent('mahjong-seat-changed',{table:$('table').value});refreshReminders();
 }catch(error){if(error.message!=='not_authenticated')seatMessage(error.message);}
 finally{seatBusy=false;seatPending='';renderSeatCards();}
}
async function cancelGame(){
 const match_id=state?.match_id,table=$('table').value;
 if(!match_id||seatBusy||swapBusy||busy||!ownWind()||!globalContext.authReady)return;
 if(!window.confirm(t('flowCancelGameConfirm')))return;
 const storageKey='mahjong-cancel-game:'+table+':'+match_id;
 let request_id=sessionStorage.getItem(storageKey);
 if(!request_id){request_id=taskKey();sessionStorage.setItem(storageKey,request_id);}
 leaving=true;seatBusy=true;seatPending=ownWind();tableReadSequence++;seatMessage('flowCancelling');renderSeatCards();
 let cancelled=false;
 try{
  await api('/api/club-tables/'+encodeURIComponent(table)+'/cancel-game',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({match_id,request_id,reason:'wrong_players'})});
  cancelled=true;sessionStorage.removeItem(storageKey);swapRequests=[];hideSwapDialog();seatMessage('flowCancelGameSaved');
  parentEvent('mahjong-seat-changed',{table});
 }catch(error){if(error.message!=='not_authenticated')seatMessage(error.message);}
 finally{leaving=false;seatBusy=false;seatPending='';renderSeatCards();await refresh();await refreshGameFlow(true);if(cancelled)refreshReminders();}
}
async function leaveTable(source='leave_button'){
 const wind=ownWind();
 if(!wind||seatBusy||swapBusy||busy||!globalContext.authReady||!globalContext.profile)return;
 if(state?.started_at){if(winds.every(seat=>state.players?.[seat]))return cancelGame();seatMessage('cannot_leave_started');return;}
 const matchId=state?.match_id;
 leaving=true;seatBusy=true;seatPending=wind;tableReadSequence++;seatMessage('pSeatLeaving');renderSeatCards();
 try{
  const response=await api('/api/club-tables/'+encodeURIComponent($('table').value)+'/leave',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason:source,match_id:matchId})});
  tableReadSequence++;swapRequests=[];hideSwapDialog();renderState(response.table_state);renderSwapUi();seatMessage('pSeatLeft');
  parentEvent('mahjong-seat-changed',{table:$('table').value});refreshReminders();
 }catch(error){if(error.message!=='not_authenticated')seatMessage(error.message);}
 finally{leaving=false;seatBusy=false;seatPending='';renderSeatCards();}
}
function hideSeatAction(){seatActionWind=null;if($('seat-action-dialog').open)$('seat-action-dialog').close();}
function showSeatAction(wind){
 const person=state?.players?.[wind];if(!person||!globalContext.profile)return;
 seatActionWind=wind;const dialog=$('seat-action-dialog');dialog.dataset.targetId=String(person.id);
 $('seat-action-target').textContent=person.name+' · '+windName(wind);$('seat-action-error').textContent='';
 $('seat-action-swap').disabled=!ownWind()||Boolean(state?.started_at)||Boolean(pendingSwap());
 $('seat-action-remove').disabled=Boolean(state?.started_at)||Boolean(state?.pending_match_id);if(state?.started_at)$('seat-action-error').textContent=t('seatActionStartedPending');dialog.showModal();$('seat-action-cancel').focus({preventScroll:true});parentEvent('mahjong-seat-action-open',{table:$('table').value});
}
$('seat-action-cancel').onclick=hideSeatAction;
$('seat-action-dialog').addEventListener('cancel',event=>{event.preventDefault();hideSeatAction();});
$('seat-action-swap').onclick=()=>{const wind=seatActionWind;hideSeatAction();if(wind)confirmSwap(wind);};
$('seat-action-remove').onclick=async()=>{
 const wind=seatActionWind,person=state?.players?.[wind];if(!wind||!person||seatBusy)return;
 if(!window.confirm(t('seatActionConfirm',{name:person.name,seat:windName(wind)})))return;
 seatBusy=true;$('seat-action-remove').disabled=true;
 try{await api('/api/club-tables/'+encodeURIComponent($('table').value)+'/seats/'+encodeURIComponent(person.id)+'/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({match_id:state.match_id,seat:wind})});hideSeatAction();seatMessage('seatActionRemoved');parentEvent('mahjong-seat-changed',{table:$('table').value});await refreshGameFlow(true);}
 catch(error){$('seat-action-error').textContent=t(error.message||'requestFailed');}
 finally{seatBusy=false;$('seat-action-remove').disabled=false;renderSeatCards();refresh();}
};
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
  const path=globalContext.profile?'/api/scoring/current-table-context?table='+encodeURIComponent($('table').value):'/api/club-tables/'+encodeURIComponent($('table').value)+'/seat-map';
  let data;try{data=await api(path);}catch(error){if(globalContext.profile&&error.message==='fixed_tournament_seating')data={requests:[],table_state:await api('/api/tables/'+encodeURIComponent($('table').value))};else throw error;}
  if(sequence!==tableReadSequence||seatBusy||swapBusy)return;
  if(data.reservation_context){reminderData=data.reservation_context;reminderClockOffset=Date.parse(reminderData.server_now)-Date.now();renderReminders();}
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
function flowGameId(game){return String(game?.game_id||game?.match_id||game?.id||'');}
function flowPlayers(game){const players=game?.players||{};return winds.map((wind,index)=>{const person=Array.isArray(players)?players[index]:players[wind];return person?windName(wind)+' '+(person.name||person.user?.name||person.user_name||''):'';}).filter(Boolean).join(' · ');}
function flowChoices(){const current=flowState?.current_game,pending=flowState?.pending_scores||[];return [...(current?[current]:[]),...pending].filter((game,index,all)=>flowGameId(game)&&all.findIndex(other=>flowGameId(other)===flowGameId(game))===index);}
function renderFlow(){
 const current=flowState?.current_game,choices=flowChoices(),currentId=flowGameId(current);
 $('flow-status').textContent=current?.all_last_at?t('flowAllLastStatus'):'';
 $('all-last').disabled=busy||!current||current.status!=='playing'||Boolean(current.all_last_at)||Boolean(current.actual_ended_at)||!globalContext.profile;
 const selector=$('score-target'),available=new Set(choices.map(flowGameId));if(!available.has(scoreTargetId))scoreTargetId=currentId||flowGameId(choices[0]);
 const signature=choices.map(game=>flowGameId(game)).join('|')+':'+language;if(selector.dataset.signature!==signature){selector.dataset.signature=signature;selector.replaceChildren();for(const game of choices){const option=document.createElement('option');option.value=flowGameId(game);option.textContent=(flowGameId(game)===currentId?t('flowCurrentGame'):t('flowPendingGame'))+' · '+(game.started_at?new Date(game.started_at).toLocaleString():'');selector.append(option);}}
 selector.value=scoreTargetId;selector.disabled=!choices.length;$('score-target-label').hidden=choices.length<=1;
 const selected=choices.find(game=>flowGameId(game)===scoreTargetId);$('score-target-players').textContent=flowPlayers(selected)||flowPlayers({players:state?.players});
 renderPhotoViewpoint();
 renderSeatCards();
}
async function refreshGameFlow(force=false){
 if(!globalContext.profile||!$('table').value||flowLoading||(!force&&Date.now()-flowLoadedAt<5000))return;
 flowLoading=true;try{flowState=await api('/api/club-tables/'+encodeURIComponent($('table').value)+'/game-flow');flowLoadedAt=Date.now();renderFlow();}catch(error){$('flow-status').textContent=t(error.message||'requestFailed');}finally{flowLoading=false;}
}
$('score-target').onchange=event=>{if(scoreTargetId===event.target.value)return;scoreTargetId=event.target.value;++photoSequence;photoTask=null;photoSelectionContext=null;preparedPhoto=null;photoPreparing=false;$('photo').value='';if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl=null;$('preview').classList.add('hidden');draft=null;lastResult=null;closeReview();$('result').classList.add('hidden');renderFlow();renderPhotoControls();};
$('all-last').onclick=async()=>{const match_id=flowGameId(flowState?.current_game);if(busy||!match_id)return;busy=true;renderFlow();try{flowState=await api('/api/club-tables/'+encodeURIComponent($('table').value)+'/all-last',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({match_id})});message('flowAllLastSaved');renderFlow();await refreshGameFlow(true);}catch(error){message(error.message);}finally{busy=false;renderFlow();}};
function reservationRange(item){return t('reservationReminderTime',{month:item.local_month,day:item.local_day,time:item.local_time});}
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
async function refreshReminders(){return refresh();}

async function boot(){
 try{
 if(location.pathname==='/sit'&&query.get('seat')&&!seated){
  await api('/api/sit?'+new URLSearchParams({table:$('table').value,seat:query.get('seat')}),{method:'POST'});seated=true;message('pSeated');
  history.replaceState(null,'',scoreUrl(new URLSearchParams({table:$('table').value})));
 }
 await refresh();await refreshGameFlow(true);
 if(query.get('draft_id')){const data=await api('/api/score_drafts/'+encodeURIComponent(query.get('draft_id')));if(data.draft_status==='submitted')message('pAlreadySaved');else showReview(data);}
 const saved=localStorage.getItem('score-result-'+$('table').value);
 if(saved){lastResult=JSON.parse(saved);renderResult();await refreshSync();}
 }catch(error){if(error.message!=='not_authenticated')message(error.message);}
}
function unitText(data){return t(data.normalization?.multiplier===100?'pHundreds':'pFullPoints');}
function unitExplanation(data){
 const normalization=data.normalization||{};
 if(normalization.multiplier===100){
  if(normalization.unit_inferred_from==='total')return t('pUnitHundredsTotal',{total:Number(normalization.raw_total||0).toLocaleString()});
  return t('pUnitHundredsPreview');
 }
 return t(normalization.unit_inferred_from==='magnitude_preview'?'pUnitPointsPreview':'pUnitPoints');
}
function renderOcrReadout(data){
 const container=$('ocr-readout');container.replaceChildren();
 const rawScores=data.raw_scores||{},mapped=data.position_to_seat||{},normalized=data.scores||{};
 ['bottom','right','top','left'].forEach(position=>{
  const seat=mapped[position],seatIndex=winds.indexOf(seat),player=data.players?.[seat];
  const card=document.createElement('div');card.className='review-readout-card';
  const heading=document.createElement('strong');heading.textContent=t('pPosition'+position[0].toUpperCase()+position.slice(1));
  const owner=document.createElement('span');owner.className='muted';owner.textContent=(seatIndex>=0?t('wind'+seatIndex):'')+(player?.name?' · '+player.name:'');
  const raw=document.createElement('span');raw.className='raw-value';raw.textContent=rawScores[position]||'—';
  const converted=document.createElement('span');converted.className='converted-value';
  const suggestion=seat?normalized[seat]:null;
  converted.textContent=suggestion===null||suggestion===undefined?t('pNoCandidate'):t('pConvertedCandidate',{score:Number(suggestion).toLocaleString()});
  card.append(heading,owner,raw,converted);container.append(card);
 });
 const issues=(data.issues||[]).filter(issue=>issue.code!=='manual_confirmation_requested');
 const list=$('review-issues');list.replaceChildren();list.hidden=!issues.length;
 issues.forEach(issue=>{const item=document.createElement('li');item.textContent=reviewIssueText(data,issue);list.append(item);});
}
function reviewIssueText(data,issue){
 const position=issue.position?t('pPosition'+issue.position[0].toUpperCase()+issue.position.slice(1)):'';
 switch(issue.code){
  case 'unstable_segments':return t('pIssueUnstable');
  case 'unreadable_segments':return t('pIssueUnreadable',{position});
  case 'invalid_leading_digit':return t('pIssueLeadingDigit',{position});
  case 'invalid_digits':return t('pIssueInvalidDigits',{position,raw:data.raw_scores?.[issue.position]||'—'});
  case 'invalid_point_increment':return t('pIssueIncrement',{position});
  case 'invalid_total':return t('pIssueTotal',{total:Number(issue.total??data.total??0).toLocaleString()});
  case 'display_count':return t('pIssueDisplayCount',{found:issue.found??0});
  case 'ambiguous_display_position':return t('pIssuePosition');
  default:return issue.message||issue.code||t('pIssuePosition');
 }
}
function renderReviewLabels(){
 $('review-reason').textContent=unitExplanation(draft);
 [...$('score-fields').children].forEach((label,i)=>label.querySelector('span').textContent=t('wind'+i)+' · '+(draft.players[winds[i]]?.name||''));
}
function showReview(data){
 draft=data;$('score-fields').replaceChildren();
 let saved={};try{saved=JSON.parse(localStorage.getItem('score-inputs-'+data.draft_id)||'{}');}catch{}
 winds.forEach((wind,i)=>{
 const label=document.createElement('label'),span=document.createElement('span'),input=document.createElement('input');
 input.name=wind;input.type='text';input.inputMode='text';input.pattern='-?[0-9]+';input.required=true;input.value=saved[wind]??data.scores[wind]??'';
 input.addEventListener('input',()=>{showTotal();localStorage.setItem('score-inputs-'+draft.draft_id,JSON.stringify(Object.fromEntries([...new FormData($('confirm'))])));});
 label.append(span,input);$('score-fields').append(label);
 });
 renderReviewLabels();renderOcrReadout(data);showTotal();renderPhotoControls();$('photo-viewpoint').value=data.uploader_seat;message('pCheckScores');
 history.replaceState(null,'',scoreUrl(new URLSearchParams({table:data.table,draft_id:data.draft_id})));parentEvent('mahjong-score-draft',{draft_id:data.draft_id});
 $('review-photo').hidden=!previewUrl;if(previewUrl){$('review-photo').src=previewUrl;$('review-photo').alt=t('pPhoto');}
 openReview();
}
function displayReview(){
 if(!$('review').open){document.body.classList.add('review-open');$('review').showModal();$('review').scrollTop=0;$('score-fields').querySelector('input')?.focus({preventScroll:true});}
}
function openReview(){
 if(!draft)return;
 if(embedded&&parent!==window){reviewPending=true;parentEvent('mahjong-score-review',{table:$('table').value,open:true});}
 else displayReview();
}
function closeReview(){
 reviewPending=false;document.body.classList.remove('review-open');if($('review').open)$('review').close();
 parentEvent('mahjong-score-review',{table:$('table').value,open:false});
}
$('review').addEventListener('close',()=>{if(!$('review').open)closeReview();});
$('review').addEventListener('cancel',event=>{if(busy)event.preventDefault();});
$('review-close').onclick=()=>{if(!busy)closeReview();};
$('review-open').onclick=openReview;
function showTotal(){
 const inputs=[...$('score-fields').querySelectorAll('input')],values=inputs.map(input=>input.value.trim());
 const parsed=values.map(value=>/^-?\d+$/.test(value)?Number(value):NaN),total=parsed.every(Number.isFinite)?parsed.reduce((sum,value)=>sum+value,0):0;
 $('total').textContent=total.toLocaleString();
 let valid=parsed.length===4&&parsed.every(Number.isFinite),status='pReviewInputRequired',vars={};
 if(valid&&parsed.some(value=>Math.abs(value)>10_000_000)){valid=false;status='pReviewLimit';}
 else if(valid&&parsed.some(value=>value%100!==0)){valid=false;status='pReviewIncrement';}
 else if(valid&&total!==100000){valid=false;status='pReviewTotalMismatch';vars={total:total.toLocaleString()};}
 else if(valid)status='pReviewValid';
 $('review-validation').textContent=t(status,vars);$('review-validation').dataset.valid=String(valid);
 $('confirm-submit').disabled=busy||!valid;
 return valid;
}
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
 closeReview();if(draft)localStorage.removeItem('score-inputs-'+draft.draft_id);draft=null;photoTask=null;preparedPhoto=null;renderPhotoControls();
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
 if(busy||!lastResult?.external_sync)return;busy=true;$('retry-sync').disabled=true;renderPhotoControls();
 try{lastResult.external_sync=await api('/api/external-deliveries/'+lastResult.external_sync.request_id+'/retry',{method:'POST'});localStorage.setItem('score-result-'+lastResult.result.table,JSON.stringify(lastResult));renderResult();}
 catch(e){message(e.message);}finally{busy=false;$('retry-sync').disabled=false;renderPhotoControls();}
};

$('load').onclick=()=>{
 if(busy)return;++photoSequence;preparedPhoto=null;photoTask=null;photoPreparing=false;state=null;draft=null;lastResult=null;closeReview();$('result').classList.add('hidden');renderPhotoControls();
 localStorage.setItem('score-table',$('table').value);history.replaceState(null,'',scoreUrl(new URLSearchParams({table:$('table').value})));refresh();
};
let preparedPhoto=null,photoSelectionContext=null,photoSequence=0,photoPreparing=false,photoRecognizing=false;
function newPhotoContext(){
 const table=$('table').value,match_id=scoreTargetId||draft?.match_id||state?.match_id;
 const viewpoint_seat=$('photo-viewpoint').value;
 return table&&match_id&&winds.includes(viewpoint_seat)?{table,match_id,viewpoint_seat,key:taskKey()}:null;
}
function renderPhotoViewpoint(){
 const selected=flowChoices().find(game=>flowGameId(game)===scoreTargetId);
 const players=selected?.players||draft?.players||state?.players||{};
 const playerAt=wind=>Array.isArray(players)?players[winds.indexOf(wind)]:players[wind];
 const selector=$('photo-viewpoint');
 const context=JSON.stringify([$('table').value,scoreTargetId||state?.match_id,globalContext.profile?.id,winds.map(wind=>playerAt(wind)?.id)]);
 const previous=selector.dataset.context===context?selector.value:(draft?.uploader_seat||winds.find(wind=>String(playerAt(wind)?.id)===String(globalContext.profile?.id)&&globalContext.profile)||'');
 const signature=context+':'+language+':'+winds.map(wind=>playerAt(wind)?.name||'').join('|');
 if(selector.dataset.signature!==signature){
  selector.dataset.context=context;selector.dataset.signature=signature;selector.replaceChildren();
  const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent=t('pPhotoViewpointChoose');selector.append(placeholder);
  winds.forEach((wind,index)=>{const option=document.createElement('option'),person=playerAt(wind);option.value=wind;option.textContent=t('wind'+index)+(person?.name?' · '+person.name:'');option.disabled=!person;selector.append(option);});selector.value=previous;
 }
 selector.disabled=busy||photoPreparing;
}
function renderPhotoControls(){
 renderPhotoViewpoint();
 $('photo').disabled=busy||photoPreparing;$('recognize').disabled=busy||photoPreparing;
 $('recognize').setAttribute('aria-busy',String(photoPreparing||photoRecognizing));
 $('recognize').textContent=t(photoRecognizing?'pRecognizing':photoPreparing?'pPreparingPhoto':preparedPhoto&&photoTask?'pRecognize':draft?'pSelectPhotoAgain':'pSelectPhoto');
 $('review-retry').disabled=$('recognize').disabled;$('review-retry').textContent=$('recognize').textContent;
 $('review-close').disabled=busy||photoPreparing;$('review-open').hidden=!draft;$('review-open').disabled=busy||photoPreparing;
}
$('photo-viewpoint').onchange=()=>{
 if(busy||photoPreparing)return;
 ++photoSequence;photoSelectionContext=null;photoTask=newPhotoContext();
 if(draft){draft=null;closeReview();history.replaceState(null,'',scoreUrl(new URLSearchParams({table:$('table').value})));parentEvent('mahjong-score-draft',{draft_id:''});}
 renderPhotoControls();
};
$('photo').onclick=event=>{photoSelectionContext=newPhotoContext();$('photo').value='';if(!photoSelectionContext){event.preventDefault();message($('photo-viewpoint').value?'pOpenFirst':'photo_viewpoint_required');$('photo-viewpoint').focus();}};
$('photo').onchange=async()=>{
 const file=$('photo').files[0];if(!file)return;
 const sequence=++photoSequence;photoTask=photoSelectionContext||newPhotoContext();preparedPhoto=null;photoPreparing=true;renderPhotoControls();
 if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl=null;$('preview').removeAttribute('src');$('preview').classList.add('hidden');
 if(!photoTask){photoPreparing=false;renderPhotoControls();message($('photo-viewpoint').value?'pOpenFirst':'photo_viewpoint_required');return;}
 message('pPreparingPhoto');
 try{
  const prepared=await shrinkPhoto(file);if(sequence!==photoSequence)return;
  preparedPhoto=prepared;previewUrl=URL.createObjectURL(prepared);$('preview').src=previewUrl;$('preview').classList.remove('hidden');
  photoPreparing=false;renderPhotoControls();await recognizePreparedPhoto(sequence);
 }catch(error){if(sequence!==photoSequence)return;photoTask=null;message(error.message);}
 finally{if(sequence===photoSequence){photoPreparing=false;renderPhotoControls();}}
};
async function shrinkPhoto(file){return PhotoUpload.prepare(file);}
async function recognizePreparedPhoto(sequence=photoSequence){
 if(busy||!photoTask||!preparedPhoto||sequence!==photoSequence)return;
 busy=true;photoRecognizing=true;renderPhotoControls();message('pRecognizing');
 const task=photoTask,file=preparedPhoto;
 try{const form=new FormData();form.append('file',file,file.name||'score.jpg');form.append('table',task.table);form.append('match_id',task.match_id);form.append('viewpoint_seat',task.viewpoint_seat);
 const result=await api('/api/recognize_photo',{method:'POST',headers:{'Idempotency-Key':task.key},body:form});if(sequence!==photoSequence)return;showResponse(result);
 // Keep the prepared image for another explicit recognition. Failed network
 // retries retain their key; a completed recognition gets a fresh task key.
 if(result.status==='needs_review')photoTask={...task,key:taskKey()};else{photoTask=null;preparedPhoto=null;}}
 catch(e){if(sequence===photoSequence)message(e.message);}finally{busy=false;photoRecognizing=false;renderPhotoControls();if(draft)showTotal();}
}
$('recognize').onclick=()=>{
 if(busy||photoPreparing)return;
 if(!preparedPhoto||!photoTask){$('photo').click();return;}
 return recognizePreparedPhoto();
};
$('review-retry').onclick=()=>$('recognize').click();
$('manual').onclick=()=>{const params=new URLSearchParams();if($('table').value)params.set('table',$('table').value);if(scoreTargetId)params.set('match_id',scoreTargetId);window.top.location.assign('/manual-score?'+params.toString());};
$('confirm').onsubmit=async event=>{
 event.preventDefault();if(busy||!draft)return;
 if(!showTotal())return;
 const scores=Object.fromEntries([...new FormData(event.target)].map(([key,value])=>[key,Number(value)]));
 busy=true;showTotal();renderPhotoControls();
 try{showResponse(await api('/api/confirm_scores',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({draft_id:draft.draft_id,scores})}));}
 catch(e){message(e.message);}finally{busy=false;renderPhotoControls();if(draft)showTotal();}
};
applyLanguage(language);setInterval(()=>{tick();renderSwapUi();},1000);setInterval(()=>{if(!seatBusy&&!swapBusy)refresh();},2000);setInterval(()=>{if(!busy)refreshGameFlow();},5000);setInterval(()=>{if(!busy&&globalContext.profile)refreshSync();},10000);parentEvent('mahjong-score-ready');boot();

document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
