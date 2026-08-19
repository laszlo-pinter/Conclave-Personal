// static/js/utils.js — Utility-Funktionen

const PALETTE=[
  {bg:'rgba(0,212,170,.13)',  bd:'rgba(0,212,170,.45)',  tx:'#00d4aa'},
  {bg:'rgba(139,108,247,.13)',bd:'rgba(139,108,247,.45)',tx:'#a594f9'},
  {bg:'rgba(245,166,35,.12)', bd:'rgba(245,166,35,.4)',  tx:'#f5a623'},
  {bg:'rgba(0,184,217,.12)',  bd:'rgba(0,184,217,.4)',   tx:'#00b8d9'},
  {bg:'rgba(255,107,157,.12)',bd:'rgba(255,107,157,.4)', tx:'#ff6b9d'},
  {bg:'rgba(82,196,26,.12)',  bd:'rgba(82,196,26,.4)',   tx:'#52c41a'},
];
const colorMap={};
function colorFor(id){if(!colorMap[id]){const i=Object.keys(colorMap).length%PALETTE.length;colorMap[id]=PALETTE[i];}return colorMap[id];}

const ROLES={
  '':null,
  writer:    (n,t)=>getLanguage()==='en'
    ? `You are ${n}, a clear writer. Be precise, structured, and easy to build on.${t?` Focus: ${t}.`:''}`
    : `Du bist ${n}, ein klarer Writer. Formuliere praezise, strukturiert und anschlussfaehig.${t?` Fokus: ${t}.`:''}`,
  reviewer:  (n,t)=>getLanguage()==='en'
    ? `You are ${n}, a careful reviewer. Check logic, completeness, and practical effect.${t?` Focus: ${t}.`:''}`
    : `Du bist ${n}, ein sorgfaeltiger Reviewer. Pruefe Logik, Vollstaendigkeit und Wirkung.${t?` Fokus: ${t}.`:''}`,
  critic:    (n,t)=>getLanguage()==='en'
    ? `You are ${n}, a constructive critic. Find weaknesses, risks, and blind spots.${t?` Focus: ${t}.`:''}`
    : `Du bist ${n}, ein konstruktiver Critic. Finde Schwaechen, Risiken und blinde Flecken.${t?` Fokus: ${t}.`:''}`,
  researcher:(n,t)=>getLanguage()==='en'
    ? `You are ${n}, a thorough researcher. Collect reliable signals and mark uncertainty.${t?` Focus: ${t}.`:''}`
    : `Du bist ${n}, ein gruendlicher Researcher. Sammle belastbare Hinweise und markiere Unsicherheit.${t?` Fokus: ${t}.`:''}`,
  planner:   (n,t)=>getLanguage()==='en'
    ? `You are ${n}, a pragmatic planner. Break work into clear steps and dependencies.${t?` Focus: ${t}.`:''}`
    : `Du bist ${n}, ein pragmatischer Planner. Zerlege Arbeit in klare Schritte und Abhaengigkeiten.${t?` Fokus: ${t}.`:''}`,
  custom:    null,
};

function openOverlay(id){document.getElementById(id).classList.add('open');}
function closeOverlay(id){document.getElementById(id).classList.remove('open');}
function scrollBottom(){const el=document.getElementById('messages');el.scrollTop=el.scrollHeight;}
function autoResize(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,120)+'px';}
function handleKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg();}}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function attr(s){
  return esc(s).replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

async function copyId(id, label='ID'){
  try{
    await navigator.clipboard.writeText(id);
    toast(t('copy.copied', {label, id: id.slice(0,8)+'…'}),'ok');
  }catch(e){
    // Clipboard-API kann in nicht-secure-Contexts oder ohne Permission scheitern
    toast(t('copy.failed', {message: e.message}),'err');
  }
}
function fmt(n){return n>=1000?(n/1000).toFixed(1)+'k':String(n);}
function fmtBytes(n){
  if(n>=1024*1024) return (n/(1024*1024)).toFixed(1)+' MB';
  if(n>=1024) return (n/1024).toFixed(0)+' KB';
  return String(n)+' B';
}

function toast(msg,type='ok'){
  const c=document.getElementById('toasts'),d=document.createElement('div');
  d.className=`toast ${type}`;d.textContent=msg;c.appendChild(d);setTimeout(()=>d.remove(),type==='err'?10000:3200);
}

function showEmpty(){
  AppState.setState({currentMessages: []});
  document.getElementById('topbar').style.display='none';document.getElementById('inputbar').style.display='none';
  document.getElementById('floorbar').classList.remove('visible');document.getElementById('floorPanel').classList.remove('visible');
  document.getElementById('btnExport').disabled=true;
  document.getElementById('messages').innerHTML=`<div class="empty"><div class="empty-icon"><svg width="22" height="22" viewBox="0 0 22 22" fill="none"><circle cx="11" cy="11" r="9" stroke="#6b7280" stroke-width="1.5"/><circle cx="7.5" cy="11" r="2" fill="#6b7280"/><circle cx="14.5" cy="11" r="2" fill="#6b7280"/></svg></div><div class="empty-title">${t('conv.noneSelected')}</div><div class="empty-sub">${t('conv.selectOrCreate')}</div></div>`;
}

function renderMarkdown(text){
  if(typeof marked==='undefined') return esc(text);
  try{return marked.parse(text);}catch{return esc(text);}
}
