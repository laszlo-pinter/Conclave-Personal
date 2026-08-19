// static/js/features/usage.js

// -- Conversation Usage (Runs workspace) ----------------------------------
let _usageSortKey='total_tokens', _usageSortAsc=false;

async function loadConversationUsage(){
  const tableEl=document.getElementById('usageTable');
  const summaryEl=document.getElementById('usageSummary');
  try{
    const d=await req('GET','/usage/conversations');
    const convs=d.conversations||[];
    const grand=d.grand_totals||{};
    if(!convs.length){
      tableEl.innerHTML=`<div class="surface-empty">${t('runs.none')}</div>`;
      summaryEl.innerHTML=`<div class="surface-empty">${t('common.noData')}</div>`;
      return;
    }
    // Sidebar summary
    summaryEl.innerHTML=`
      <div class="usage-card">
        <div class="usage-card-stats">
          <div class="usage-stat"><span class="usage-stat-value">${fmt(grand.total_tokens||0)}</span><span class="usage-stat-label">Tokens</span></div>
          <div class="usage-stat"><span class="usage-stat-value">${grand.calls||0}</span><span class="usage-stat-label">Calls</span></div>
          <div class="usage-stat"><span class="usage-stat-value">${convs.length}</span><span class="usage-stat-label">Chats</span></div>
        </div>
      </div>`;
    // Sort
    const sorted=[...convs].sort((a,b)=>{
      let va=a.totals[_usageSortKey]||0, vb=b.totals[_usageSortKey]||0;
      if(_usageSortKey==='topic'){va=a.topic||'';vb=b.topic||'';}
      if(va<vb)return _usageSortAsc?-1:1;
      if(va>vb)return _usageSortAsc?1:-1;
      return 0;
    });
    // Table
    const arrow=k=>_usageSortKey===k?(_usageSortAsc?' &#9650;':' &#9660;'):'';
    tableEl.innerHTML=`
      <table class="usage-tbl">
        <thead><tr>
          <th class="usage-th-topic" data-action="sort-usage" data-sort-key="topic">Conversation${arrow('topic')}</th>
          <th class="usage-th-num" data-action="sort-usage" data-sort-key="total_tokens">Total${arrow('total_tokens')}</th>
          <th class="usage-th-num" data-action="sort-usage" data-sort-key="input_tokens">Input${arrow('input_tokens')}</th>
          <th class="usage-th-num" data-action="sort-usage" data-sort-key="output_tokens">Output${arrow('output_tokens')}</th>
          <th class="usage-th-num" data-action="sort-usage" data-sort-key="calls">Calls${arrow('calls')}</th>
          <th class="usage-th-prov">Provider</th>
        </tr></thead>
        <tbody>${sorted.map(c=>{
          const t=c.totals;
          const topic=c.topic||c.conversation_id.slice(0,8)+'...';
          const provs=c.providers.map(p=>`<span class="usage-prov-tag">${esc(p.provider)} ${fmt(p.total_tokens)}</span>`).join(' ');
          return `<tr class="usage-row" data-action="toggle-usage-detail">
            <td class="usage-td-topic" title="${esc(c.conversation_id)}">${esc(topic)}</td>
            <td class="usage-td-num"><strong>${fmt(t.total_tokens)}</strong></td>
            <td class="usage-td-num">${fmt(t.input_tokens)}</td>
            <td class="usage-td-num">${fmt(t.output_tokens)}</td>
            <td class="usage-td-num">${t.calls}</td>
            <td class="usage-td-prov">${provs}</td>
          </tr>
          <tr class="usage-detail" style="display:none"><td colspan="6">
            <table class="usage-detail-tbl"><thead><tr><th>Provider</th><th>Model</th><th>Total</th><th>Input</th><th>Output</th><th>Calls</th></tr></thead>
            <tbody>${c.providers.map(p=>`<tr>
              <td>${esc(p.provider)}</td><td>${esc(p.model||'-')}</td>
              <td><strong>${fmt(p.total_tokens)}</strong></td><td>${fmt(p.input_tokens)}</td>
              <td>${fmt(p.output_tokens)}</td><td>${p.calls}</td>
            </tr>`).join('')}</tbody></table>
          </td></tr>`;
        }).join('')}</tbody>
        <tfoot><tr class="usage-foot">
          <td><strong>${getLanguage()==='en'?'Total':'Gesamt'} (${sorted.length} Conversations)</strong></td>
          <td class="usage-td-num"><strong>${fmt(grand.total_tokens||0)}</strong></td>
          <td class="usage-td-num">${fmt(grand.input_tokens||0)}</td>
          <td class="usage-td-num">${fmt(grand.output_tokens||0)}</td>
          <td class="usage-td-num">${grand.calls||0}</td>
          <td></td>
        </tr></tfoot>
      </table>`;
  }catch(e){tableEl.innerHTML=`<div class="surface-empty">${t('common.errorPrefix')}: ${esc(e.message)}</div>`;}
}

function sortUsage(key){
  if(_usageSortKey===key)_usageSortAsc=!_usageSortAsc;
  else{_usageSortKey=key;_usageSortAsc=false;}
  loadConversationUsage();
}

function toggleUsageDetail(row){
  const detail=row.nextElementSibling;
  if(detail&&detail.classList.contains('usage-detail')){
    detail.style.display=detail.style.display==='none'?'':'none';
  }
}
