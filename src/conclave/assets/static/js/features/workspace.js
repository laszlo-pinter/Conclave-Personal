// static/js/features/workspace.js

async function openRulesModal(){
  if(!currentConvId){toast(t('conv.chooseFirst'),'err');return;}
  try{
    const d=await req('GET',`/conversations/${currentConvId}/rules`);
    currentRules=d.rules||'';
  }catch{currentRules='';}
  document.getElementById('rulesInput').value=currentRules;
  openOverlay('overlayRules');
}

async function saveRules(){
  const rules=document.getElementById('rulesInput').value;
  try{
    await req('POST',`/conversations/${currentConvId}/rules`,{rules});
    currentRules=rules;
    closeOverlay('overlayRules');
    toast(rules?t('rules.saved'):t('rules.removed'),'ok');
  }catch(e){toast(e.message,'err');}
}

// ── Workspace ────────────────────────────────────────────────────────
async function loadWorkspace(){
  const el=document.getElementById('workspaceList');
  const mainEl=document.getElementById('workspaceMainList');
  try{
    const d=await req('GET','/workspace');
    const files=d.files||[];
    renderWorkspaceLimits(d.limits||{});
    if(!files.length){
      const empty=`<div class="surface-empty">${t('workspace.none')}</div>`;
      if(el) el.innerHTML=empty;
      if(mainEl) mainEl.innerHTML=empty;
      return;
    }
    const tree=_renderFileTree(_buildFileTree(files));
    if(el) el.innerHTML=tree;
    if(mainEl) mainEl.innerHTML=tree;
  }catch(e){
    const err=`<div class="surface-empty">${esc(e.message)}</div>`;
    if(el) el.innerHTML=err;
    if(mainEl) mainEl.innerHTML=err;
  }
}

function renderWorkspaceLimits(limits){
  const el=document.getElementById('workspaceLimits');
  if(!el) return;
  const ui=limits.ui_read_bytes?`${fmtBytes(limits.ui_read_bytes)} UI`:'UI';
  const agent=limits.agent_read_bytes?`${fmtBytes(limits.agent_read_bytes)} Agent`:'Agent';
  const write=limits.write_bytes?`${fmtBytes(limits.write_bytes)} Write`:'Write';
  el.innerHTML=`<span>${ui}</span><span>${agent}</span><span>${write}</span><span>Hidden off</span>`;
}

function _buildFileTree(files){
  const root={_files:[],_dirs:{}};
  for(const f of files){
    const parts=f.path.split('/');
    let node=root;
    for(let i=0;i<parts.length-1;i++){
      if(!node._dirs[parts[i]]) node._dirs[parts[i]]={_files:[],_dirs:{}};
      node=node._dirs[parts[i]];
    }
    node._files.push(f);
  }
  return root;
}

function _renderFileTree(node,prefix='',depth=0){
  let html='';
  // Ordner
  const dirs=Object.keys(node._dirs).sort();
  for(const dir of dirs){
    const sub=node._dirs[dir];
    const count=_countFiles(sub);
    const id='ws-dir-'+prefix+dir;
    const open=depth<1; // Erste Ebene offen, Rest zu
    html+=`<div class="surface-item" style="padding:4px 10px;cursor:pointer;user-select:none" onclick="document.getElementById('${id}').style.display=document.getElementById('${id}').style.display==='none'?'':'none';this.querySelector('.ws-arrow').textContent=document.getElementById('${id}').style.display==='none'?'\\u25B6':'\\u25BC'">
      <span class="ws-arrow" style="font-size:9px;margin-right:4px;color:var(--text-faint)">${open?'\u25BC':'\u25B6'}</span>
      <span style="font-family:var(--font-mono);font-size:11px;font-weight:600;color:var(--text-dim)">${esc(dir)}/</span>
      <span style="font-size:10px;color:var(--text-faint);margin-left:4px">(${count})</span>
    </div>`;
    html+=`<div id="${id}" style="padding-left:12px;${open?'':'display:none'}">`;
    html+=_renderFileTree(sub,prefix+dir+'/',depth+1);
    html+='</div>';
  }
  // Dateien
  for(const f of node._files.sort((a,b)=>a.path.localeCompare(b.path))){
    const name=f.path.split('/').pop();
    html+=`<div class="surface-item" style="padding:3px 10px"><div class="surface-item-row">
      <span class="surface-item-label" style="cursor:pointer;font-size:11px" onclick="insertWorkspaceRef('${esc(f.path)}')" title="@workspace/${esc(f.path)}">${esc(name)}</span>
      <span style="font-size:10px;color:var(--text-faint)">${(f.size/1024).toFixed(1)} KB</span>
    </div></div>`;
  }
  return html;
}

function _countFiles(node){
  let n=node._files.length;
  for(const d of Object.values(node._dirs)) n+=_countFiles(d);
  return n;
}

async function uploadWsFile(input){
  const file=input.files[0];if(!file)return;
  input.value='';
  if(file.size>512*1024){toast(t('workspace.fileTooLarge'),'err');return;}
  const reader=new FileReader();
  reader.onload=async function(e){
    try{
      await req('POST',`/workspace/${file.name}`,{content:e.target.result});
      toast(t('workspace.uploaded', {name: file.name}),'ok');
      loadWorkspace();
    }catch(err){toast(err.message,'err');}
  };
  reader.readAsText(file);
}

function openWsTextModal(){
  document.getElementById('wsFileName').value='';
  document.getElementById('wsFileContent').value='';
  openOverlay('overlayWsText');
  setTimeout(()=>document.getElementById('wsFileName').focus(),100);
}

async function saveWsText(){
  const name=document.getElementById('wsFileName').value.trim();
  const content=document.getElementById('wsFileContent').value;
  if(!name){toast(t('workspace.fileNameRequired'),'err');return;}
  try{
    await req('POST',`/workspace/${name}`,{content});
    toast(t('workspace.saved', {name}),'ok');
    closeOverlay('overlayWsText');
    loadWorkspace();
  }catch(e){toast(e.message,'err');}
}

function insertWorkspaceRef(path){
  const ta=document.getElementById('msgInput');
  const ref=`@workspace/${path}`;
  if(ta.value.trim()) ta.value+='\n'+ref;
  else ta.value=ref;
  autoResize(ta);ta.focus();
  toast(t('workspace.inserted', {ref}),'ok');
  switchTab('conv');
}

// ── File Upload ──────────────────────────────────────────────────────
function pickFile(){document.getElementById('fileInput').click();}

function handleFile(input){
  const file=input.files[0];if(!file)return;
  input.value='';
  const ext=file.name.split('.').pop().toLowerCase();
  const maxSize=512*1024; // 512 KB
  if(file.size>maxSize){toast(t('workspace.fileTooLarge'),'err');return;}
  const reader=new FileReader();
  reader.onload=function(e){
    const content=e.target.result;
    const wrapped=`--- ${t('workspace.filePrefix')}: ${file.name} ---\n\`\`\`${ext}\n${content}\n\`\`\``;
    const textarea=document.getElementById('msgInput');
    if(textarea.value.trim()){
      textarea.value+='\n\n'+wrapped;
    } else {
      textarea.value=wrapped;
    }
    autoResize(textarea);
    textarea.focus();
    toast(t('workspace.attached', {name: file.name}),'ok');
  };
  reader.onerror=function(){toast(t('workspace.readFailed'),'err');};
  reader.readAsText(file);
}

