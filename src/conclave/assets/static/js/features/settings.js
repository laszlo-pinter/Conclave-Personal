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
    // safe-html: err enthaelt Fehlertext via esc()
    if(runtime) runtime.innerHTML=err;
    // safe-html: err enthaelt Fehlertext via esc()
    if(summary) summary.innerHTML=err;
  }
}

function renderSettings(settings){
  const limits=settings.workspace_limits||{};
  const rows=[
    [t('settings.mode'), settings.mode||'-'],
    [t('settings.server'), `${settings.host||'127.0.0.1'}:${settings.port||8000}`],
    [t('settings.database'), settings.db_provider||'sqlite'],
    [t('settings.dbPath'), settings.db_path||'-'],
    [t('workspace.title'), settings.workspace_path||'-'],
  ];
  const runtime=document.getElementById('settingsRuntime');
  if(runtime){
    // safe-html: Werte via esc()/attr()
    runtime.innerHTML=`<div class="settings-kv">${rows.map(([k,v])=>`
      <div class="settings-kv-row"><span>${esc(k)}</span><strong title="${attr(v)}">${esc(v)}</strong></div>
    `).join('')}</div>`;
  }

  const input=document.getElementById('settingsWorkspacePath');
  if(input) input.value=settings.workspace_path||'';
  const policy=document.getElementById('settingsWorkspacePolicy');
  if(policy){
    const ui=limits.ui_read_bytes?`${fmtBytes(limits.ui_read_bytes)} UI`:'UI';
    const agent=limits.agent_read_bytes?`${fmtBytes(limits.agent_read_bytes)} Agent`:'Agent';
    const write=limits.write_bytes?`${fmtBytes(limits.write_bytes)} Write`:'Write';
    // safe-html: Groessen via fmtBytes() (nur Zahlen), sonst feste Texte
    policy.innerHTML=`<span>${ui}</span><span>${agent}</span><span>${write}</span><span>Hidden off</span>`;
  }

  renderRateLimit(settings.rate_limit||{});

  const keys=settings.provider_keys||{};
  const summary=document.getElementById('settingsSummary');
  if(summary){
    const keyNames=Object.keys(keys);
    // safe-html: Schluesselnamen via esc(), sonst Zahlen und Uebersetzungen ohne Platzhalter
    summary.innerHTML=`
      <div class="usage-card">
        <div class="usage-card-stats">
          <div class="usage-stat"><span class="usage-stat-value">${settings.auth_required?t('settings.authOn'):t('settings.authOff')}</span><span class="usage-stat-label">${t('settings.apiAuth')}</span></div>
          <div class="usage-stat"><span class="usage-stat-value">${keyNames.filter(k=>keys[k]).length}</span><span class="usage-stat-label">Keys</span></div>
        </div>
      </div>
      <div class="settings-key-list">${keyNames.map(k=>`
        <div class="settings-key"><span>${esc(k)}</span><span class="status-chip ${keys[k]?'ok':'muted'}">${keys[k]?t('settings.keySet'):t('settings.keyEmpty')}</span></div>
      `).join('')}</div>`;
  }
}

function renderRateLimit(rl){
  const input=document.getElementById('settingsRateLimit');
  const info=document.getElementById('settingsRateLimitInfo');
  const btn=document.getElementById('btnSaveRateLimit');
  if(!input||!info) return;
  input.value=rl.value||'';
  input.disabled=rl.editable===false;
  if(btn) btn.disabled=rl.editable===false;
  if(rl.editable===false) info.textContent=t('settings.rateLimitLocked');
  else if(rl.persistent===false) info.textContent=t('settings.rateLimitSession');
  else info.textContent=t('settings.rateLimitHint');
}

async function saveRateLimit(){
  const input=document.getElementById('settingsRateLimit');
  const rate_limit=(input?.value||'').trim();
  if(!rate_limit){toast(t('settings.rateLimitRequired'),'err');return;}
  try{
    const d=await req('PUT','/settings',{rate_limit});
    renderSettings(d.settings||{});
    toast(t('settings.rateLimitSaved'),'ok');
  }catch(e){toast(e.message,'err');}
}

// ── Server-Log ────────────────────────────────────────────────────────
async function loadLogs(){
  const list=document.getElementById('logList');
  const file=document.getElementById('logFile');
  if(!list) return;
  const level=document.getElementById('logLevel')?.value||'DEBUG';
  try{
    const d=await req('GET',`/logs?limit=300&level=${encodeURIComponent(level)}`);
    if(file) file.textContent=d.log_file||'';
    if(!d.available){_logMessage(list,d.hint||t('settings.logsUnavailable'));return;}
    const entries=d.entries||[];
    if(!entries.length){_logMessage(list,t('settings.logsEmpty'));return;}
    // Neueste zuerst; nur textContent (Logzeilen koennen beliebigen Text enthalten)
    list.replaceChildren(...entries.slice().reverse().map(_logRow));
  }catch(e){_logMessage(list,e.message);}
}

function _logMessage(list,text){
  const div=document.createElement('div');div.className='surface-empty';div.textContent=text;
  list.replaceChildren(div);
}

function _logRow(entry){
  const row=document.createElement('div');row.className='log-row';
  const time=document.createElement('span');time.className='log-time';
  time.textContent=String(entry.timestamp||'').slice(11,19);
  const level=String(entry.level||'');
  const lvl=document.createElement('span');lvl.className='log-level '+level.replace(/[^A-Z]/g,'');
  lvl.textContent=level;
  const msg=document.createElement('span');msg.className='log-msg';
  msg.textContent=String(entry.message||'');
  row.append(time,lvl,msg);
  return row;
}

async function saveSettingsWorkspace(){
  const input=document.getElementById('settingsWorkspacePath');
  const workspace_path=(input?.value||'').trim();
  if(!workspace_path){toast(t('settings.workspaceRequired'),'err');return;}
  try{
    const d=await req('PUT','/settings',{workspace_path});
    renderSettings(d.settings||{});
    await loadWorkspace();
    toast(t('settings.workspaceSaved'),'ok');
  }catch(e){toast(e.message,'err');}
}

async function createBackup(){
  const status=document.getElementById('backupStatus');
  if(status) status.textContent=t('settings.backupRunning');
  try{
    const d=await req('POST','/backup',{});
    const path=d.backup_path||t('settings.backupCreated');
    if(status) status.textContent=path;
    toast(t('settings.backupCreated'),'ok');
  }catch(e){
    if(status) status.textContent=e.message;
    toast(e.message,'err');
  }
}
