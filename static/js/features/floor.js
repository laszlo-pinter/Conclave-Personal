// static/js/features/floor.js

// ── Floor ─────────────────────────────────────────────────────────────────
function renderFloorUI(){
  const floorbar=document.getElementById('floorbar'),floorPanel=document.getElementById('floorPanel');
  const models=participants.filter(p=>p.type==='model');
  if(currentFloor){
    const holder=participants.find(p=>p.id===currentFloor);
    const name=holder?holder.name:currentFloor;
    const c=colorFor(currentFloor);
    floorbar.classList.add('visible');
    document.getElementById('floorHolder').innerHTML=`<span style="color:${c.tx};font-weight:600">${esc(name)}</span>`;
  } else {floorbar.classList.remove('visible');}
  if(models.length>0){
    floorPanel.classList.add('visible');
    document.getElementById('floorGrantBtns').innerHTML=models.map(p=>{
      const c=colorFor(p.id),isActive=p.id===currentFloor;
      return `<button class="floor-grant-btn${isActive?' active':''}" style="${isActive?`background:${c.bg};border-color:${c.bd};color:${c.tx}`:''}" onclick="grantFloor('${p.id}')">&#127908; ${esc(p.name)}</button>`;
    }).join('');
  } else {floorPanel.classList.remove('visible');}
}

async function grantFloor(pid){
  try{
    await req('POST',`/conversations/${currentConvId}/floor/grant`,{participant_id:pid});
    currentFloor=pid;renderFloorUI();
    const p=participants.find(x=>x.id===pid);
    toast(`${p?.name||pid} hat das Wort`,'floor');
  }catch(e){toast(e.message,'err');}
}

async function revokeFloor(){
  try{await req('POST',`/conversations/${currentConvId}/floor/revoke`);currentFloor=null;renderFloorUI();toast('Rederecht entzogen','ok');}
  catch(e){toast(e.message,'err');}
}

async function invokeWithFloor(){
  if(!currentFloor){toast('Kein Participant hat das Wort','err');return;}
  const btn=document.getElementById('btnFloorInvoke');
  btn.disabled=true;btn.innerHTML='<span class="spinner"></span> Antwortet…';
  try{
    await req('POST',`/conversations/${currentConvId}/floor/invoke`);
    currentFloor=null;
    const conv=await req('GET',`/conversations/${currentConvId}`);
    renderMessages(conv.messages||[]);renderFloorUI();
    toast('Antwort erhalten','ok');
  }catch(e){toast(e.message,'err');}
  finally{btn.disabled=false;btn.innerHTML='Antworten lassen';}
}

