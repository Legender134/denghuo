'use strict';
let updateRequest=false;
function renderUpdate(){
  const update=state?.update||{},status=update.state||'idle';
  const busy=updateRequest||['checking','downloading','verifying','installing'].includes(status);
  const available=['available','ready'].includes(status);
  $('#update-entry').textContent=available?`更新 ${update.latest_version}`:'检查更新';
  $('#update-entry').classList.toggle('update-available',available);
  $('#update-entry').disabled=!state||busy;
  $('#update-status').textContent=`灯火 ${update.current_version||''} · ${update.message||'启动时检查更新'}${status==='downloading'?` ${update.progress}%`:''}`;
  $('#update-notes').textContent=update.notes||'';
  $('#update-notes-details').hidden=!update.notes;
  $('#update-check').disabled=!state||busy;
  $('#update-download').hidden=status!=='available';
  $('#update-install').hidden=status!=='ready'||!update.can_install;
  $('#update-cancel').hidden=status!=='downloading';
  $('#update-cancel').disabled=!state||updateRequest;
  $('#update-download').disabled=$('#update-install').disabled=!state||busy;
  if(status==='ready'&&!update.can_install)$('#update-status').textContent+=' · 源码运行，请使用正式安装版更新';
}
async function updateAction(action){
  if(updateRequest)return;
  const owner=state?.started;
  updateRequest=true;renderUpdate();
  try{
    if(action==='install'){
      const captured=currentWebDraft();
      const reported=await post('/api/session-exit',{action:'report',surface_id:webSurfaceId,kind:'web',label:'完整网页面板',revision:captured.revision,dirty:captured.dirty,draft:captured.draft});
      const own=reported.exit?.participants?.find(row=>row.surface_id===webSurfaceId);
      if(!own||own.revision!==captured.revision||own.dirty!==captured.dirty||!own.has_reported_draft||currentWebDraft().revision!==captured.revision)throw new Error('输入发生变化，请核对后再安装');
    }
    if(!state||state.started!==owner)return;
    const result=await post('/api/update',{action,surface_id:webSurfaceId});
    if(!state||state.started!==owner)return;
    state.update=result.update;
    inlineError($('#update-error'),'');
  }catch(error){inlineError($('#update-error'),error.message);}
  finally{updateRequest=false;renderUpdate();}
}
$('#update-entry').addEventListener('click',()=>{navigate('help');if(!['available','ready'].includes(state?.update?.state))void updateAction('check');$('#update-section').scrollIntoView({block:'nearest'});});
for(const action of ['check','download','install','cancel'])$('#update-'+action).addEventListener('click',()=>void updateAction(action));
