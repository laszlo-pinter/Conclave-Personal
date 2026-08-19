// static/js/features/autoloop.js
//
// Auto-Loop: laesst mehrere Agenten automatisch miteinander diskutieren.
// Ruft POST /conversations/<id>/auto-loop und streamt die SSE-Events
// (start / invoke / response / stop) live in den Messages-Container.

function openAutoloop(){
  const models=participants.filter(p=>p.type==='model');
  // Default-Reihenfolge: alle Model-Participants einmal.
  document.getElementById('loopSeq').value=models.map(p=>p.id).join(', ');
  document.getElementById('loopRounds').value=6;
  document.getElementById('loopStop').value='@done';
  document.getElementById('loopRotation').value='none';
  openOverlay('overlayAutoloop');
}

async function runAutoloop(){
  const seq=document.getElementById('loopSeq').value.split(',').map(s=>s.trim()).filter(Boolean);
  const maxRounds=parseInt(document.getElementById('loopRounds').value,10)||10;
  const stopSignal=document.getElementById('loopStop').value.trim()||'@done';
  const rotation=document.getElementById('loopRotation').value||'none';
  if(seq.length<1){toast(t('autoloop.needOne'),'err');return;}
  if(seq.length>20){toast(t('autoloop.tooManyParticipants'),'err');return;}
  if(maxRounds<1||maxRounds>50){toast(t('autoloop.invalidRounds'),'err');return;}
  if(!stopSignal||stopSignal.length>128){toast(t('autoloop.invalidStopSignal'),'err');return;}
  closeOverlay('overlayAutoloop');

  const btn=document.getElementById('btnAutoloop');btn.disabled=true;btn.innerHTML='<span class="spinner"></span> Loop';
  const el=document.getElementById('messages');
  const empty=document.getElementById('emptyMsg');if(empty)empty.style.display='none';

  // Status-Banner oben im Messages-Container
  const banner=document.createElement('div');banner.className='loop-banner';
  banner.innerHTML=`<span class="spinner"></span> <span id="loopStatus">${t('autoloop.starting')}</span>`;
  el.appendChild(banner);scrollBottom();
  const status=banner.querySelector('#loopStatus');

  let liveDiv=null,liveContent=null,buf='';
  // Schliesst die gerade laufende Live-Card ab (Markdown rendern).
  const finishLive=()=>{
    if(liveContent&&buf){liveContent.innerHTML=renderMarkdown(buf);liveContent.querySelectorAll('pre code').forEach(c=>hljs.highlightElement(c));}
    liveDiv=null;liveContent=null;buf='';
  };

  try{
    const hdrs={'Content-Type':'application/json'};if(apiKey)hdrs['Authorization']='Bearer '+apiKey;
    const res=await fetch(`${API}/conversations/${currentConvId}/auto-loop`,{
      method:'POST',headers:hdrs,
      body:JSON.stringify({sequence:seq,stop_signal:stopSignal,max_rounds:maxRounds,rotation}),
    });
    if(!res.ok){const t=await res.text();throw new Error(`HTTP ${res.status}: ${t.slice(0,200)}`);}

    const reader=res.body.getReader(),dec=new TextDecoder();let done=false,sse='';
    while(!done){
      const{value,done:d}=await reader.read();done=d;
      sse+=dec.decode(value||new Uint8Array(),{stream:!done});
      const parts=sse.split('\n');sse=parts.pop();  // letzte (evtl. unvollstaendige) Zeile zurueckhalten
      for(const line of parts){
        if(!line.startsWith('data: '))continue;
        const payload=line.slice(6);
        if(payload==='[DONE]'){done=true;break;}
        let ev;try{ev=JSON.parse(payload);}catch{continue;}
        handleLoopEvent(ev,seq,{status,el,finishLive,
          setLive:(div,content)=>{liveDiv=div;liveContent=content;buf='';},
          appendBuf:(txt)=>{buf=txt;if(liveContent){liveContent.textContent=txt;scrollBottom();}},
        });
      }
    }
    finishLive();
    banner.remove();
    // Echte Messages mit korrekten Sequenznummern nachladen.
    const data=await req('GET',`/conversations/${currentConvId}`);
    renderMessages(data.messages||[]);
    toast(t('autoloop.finished'),'ok');
  }catch(e){
    finishLive();banner.remove();toast(e.message,'err');
  }finally{
    btn.disabled=false;btn.innerHTML=`&#8734; ${t('input.autoloop')}`;
  }
}

// Verarbeitet ein einzelnes SSE-Event und aktualisiert die UI.
function handleLoopEvent(ev,seq,ctx){
  if(ev.event==='start'){
    ctx.status.textContent=t('autoloop.running', {rounds: ev.max_rounds, signal: ev.stop_signal});
    return;
  }
  if(ev.event==='invoke'){
    const pName=participants.find(p=>p.id===ev.participant)?.name||ev.participant;
    ctx.status.textContent=t('autoloop.thinking', {round: ev.round, name: pName});
    // Live-Card vorbereiten, in die der Response-Text geschrieben wird.
    const c=colorFor(ev.participant);
    const div=document.createElement('div');div.className='msg model';div.style.borderLeftColor=c.bd;
    div.innerHTML=`<div class="msg-header"><span class="msg-label" style="color:${c.tx}">${esc(pName)}</span><span class="msg-seq">${t('autoloop.round', {round: ev.round})} <span class="spinner"></span></span></div><div class="msg-content"></div>`;
    ctx.el.insertBefore(div,ctx.el.lastElementChild);  // vor dem Banner einfuegen
    ctx.setLive(div,div.querySelector('.msg-content'));
    scrollBottom();
    return;
  }
  if(ev.event==='response'){
    ctx.appendBuf(ev.content||'');
    ctx.finishLive();
    return;
  }
  if(ev.event==='stop'){
    const reasons={signal:t('autoloop.signal', {signal: ev.signal, round: ev.round}),
                   max_rounds:t('autoloop.maxReached', {rounds: ev.rounds}),
                   error:t('autoloop.abort', {message: ev.message||t('common.errorPrefix')})};
    ctx.status.textContent=reasons[ev.reason]||t('autoloop.ended');
    return;
  }
}
