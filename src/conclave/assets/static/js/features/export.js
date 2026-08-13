// static/js/features/export.js

async function exportConv(){
  if(!currentConvId){toast(t('workspace.noConversation'),'err');return;}
  try{
    const d=await req('GET',`/conversations/${currentConvId}/export`);
    const blob=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob);
    const a=document.createElement('a');
    a.href=url;
    a.download=`conclave-export-${currentConvId.slice(0,8)}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast(t('workspace.exportDownloaded'),'ok');
  }catch(e){toast(e.message,'err');}
}
