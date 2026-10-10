'use strict';
let backupDestinationState=null,backupDestinationBaseline=null,backupDestinationGeneration=0;
let backupDestinationRequest=0,backupDestinationLoading=false,backupDestinationBusy=false,backupDestinationPreview=null;
function backupDestinationDirty(){return $('#backup-destination-start-new').checked||(backupDestinationBaseline===null?!!$('#backup-destination-root').value:$('#backup-destination-root').value!==backupDestinationBaseline);}
function captureBackupDestinationDraft(){return backupDestinationDirty()?{backup_root:$('#backup-destination-root').value,start_new:$('#backup-destination-start-new').checked}:null;}
function checkedBackupDestinationDraft(draft){
  if(!draft||typeof draft!=='object'||Array.isArray(draft)||Object.keys(draft).some(key=>!['backup_root','start_new'].includes(key))||typeof draft.backup_root!=='string'||draft.backup_root.length>1000||('start_new' in draft&&typeof draft.start_new!=='boolean'))throw new Error('备份位置草稿格式不正确；原副本仍保留。');
  return {backup_root:draft.backup_root,start_new:draft.start_new===true};
}
function restoreBackupDestinationDraft(draft){
  const raw=checkedBackupDestinationDraft(draft);backupDestinationGeneration++;backupDestinationPreview=null;
  $('#backup-destination-root').value=raw.backup_root;$('#backup-destination-start-new').checked=raw.start_new;$('#backup-destination-preview').hidden=true;
  $('#backup-destination-confirm').checked=false;$('#backup-destination-message').textContent='已找回备份位置草稿，尚未复制历史或切换位置。请核对后预览。';renderBackupDestinationControls();
}
function renderBackupDestinationControls(){
  $('#backup-destination-submit').disabled=backupDestinationBusy||!backupDestinationState;
  $('#backup-destination-reload').disabled=backupDestinationBusy;
  $('#backup-destination-apply').disabled=backupDestinationBusy||!backupDestinationPreview||!$('#backup-destination-confirm').checked;
}
async function loadBackupDestination(force=false){
  if(backupDestinationLoading||backupDestinationBusy)return;backupDestinationLoading=true;
  const request=++backupDestinationRequest,generation=backupDestinationGeneration;
  try{const result=await getJSON('/api/backup-destination');if(request!==backupDestinationRequest)return;
    const edited=backupDestinationDirty();
    if(force&&generation!==backupDestinationGeneration)throw new Error('读取期间有新编辑，备份位置草稿仍保留。');
    if(force||!edited){backupDestinationState=result;backupDestinationBaseline=result.backup_root;$('#backup-destination-root').value=result.backup_root;
      if(force){backupDestinationGeneration++;backupDestinationPreview=null;$('#backup-destination-preview').hidden=true;$('#backup-destination-confirm').checked=false;$('#backup-destination-start-new').checked=false;}}
    else if(backupDestinationState&&result.backup_root!==backupDestinationState.backup_root){
      $('#backup-destination-message').textContent='备份位置已被其他窗口修改；本地草稿保留。请重新读取已保存位置，再决定是否切换。';
    }
    if(!backupDestinationState)backupDestinationState=result;
    $('#backup-destination-current').textContent='当前备份目录：'+result.directory;
    $('#backup-destination-health').textContent=result.available?'此位置可用；自动备份仍按当前开关运行。':'此位置不可用：'+(result.error||'请重新连接原磁盘或明确切换位置。');
    if(force)inlineError($('#backup-destination-error'),'');
  }catch(error){if(request===backupDestinationRequest)inlineError($('#backup-destination-error'),error.message);}
  finally{if(request===backupDestinationRequest){backupDestinationLoading=false;renderBackupDestinationControls();}}
}
function backupDestinationEdited(){
  backupDestinationGeneration++;backupDestinationPreview=null;$('#backup-destination-preview').hidden=true;$('#backup-destination-confirm').checked=false;
  $('#backup-destination-message').textContent=backupDestinationDirty()?'位置草稿尚未应用，原位置仍在使用。':'正在使用已保存的位置。';renderBackupDestinationControls();
}
$('#backup-destination-root').addEventListener('input',backupDestinationEdited);
$('#backup-destination-start-new').addEventListener('change',backupDestinationEdited);
$('#backup-destination-reload').addEventListener('click',()=>loadBackupDestination(true));
$('#backup-destination-confirm').addEventListener('change',renderBackupDestinationControls);
$('#backup-destination-form').addEventListener('submit',async event=>{
  event.preventDefault();if(backupDestinationBusy||!backupDestinationState)return;
  const generation=backupDestinationGeneration,submitted=$('#backup-destination-root').value,startNew=$('#backup-destination-start-new').checked;
  backupDestinationBusy=true;backupDestinationPreview=null;$('#backup-destination-preview').hidden=true;renderBackupDestinationControls();
  try{const result=await post('/api/backup-destination',{action:'preview',backup_root:submitted,start_new:startNew,
      expected_settings_revision:backupDestinationState.settings_revision,context:backupDestinationState.context});
    if(generation!==backupDestinationGeneration)return;
    backupDestinationPreview={...result,backup_root:result.backup_root??submitted,start_new:result.start_new??startNew};$('#backup-destination-confirm').checked=false;
    $('#backup-destination-confirm-text').textContent=result.start_new?'我已知晓旧历史本次无法复制，确认保留旧历史并在新位置继续备份':'我已核对位置，确认复制历史并切换后续备份';
    $('#backup-destination-apply').textContent=result.start_new?'保留离线旧历史，在新位置继续':'保留原件，复制并切换';
    $('#backup-destination-summary').textContent=result.start_new?`原备份位置暂不可用：${result.source_directory}\n新位置：${result.target_directory}\n旧历史本次未读取、未复制；旧目的地和原件仍保留。\n${result.message}`:`从 ${result.source_directory}\n复制到 ${result.target_directory}\n${result.file_count} 个文件，共 ${result.bytes} 字节；${result.library_count} 个存档库，${result.verified_archives} 份已校验备份。\n${result.message||'保留原件；确认后才复制历史并切换后续备份。'}`;
    $('#backup-destination-preview').hidden=false;inlineError($('#backup-destination-error'),'');
  }catch(error){inlineError($('#backup-destination-error'),error.message);}
  finally{backupDestinationBusy=false;renderBackupDestinationControls();}
});
if(typeof view!=='undefined'&&view==='play-settings')loadBackupDestination();
$('#backup-destination-apply').addEventListener('click',async()=>{
  if(backupDestinationBusy||!backupDestinationPreview||!$('#backup-destination-confirm').checked)return;
  const preview=backupDestinationPreview,generation=backupDestinationGeneration;
  backupDestinationBusy=true;settingsWriteGeneration++;backupDestinationRequest++;backupDestinationLoading=false;renderBackupDestinationControls();
  try{const result=await post('/api/backup-destination',{action:'apply',backup_root:preview.backup_root,start_new:preview.start_new,
      expected_settings_revision:preview.settings_revision,context:preview.context,expected:preview.expected,confirmed:true});
    backupDestinationBaseline=result.settings.backup_root;
    backupDestinationState={backup_root:result.settings.backup_root,directory:result.directory,
      settings_revision:result.settings_revision,context:result.context};
    if(generation===backupDestinationGeneration){$('#backup-destination-root').value=result.settings.backup_root;$('#backup-destination-start-new').checked=false;backupDestinationPreview=null;
      $('#backup-destination-preview').hidden=true;$('#backup-destination-confirm').checked=false;}
    $('#backup-destination-current').textContent='当前备份目录：'+result.directory;
    $('#backup-destination-message').textContent=(result.message||'历史已复制，后续备份使用新位置；原件保留。')+(backupDestinationDirty()?' 新的位置修改仍是未应用草稿。':'');
    inlineError($('#backup-destination-error'),'');await poll();
  }catch(error){inlineError($('#backup-destination-error'),error.message);}
  finally{backupDestinationBusy=false;renderBackupDestinationControls();}
});
