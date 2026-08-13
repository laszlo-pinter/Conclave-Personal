// static/js/features/conversations.js

// ── Tabs ──────────────────────────────────────────────────────────────────
function switchTab(tab){
  // Sidebar-Panels
  const tabs=['conv','agents','workspace','runs','settings'];
  document.querySelectorAll('.sb-tab').forEach((t,i)=>t.classList.toggle('active',tabs[i]===tab));
  document.getElementById('panelConv').classList.toggle('active',tab==='conv');
  document.getElementById('panelAgents').classList.toggle('active',tab==='agents');
  document.getElementById('panelWorkspace').classList.toggle('active',tab==='workspace');
  document.getElementById('panelRuns').classList.toggle('active',tab==='runs');
  document.getElementById('panelSettings').classList.toggle('active',tab==='settings');

  // Main-Panels: Studio (Chat) vs Agents vs Workspace vs Runs vs Settings
  const isStudio = tab==='conv';
  const isAgents = tab==='agents';
  const isWorkspace = tab==='workspace';
  const isRuns = tab==='runs';
  const isSettings = tab==='settings';

  // Studio-Elemente
  document.getElementById('messages').style.display = isStudio ? '' : 'none';
  document.getElementById('inputbar').style.display = (isStudio && currentConvId) ? 'block' : 'none';
  document.getElementById('topbar').style.display = (isStudio && currentConvId) ? 'flex' : 'none';
  document.getElementById('floorbar').style.display = (isStudio && currentFloor) ? 'flex' : 'none';
  document.getElementById('floorPanel').style.display = (isStudio && participants.some(p=>p.type==='model')) ? 'flex' : 'none';

  // Personal workspaces
  document.getElementById('registryMain').style.display = isAgents ? '' : 'none';
  document.getElementById('workspaceMain').style.display = isWorkspace ? '' : 'none';
  document.getElementById('runsMain').style.display = isRuns ? '' : 'none';
  document.getElementById('settingsMain').style.display = isSettings ? '' : 'none';

  if(isAgents){loadAgents();loadProviders();}
  if(isWorkspace){loadWorkspace();}
  if(isRuns){loadRuns();loadConversationUsage();}
  if(isSettings){loadSettings();}
}

// ── Conversations ─────────────────────────────────────────────────────────
async function loadConversations(){
  try{const d=await req('GET','/conversations');conversations=d.conversations||[];renderConvList();}catch{}
}

function renderConvList(){
  const el=document.getElementById('convList');
  if(!conversations.length){el.innerHTML='<div class="empty-list">Noch keine Conversations</div>';return;}
  el.innerHTML=conversations.map(c=>{
    const title=c.topic||c.id.slice(0,8)+'…';
    const short=c.id.slice(0,8);
    const date=new Date(c.created_at).toLocaleDateString('de-DE',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
    return `<div class="conv-item${c.id===currentConvId?' active':''}" onclick="selectConv('${c.id}')">
      <div class="conv-item-id" style="font-size:12px;font-weight:600;font-family:var(--font-ui);color:var(--text)">${esc(title)}</div>
      <div class="conv-item-meta"><div class="conv-dot"></div><span class="copyable" onclick="event.stopPropagation();copyId('${c.id}','Conv-ID')" title="Volle ID kopieren: ${c.id}">${short}</span> · ${date}</div>
      <button class="row-del" onclick="delConv(event,'${c.id}')">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 3h8M5 1h2M4 3v7M8 3v7" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
      </button>
    </div>`;
  }).join('');
}

function openNewConv(){
  document.getElementById('newConvTopic').value='';
  openOverlay('overlayNewConv');
  setTimeout(()=>document.getElementById('newConvTopic').focus(),100);
}

async function createConv(){
  const topic=document.getElementById('newConvTopic').value.trim();
  try{
    const d=await req('POST','/conversations');
    if(topic) await req('POST',`/conversations/${d.conversation_id}/topic`,{topic});
    toast('Conversation erstellt','ok');
    closeOverlay('overlayNewConv');
    await loadConversations();
    selectConv(d.conversation_id);
  }catch(e){toast(e.message,'err');}
}

async function delConv(e,id){
  e.stopPropagation();
  try{await req('DELETE',`/conversations/${id}`);if(currentConvId===id){currentConvId=null;showEmpty();}await loadConversations();toast('Geloescht','ok');}
  catch(e){toast(e.message,'err');}
}

async function selectConv(id){
  currentConvId=id;renderConvList();
  document.getElementById('topbar').style.display='flex';
  document.getElementById('inputbar').style.display='block';
  const tb=document.getElementById('topbarId');
  tb.textContent=id;
  tb.classList.add('copyable');
  tb.title='ID kopieren';
  tb.onclick=()=>copyId(id,'Conv-ID');
  document.getElementById('btnExport').disabled=false;
  try{
    const d=await req('GET',`/conversations/${id}`);
    participants=d.participants||[];
    currentFloor=d.floor||null;
    currentTopic=d.topic||'';
    renderBadges();renderMessages(d.messages||[]);updatePSel();
    renderTopicUI();renderFloorUI();
  }catch(e){
    // 404: Conversation existiert nicht mehr → deselect
    currentConvId=null;showEmpty();
    await loadConversations();
    toast('Conversation nicht mehr vorhanden','err');
  }
}

// ── Topic ─────────────────────────────────────────────────────────────────
function renderTopicUI(){
  const pill=document.getElementById('topicPill'),btnSet=document.getElementById('btnTopicSet');
  if(currentTopic){pill.style.display='flex';document.getElementById('topicText').textContent=currentTopic;btnSet.style.display='none';}
  else{pill.style.display='none';btnSet.style.display='flex';}
}

function openTopicModal(){
  document.getElementById('topicInput').value=currentTopic;
  openOverlay('overlayTopic');
  setTimeout(()=>document.getElementById('topicInput').focus(),100);
}

async function saveTopic(){
  const topic=document.getElementById('topicInput').value.trim();
  try{
    await req('POST',`/conversations/${currentConvId}/topic`,{topic});
    currentTopic=topic;renderTopicUI();
    await loadConversations();
    closeOverlay('overlayTopic');
    toast(topic?`Thema: ${topic}`:'Thema entfernt','ok');
  }catch(e){toast(e.message,'err');}
}

