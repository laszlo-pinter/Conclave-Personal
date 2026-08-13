// static/js/features/speech.js

// ── Spracheingabe ───────────────────────────────────────────────────
// micActive ist jetzt in AppState
let recognition=null;

function initSpeech(){
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){document.getElementById('btnMic').style.display='none';return;}
  recognition=new SR();
  recognition.lang=getLanguage()==='en'?'en-US':'de-DE';
  recognition.continuous=true;
  recognition.interimResults=true;

  let finalText='', silenceTimer=null;

  recognition.onresult=function(e){
    let interim='';
    finalText='';
    for(let i=0;i<e.results.length;i++){
      if(e.results[i].isFinal) finalText+=e.results[i][0].transcript;
      else interim+=e.results[i][0].transcript;
    }
    const ta=document.getElementById('msgInput');
    ta.value=finalText+interim;
    autoResize(ta);

    // Auto-Stop nach 3s Stille
    clearTimeout(silenceTimer);
    silenceTimer=setTimeout(()=>{if(micActive)stopMic();},3000);
  };

  recognition.onerror=function(e){
    if(e.error!=='no-speech') toast(t('speech.error', {error: e.error}),'err');
    stopMic();
  };

  recognition.onend=function(){
    if(micActive) stopMic();
  };
}

function toggleMic(){
  if(micActive) stopMic();
  else startMic();
}

function startMic(){
  if(!recognition){toast(t('speech.unavailable'),'err');return;}
  micActive=true;
  document.getElementById('btnMic').classList.add('recording');
  recognition.lang=getLanguage()==='en'?'en-US':'de-DE';
  recognition.start();
  toast(t('speech.recording'),'floor');
}

function stopMic(){
  micActive=false;
  document.getElementById('btnMic').classList.remove('recording');
  try{recognition.stop();}catch{}
  const ta=document.getElementById('msgInput');
  if(ta.value.trim()) autoResize(ta);
}

initSpeech();

// ── Chat-Regeln ─────────────────────────────────────────────────────
// currentRules ist jetzt in AppState

