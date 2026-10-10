'use strict';
let globalHistoryState=null,globalHistoryPreview=null,globalHistoryBusy=false,globalHistoryRestoring=false,globalHistoryLoading=false;
let globalHistoryRequest=0,globalHistoryPreviewRequest=0,globalHistoryLoadedAt=0,globalHistoryLimit=20;
let globalHistoryPortable=null,globalHistoryExporting=false;
const globalFileNames={'badges.dat':'成就记录','rankings.dat':'排行榜与每日记录'};
function globalProgressLabel(health){
  const labels={protected:'成就与排行榜最近文件已备份',warning:'全局进度结构不支持，原始字节已保留',blocked:'全局历史新增受阻',paused:'全局自动历史已暂停',waiting:'等待游戏产生成就与排行榜文件',working:'正在核对全局历史',unknown:'全局历史尚未确认',archived:'正在查看其他存档目录的全局历史'};
  const present=Object.keys(health?.files||{});
  const label=health?.state==='protected'&&present.length===1?`${globalFileNames[present[0]]||'已有全局文件'}最近文件已备份`:labels[health?.state]||labels.unknown;
  return label+(health?.error?' · '+health.error:'');
}
function globalSummary(name,summary){
  if(!summary)return '捕获时结构不支持，仅保留原始字节';
  return name==='badges.dat'?`${summary.badges} 项成就`:`累计 ${summary.total} 局，获胜 ${summary.won} 局，排行榜 ${summary.records} 项，每日记录 ${summary.daily_history} 项`;
}
function globalHistoryCurrent(context){return !state?.backup_context||state.backup_context===context;}
function renderGlobalHistoryControls(){
  $('#global-history-library').disabled=globalHistoryBusy;$('#global-history-reload').disabled=globalHistoryBusy;
  $('#global-history-more').disabled=globalHistoryBusy;$('#global-history-close').disabled=globalHistoryRestoring;
  $('#global-history-recovery').disabled=globalHistoryRestoring;
  $('#global-history-repreview').disabled=globalHistoryBusy||!globalHistoryPreview;
  for(const button of $$('[data-global-history-export],[data-global-history-preview],[data-global-history-portable]'))button.disabled=globalHistoryBusy||button.dataset.invalid==='true';
  for(const input of $$('[data-global-restore-name]'))input.disabled=globalHistoryRestoring||input.dataset.invalid==='true';
  $('#global-history-version').disabled=globalHistoryRestoring;$('#global-history-confirm').disabled=globalHistoryRestoring;
  const chosen=$$('[data-global-restore-name]').some(input=>input.checked&&!input.disabled);
  $('#global-history-restore').disabled=globalHistoryBusy||!globalHistoryPreview||!globalHistoryCurrent(globalHistoryPreview.context)||!chosen||!$('#global-history-version').checked||!$('#global-history-confirm').checked;
  $('#global-history-export-close').disabled=globalHistoryExporting;$('#global-history-export-version').disabled=globalHistoryExporting;
  for(const input of $$('[data-global-portable-name]'))input.disabled=globalHistoryExporting||input.dataset.invalid==='true';
  $('#global-history-portable-export').disabled=globalHistoryBusy||!globalHistoryPortable||!globalHistoryCurrent(globalHistoryPortable.context)||!$('#global-history-export-version').checked||!$$('[data-global-portable-name]').some(input=>input.checked&&!input.disabled);
}
function renderGlobalHistory(){
  const value=globalHistoryState;if(!value)return;
  $('#global-history-health').textContent=globalProgressLabel(value.health);
  $('#global-history-storage').textContent=`此库 ${value.history.length} / ${value.snapshot_limit} 份历史，占用 ${(value.storage.bytes/1048576).toFixed(2)} / ${(value.storage.limit/1048576).toFixed(0)} MiB。内容不变时不重复保存，达到容量后停止新增并保留已有历史。`+(value.storage.pending_originals?` 另有 ${value.storage.pending_originals} 份中断暂存原件保留，未计作已保护快照。`:'');
  $('#global-history-library').innerHTML=value.libraries.map(row=>`<option value="${escapeHTML(row.id)}">${row.current?'当前存档目录':'其他存档目录'} · ${escapeHTML(row.id.slice(0,12))}</option>`).join('');
  $('#global-history-library').value=value.library;
  $('#global-history-list').innerHTML=value.history.slice(0,globalHistoryLimit).map(row=>{
    const entries=Object.entries(row.files),valid=entries.some(([,item])=>item.valid);
    return `<article class="backup-card"><h3>${escapeHTML(fmtTime(row.time))}</h3>${entries.map(([name,item])=>`<p>${escapeHTML(globalFileNames[name])} · ${escapeHTML(globalSummary(name,item.summary))}${item.error?' · '+escapeHTML(item.error):''}</p>`).join('')}<div class="form-actions"><button type="button" class="secondary" data-global-history-export="${escapeHTML(row.id)}">导出原始副本</button><button type="button" class="secondary" data-global-history-portable="${escapeHTML(row.id)}" data-invalid="${!valid}" ${valid?'':'disabled'}>导出搬机迁移包</button><button type="button" class="secondary" data-global-history-preview="${escapeHTML(row.id)}" data-invalid="${!valid}" ${valid?'':'disabled'}>预览逐文件恢复</button></div></article>`;
  }).join('')||'<p class="muted">游戏产生全局文件后，灯火会自动保留历史。现有局内存档历史仍在下方。</p>';
  $('#global-history-more').hidden=value.history.length<=globalHistoryLimit;
  for(const button of $$('[data-global-history-export]'))button.addEventListener('click',()=>exportGlobalHistory(button.dataset.globalHistoryExport));
  for(const button of $$('[data-global-history-preview]'))button.addEventListener('click',()=>previewGlobalHistory(button.dataset.globalHistoryPreview));
  for(const button of $$('[data-global-history-portable]'))button.addEventListener('click',()=>openGlobalHistoryPortable(button.dataset.globalHistoryPortable));
  renderGlobalHistoryControls();
}
async function loadGlobalHistory(force=false){
  if(globalHistoryState&&!globalHistoryCurrent(globalHistoryState.context)){
    globalHistoryLoadedAt=0;$('#global-history-library').value='';globalHistoryPreview=null;globalHistoryPreviewRequest++;
    globalHistoryPortable=null;
    if($('#global-history-export-dialog').open)inlineError($('#global-history-export-error'),'存档连接已变化，请关闭后重新选择历史导出。');
    $('#global-history-health').textContent='存档连接已变化，正在重新读取全局历史。';renderGlobalHistoryControls();
  }
  if(globalHistoryBusy||globalHistoryLoading||!force&&Date.now()-globalHistoryLoadedAt<10000)return;
  globalHistoryLoading=true;const request=++globalHistoryRequest,context=state?.backup_context;
  const library=$('#global-history-library').value;
  try{
    const value=await getJSON('/api/global-history?'+new URLSearchParams({...library?{library}:{},...context?{context}:{}}));
    if(request!==globalHistoryRequest||context&&!globalHistoryCurrent(context))return;
    globalHistoryState=value;globalHistoryLoadedAt=Date.now();
    if(globalHistoryPreview&&!globalHistoryCurrent(globalHistoryPreview.context)){
      globalHistoryPreview=null;inlineError($('#global-history-restore-error'),'存档连接已变化，请关闭预览并重新选择历史；尚未恢复。');
    }
    renderGlobalHistory();inlineError($('#global-history-error'),'');
  }catch(error){if(request===globalHistoryRequest){$('#global-history-health').textContent='全局历史状态尚未确认';inlineError($('#global-history-error'),error.message);}}
  finally{if(request===globalHistoryRequest)globalHistoryLoading=false;}
}
async function exportGlobalHistory(id,portable=null){
  if(globalHistoryBusy||!globalHistoryState)return;
  const value=portable||globalHistoryState;globalHistoryBusy=true;globalHistoryExporting=!!portable;renderGlobalHistoryControls();
  try{
    if(!globalHistoryCurrent(value.context))throw new Error('连接已变化，请重新读取全局历史。');
    const response=await fetch('/api/global-history',{method:'POST',headers:{'Content-Type':'application/json','X-Companion-Token':token},body:JSON.stringify({action:portable?'portable-export':'export',context:value.context,library:value.library,id,...portable?{selected:portable.selected,version:'4.0.2',version_confirmed:true}:{}})});
    if(!response.ok)throw new Error((await response.json()).error||'全局历史导出未完成');
    const blob=await response.blob();if(!globalHistoryCurrent(value.context))throw new Error('连接已变化，请重新选择并导出。');
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`灯火-${portable?'全局迁移包':'全局原件'}-${id.slice(0,12)}.zip`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    inlineError($('#global-history-error'),'');
    if(portable){globalHistoryPortable=null;$('#global-history-export-dialog').close();$('#global-history-result').textContent='已导出全局历史迁移包。请在目标灯火的「搬机与迁移」中选择此文件，逐份核对后恢复。';}
  }catch(error){inlineError($(portable?'#global-history-export-error':'#global-history-error'),error.message);}
  finally{globalHistoryBusy=globalHistoryExporting=false;renderGlobalHistoryControls();}
}
function openGlobalHistoryPortable(id){
  if(globalHistoryBusy||!globalHistoryState)return;
  const row=globalHistoryState.history.find(row=>row.id===id);if(!row)return;
  globalHistoryPortable={id,library:globalHistoryState.library,context:globalHistoryState.context};
  $('#global-history-export-choices').innerHTML=Object.entries(row.files).map(([name,item])=>`<label class="check"><input type="checkbox" data-global-portable-name="${escapeHTML(name)}" data-invalid="${!item.valid}" ${item.valid?'':'disabled'}>${escapeHTML(globalFileNames[name])} · ${escapeHTML(globalSummary(name,item.summary))}${item.error?' · '+escapeHTML(item.error):''}</label>`).join('');
  $('#global-history-export-version').checked=false;inlineError($('#global-history-export-error'),'');
  for(const input of $$('[data-global-portable-name]'))input.addEventListener('change',renderGlobalHistoryControls);
  $('#global-history-export-dialog').showModal();renderGlobalHistoryControls();
}
$('#global-history-export-version').addEventListener('change',renderGlobalHistoryControls);
$('#global-history-export-close').addEventListener('click',()=>{if(!globalHistoryExporting){globalHistoryPortable=null;$('#global-history-export-dialog').close();}});
$('#global-history-export-dialog').addEventListener('cancel',event=>{if(globalHistoryExporting)event.preventDefault();else globalHistoryPortable=null;});
$('#global-history-export-form').addEventListener('submit',async event=>{
  event.preventDefault();renderGlobalHistoryControls();if($('#global-history-portable-export').disabled)return;
  const value={...globalHistoryPortable,selected:$$('[data-global-portable-name]').filter(input=>input.checked&&!input.disabled).map(input=>input.dataset.globalPortableName)};
  await exportGlobalHistory(value.id,value);
});
async function previewGlobalHistory(id,library=globalHistoryState?.library){
  if(globalHistoryBusy||!globalHistoryState)return;
  const context=globalHistoryState.context,request=++globalHistoryPreviewRequest;
  globalHistoryBusy=true;renderGlobalHistoryControls();
  try{
    const result=await post('/api/global-history',{action:'restore-preview',context,library,id});
    if(request!==globalHistoryPreviewRequest||!globalHistoryCurrent(context))return;
    globalHistoryPreview=result;
    $('#global-history-target').textContent=`恢复目标：${result.target_root}\n${result.message}`;
    $('#global-history-choices').innerHTML=result.files.map(row=>`<label class="check"><input type="checkbox" data-global-restore-name="${escapeHTML(row.name)}" data-invalid="${!row.valid}" ${row.valid?'':'disabled'}>恢复${escapeHTML(globalFileNames[row.name])} · ${escapeHTML(globalSummary(row.name,row.source))} · ${row.target_exists?'当前文件存在，先保留原件':'目标尚无此文件'}${row.same_bytes?' · 与当前字节相同':''}${row.error?' · '+escapeHTML(row.error):''}</label>`).join('');
    $('#global-history-version').checked=false;$('#global-history-confirm').checked=false;
    for(const input of $$('[data-global-restore-name]'))input.addEventListener('change',renderGlobalHistoryControls);
    inlineError($('#global-history-restore-error'),'');if(!$('#global-history-dialog').open)$('#global-history-dialog').showModal();
  }catch(error){inlineError($('#global-history-error'),error.message);if($('#global-history-dialog').open)inlineError($('#global-history-restore-error'),error.message);}
  finally{globalHistoryBusy=false;renderGlobalHistoryControls();}
}
$('#global-history-reload').addEventListener('click',()=>loadGlobalHistory(true));
$('#global-history-library').addEventListener('change',()=>{globalHistoryLimit=20;loadGlobalHistory(true);});
$('#global-history-more').addEventListener('click',()=>{globalHistoryLimit+=20;renderGlobalHistory();});
$('#global-history-version').addEventListener('change',renderGlobalHistoryControls);
$('#global-history-confirm').addEventListener('change',renderGlobalHistoryControls);
$('#global-history-close').addEventListener('click',()=>{if(!globalHistoryRestoring){globalHistoryPreview=null;globalHistoryPreviewRequest++;$('#global-history-dialog').close();}});
$('#global-history-dialog').addEventListener('cancel',event=>{if(globalHistoryRestoring)event.preventDefault();else{globalHistoryPreview=null;globalHistoryPreviewRequest++;}});
$('#global-history-repreview').addEventListener('click',()=>{if(globalHistoryPreview)previewGlobalHistory(globalHistoryPreview.id,globalHistoryPreview.library);});
$('#global-history-recovery').addEventListener('click',()=>{if(!globalHistoryRestoring){globalHistoryPreview=null;globalHistoryPreviewRequest++;$('#global-history-dialog').close();navigate('migration');}});
$('#global-history-restore-form').addEventListener('submit',async event=>{
  event.preventDefault();renderGlobalHistoryControls();if($('#global-history-restore').disabled)return;
  const preview=globalHistoryPreview,choices=Object.fromEntries($$('[data-global-restore-name]').map(input=>[input.dataset.globalRestoreName,input.checked&&!input.disabled?'replace':'keep']));
  globalHistoryBusy=globalHistoryRestoring=true;renderGlobalHistoryControls();
  try{
    const result=await post('/api/global-history',{action:'restore',context:preview.context,library:preview.library,id:preview.id,expected:preview.expected,
      choices,version:'4.0.2',version_confirmed:$('#global-history-version').checked,confirmed:$('#global-history-confirm').checked});
    $('#global-history-result').textContent=result.message+' 原件保留于：'+result.retained_directory;
    globalHistoryPreview=null;$('#global-history-dialog').close();globalHistoryLoadedAt=0;await poll();
  }catch(error){inlineError($('#global-history-restore-error'),error.message);$('#global-history-confirm').checked=false;}
  finally{globalHistoryBusy=globalHistoryRestoring=false;renderGlobalHistoryControls();}
  if(!globalHistoryPreview)await loadGlobalHistory(true);
});
