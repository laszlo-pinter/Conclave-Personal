// static/js/features/participants.js

// ── Participants ──────────────────────────────────────────────────────────
function renderBadges(){
  document.getElementById('pBadges').innerHTML=participants.map(p=>{
    const c=colorFor(p.id);
    return `<span class="p-badge" style="background:${c.bg};border-color:${c.bd};color:${c.tx}">${esc(p.name)}</span>`;
  }).join('');
  updatePSel();
  const has=participants.some(p=>p.type==='model');
  ['btnInvoke','btnStream','btnOrch','btnAutoloop'].forEach(id=>document.getElementById(id).disabled=!has);
}

function updatePSel(){
  const sel=document.getElementById('pSel'),models=participants.filter(p=>p.type==='model');
  sel.innerHTML=models.length
    ?`<option value="">${t('participants.pick')}</option>`+models.map(p=>`<option value="${p.id}">${esc(p.name)} (${p.id})</option>`).join('')
    :`<option value="">${t('participants.noModel')}</option>`;
}

function onPSelChange(){
  const pid=document.getElementById('pSel').value;
  document.getElementById('btnInvoke').disabled=!pid;
  document.getElementById('btnStream').disabled=!pid;
}

function openAddParticipant(){
  document.getElementById('pFormId').value='';document.getElementById('pFormName').value='';document.getElementById('pFormType').value='model';
  const pick=document.getElementById('agentPick');
  pick.innerHTML=`<option value="">${t('participants.manual')}</option>`+agents.map(a=>`<option value="${a.id}">${esc(a.name)} (${a.id})</option>`).join('');
  openOverlay('overlayParticipant');
}

function fillFromAgent(){
  const a=agents.find(x=>x.id===document.getElementById('agentPick').value);
  if(!a)return;
  document.getElementById('pFormId').value=a.id;
  document.getElementById('pFormName').value=a.name;
}

async function addParticipant(){
  const pid=document.getElementById('pFormId').value.trim(),name=document.getElementById('pFormName').value.trim(),type=document.getElementById('pFormType').value;
  if(!pid||!name){toast(t('common.requiredIdName'),'err');return;}
  try{
    await req('POST',`/conversations/${currentConvId}/participants`,{participant_id:pid,name,type});
    closeOverlay('overlayParticipant');toast(t('participants.registered', {name}),'ok');
    const d=await req('GET',`/conversations/${currentConvId}`);
    participants=d.participants||[];renderBadges();renderFloorUI();
  }catch(e){toast(e.message,'err');}
}

