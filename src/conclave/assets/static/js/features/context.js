// static/js/features/context.js
//
// Kontext-Chip unter Modellantworten: welcher Kontext tatsaechlich an den
// Provider ging (gesendete/ausgelassene Nachrichten, Dateien, Token).
// Alles wird per createElement/textContent gebaut - Pfade sind Nutzerdaten.

const CONTEXT_LARGE_TOKENS = 50000;

function _num(n){
  return Number(n||0).toLocaleString(getLanguage()==='en'?'en-US':'de-DE');
}

function _el(tag,cls,text){
  const e=document.createElement(tag);
  if(cls)e.className=cls;
  if(text!==undefined&&text!==null)e.textContent=String(text);
  return e;
}

function contextChipText(ctx){
  const parts=[t('context.messages',{sent:_num(ctx.messages_sent),total:_num(ctx.messages_total)})];
  if(ctx.files)parts.push(t(ctx.files===1?'context.file':'context.files',{count:_num(ctx.files)}));
  if(ctx.read_results)parts.push(t('context.readResults',{count:_num(ctx.read_results)}));
  let tokens=t('context.tokens',{tokens:_num(ctx.estimated_tokens)});
  if(typeof ctx.billed_input_tokens==='number')tokens+=' '+t('context.billed',{tokens:_num(ctx.billed_input_tokens)});
  parts.push(tokens);
  return `${t('context.label')}: ${parts.join(' · ')}`;
}

// Chip-Element fuer eine Modellantwort; null, wenn kein Report vorliegt.
function buildContextChip(ctx,messageId){
  if(!ctx)return null;
  const wrap=_el('div','ctx');
  const chip=_el('button','ctx-chip',contextChipText(ctx));
  chip.type='button';
  chip.dataset.action='toggle-context';
  if(messageId)chip.dataset.messageId=messageId;
  if(ctx.truncated){
    chip.classList.add('truncated');
    if(ctx.messages_sent*2<ctx.messages_total)chip.classList.add('strong');
  }
  const large=!ctx.truncated&&ctx.estimated_tokens>=CONTEXT_LARGE_TOKENS;
  if(large)chip.classList.add('large');
  if(ctx.skipped_files)chip.classList.add('skipped');
  chip.title=t(large?'context.largeHint':'context.openDetails');
  wrap.appendChild(chip);
  return wrap;
}

// Haengt den Chip an eine Nachricht (ersetzt einen vorhandenen).
function attachContextChip(div,ctx,messageId){
  if(!div)return;
  div.querySelectorAll(':scope > .ctx').forEach(el=>el.remove());
  const chip=buildContextChip(ctx,messageId);
  if(chip)div.appendChild(chip);
}

async function toggleContextDetails(chip){
  const wrap=chip.closest('.ctx');
  const open=wrap.querySelector('.ctx-details');
  if(open){open.remove();chip.setAttribute('aria-expanded','false');return;}
  const id=chip.dataset.messageId;
  if(!id||!currentConvId)return;
  const panel=_el('div','ctx-details',t('common.loading'));
  wrap.appendChild(panel);chip.setAttribute('aria-expanded','true');
  try{
    const data=await req('GET',`/conversations/${encodeURIComponent(currentConvId)}/messages/${encodeURIComponent(id)}/context`);
    panel.replaceChildren(...renderContextDetails(data));
    panel.scrollIntoView({behavior:'smooth',block:'nearest'});
  }catch(e){
    panel.textContent=`${t('common.errorPrefix')}: ${e.message}`;
  }
}

function _row(label,...values){
  const row=_el('div','ctx-row');
  row.appendChild(_el('span','ctx-key',label));
  const val=_el('span','ctx-val');
  values.forEach(v=>val.appendChild(typeof v==='string'?document.createTextNode(v):v));
  row.appendChild(val);
  return row;
}

function _fileList(files,withSeq){
  const ul=_el('ul','ctx-files');
  files.forEach(f=>{
    const li=_el('li');
    li.appendChild(_el('span','ctx-path',f.path));
    const meta=[];
    if(typeof f.bytes==='number')meta.push(fmtBytes(f.bytes));
    if(withSeq&&f.message_seq!==undefined)meta.push('#'+f.message_seq);
    if(f.reason)meta.push(t('context.reason.'+f.reason));
    if(meta.length)li.appendChild(_el('span','ctx-meta',' '+meta.join(' · ')));
    ul.appendChild(li);
  });
  return ul;
}

function renderContextDetails(data){
  const r=data.report||{},u=data.usage||{},rows=[];
  rows.push(_row(t('context.d.messages'),t('context.d.sentOf',{sent:_num(r.messages_sent),total:_num(r.messages_total)})));
  if(r.omitted_sequences){
    const [from,to]=r.omitted_sequences;
    const jump=_el('button','ctx-jump',t('context.d.jump'));
    jump.type='button';jump.dataset.action='jump-to-message';jump.dataset.seq=from;
    rows.push(_row(t('context.d.omitted'),`#${from}–#${to} `,jump));
  }
  if(r.anchor_sequence)rows.push(_row(t('context.d.anchor'),'#'+r.anchor_sequence));
  rows.push(_row(t('context.d.limit'),r.truncation_limit?_num(r.truncation_limit):t('context.d.noLimit')));
  const parts=(r.system_parts||[]).map(p=>t('context.part.'+p));
  rows.push(_row(t('context.d.system'),parts.length?parts.join(', '):t('common.none')));
  if((r.context_files||[]).length)rows.push(_row(t('context.d.contextFiles'),_fileList(r.context_files,false)));
  if((r.inline_files||[]).length)rows.push(_row(t('context.d.inlineFiles'),_fileList(r.inline_files,true)));
  if((r.read_results||[]).length)rows.push(_row(t('context.d.readResults'),_fileList(r.read_results,true)));
  if((r.skipped_context_files||[]).length)rows.push(_row(t('context.d.skipped'),_fileList(r.skipped_context_files,false)));
  let tokens=t('context.tokens',{tokens:_num(r.estimated_tokens)});
  if(typeof u.input_tokens==='number')tokens+=' · '+t('context.d.billedInOut',{input:_num(u.input_tokens),output:_num(u.output_tokens)});
  rows.push(_row(t('context.d.tokens'),tokens));
  rows.push(_row(t('context.d.adapter'),String(r.adapter||'')));
  if(r.attempts>1)rows.push(_row(t('context.d.attempts'),_num(r.attempts)));
  if(!r.truncation_limit&&r.estimated_tokens>=CONTEXT_LARGE_TOKENS){
    rows.push(_el('div','ctx-warn',t('context.largeHint')));
  }
  return rows;
}

function jumpToMessage(el){
  const target=document.querySelector(`#messages .msg[data-seq="${CSS.escape(String(el.dataset.seq))}"]`);
  if(!target)return;
  target.scrollIntoView({behavior:'smooth',block:'center'});
  target.classList.add('flash');
  setTimeout(()=>target.classList.remove('flash'),1600);
}

// ── Vorschau vor dem Aufruf (K4) ─────────────────────────────────────────
// Was der naechste Aufruf senden wuerde - ohne Provider-Aufruf, nichts wird gespeichert.

const CONTEXT_PREVIEW_DELAY = 300;
let _previewTimer=null,_previewToken=0;

async function _fetchPreview(pid){
  const data=await req('GET',`/conversations/${encodeURIComponent(currentConvId)}/participants/${encodeURIComponent(pid)}/context-preview`);
  return data&&data.report;
}

function previewText(r){
  const msgs=r.messages_sent<r.messages_total
    ?t('context.preview.partial',{sent:_num(r.messages_sent),total:_num(r.messages_total)})
    :t('context.preview.all',{total:_num(r.messages_total)});
  return `${msgs} · ${t('context.tokens',{tokens:_num(r.estimated_tokens)})}`;
}

function _previewClasses(el,r){
  const truncated=r.messages_sent<r.messages_total;
  el.classList.toggle('truncated',truncated);
  el.classList.toggle('strong',truncated&&r.messages_sent*2<r.messages_total);
  el.classList.toggle('large',!r.truncation_limit&&r.estimated_tokens>=CONTEXT_LARGE_TOKENS);
}

// Entprellt: bei Teilnehmerwahl und nach neuen Nachrichten.
function schedulePreview(){
  clearTimeout(_previewTimer);
  _previewTimer=setTimeout(refreshPreview,CONTEXT_PREVIEW_DELAY);
}

async function refreshPreview(){
  const el=document.getElementById('ctxPreview');
  if(!el)return;
  const pid=document.getElementById('pSel')?.value;
  const token=++_previewToken;
  if(!pid||!currentConvId){el.hidden=true;return;}
  try{
    const r=await _fetchPreview(pid);
    if(token!==_previewToken)return;            // veraltete Antwort
    if(!r){el.hidden=true;return;}
    el.textContent=previewText(r);
    const large=!r.truncation_limit&&r.estimated_tokens>=CONTEXT_LARGE_TOKENS;
    el.title=t(large?'context.largeHint':'context.preview.hint');
    _previewClasses(el,r);
    el.hidden=false;
  }catch{
    if(token===_previewToken)el.hidden=true;   // z. B. 409: Adapter ohne Vorschau
  }
}

// Vorschau pro Teilnehmer fuer Orchestrierungs- und Auto-Loop-Dialog.
const _seqTimers={},_seqTokens={};
function scheduleSequencePreview(inputId,listId){
  clearTimeout(_seqTimers[listId]);
  _seqTimers[listId]=setTimeout(()=>refreshSequencePreview(inputId,listId),CONTEXT_PREVIEW_DELAY);
}

async function refreshSequencePreview(inputId,listId){
  const list=document.getElementById(listId);
  if(!list||!currentConvId)return;
  const ids=[...new Set(document.getElementById(inputId).value.split(',').map(s=>s.trim()).filter(Boolean))].slice(0,20);
  const token=(_seqTokens[listId]||0)+1;
  _seqTokens[listId]=token;
  const rows=await Promise.all(ids.map(async pid=>{
    let r;
    try{r=await _fetchPreview(pid);}catch{return null;}   // unbekannt oder ohne Vorschau: weglassen
    if(!r)return null;
    const row=_el('div','ctx-preview-row');
    row.appendChild(_el('span','ctx-preview-name',participants.find(p=>p.id===pid)?.name||pid));
    const val=_el('span','ctx-preview',previewText(r));
    _previewClasses(val,r);
    row.appendChild(val);
    return row;
  }));
  if(_seqTokens[listId]!==token)return;
  const shown=rows.filter(Boolean);
  list.replaceChildren(...shown);
  if(shown.length)list.prepend(_el('div','ctx-preview-title',t('context.preview.title')));
}
