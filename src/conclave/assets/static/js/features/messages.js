// static/js/features/messages.js

// ── Messages ──────────────────────────────────────────────────────────────
function renderMessages(msgs){
  msgs = msgs || [];
  AppState.setState({currentMessages: msgs});
  const el=document.getElementById('messages');el.innerHTML='';msgs.forEach(m=>el.appendChild(buildMsg(m)));scrollBottom();
}

function buildMsg(m){
  const isUser=m.author_type==='user',pid=m.author_id,c=pid?colorFor(pid):null;
  const pName=pid?(participants.find(p=>p.id===pid)?.name||pid):'User';
  const div=document.createElement('div');div.className=`msg ${isUser?'user':'model'}`;
  if(!isUser&&c) div.style.borderLeftColor=c.bd;
  const dlBtn=isUser?'':`<button class="msg-dl" onclick="downloadMsg(this)" data-name="${esc(pName)}" data-seq="${m.sequence}" title="${t('download.response')}">&#8615;</button>`;
  const rendered=isUser?esc(m.content):renderMarkdown(m.content);
  div.innerHTML=`<div class="msg-header"><span class="msg-label" style="color:${isUser?'var(--text-dim)':(c?.tx||'var(--accent)')}">${esc(pName)}</span><span class="msg-seq">#${m.sequence}</span>${dlBtn}</div><div class="msg-content">${rendered}</div>`;
  // Code-Highlighting auf alle pre>code Bloecke
  if(!isUser) div.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));
  return div;
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
  const btn=document.getElementById('btnInvoke');btn.disabled=true;btn.innerHTML='<span class="spinner"></span>';
  try{await req('POST',`/conversations/${currentConvId}/participants/${pid}/invoke`);const d=await req('GET',`/conversations/${currentConvId}`);renderMessages(d.messages||[]);toast(t('input.answerReceived'),'ok');}
  catch(e){toast(e.message,'err');}
  finally{btn.disabled=false;btn.innerHTML=t('input.invoke');}
}

async function streamP(){
  const pid=document.getElementById('pSel').value;if(!pid){toast(t('participants.chooseRequired'),'err');return;}
  if(!AppState.getState('currentMessages').length){toast(t('input.writeFirst'),'err');return;}
  const btn=document.getElementById('btnStream');btn.disabled=true;btn.innerHTML='<span class="spinner"></span> Stream';
  const el=document.getElementById('messages');
  const c=colorFor(pid),pName=participants.find(p=>p.id===pid)?.name||pid;
  const div=document.createElement('div');div.className='msg model';div.style.borderLeftColor=c.bd;
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
    if(sc2&&buf) {sc2.innerHTML=renderMarkdown(buf);sc2.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));}
    const data=await req('GET',`/conversations/${currentConvId}`);
    const last=data.messages.at(-1);
    div.querySelector('.msg-seq').textContent=last?'#'+last.sequence:'';
    div.removeAttribute('id');toast(t('input.streamDone'),'ok');
  }catch(e){cursor.remove();toast(e.message,'err');}
  btn.disabled=false;btn.innerHTML=`&#9654; ${t('input.stream')}`;
}

function openOrch(){
  document.getElementById('orchSeq').value=participants.filter(p=>p.type==='model').map(p=>p.id).join(', ');
  document.getElementById('orchParallel').checked=true;
  openOverlay('overlayOrch');
}

async function runOrch(){
  const seq=document.getElementById('orchSeq').value.split(',').map(s=>s.trim()).filter(Boolean);
  const parallel=document.getElementById('orchParallel').checked;
  if(!seq.length){toast(t('input.idsRequired'),'err');return;}
  if(!AppState.getState('currentMessages').length){toast(t('input.writeFirst'),'err');return;}
  closeOverlay('overlayOrch');
  const btn=document.getElementById('btnOrch');btn.disabled=true;btn.innerHTML='<span class="spinner"></span>';
  try{
    const endpoint=parallel?'/orchestrate-parallel':'/orchestrate';
    const body=parallel?{groups:seq.map(id=>[id])}:{sequence:seq};
    await req('POST',`/conversations/${currentConvId}${endpoint}`,body);
    const d=await req('GET',`/conversations/${currentConvId}`);renderMessages(d.messages||[]);
    toast(t('input.answers', {count: seq.length, parallel: parallel ? ' (parallel)' : ''}),`ok`);
  }catch(e){toast(e.message,'err');}
  finally{btn.disabled=false;btn.innerHTML=`&#8635; ${t('input.orchestrate')}`;}
}

