// static/js/features/auth.js

// ── API-Key ──────────────────────────────────────────────────────────────
function updateKeyUI(){
  const dot=document.getElementById('keyDot');
  const lbl=document.getElementById('keyLabel');
  if(apiKey){dot.className='key-dot set';lbl.textContent=t('auth.keySet');}
  else{dot.className='key-dot unset';lbl.textContent=t('auth.setKey');}
}

function openKeyModal(){
  document.getElementById('keyApiUrl').value=API;
  document.getElementById('keyInput').value=apiKey;
  openOverlay('overlayKey');
}

function saveKey(){
  const url=document.getElementById('keyApiUrl').value.trim().replace(/\/$/,'');
  apiKey=document.getElementById('keyInput').value.trim();
  if(url) API=url;
  storeValue(API_URL_KEY,API);
  storeValue(TOKEN_KEY,apiKey);
  updateKeyUI();closeOverlay('overlayKey');
  toast(t('auth.saved'),'ok');
  checkApi();loadConversations();loadAgents();
}

function clearKey(){
  apiKey='';
  storeValue(TOKEN_KEY,'');
  document.getElementById('keyInput').value='';
  updateKeyUI();closeOverlay('overlayKey');
  toast(t('auth.removed'),'ok');
  checkApi();
}


// Rolle eines Tokens laut Server. Nur 401/403 heissen "ungueltig"; ein voruebergehender Fehler
// (Netzwerk, 5xx, 429) wird kurz wiederholt, statt das Token zu verwerfen (#96).
const WHOAMI_RETRY_DELAYS_MS=[250,750,1500];
async function _whoamiRole(token){
  for(let attempt=0;;attempt++){
    try{
      const r=await fetch(window.location.origin+'/auth/whoami',{headers:{'Authorization':'Bearer '+token}});
      if(r.ok) return (await r.json()).role||'';
      if(r.status===401||r.status===403) return '';
    }catch{}
    if(attempt>=WHOAMI_RETRY_DELAYS_MS.length) return '';
    await new Promise(resolve=>setTimeout(resolve,WHOAMI_RETRY_DELAYS_MS[attempt]));
  }
}

// Token aus dem Fragment (#token=…): erst die Rolle pruefen, dann uebernehmen oder nachfragen (R5).
async function confirmPendingToken(){
  const pending=AppState.getState('pendingToken');
  if(!pending) return;
  AppState.setState({pendingToken:''});
  const role=await _whoamiRole(pending);
  // Ohne gespeichertes Token gilt ein Mensch-Token sofort (Start ueber conclave desktop/web);
  // ein Agent-Token, ein ungueltiges oder ein Wechsel brauchen eine Bestaetigung.
  const silent=!storedValue(TOKEN_KEY)&&role==='human';
  const label=role==='human'?t('auth.roleHuman'):role==='agent'?t('auth.roleAgent'):t('auth.roleInvalid');
  if(!silent&&!window.confirm(t('auth.switchToken',{role:label}))) return;
  API=window.location.origin;
  apiKey=pending;
  storeValue(API_URL_KEY,'');
  storeValue(TOKEN_KEY,pending);
}
