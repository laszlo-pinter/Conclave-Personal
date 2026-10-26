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
// Maskiert fuer HTML-Text und Attributwerte (& < > " ').
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function attr(s){return esc(s);}

async function copyId(id, label='ID'){
  try{
    await navigator.clipboard.writeText(id);
    toast(t('copy.copied', {label, id: id.slice(0,8)+'…'}),'ok');
  }catch(e){
    // Clipboard-API kann in nicht-secure-Contexts oder ohne Permission scheitern
    toast(t('copy.failed', {message: e.message}),'err');
  }
}
// Zahlen aus API-Antworten: nur echte Zahlen ausgeben, nie Rohwerte (landen in innerHTML).
function fmt(n){n=Number(n);if(!Number.isFinite(n))return '-';return n>=1000?(n/1000).toFixed(1)+'k':String(n);}
function fmtBytes(n){
  n=Number(n);if(!Number.isFinite(n))return '-';
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
  // safe-html: statisches Markup + Uebersetzungen
  document.getElementById('messages').innerHTML=`<div class="empty"><div class="empty-icon"><svg width="22" height="22" viewBox="0 0 22 22" fill="none"><circle cx="11" cy="11" r="9" stroke="#6b7280" stroke-width="1.5"/><circle cx="7.5" cy="11" r="2" fill="#6b7280"/><circle cx="14.5" cy="11" r="2" fill="#6b7280"/></svg></div><div class="empty-title">${t('conv.noneSelected')}</div><div class="empty-sub">${t('conv.selectOrCreate')}</div></div>`;
}

// ── Markdown ──────────────────────────────────────────────────────────────
// Modellausgaben sind nicht vertrauenswuerdig: marked erzeugt HTML, DOMPurify
// filtert es. Ohne DOMPurify wird nie HTML ausgegeben, nur escapter Text.
const MARKDOWN_ALLOWED_TAGS=['a','b','blockquote','br','code','del','div','em','h1','h2','h3','h4','h5','h6',
  'hr','i','input','li','ol','p','pre','s','span','strong','sub','sup','table','tbody','td','th','thead','tr','ul'];
const MARKDOWN_ALLOWED_ATTR=['align','checked','class','colspan','disabled','href','rowspan','start','title','type'];
// Attribute ohne URL-Bedeutung: sonst prueft DOMPurify sie gegen ALLOWED_URI_REGEXP und entfernt sie
const MARKDOWN_URI_SAFE_ATTR=['align','checked','colspan','disabled','rowspan','start','type'];
const _markdownPurifier=_createMarkdownPurifier();

function _createMarkdownPurifier(){
  if(typeof DOMPurify!=='function') return null;
  const purifier=DOMPurify(window);  // eigene Instanz, damit die Hooks lokal bleiben
  if(!purifier.isSupported) return null;
  purifier.addHook('afterSanitizeAttributes',node=>{
    if(node.tagName==='A'&&node.hasAttribute('href')){
      node.setAttribute('target','_blank');
      node.setAttribute('rel','noopener noreferrer');
    }
    // GFM-Tasklisten: nur deaktivierte Checkboxen
    if(node.tagName==='INPUT'){
      if(node.getAttribute('type')!=='checkbox'){node.remove();return;}
      node.setAttribute('disabled','');
    }
  });
  return purifier;
}

function sanitizeHtml(html){
  if(!_markdownPurifier) return esc(html);
  return _markdownPurifier.sanitize(html,{
    ALLOWED_TAGS:MARKDOWN_ALLOWED_TAGS,
    ALLOWED_ATTR:MARKDOWN_ALLOWED_ATTR,
    ALLOWED_URI_REGEXP:/^(?:(?:https?|mailto):|#)/i,
    ADD_URI_SAFE_ATTR:MARKDOWN_URI_SAFE_ATTR,
    ALLOW_DATA_ATTR:false,
  });
}

function renderMarkdown(text){
  if(typeof marked==='undefined'||!_markdownPurifier) return esc(text);
  try{return sanitizeHtml(marked.parse(String(text)));}catch{return esc(text);}
}
