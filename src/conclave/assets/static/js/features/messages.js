// static/js/features/messages.js

// ── Messages ──────────────────────────────────────────────────────────────
function renderMessages(msgs){
  msgs = msgs || [];
  AppState.setState({currentMessages: msgs});
  const el=document.getElementById('messages');el.replaceChildren();msgs.forEach(m=>el.appendChild(buildMsg(m)));scrollBottom();
  schedulePreview();
}

function buildMsg(m){
  const isUser=m.author_type==='user',pid=m.author_id,c=pid?colorFor(pid):null;
  const pName=pid?(participants.find(p=>p.id===pid)?.name||pid):'User';
  const div=document.createElement('div');div.className=`msg ${isUser?'user':'model'}`;
  div.dataset.seq=m.sequence;if(m.id)div.dataset.messageId=m.id;
  if(!isUser&&c) div.style.borderLeftColor=c.bd;
  // Z4: Herkunft nur bei User-Nachrichten; null (alt/CLI) zeigt nichts, statt etwas zu behaupten
  const originTag=isUser&&m.origin==='agent'?`<span class="msg-origin" title="${attr(t('message.via_agent_hint'))}">${esc(t('message.via_agent'))}</span>`:'';
  const dlBtn=isUser?'':`<button class="msg-dl" data-action="download-message" data-name="${attr(pName)}" data-seq="${attr(m.sequence)}" title="${attr(t('download.response'))}">&#8615;</button>`;
  const content=stripToolEventRefs(m.content||'',m.tool_events||[]);
  const rendered=isUser?esc(content):renderMarkdown(content);
  const toolEventsHtml=renderToolEvents(m.tool_events||[]);
  // safe-html: Werte via esc()/attr(), Inhalt via renderMarkdown() (DOMPurify), Farben aus PALETTE
  div.innerHTML=`<div class="msg-header"><span class="msg-label" style="color:${isUser?'var(--text-dim)':(c?.tx||'var(--accent)')}">${esc(pName)}</span>${originTag}<span class="msg-seq">#${esc(m.sequence)}</span>${dlBtn}</div><div class="msg-content">${rendered}</div>`;
  // safe-html: renderToolEvents() escaped alle Werte
  if(toolEventsHtml) div.insertAdjacentHTML('beforeend',toolEventsHtml);
  if(!isUser) attachContextChip(div,m.context,m.id);
  // Code-Highlighting auf alle pre>code Bloecke
  if(!isUser) div.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));
  return div;
}

function stripToolEventRefs(content,events){
  if(!events.length) return content;
  return String(content).replace(/\[tool_event:[0-9a-fA-F-]{36}\]/g,'').trim();
}

function renderToolEvents(events){
  if(!events.length) return '';
  return `<div class="tool-events">${events.map(renderToolEvent).join('')}</div>`;
}

function renderToolEvent(event){
  const ok=event.status==='succeeded';
  const path=event.output?.path||event.input?.path||'';
  const byteCount=typeof event.output?.bytes_written==='number'?event.output.bytes_written:event.output?.bytes_read;
  const bytes=typeof byteCount==='number'?` · ${fmtBytes(byteCount)}`:'';
  const label=event.tool==='workspace.save'||event.tool==='workspace.read'?event.tool:(event.tool||'tool');
  const okText=event.tool==='workspace.save'?'saved':(event.tool==='workspace.read'?'read':'ok');
  const detail=ok
    ? `${path?esc(path):esc(event.id)}${bytes}`
    : `${path?esc(path):esc(event.id)}${event.error?` · ${esc(event.error)}`:''}`;
  return `<div class="tool-event ${ok?'ok':'err'}"><span class="tool-event-dot"></span><span class="tool-event-name">${esc(label)}</span><span class="tool-event-status">${ok?okText:'failed'}</span><span class="tool-event-detail">${detail}</span></div>`;
}

// renderMarkdown → static/js/utils.js

function downloadMsg(btn){
  const card=btn.closest('.msg');
  const content=card.querySelector('.msg-content').textContent;
  const name=btn.dataset.name||'antwort';
  const seq=btn.dataset.seq||'0';
  const blob=new Blob([content],{type:'text/markdown'});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;a.download=`${name}-${seq}.md`;
  document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
  toast(t('download.done', {name, seq}),'ok');
}

// ── Message actions ───────────────────────────────────────────────────────
async function sendMsg(){
  const input=document.getElementById('msgInput'),content=input.value.trim();
  if(!content||!currentConvId)return;
  input.value='';autoResize(input);
  try{await req('POST',`/conversations/${currentConvId}/messages`,{content});const d=await req('GET',`/conversations/${currentConvId}`);renderMessages(d.messages||[]);}
  catch(e){toast(e.message,'err');}
}

async function invokeP(){
  const pid=document.getElementById('pSel').value;if(!pid){toast(t('participants.chooseRequired'),'err');return;}
  if(!AppState.getState('currentMessages').length){toast(t('input.writeFirst'),'err');return;}
  const btn=document.getElementById('btnInvoke');btn.disabled=true;
  // safe-html: statisches Markup
  btn.innerHTML='<span class="spinner"></span>';
  try{await req('POST',`/conversations/${currentConvId}/participants/${pid}/invoke`);const d=await req('GET',`/conversations/${currentConvId}`);renderMessages(d.messages||[]);toast(t('input.answerReceived'),'ok');}
  catch(e){toast(e.message,'err');}
  finally{btn.disabled=false;btn.textContent=t('input.invoke');}
}

async function streamP(){
  const pid=document.getElementById('pSel').value;if(!pid){toast(t('participants.chooseRequired'),'err');return;}
  if(!AppState.getState('currentMessages').length){toast(t('input.writeFirst'),'err');return;}
  const btn=document.getElementById('btnStream');btn.disabled=true;
  // safe-html: statisches Markup
  btn.innerHTML='<span class="spinner"></span> Stream';
  const el=document.getElementById('messages');
  const c=colorFor(pid),pName=participants.find(p=>p.id===pid)?.name||pid;
  const div=document.createElement('div');div.className='msg model';div.style.borderLeftColor=c.bd;
  // safe-html: Name via esc(), Farbe aus PALETTE
  div.innerHTML=`<div class="msg-header"><span class="msg-label" style="color:${c.tx}">${esc(pName)}</span><span class="msg-seq"><span class="spinner"></span></span></div><div class="msg-content" id="sc"></div>`;
  el.appendChild(div);scrollBottom();
  const sc=document.getElementById('sc');const cursor=document.createElement('span');cursor.className='cursor';sc.appendChild(cursor);
  let buf='';
  try{
    const hdrs={};if(apiKey) hdrs['Authorization']='Bearer '+apiKey;
    const res=await fetch(`${API}/conversations/${currentConvId}/participants/${pid}/stream`,{headers:hdrs});
    const reader=res.body.getReader(),dec=new TextDecoder();let done=false;
    while(!done){
      const{value,done:d}=await reader.read();done=d;
      for(const line of dec.decode(value||new Uint8Array(),{stream:!done}).split('\n')){
        if(!line.startsWith('data: '))continue;
        const p=line.slice(6);if(p==='[DONE]'||p.startsWith('[ERROR]')){done=true;break;}
        buf+=p;sc.textContent=buf;sc.appendChild(cursor);scrollBottom();
      }
    }
    cursor.remove();
    // Markdown rendern nach Stream-Ende
    const sc2=div.querySelector('.msg-content');
    // safe-html: renderMarkdown() (DOMPurify)
    if(sc2&&buf) {sc2.innerHTML=renderMarkdown(buf);sc2.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));}
    const data=await req('GET',`/conversations/${currentConvId}`);
    const last=data.messages.at(-1);
    div.querySelector('.msg-seq').textContent=last?'#'+last.sequence:'';
    if(last){div.dataset.seq=last.sequence;attachContextChip(div,last.context,last.id);}
    schedulePreview();
    div.removeAttribute('id');toast(t('input.streamDone'),'ok');
  }catch(e){cursor.remove();toast(e.message,'err');}
  btn.disabled=false;btn.textContent=`▶ ${t('input.stream')}`;
}

function openOrch(){
  document.getElementById('orchSeq').value=participants.filter(p=>p.type==='model').map(p=>p.id).join(', ');
  refreshSequencePreview('orchSeq','orchPreview');
  document.getElementById('orchParallel').checked=true;
  openOverlay('overlayOrch');
}

async function runOrch(){
  const seq=document.getElementById('orchSeq').value.split(',').map(s=>s.trim()).filter(Boolean);
  const parallel=document.getElementById('orchParallel').checked;
  if(!seq.length){toast(t('input.idsRequired'),'err');return;}
  if(!AppState.getState('currentMessages').length){toast(t('input.writeFirst'),'err');return;}
  closeOverlay('overlayOrch');
  const btn=document.getElementById('btnOrch');btn.disabled=true;
  // safe-html: statisches Markup
  btn.innerHTML='<span class="spinner"></span>';
  if(parallel){
    await runParallelOrchStream(seq,btn);
    return;
  }
  try{
    await req('POST',`/conversations/${currentConvId}/orchestrate`,{sequence:seq});
    const d=await req('GET',`/conversations/${currentConvId}`);renderMessages(d.messages||[]);
    toast(t('input.answers', {count: seq.length, parallel: ''}),`ok`);
  }catch(e){toast(e.message,'err');}
  finally{btn.disabled=false;btn.textContent=`↻ ${t('input.orchestrate')}`;}
}

async function runParallelOrchStream(seq,btn){
  const el=document.getElementById('messages');
  const pending=new Map();
  const banner=document.createElement('div');banner.className='loop-banner';
  // safe-html: statisches Markup + Uebersetzung ohne Platzhalter
  banner.innerHTML=`<span class="spinner"></span> <span id="orchLiveStatus">${t('orch.parallelStarting')}</span>`;
  el.appendChild(banner);
  seq.forEach((pid,slot)=>{
    const pName=participants.find(p=>p.id===pid)?.name||pid;
    const c=colorFor(pid);
    const div=document.createElement('div');div.className='msg model pending';div.style.borderLeftColor=c.bd;
    // safe-html: Name via esc(), Farbe aus PALETTE, Uebersetzungen ohne Platzhalter
    div.innerHTML=`<div class="msg-header"><span class="msg-label" style="color:${c.tx}">${esc(pName)}</span><span class="msg-seq">${t('orch.pending')} <span class="spinner"></span></span></div><div class="msg-content">${esc(t('orch.working'))}</div>`;
    el.insertBefore(div,banner);
    pending.set(`1:${slot}`,div);
  });
  scrollBottom();
  const status=banner.querySelector('#orchLiveStatus');

  try{
    const hdrs={'Content-Type':'application/json'};if(apiKey)hdrs['Authorization']='Bearer '+apiKey;
    const res=await fetch(`${API}/conversations/${currentConvId}/orchestrate-parallel-stream`,{
      method:'POST',headers:hdrs,body:JSON.stringify({groups:[seq]}),
    });
    if(!res.ok){const txt=await res.text();throw new Error(`HTTP ${res.status}: ${txt.slice(0,200)}`);}
    const reader=res.body.getReader(),dec=new TextDecoder();let done=false,sse='';
    while(!done){
      const{value,done:d}=await reader.read();done=d;
      sse+=dec.decode(value||new Uint8Array(),{stream:!done});
      const parts=sse.split('\n');sse=parts.pop();
      for(const line of parts){
        if(!line.startsWith('data: '))continue;
        const payload=line.slice(6);
        if(payload==='[DONE]'){done=true;break;}
        let ev;try{ev=JSON.parse(payload);}catch{continue;}
        handleParallelOrchEvent(ev,{pending,status});
      }
    }
    const data=await req('GET',`/conversations/${currentConvId}`);
    renderMessages(data.messages||[]);
    toast(t('input.answers', {count: seq.length, parallel: ' (parallel)'}),'ok');
  }catch(e){
    pending.forEach(div=>markParallelOrchError(div,e.message));
    toast(e.message,'err');
  }finally{
    banner.remove();
    btn.disabled=false;btn.textContent=`↻ ${t('input.orchestrate')}`;
  }
}

function handleParallelOrchEvent(ev,ctx){
  if(ev.event==='start'){
    ctx.status.textContent=t('orch.parallelRunning', {count: ev.total||0});
    return;
  }
  if(ev.event==='invoke'){
    const div=ctx.pending.get(`${ev.group}:${ev.slot}`);
    // safe-html: Uebersetzung ohne Platzhalter + statisches Markup
    if(div)div.querySelector('.msg-seq').innerHTML=`${t('orch.pending')} <span class="spinner"></span>`;
    return;
  }
  if(ev.event==='response'){
    const div=ctx.pending.get(`${ev.group}:${ev.slot}`);
    if(!div)return;
    renderParallelOrchResponse(div,ev);
    ctx.pending.delete(`${ev.group}:${ev.slot}`);
    ctx.status.textContent=t('orch.parallelReceived', {count: ev.sequence||''});
    return;
  }
  if(ev.event==='error'||ev.event==='stop'){
    const div=ctx.pending.get(`${ev.group}:${ev.slot}`);
    if(div)markParallelOrchError(div,ev.message||t('common.errorPrefix'));
    ctx.status.textContent=ev.message||t('common.errorPrefix');
  }
}

function renderParallelOrchResponse(div,ev){
  div.classList.remove('pending');
  div.querySelector('.msg-seq').textContent=ev.sequence?'#'+ev.sequence:'';
  const content=stripToolEventRefs(ev.content||'',ev.tool_events||[]);
  // safe-html: renderMarkdown() (DOMPurify)
  div.querySelector('.msg-content').innerHTML=renderMarkdown(content);
  div.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));
  div.querySelectorAll('.tool-events').forEach(el=>el.remove());
  const toolEventsHtml=renderToolEvents(ev.tool_events||[]);
  // safe-html: renderToolEvents() escaped alle Werte
  if(toolEventsHtml)div.insertAdjacentHTML('beforeend',toolEventsHtml);
  if(ev.sequence)div.dataset.seq=ev.sequence;
  attachContextChip(div,ev.context,ev.message_id);
  scrollBottom();
}

function markParallelOrchError(div,message){
  div.classList.remove('pending');
  div.classList.add('error');
  div.querySelector('.msg-seq').textContent=t('common.errorPrefix');
  div.querySelector('.msg-content').textContent=message;
}

