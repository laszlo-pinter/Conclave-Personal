// static/js/features/runs.js

async function loadRuns(){
  const listEl=document.getElementById('runList');
  const tableEl=document.getElementById('runsTable');
  try{
    const d=await req('GET','/runs?limit=100');
    const runs=d.runs||[];
    if(!runs.length){
      listEl.innerHTML=`<div class="surface-empty">${t('runs.none')}</div>`;
      tableEl.innerHTML=`<div class="surface-empty">${t('runs.none')}</div>`;
      return;
    }
    listEl.innerHTML=runs.slice(0,12).map(r=>`
      <div class="surface-item">
        <div class="surface-item-row">
          <span class="surface-item-label">${esc(r.kind)}</span>
          <span class="surface-item-status ${r.status==='succeeded'?'active':'inactive'}">${esc(r.status)}</span>
        </div>
        <div style="font-size:10px;color:var(--text-faint);margin-top:4px">${esc((r.participants||[]).join(', ')||'-')}</div>
      </div>`).join('');
    tableEl.innerHTML=`
      <table class="usage-tbl">
        <thead><tr>
          <th>Start</th><th>Status</th><th>${t('runs.type')}</th><th>${t('runs.participants')}</th><th>Provider</th><th class="usage-th-num">Tokens</th><th>${t('runs.error')}</th>
        </tr></thead>
        <tbody>${runs.map(r=>{
          const usage=r.usage||{};
          const tokens=usage.total_tokens!==undefined&&usage.total_tokens!==null?fmt(usage.total_tokens):'-';
          return `<tr class="usage-row">
            <td>${esc(new Date(r.started_at).toLocaleString(getLanguage()==='en'?'en-US':'de-DE'))}</td>
            <td>${esc(r.status)}</td>
            <td>${esc(r.kind)}</td>
            <td>${esc((r.participants||[]).join(', '))}</td>
            <td>${esc(usage.provider||'-')}</td>
            <td class="usage-td-num">${tokens}</td>
            <td>${esc(r.error||'')}</td>
          </tr>`;
        }).join('')}</tbody>
      </table>`;
  }catch(e){
    listEl.innerHTML=`<div class="surface-empty">${esc(e.message)}</div>`;
    tableEl.innerHTML=`<div class="surface-empty">${t('common.errorPrefix')}: ${esc(e.message)}</div>`;
  }
}
