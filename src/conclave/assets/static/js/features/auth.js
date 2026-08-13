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
  localStorage.setItem('conclave_api_url',API);
  if(apiKey) localStorage.setItem('conclave_api_key',apiKey);
  else localStorage.removeItem('conclave_api_key');
  updateKeyUI();closeOverlay('overlayKey');
  toast(t('auth.saved'),'ok');
  checkApi();loadConversations();loadAgents();
}

function clearKey(){
  apiKey='';
  localStorage.removeItem('conclave_api_key');
  document.getElementById('keyInput').value='';
  updateKeyUI();closeOverlay('overlayKey');
  toast(t('auth.removed'),'ok');
  checkApi();
}

