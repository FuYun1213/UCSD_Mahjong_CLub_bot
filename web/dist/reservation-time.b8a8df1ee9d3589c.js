/* Reservation date state. Server-resolved instants preserve year, timezone and DST fold. */
(function(root) {
  "use strict";
  function dateParts(value, timezone, end=false) {
    if(!value)return {month:"",day:"",time:""};
    const prefix=end?"end_local_":"local_",instant=end?value.end_at:(value.start_at||value.scheduled_at);
    if(value[prefix+"month"])return {month:String(value[prefix+"month"]),day:String(value[prefix+"day"]),time:value[prefix+"time"]};
    if(!instant)return {month:"",day:"",time:""};
    const parts=Object.fromEntries(new Intl.DateTimeFormat("en-US",{timeZone:timezone,month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).formatToParts(new Date(instant)).map(p=>[p.type,p.value]));
    return {month:String(Number(parts.month)),day:String(Number(parts.day)),time:parts.hour+":"+parts.minute};
  }
  function endParts(value,timezone){const p=dateParts(value,timezone,true);return {end_month:p.month,end_day:p.day,end_time:p.time};}
  function oneHour(start){return start?new Date(Date.parse(start)+3600000).toISOString():null;}
  function create(reservation,timezone) {
    const start=reservation?.start_at||reservation?.scheduled_at||null,end=reservation?.end_at||oneHour(start);
    return {...dateParts(reservation,timezone),...endParts(reservation?{...reservation,end_at:end}:null,timezone),
      scheduled_at:start,start_at:start,end_at:end,reference_start:start,timezone,revision:0,
      endTimeWasManuallyEdited:Boolean(reservation),default_pending:!reservation};
  }
  function applyDefault(state,value) {
    if(!state.default_pending)return state;
    const end=value.end_at||oneHour(value.start_at||value.scheduled_at);
    return {...state,...dateParts(value,value.timezone),...endParts({...value,end_at:end},value.timezone),
      start_at:value.start_at||value.scheduled_at,scheduled_at:value.start_at||value.scheduled_at,end_at:end,
      timezone:value.timezone,default_pending:false};
  }
  function editDate(state,field,value) {
    if(!["month","day","time","end_month","end_day","end_time"].includes(field))throw new Error("invalid_reservation_time");
    if(field.startsWith('end_'))return {...state,[field]:value,end_at:null,endTimeWasManuallyEdited:true,default_pending:false};
    return {...state,[field]:value,start_at:null,scheduled_at:null,revision:state.revision+1,default_pending:false};
  }
  function applyResolved(state,value,revision) {
    if(state.revision!==revision||!value.resolved_start_at)return state;
    const next={...state,start_at:value.resolved_start_at,scheduled_at:value.resolved_start_at};
    if(state.endTimeWasManuallyEdited)return next;
    const end=value.default_end_at||oneHour(value.resolved_start_at);
    return {...next,...endParts({...value,end_at:end},value.timezone||state.timezone),end_at:end};
  }
  function resetDuration(state) {
    const end=oneHour(state.start_at);
    return {...state,...(end?endParts({end_at:end},state.timezone):{}),end_at:end,
      endTimeWasManuallyEdited:false,revision:state.revision+1};
  }
  function startPayload(state) {
    return state.start_at?{scheduled_at:state.start_at}:{month:Number(state.month),day:Number(state.day),time:state.time};
  }
  function payload(state) {
    return {...startPayload(state),...(state.end_at?{end_at:state.end_at}:{end_month:Number(state.end_month),end_day:Number(state.end_day),end_time:state.end_time})};
  }
  const api={dateParts,create,applyDefault,editDate,applyResolved,resetDuration,startPayload,payload,oneHour};
  root.ReservationTime=api;
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
})(typeof window!=="undefined"?window:globalThis);
