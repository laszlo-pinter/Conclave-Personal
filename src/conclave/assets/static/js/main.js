// static/js/main.js — Conclave UI Bootstrap, State-Bridge, Event-Delegation
//
// Laedt nach: state.js, api.js, utils.js, features/*.js
// Enthaelt: State-Bridge + Event-Delegation + Init-Code

// ── State-Bridge ─────────────────────────────────────────────────────────
const _stateKeys = ['currentConvId','conversations','participants','agents','presetsData',
  'currentFloor','currentTopic','currentRules','editingAgentId','sysEdited','micActive'];
_stateKeys.forEach(k => {
  Object.defineProperty(window, k, {
    get() { return AppState.getState(k) },
    set(v) { AppState.setState({[k]: v}) },
  })
})
Object.defineProperty(window, 'API', {
  get() { return AppState.getState('api') },
  set(v) { AppState.setState({api: v}) },
})
Object.defineProperty(window, 'apiKey', {
  get() { return AppState.getState('apiKey') },
  set(v) { AppState.setState({apiKey: v}) },
})

// ── Event-Delegation ─────────────────────────────────────────────────────
// Alle data-action Handler zentral statt inline onclick.
const _actions = {
  'switch-tab':          (el) => switchTab(el.dataset.tab),
  'close-overlay':       (el) => closeOverlay(el.dataset.overlay),
  'open-new-conv':       () => openNewConv(),
  'create-conv':         () => createConv(),
  'open-topic-modal':    () => openTopicModal(),
  'save-topic':          () => saveTopic(),
  'open-add-participant':() => openAddParticipant(),
  'add-participant':     () => addParticipant(),
  'open-rules-modal':    () => openRulesModal(),
  'save-rules':          () => saveRules(),
  'invoke-with-floor':   () => invokeWithFloor(),
  'revoke-floor':        () => revokeFloor(),
  'toggle-mic':          () => toggleMic(),
  'pick-file':           () => pickFile(),
  'send-msg':            () => sendMsg(),
  'invoke-p':            () => invokeP(),
  'stream-p':            () => streamP(),
  'open-orch':           () => openOrch(),
  'run-orch':            () => runOrch(),
  'open-autoloop':       () => openAutoloop(),
  'run-autoloop':        () => runAutoloop(),
  'open-agent-form':     () => openAgentForm(null),
  'edit-agent':          (el) => openAgentForm(el.dataset.agentId),
  'delete-agent':        (el) => deleteAgent(el.dataset.agentId),
  'save-agent':          () => saveAgent(),
  'test-agent':          () => testAgent(),
  'toggle-advanced':     () => toggleAdvanced(),
  'select-role':         (el) => selectRole(el),
  'select-conversation': (el) => selectConv(el.dataset.conversationId),
  'copy-conversation-id':(el) => copyId(el.dataset.conversationId,'Conv-ID'),
  'delete-conversation': (el) => delConv(el.dataset.conversationId),
  'copy-topbar-id':      () => copyId(currentConvId,'Conv-ID'),
  'grant-floor':         (el) => grantFloor(el.dataset.participantId),
  'download-message':    (el) => downloadMsg(el),
  'sort-usage':          (el) => sortUsage(el.dataset.sortKey),
  'toggle-usage-detail': (el) => toggleUsageDetail(el),
  'toggle-workspace-dir':(el) => toggleWorkspaceDir(el),
  'insert-workspace-ref':(el) => insertWorkspaceRef(el.dataset.path),
  'export-conv':         () => exportConv(),
  'open-key-modal':      () => openKeyModal(),
  'save-key':            () => saveKey(),
  'clear-key':           () => clearKey(),
  'open-ws-text':        () => openWsTextModal(),
  'save-ws-text':        () => saveWsText(),
  'ws-upload-click':     () => document.getElementById('wsUpload').click(),
  'save-settings-workspace': () => saveSettingsWorkspace(),
  'create-backup':       () => createBackup(),
}

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]')
  if (!el) return
  const action = el.dataset.action
  const handler = _actions[action]
  if (handler) handler(el)
})

function _bindStaticUiEvents() {
  const on = (id, event, handler) => {
    const el = document.getElementById(id)
    if (el) el.addEventListener(event, handler)
  }
  on('languageSelect', 'change', (e) => setLanguage(e.target.value))
  on('wsUpload', 'change', (e) => uploadWsFile(e.target))
  on('fileInput', 'change', (e) => handleFile(e.target))
  on('pSel', 'change', () => onPSelChange())
  on('agentPick', 'change', () => fillFromAgent())
  on('msgInput', 'keydown', handleKey)
  on('msgInput', 'input', (e) => autoResize(e.target))
  ;['aId','aName','aTopic'].forEach(id => on(id, 'input', updatePrompt))
  on('aPreset', 'change', onPresetChange)
  on('aSysPrompt', 'input', onSysEdit)
}

// ── Overlay-Klick-Handler ────────────────────────────────────────────────
document.querySelectorAll('.overlay').forEach(o=>o.addEventListener('click',e=>{if(e.target===o)o.classList.remove('open');}));

// ── Init ─────────────────────────────────────────────────────────────────
if(typeof marked!=='undefined'){
  marked.setOptions({gfm:true,breaks:true,headerIds:false,mangle:false});
}
initI18n();
_bindStaticUiEvents();
updateKeyUI();
checkApi();
loadConversations();
loadAgents();
loadPresets();

// Polling nur im aktiven Tab, mit laengeren Intervallen
let _pollTimer = null;
function _startPolling() {
  if (_pollTimer) return;
  _pollTimer = setInterval(() => {
    if (document.visibilityState === 'hidden') return;
    checkApi();
    loadConversations();
    loadAgents();
  }, 15000);
}
function _stopPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    // Sofort aktualisieren wenn Tab wieder aktiv
    checkApi(); loadConversations(); loadAgents();
    _startPolling();
  } else {
    _stopPolling();
  }
});
_startPolling();
