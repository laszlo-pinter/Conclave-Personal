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
      // safe-html: statisches Markup + Uebersetzung ohne Platzhalter
      if(el) el.innerHTML=empty;
      // safe-html: statisches Markup + Uebersetzung ohne Platzhalter
      if(mainEl) mainEl.innerHTML=empty;
      return;
    }
    const root=_buildFileTree(files);
    // Seitenleiste im Chat: Klick fuegt @workspace/ ein; Files-Bereich: Klick oeffnet den Viewer
    // safe-html: _renderFileTree() escaped alle Werte
    if(el) el.innerHTML=_renderFileTree(root,'',0,'insert-workspace-ref');
    // safe-html: _renderFileTree() escaped alle Werte
    if(mainEl) mainEl.innerHTML=_renderFileTree(root,'',0,'open-workspace-file');
  }catch(e){
    const err=`<div class="surface-empty">${esc(e.message)}</div>`;
    // safe-html: err enthaelt Fehlertext via esc()
    if(el) el.innerHTML=err;
    // safe-html: err enthaelt Fehlertext via esc()
    if(mainEl) mainEl.innerHTML=err;
  }
}

function renderWorkspaceLimits(limits){
  const el=document.getElementById('workspaceLimits');
  if(!el) return;
  const ui=limits.ui_read_bytes?`${fmtBytes(limits.ui_read_bytes)} UI`:'UI';
  const agent=limits.agent_read_bytes?`${fmtBytes(limits.agent_read_bytes)} Agent`:'Agent';
  const write=limits.write_bytes?`${fmtBytes(limits.write_bytes)} Write`:'Write';
  // safe-html: Groessen via fmtBytes() (nur Zahlen), sonst feste Texte
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

function _renderFileTree(node,prefix='',depth=0,fileAction='insert-workspace-ref'){
  let html='';
  // Ordner
  const dirs=Object.keys(node._dirs).sort();
  for(const dir of dirs){
    const sub=node._dirs[dir];
    const count=_countFiles(sub);
    const id='ws-dir-'+Array.from(prefix+dir).map(ch=>ch.charCodeAt(0).toString(16)).join('-');
    const open=depth<1; // Erste Ebene offen, Rest zu
    html+=`<div class="surface-item ws-dir-toggle" data-action="toggle-workspace-dir" data-target-id="${attr(id)}">
      <span class="ws-arrow" style="font-size:9px;margin-right:4px;color:var(--text-faint)">${open?'\u25BC':'\u25B6'}</span>
      <span style="font-family:var(--font-mono);font-size:11px;font-weight:600;color:var(--text-dim)">${esc(dir)}/</span>
      <span style="font-size:10px;color:var(--text-faint);margin-left:4px">(${count})</span>
    </div>`;
    html+=`<div id="${id}" style="padding-left:12px;${open?'':'display:none'}">`;
    html+=_renderFileTree(sub,prefix+dir+'/',depth+1,fileAction);
    html+='</div>';
  }
  // Dateien
  for(const f of node._files.sort((a,b)=>a.path.localeCompare(b.path))){
    const name=f.path.split('/').pop();
    html+=`<div class="surface-item" style="padding:3px 10px"><div class="surface-item-row">
      <span class="surface-item-label ws-file-ref" data-action="${attr(fileAction)}" data-path="${attr(f.path)}" data-size="${attr(f.size)}" title="@workspace/${attr(f.path)}">${esc(name)}</span>
      <span style="font-size:10px;color:var(--text-faint)">${(Number(f.size)/1024).toFixed(1)} KB</span>
    </div></div>`;
  }
  return html;
}

function _countFiles(node){
  let n=node._files.length;
  for(const d of Object.values(node._dirs)) n+=_countFiles(d);
  return n;
}

function toggleWorkspaceDir(el){
  const target=document.getElementById(el.dataset.targetId);
  if(!target) return;
  const isHidden=target.style.display==='none';
  target.style.display=isHidden?'':'none';
  const arrow=el.querySelector('.ws-arrow');
  if(arrow) arrow.textContent=isHidden?'\u25BC':'\u25B6';
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

// ── Datei-Viewer (Files-Bereich, nur lesen) ───────────────────────────
let wsViewer=null; // {path, size, content, markdown, mode}

function _wsPathUrl(path){
  return '/workspace/'+String(path).split('/').map(encodeURIComponent).join('/');
}

async function openWorkspaceFile(path,size){
  const box=document.getElementById('wsViewer');
  if(!box) return;
  box.hidden=false;
  document.getElementById('wsViewerName').textContent=path;
  document.getElementById('wsViewerSize').textContent=size!==undefined&&size!==''?fmtBytes(Number(size)):'';
  const body=document.getElementById('wsViewerBody');
  body.className='ws-viewer-body';
  body.textContent=t('workspace.viewerLoading');
  document.getElementById('wsViewerMode').hidden=true;
  wsViewer={path, size, content:null, markdown:/\.(md|markdown)$/i.test(path), mode:'rendered'};
  const current=wsViewer;
  try{
    const d=await req('GET',_wsPathUrl(path));
    if(wsViewer!==current) return;                // inzwischen andere Datei gewaehlt
    current.content=String(d.content??'');
    renderWorkspaceViewer();
  }catch(e){
    if(wsViewer!==current) return;
    body.className='ws-viewer-body ws-viewer-error';
    body.textContent=e.message;                     // Fehlertext nur als Text
  }
  box.scrollIntoView({block:'nearest'});
}

function renderWorkspaceViewer(){
  const v=wsViewer;
  if(!v||v.content===null) return;
  const body=document.getElementById('wsViewerBody');
  const modeBtn=document.getElementById('wsViewerMode');
  modeBtn.hidden=!v.markdown;
  modeBtn.textContent=v.mode==='rendered'?t('workspace.viewerSource'):t('workspace.viewerRendered');
  if(v.markdown&&v.mode==='rendered'){
    body.className='ws-viewer-body msg-content ws-viewer-md';
    // safe-html: renderMarkdown() filtert ueber DOMPurify (wie Modellantworten), ohne DOMPurify nur esc()
    body.innerHTML=renderMarkdown(v.content);
    body.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));
    return;
  }
  body.className='ws-viewer-body ws-viewer-source';
  const pre=document.createElement('pre');
  const code=document.createElement('code');
  code.textContent=v.content;
  pre.appendChild(code);
  body.replaceChildren(pre);
  if(!v.markdown&&typeof hljs!=='undefined') hljs.highlightElement(code);
}

function toggleWorkspaceViewerMode(){
  if(!wsViewer) return;
  wsViewer.mode=wsViewer.mode==='rendered'?'source':'rendered';
  renderWorkspaceViewer();
}

function closeWorkspaceViewer(){
  wsViewer=null;
  const box=document.getElementById('wsViewer');
  if(box) box.hidden=true;
  const body=document.getElementById('wsViewerBody');
  if(body) body.replaceChildren();
}

function insertViewerRef(){
  if(wsViewer) insertWorkspaceRef(wsViewer.path);
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

