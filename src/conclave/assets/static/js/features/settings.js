// static/js/features/settings.js

async function loadSettings(){
  try{
    const d=await req('GET','/settings');
    const settings=d.settings||{};
    renderSettings(settings);
  }catch(e){
    const err=`<div class="surface-empty">${esc(e.message)}</div>`;
    const runtime=document.getElementById('settingsRuntime');
    const summary=document.getElementById('settingsSummary');
    if(runtime) runtime.innerHTML=err;
    if(summary) summary.innerHTML=err;
  }
}

function renderSettings(settings){
  const limits=settings.workspace_limits||{};
  const rows=[
    ['Modus', settings.mode||'-'],
    ['Server', `${settings.host||'127.0.0.1'}:${settings.port||8000}`],
    ['Datenbank', settings.db_provider||'sqlite'],
    ['DB-Pfad', settings.db_path||'-'],
    ['Workspace', settings.workspace_path||'-'],
  ];
  const runtime=document.getElementById('settingsRuntime');
  if(runtime){
    runtime.innerHTML=`<div class="settings-kv">${rows.map(([k,v])=>`
      <div class="settings-kv-row"><span>${esc(k)}</span><strong title="${esc(v)}">${esc(v)}</strong></div>
    `).join('')}</div>`;
  }

  const input=document.getElementById('settingsWorkspacePath');
  if(input) input.value=settings.workspace_path||'';
  const policy=document.getElementById('settingsWorkspacePolicy');
  if(policy){
    const ui=limits.ui_read_bytes?`${fmtBytes(limits.ui_read_bytes)} UI`:'UI';
    const agent=limits.agent_read_bytes?`${fmtBytes(limits.agent_read_bytes)} Agent`:'Agent';
    const write=limits.write_bytes?`${fmtBytes(limits.write_bytes)} Write`:'Write';
    policy.innerHTML=`<span>${ui}</span><span>${agent}</span><span>${write}</span><span>Hidden off</span>`;
  }

  const keys=settings.provider_keys||{};
  const summary=document.getElementById('settingsSummary');
  if(summary){
    const keyNames=Object.keys(keys);
    summary.innerHTML=`
      <div class="usage-card">
        <div class="usage-card-stats">
          <div class="usage-stat"><span class="usage-stat-value">${settings.auth_required?'An':'Aus'}</span><span class="usage-stat-label">API Auth</span></div>
          <div class="usage-stat"><span class="usage-stat-value">${keyNames.filter(k=>keys[k]).length}</span><span class="usage-stat-label">Keys</span></div>
        </div>
      </div>
      <div class="settings-key-list">${keyNames.map(k=>`
        <div class="settings-key"><span>${esc(k)}</span><span class="status-chip ${keys[k]?'ok':'muted'}">${keys[k]?'gesetzt':'leer'}</span></div>
      `).join('')}</div>`;
  }
}

async function saveSettingsWorkspace(){
  const input=document.getElementById('settingsWorkspacePath');
  const workspace_path=(input?.value||'').trim();
  if(!workspace_path){toast('Workspace-Pfad ist erforderlich','err');return;}
  try{
    const d=await req('PUT','/settings',{workspace_path});
    renderSettings(d.settings||{});
    await loadWorkspace();
    toast('Workspace-Pfad gespeichert','ok');
  }catch(e){toast(e.message,'err');}
}

async function createBackup(){
  const status=document.getElementById('backupStatus');
  if(status) status.textContent='Backup laeuft...';
  try{
    const d=await req('POST','/backup',{});
    const path=d.backup_path||'Backup erstellt';
    if(status) status.textContent=path;
    toast('Backup erstellt','ok');
  }catch(e){
    if(status) status.textContent=e.message;
    toast(e.message,'err');
  }
}
