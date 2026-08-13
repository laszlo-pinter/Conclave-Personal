// static/js/features/agents.js

// ── Agents ────────────────────────────────────────────────────────────────
async function loadAgents(){
  try{const d=await req('GET','/agents');agents=d.agents||[];renderAgentList();renderAgentWorkbench();}
  catch{
    document.getElementById('agentList').innerHTML=`<div class="empty-list">${t('common.apiUnreachable')}</div>`;
    const wb=document.getElementById('agentWorkbench');
    if(wb) wb.innerHTML=`<div class="surface-empty">${t('common.apiUnreachable')}.</div>`;
  }
}

function renderAgentList(){
  const el=document.getElementById('agentList');
  if(!el) return;
  if(!agents.length){el.innerHTML=`<div class="empty-list">${t('agents.none')}</div>`;return;}
  el.innerHTML=agents.map(a=>_agentCard(a)).join('');
}

function renderAgentWorkbench(){
  const el=document.getElementById('agentWorkbench');
  if(!el) return;
  if(!agents.length){el.innerHTML=`<div class="surface-empty">${t('agents.none')}</div>`;return;}
  el.innerHTML=agents.map(a=>_agentCard(a,'agent-card-wide')).join('');
}

function _agentCard(a,extraClass=''){
  const c=colorFor(a.id);
  const chip=a.role?`<span class="role-chip" style="background:${c.bg};border:1px solid ${c.bd};color:${c.tx}">${esc(a.role)}</span>`:'';
  const key=a.api_key_set?'<span class="status-chip ok">Key</span>':'<span class="status-chip muted">Env</span>';
  return `<div class="agent-item ${extraClass}">
      <div class="agent-item-name">${esc(a.name)}${chip}</div>
      <div class="agent-item-id">${esc(a.id)}</div>
      <div class="agent-item-meta"><span>${esc(a.preset||a.provider)}</span><span>${esc(a.model)}</span>${key}</div>
      ${a.topic?`<div class="agent-item-topic">${t('agents.topicPrefix')}: ${esc(a.topic)}</div>`:''}
      <div class="agent-actions">
        <button class="icon-btn" onclick="openAgentForm('${a.id}')">
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M9 2.5l1.5 1.5-7 7H2v-1.5l7-7z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg>
        </button>
        <button class="icon-btn del" onclick="deleteAgent('${a.id}')">
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M2.5 3.5h8M5 2h3M4 3.5V10M9 3.5V10" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
        </button>
      </div>
    </div>`;
}

async function loadProviders(){
  const el=document.getElementById('providerWorkbench');
  if(!el) return;
  try{
    const d=await req('GET','/providers');
    const providers=d.providers||[];
    if(!providers.length){el.innerHTML=`<div class="surface-empty">${t('agents.noProviders')}</div>`;return;}
    el.innerHTML=providers.map(p=>`
      <div class="surface-item provider-item">
        <div class="surface-item-row">
          <span class="surface-item-label">${esc(p.label||p.name)}</span>
          <span class="surface-item-status ${p.api_key_configured||p.requires_api_key===false?'active':'inactive'}">${p.api_key_configured||p.requires_api_key===false?t('agents.ready'):t('agents.keyMissing')}</span>
        </div>
        <div class="provider-models">${(p.models||[]).slice(0,4).map(m=>`<span>${esc(m)}</span>`).join('')}</div>
      </div>`).join('');
  }catch(e){el.innerHTML=`<div class="surface-empty">${esc(e.message)}</div>`;}
}

// presetsData ist jetzt in AppState

async function loadPresets(){
  try{const d=await req('GET','/presets');presetsData=d.presets||[];}catch{presetsData=[];}
  const sel=document.getElementById('aPreset');
  sel.innerHTML=presetsData.map(p=>`<option value="${p.name}">${esc(p.label||p.name)}</option>`).join('');
}

function onPresetChange(){
  const name=document.getElementById('aPreset').value;
  const p=presetsData.find(x=>x.name===name);
  if(!p)return;
  // Modelle aktualisieren
  const mSel=document.getElementById('aModel');
  const models=p.models||[];
  if(models.length){
    mSel.innerHTML=models.map((m,i)=>`<option value="${m}">${m}${i===0?` (${t('agents.recommended')})`:''}</option>`).join('');
  } else {
    mSel.innerHTML=`<option value="">${t('agents.modelInput')}</option>`;
  }
  // Erweiterte Felder setzen
  document.getElementById('aApiUrl').value=p.api_url||'';
  document.getElementById('aResponsePath').value=p.response_path||'';
  document.getElementById('aMsgFormat').value=p.message_format||'standard';
  // Provider aus Preset-Name ableiten
  document.getElementById('aApiKey').value='';
}

function toggleAdvanced(){
  const el=document.getElementById('advancedFields');
  const btn=document.getElementById('btnAdvanced');
  if(el.style.display==='none'){el.style.display='block';btn.textContent=t('agents.advancedHide');}
  else{el.style.display='none';btn.textContent=t('agents.advancedShow');}
}

function openAgentForm(id){
  editingAgentId=id||null;sysEdited=false;
  document.getElementById('agentModalTitle').textContent=id?t('agents.modalTitleEdit'):t('agents.modalTitleCreate');
  document.getElementById('advancedFields').style.display='none';
  document.getElementById('btnAdvanced').textContent=t('agents.advancedShow');
  document.querySelectorAll('#roleGroup .radio-opt').forEach(el=>el.className='radio-opt');
  document.querySelector('#roleGroup .radio-opt[data-role=""]').classList.add('sel-none');

  if(id){
    const a=agents.find(x=>x.id===id);if(!a)return;
    document.getElementById('aId').value=a.id;
    document.getElementById('aName').value=a.name;
    // Preset setzen
    const presetName=a.preset||a.provider||'';
    document.getElementById('aPreset').value=presetName;
    onPresetChange();
    document.getElementById('aModel').value=a.model;
    document.getElementById('aTopic').value=a.topic||'';
    document.getElementById('aSysPrompt').value=a.system_prompt||'';
    document.getElementById('aApiKey').value=''; // Nie vorausfuellen
    document.getElementById('aApiUrl').value=a.api_url||'';
    document.getElementById('aResponsePath').value=a.response_path||'';
    document.getElementById('aMsgFormat').value=a.message_format||'standard';
    if(a.system_prompt) sysEdited=true;
    const ro=document.querySelector(`#roleGroup .radio-opt[data-role="${a.role||''}"]`);
    if(ro){document.querySelectorAll('#roleGroup .radio-opt').forEach(el=>el.className='radio-opt');ro.classList.add(ro.dataset.role?'sel-role':'sel-none');}
  } else {
    ['aId','aName','aTopic','aSysPrompt','aApiKey','aApiUrl','aResponsePath'].forEach(id=>document.getElementById(id).value='');
    document.getElementById('aPreset').value=presetsData.length?presetsData[0].name:'';
    onPresetChange();
  }
  openOverlay('overlayAgent');setTimeout(()=>document.getElementById('aId').focus(),120);
}

function selectRole(el){
  document.querySelectorAll('#roleGroup .radio-opt').forEach(x=>x.className='radio-opt');
  el.classList.add(el.dataset.role?'sel-role':'sel-none');
  if(!sysEdited) updatePrompt();
}

function getCurrentRole(){
  const s=document.querySelector('#roleGroup .radio-opt.sel-role, #roleGroup .radio-opt.sel-none');return s?s.dataset.role:'';
}

function updatePrompt(){
  if(sysEdited)return;
  const role=getCurrentRole(),name=document.getElementById('aName').value.trim()||'Assistent',topic=document.getElementById('aTopic').value.trim();
  const fn=ROLES[role];document.getElementById('aSysPrompt').value=fn?fn(name,topic):'';
}
function onSysEdit(){sysEdited=true;}

async function saveAgent(){
  const id=document.getElementById('aId').value.trim(),name=document.getElementById('aName').value.trim();
  const preset=document.getElementById('aPreset').value;
  const p=presetsData.find(x=>x.name===preset)||{};
  const provider=preset==='custom'?'custom':(p.name||preset);
  const model=document.getElementById('aModel').value;
  const topic=document.getElementById('aTopic').value.trim(),role=getCurrentRole();
  const system_prompt=document.getElementById('aSysPrompt').value.trim();
  const api_key=document.getElementById('aApiKey').value;
  const api_url=document.getElementById('aApiUrl').value.trim();
  const response_path=document.getElementById('aResponsePath').value.trim();
  const message_format=document.getElementById('aMsgFormat').value;
  if(!id||!name){toast(t('common.requiredIdName'),'err');return;}
  const btn=document.getElementById('btnSaveAgent'),lbl=document.getElementById('btnSaveAgentLabel');
  btn.disabled=true;lbl.innerHTML='<span class="spinner"></span>';
  const wasEditing=Boolean(editingAgentId);
  try{
    const body={id,name,provider,model,role,topic,system_prompt,preset,api_url,response_path,message_format};
    if(api_key) body.api_key=api_key;
    if(editingAgentId) await req('PUT',`/agents/${editingAgentId}`,body);
    else await req('POST','/agents',body);
    editingAgentId=id;
    toast(wasEditing?t('agents.updated'):t('agents.created'),'ok');
    closeOverlay('overlayAgent');await loadAgents();
  }catch(e){toast(e.message,'err');}
  finally{btn.disabled=false;lbl.textContent=t('common.save');}
}

async function testAgent(){
  if(!editingAgentId){
    // Erst speichern
    await saveAgent();
    if(!editingAgentId) return;
  }
  const btn=document.getElementById('btnTestAgent');
  btn.disabled=true;btn.textContent=t('agents.testing');
  try{
    const d=await req('POST',`/agents/${editingAgentId}/test`);
    if(d.success) toast(`Test OK: ${d.message}`,'ok');
    else toast(t('agents.testFailed', {message: d.message}),'err');
  }catch(e){toast(e.message,'err');}
  finally{btn.disabled=false;btn.textContent=t('agents.test');}
}

async function deleteAgent(id){
  try{await req('DELETE',`/agents/${id}`);toast(t('agents.deleted'),'ok');await loadAgents();}
  catch(e){toast(e.message,'err');}
}

