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
  openOverlay('overlayAutoloop');
}

async function runAutoloop(){
  const seq=document.getElementById('loopSeq').value.split(',').map(s=>s.trim()).filter(Boolean);
  const maxRounds=parseInt(document.getElementById('loopRounds').value,10)||10;
  const stopSignal=document.getElementById('loopStop').value.trim()||'@done';
  if(seq.length<1){toast('Bitte mindestens eine Participant-ID angeben','err');return;}
  closeOverlay('overlayAutoloop');

  const btn=document.getElementById('btnAutoloop');btn.disabled=true;btn.innerHTML='<span class="spinner"></span> Loop';
  const el=document.getElementById('messages');
  const empty=document.getElementById('emptyMsg');if(empty)empty.style.display='none';

  // Status-Banner oben im Messages-Container
  const banner=document.createElement('div');banner.className='loop-banner';
  banner.innerHTML='<span class="spinner"></span> <span id="loopStatus">Auto-Loop startet…</span>';
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
      body:JSON.stringify({sequence:seq,stop_signal:stopSignal,max_rounds:maxRounds}),
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
    toast('Auto-Loop beendet','ok');
  }catch(e){
    finishLive();banner.remove();toast(e.message,'err');
  }finally{
    btn.disabled=false;btn.innerHTML='&#8734; Auto-Loop';
  }
}

// Verarbeitet ein einzelnes SSE-Event und aktualisiert die UI.
function handleLoopEvent(ev,seq,ctx){
  if(ev.event==='start'){
    ctx.status.textContent=`Auto-Loop läuft — bis zu ${ev.max_rounds} Runden, Stop bei „${ev.stop_signal}"`;
    return;
  }
  if(ev.event==='invoke'){
    const pName=participants.find(p=>p.id===ev.participant)?.name||ev.participant;
    ctx.status.textContent=`Runde ${ev.round} — ${pName} denkt nach…`;
    // Live-Card vorbereiten, in die der Response-Text geschrieben wird.
    const c=colorFor(ev.participant);
    const div=document.createElement('div');div.className='msg model';div.style.borderLeftColor=c.bd;
    div.innerHTML=`<div class="msg-header"><span class="msg-label" style="color:${c.tx}">${esc(pName)}</span><span class="msg-seq">Runde ${ev.round} <span class="spinner"></span></span></div><div class="msg-content"></div>`;
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
    const reasons={signal:`Konsens erreicht — „${ev.signal}" in Runde ${ev.round}`,
                   max_rounds:`Maximale Rundenzahl (${ev.rounds}) erreicht`,
                   error:`Abbruch: ${ev.message||'Fehler'}`};
    ctx.status.textContent=reasons[ev.reason]||'Beendet';
    return;
  }
}
