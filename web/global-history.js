'use strict';
let globalHistoryState=null,globalHistoryPreview=null,globalHistoryBusy=false,globalHistoryRestoring=false,globalHistoryLoading=false;
let globalHistoryRequest=0,globalHistoryPreviewRequest=0,globalHistoryLoadedAt=0,globalHistoryLimit=20;
let globalHistoryRenderedSource=null;
let globalHistoryPortable=null,globalHistoryExporting=false;
let globalHistoryMaintenance=null,globalHistoryMaintenanceRequest=0,globalHistoryMaintaining=false,globalHistoryOperation=0;
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
function globalHistoryFileSummary(name,item){return item.integrity==='damaged'?'当前历史原件损坏，无法校验':item.integrity==='verified'&&!item.valid?'原始字节完整，当前结构校验不支持':globalSummary(name,item.summary);}
function globalHistoryCurrent(context){return !state?.backup_context||state.backup_context===context;}
function globalHistoryScopeCurrent(value){return !!value&&globalHistoryCurrent(value.context)&&(!$('#global-history-library').value||$('#global-history-library').value===value.library)&&($('#global-history-archive').value||null)===(value.archive||null);}
function globalHistoryBytes(value){return `${Number(value||0).toLocaleString()} 字节（${(Number(value||0)/1048576).toFixed(2)} MiB）`;}
function globalHistorySource(value){return {context:value.context,library:value.library,...value.archive?{archive:value.archive}:{}};}
function filterGlobalHistory(value,query='',file='all',health='all'){
  const terms=query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const matches=text=>terms.every(term=>text.toLocaleLowerCase().includes(term));
  const history=value.history.filter(row=>{
    const entries=Object.entries(row.files).filter(([name])=>file==='all'||name===file);
    if(!entries.length)return false;
    if(health==='restorable'&&!entries.some(([,item])=>item.valid))return false;
    if(health==='damaged'&&!entries.some(([,item])=>item.integrity==='damaged'))return false;
    if(health==='raw-only'&&!entries.every(([,item])=>item.integrity==='verified'&&!item.valid))return false;
    const date=new Date(row.time*1000);
    return matches([row.id,fmtTime(row.time),Number.isNaN(date.getTime())?'':date.toISOString(),...entries.map(([name,item])=>`${name} ${globalFileNames[name]} ${globalHistoryFileSummary(name,item)} ${item.error||''}`)].join(' '));
  });
  // A damaged manifest cannot prove which files it contains.
  const damaged=(value.damaged_rows||[]).filter(row=>file==='all'&&(health==='all'||health==='damaged')&&matches(`${row.id} ${row.error||''} 损坏历史清单`));
  return {history,damaged,total:value.history.length+(value.damaged_rows||[]).length};
}
function invalidateGlobalHistoryDialogs(){
  const message='存档连接已变化或所选历史库已变化，请重新读取并预览；原选择仍保留。';
  if(globalHistoryPreview&&!globalHistoryScopeCurrent(globalHistoryPreview)){$('#global-history-confirm').checked=false;inlineError($('#global-history-restore-error'),message);}
  if(globalHistoryPortable&&!globalHistoryScopeCurrent(globalHistoryPortable)){$('#global-history-export-version').checked=false;inlineError($('#global-history-export-error'),message);}
  if(globalHistoryMaintenance&&!globalHistoryScopeCurrent(globalHistoryMaintenance)){globalHistoryMaintenance.stale=true;$('#global-history-maintenance-confirm').checked=false;inlineError($('#global-history-maintenance-error'),message);}
}
function renderGlobalHistoryControls(){
  $('#global-history-library').disabled=globalHistoryBusy;$('#global-history-reload').disabled=globalHistoryBusy;
  $('#global-history-archive').disabled=globalHistoryBusy;
  $('#global-history-maintenance-open').disabled=globalHistoryBusy||!globalHistoryState||!!globalHistoryState.archive||!!globalHistoryState.pending_maintenance||!globalHistoryScopeCurrent(globalHistoryState);
  $('#global-history-maintenance-pending').disabled=globalHistoryBusy||!!globalHistoryState?.archive||!globalHistoryState?.pending_maintenance||!globalHistoryScopeCurrent(globalHistoryState);
  $('#global-history-more').disabled=globalHistoryBusy;$('#global-history-close').disabled=globalHistoryRestoring;
  $('#global-history-recovery').disabled=globalHistoryRestoring;
  $('#global-history-repreview').disabled=globalHistoryBusy||!globalHistoryPreview;
  for(const button of $$('[data-global-history-export],[data-global-history-preview],[data-global-history-portable],[data-global-history-file],[data-global-damaged-export]'))button.disabled=globalHistoryBusy||button.dataset.invalid==='true';
  for(const input of $$('[data-global-restore-name]'))input.disabled=globalHistoryRestoring||input.dataset.invalid==='true';
  $('#global-history-version').disabled=globalHistoryRestoring;$('#global-history-confirm').disabled=globalHistoryRestoring;
  const chosen=$$('[data-global-restore-name]').some(input=>input.checked&&!input.disabled);
  $('#global-history-restore').disabled=globalHistoryBusy||!globalHistoryScopeCurrent(globalHistoryPreview)||!chosen||!$('#global-history-version').checked||!$('#global-history-confirm').checked;
  $('#global-history-export-close').disabled=globalHistoryExporting;$('#global-history-export-version').disabled=globalHistoryExporting;
  for(const input of $$('[data-global-portable-name]'))input.disabled=globalHistoryExporting||input.dataset.invalid==='true';
  $('#global-history-portable-export').disabled=globalHistoryBusy||!globalHistoryScopeCurrent(globalHistoryPortable)||!$('#global-history-export-version').checked||!$$('[data-global-portable-name]').some(input=>input.checked&&!input.disabled);
  $('#global-history-archive-export').disabled=globalHistoryBusy||!globalHistoryState?.archive||!globalHistoryScopeCurrent(globalHistoryState);
  $('#global-history-maintenance-close').disabled=globalHistoryMaintaining;
  for(const id of ['global-history-maintenance-choice','global-history-maintenance-confirm'])$('#'+id).disabled=globalHistoryBusy;
  $('#global-history-maintenance-repreview').disabled=globalHistoryBusy||!globalHistoryMaintenance;
  const maintenanceChoice=$('#global-history-maintenance-choice').value,maintenance=globalHistoryMaintenance;
  const allowed=maintenance?.kind==='recovery'?maintenanceChoice==='continue'&&maintenance.can_continue||maintenanceChoice==='cancel'&&maintenance.can_cancel:maintenanceChoice==='retain-local';
  $('#global-history-maintenance-submit').disabled=globalHistoryBusy||!globalHistoryScopeCurrent(maintenance)||maintenance.stale||!allowed||!$('#global-history-maintenance-confirm').checked;
}
function renderGlobalHistory(){
  const value=globalHistoryState;if(!value)return;
  const holders=['#global-history-list','#global-history-damaged'].map(selector=>$(selector)),active=document.activeElement;
  const action=active&&holders.some(holder=>holder.contains(active))&&Object.entries(active.dataset).find(([name])=>['globalHistoryExport','globalHistoryPreview','globalHistoryPortable','globalHistoryFile','globalDamagedExport'].includes(name));
  const source=JSON.stringify(globalHistorySource(value)),sameSource=source===globalHistoryRenderedSource;
  const filtered=filterGlobalHistory(value,$('#global-history-search').value,$('#global-history-file-filter').value,$('#global-history-health-filter').value);
  $('#global-history-health').textContent=globalProgressLabel(value.health);
  const selectedArchive=(value.archives||[]).find(row=>row.id===value.archive),selectedCount=value.archive?selectedArchive?.count??value.history.length+(value.damaged_rows||[]).length:value.storage.active_count??value.history.length;
  $('#global-history-storage').textContent=`${value.archive?'所选归档':'活动库'} ${selectedCount} 份历史，占用 ${globalHistoryBytes(value.storage.bytes)}。活动额度 ${value.storage.active_count??value.history.length} / ${value.snapshot_limit} 份、${globalHistoryBytes(value.storage.active_bytes??value.storage.bytes)} / ${(value.storage.limit/1048576).toFixed(0)} MiB。内容不变时不重复保存，达到活动容量后停止新增。普通导出不会释放活动额度。`+(value.storage.pending_originals?` 另有 ${value.storage.pending_originals} 份中断暂存原件保留，未计作已保护快照。`:'')+(value.storage.total_local_bytes!=null?` 本地活动库与保留归档${value.storage.inventory_complete===false?'已核对至少 ': '合计 '}${globalHistoryBytes(value.storage.total_local_bytes)}。`:'')+(value.storage.inventory_complete===false?` 另有 ${value.storage.unaccounted_containers||1} 处保留原件未能核对、未计入上述下限；其字节数未知。`:'')+(value.archives||[]).filter(row=>row.state!=='completed').map(row=>` 保留归档 ${row.id.slice(0,12)} 尚不可核对，数量/字节未知（未完整核验），原件保留：${row.error||'需要核对维护状态'}。`).join('');
  $('#global-history-library').innerHTML=value.libraries.map(row=>`<option value="${escapeHTML(row.id)}">${row.current?'当前存档目录':'其他存档目录'} · ${escapeHTML(row.id.slice(0,12))}</option>`).join('');
  $('#global-history-library').value=value.library;
  $('#global-history-archive').innerHTML='<option value="">活动历史库</option>'+(value.archives||[]).map(row=>`<option value="${escapeHTML(row.id)}" ${row.state!=='completed'?'disabled':''}>保留归档 ${escapeHTML(row.id.slice(0,12))} · ${row.state==='completed'?`${row.count} 份 · ${globalHistoryBytes(row.bytes)}`:`${row.state==='unassociated'?'未完成关联':'原件暂不可核对'} · 数量/字节未知（未完整核验）`}</option>`).join('');
  $('#global-history-archive').value=value.archive||'';
  $('#global-history-archive-export').hidden=!value.archive;
  $('#global-history-maintenance-pending').hidden=!value.pending_maintenance;
  $('#global-history-damaged').innerHTML=filtered.damaged.map(row=>`<article class="backup-card"><h3>隔离的损坏历史清单 · ${escapeHTML(row.id.slice(0,12))}</h3><p>${escapeHTML(row.error)} · ${row.bytes==null?'字节数暂不可核对':globalHistoryBytes(row.bytes)}</p><p class="muted">该清单不能作为恢复依据；其他独立健康历史与健康文件仍可使用。${row.available===false?'此原件目前不可读取，未自动覆盖或移除。':'原始字节仍保留。'}</p><button type="button" class="secondary" data-global-damaged-export="${escapeHTML(row.id)}" data-invalid="${row.available===false}" ${row.available===false?'disabled':''}>导出损坏清单原件</button></article>`).join('');
  $('#global-history-list').innerHTML=filtered.history.slice(0,globalHistoryLimit).map(row=>{
    const entries=Object.entries(row.files),valid=entries.some(([,item])=>item.valid);
    return `<article class="backup-card"><h3>${escapeHTML(fmtTime(row.time))}</h3>${entries.map(([name,item])=>`<p>${escapeHTML(globalFileNames[name])} · ${escapeHTML(globalHistoryFileSummary(name,item))}${item.error?' · '+escapeHTML(item.error):''}${!item.valid?' · 此文件不可恢复，其他健康文件可独立使用':''}</p>`).join('')}<div class="form-actions"><button type="button" class="secondary" data-global-history-export="${escapeHTML(row.id)}">导出原始副本</button>${entries.filter(([,item])=>item.valid).map(([name])=>`<button type="button" class="secondary" data-global-history-file="${escapeHTML(row.id)}" data-file="${escapeHTML(name)}">仅导出${escapeHTML(globalFileNames[name])}原始副本</button>`).join('')}<button type="button" class="secondary" data-global-history-portable="${escapeHTML(row.id)}" data-invalid="${!valid}" ${valid?'':'disabled'}>选择文件导出搬机迁移包</button><button type="button" class="secondary" data-global-history-preview="${escapeHTML(row.id)}" data-invalid="${!valid}" ${valid?'':'disabled'}>预览健康文件恢复</button></div></article>`;
  }).join('')||(filtered.damaged.length?'':filtered.total?'<p class="muted">没有符合条件的历史。可修改搜索、筛选或清除条件；原历史仍保留。</p>':'<p class="muted">游戏产生全局文件后，灯火会自动保留历史。现有局内存档历史仍在下方。</p>');
  $('#global-history-count').textContent=`当前库共 ${filtered.total} 份，符合条件 ${filtered.history.length+filtered.damaged.length} 份，已显示 ${Math.min(filtered.history.length,globalHistoryLimit)+filtered.damaged.length} 份。搜索与筛选覆盖当前所选库或归档的全部历史。`;
  $('#global-history-more').hidden=filtered.history.length<=globalHistoryLimit;
  for(const button of $$('[data-global-history-export]'))button.addEventListener('click',()=>exportGlobalHistory(button.dataset.globalHistoryExport));
  for(const button of $$('[data-global-history-preview]'))button.addEventListener('click',()=>previewGlobalHistory(button.dataset.globalHistoryPreview));
  for(const button of $$('[data-global-history-portable]'))button.addEventListener('click',()=>openGlobalHistoryPortable(button.dataset.globalHistoryPortable));
  for(const button of $$('[data-global-history-file]'))button.addEventListener('click',()=>exportGlobalHistory(button.dataset.globalHistoryFile,null,[button.dataset.file]));
  for(const button of $$('[data-global-damaged-export]'))button.addEventListener('click',()=>exportGlobalHistory(button.dataset.globalDamagedExport,null,null,'damaged-export'));
  renderGlobalHistoryControls();
  globalHistoryRenderedSource=source;
  if(action){const [name,id]=action;const next=sameSource&&holders.flatMap(holder=>[...holder.querySelectorAll('button')]).find(button=>button.dataset[name]===id&&button.dataset.file===active.dataset.file&&!button.disabled);(next||$('#global-history-search')).focus({preventScroll:true});}
}
async function loadGlobalHistory(force=false){
  if(globalHistoryState&&!globalHistoryCurrent(globalHistoryState.context)){
    globalHistoryLoadedAt=0;$('#global-history-library').value='';$('#global-history-archive').value='';globalHistoryPreviewRequest++;globalHistoryMaintenanceRequest++;globalHistoryOperation++;
    invalidateGlobalHistoryDialogs();
    $('#global-history-health').textContent='存档连接已变化，正在重新读取全局历史。';renderGlobalHistoryControls();
  }
  if(globalHistoryBusy||globalHistoryLoading&&!force||!force&&Date.now()-globalHistoryLoadedAt<10000)return;
  globalHistoryLoading=true;const request=++globalHistoryRequest,context=state?.backup_context;
  const library=$('#global-history-library').value,archive=$('#global-history-archive').value;
  try{
    const value=await getJSON('/api/global-history?'+new URLSearchParams({...library?{library}:{},...archive?{archive}:{},...context?{context}:{}}));
    if(request!==globalHistoryRequest||context&&!globalHistoryCurrent(context)||$('#global-history-library').value!==library||$('#global-history-archive').value!==archive)return;
    globalHistoryState=value;globalHistoryLoadedAt=Date.now();
    invalidateGlobalHistoryDialogs();
    renderGlobalHistory();inlineError($('#global-history-error'),'');
  }catch(error){if(request===globalHistoryRequest){$('#global-history-health').textContent='全局历史状态尚未确认';inlineError($('#global-history-error'),error.message);}}
  finally{if(request===globalHistoryRequest)globalHistoryLoading=false;}
}
async function exportGlobalHistory(id,portable=null,selected=null,action='export'){
  if(globalHistoryBusy||!globalHistoryState)return;
  const value=portable||globalHistoryState,operation=++globalHistoryOperation;globalHistoryBusy=true;globalHistoryExporting=!!portable;renderGlobalHistoryControls();
  try{
    if(!globalHistoryScopeCurrent(value))throw new Error('连接或历史库已变化，请重新读取全局历史。');
    const response=await fetch('/api/global-history',{method:'POST',headers:{'Content-Type':'application/json','X-Companion-Token':token},body:JSON.stringify({action:portable?'portable-export':action,...globalHistorySource(value),...id?{id}:{},...selected?{selected}:{},...portable?{selected:portable.selected,version:'4.0.2',version_confirmed:true}:{}})});
    if(!response.ok)throw new Error((await response.json()).error||'全局历史导出未完成');
    const blob=await response.blob();if(operation!==globalHistoryOperation||!globalHistoryScopeCurrent(value))throw new Error('连接或历史库已变化，请重新选择并导出。');
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`灯火-${portable?'全局迁移包':action==='archive-export'?'保留归档':'全局原件'}-${(id||value.archive).slice(0,12)}.zip`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    inlineError($('#global-history-error'),'');
    if(portable){globalHistoryPortable=null;$('#global-history-export-dialog').close();$('#global-history-result').textContent='已导出全局历史迁移包。请在目标灯火的「搬机与迁移」中选择此文件，逐份核对后恢复。';}
  }catch(error){inlineError($(portable?'#global-history-export-error':'#global-history-error'),error.message);}
  finally{globalHistoryBusy=globalHistoryExporting=false;renderGlobalHistoryControls();}
}
function openGlobalHistoryPortable(id){
  if(globalHistoryBusy||!globalHistoryState)return;
  const row=globalHistoryState.history.find(row=>row.id===id);if(!row)return;
  globalHistoryPortable={id,...globalHistorySource(globalHistoryState)};
  $('#global-history-export-choices').innerHTML=Object.entries(row.files).map(([name,item])=>`<label class="check"><input type="checkbox" data-global-portable-name="${escapeHTML(name)}" data-invalid="${!item.valid}" ${item.valid?'':'disabled'}>${escapeHTML(globalFileNames[name])} · ${escapeHTML(globalHistoryFileSummary(name,item))}${item.error?' · '+escapeHTML(item.error):''}</label>`).join('');
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
function renderGlobalHistoryMaintenance(value){
  const recovery=value.kind==='recovery';
  $('#global-history-maintenance-title').textContent=recovery?'核对未完成的全局历史维护':'预览保留归档与恢复活动额度';
  $('#global-history-maintenance-summary').textContent=recovery?
    `维护记录 ${value.id||''} · ${{prepared:'已准备保留原件',continuing:'归档维护中断',cancelling:'取消维护中断',unrecognized:'原件尚不可核对'}[value.state]||'等待核对'}\n${value.message||''}\n${value.continue_reason||''}`:
    `将保留 ${value.records} 份历史清单及其现存原件、${globalHistoryBytes(value.bytes)}；已识别损坏、结构不可用或缺失原件 ${value.damaged_count} 项（共享原件不重复计数）。${value.missing_originals?.length?` 其中 ${value.missing_originals.length} 项已缺失，无法保留或恢复；请核对下方精确列表。`:''}\n${value.message||''}\n本地轮换只恢复活动历史的记录与字节额度，磁盘释放 0 字节；所有归档仍占用本地磁盘。`;
  const latest=value.latest_usable;
  const captureNotice=value.current_library===false?'此旧库恢复活动额度后不新增当前游戏的保护；当前存档目录的保护需在其活动库核对。':'轮换完成后立即尝试保护当前游戏文件，结果另行显示。';
  $('#global-history-maintenance-latest').textContent=recovery?'继续或取消只按本次预览的实际状态执行；内容变化会拒绝并保留输入与原件。':
    latest?`最近可用历史：${fmtTime(latest.time)} · ${latest.id.slice(0,12)} · ${(latest.files||[]).map(name=>globalFileNames[name]||name).join('、')}。此历史会保留在归档中；${captureNotice}`:`没有可验证的健康历史；现存不可用原件仍完整保留。${captureNotice}`;
  $('#global-history-maintenance-originals').innerHTML=(value.originals||[]).map(row=>`<li>${escapeHTML(row.path)}${row.damaged?' · 损坏或结构不可用原件仍保留':''} · ${globalHistoryBytes(row.bytes)} · SHA-256 ${escapeHTML(row.sha256)}</li>`).join('')+(value.missing_originals||[]).map(name=>`<li>${escapeHTML(name)} · 关联原件已缺失，无法保留或恢复</li>`).join('');
  $('#global-history-maintenance-choice').innerHTML='<option value="">预览后选择本次操作</option>'+(recovery?
    `${value.can_continue?'<option value="continue">继续已保留原件的维护，恢复活动额度</option>':''}${value.can_cancel?'<option value="cancel">取消维护，按预览保留或还原原件</option>':''}`:
    '<option value="retain-local">将此库全部历史保留为本地归档，恢复活动额度</option>');
  $('#global-history-maintenance-confirm').checked=false;
}
async function previewGlobalHistoryMaintenance(recovery=false,refresh=false){
  if(globalHistoryBusy||!globalHistoryState||globalHistoryState.archive)return;
  const scope={context:globalHistoryState.context,library:globalHistoryState.library,archive:null,current_library:globalHistoryState.current_library!==false},request=++globalHistoryMaintenanceRequest;
  const previousChoice=refresh?$('#global-history-maintenance-choice').value:'';
  globalHistoryBusy=true;renderGlobalHistoryControls();
  try{
    if(!globalHistoryScopeCurrent(scope))throw new Error('连接或历史库已变化，请重新读取后预览。');
    const result=await post('/api/global-history',{action:recovery?'maintenance-recovery-preview':'maintenance-preview',...globalHistorySource(scope)});
    if(request!==globalHistoryMaintenanceRequest||!globalHistoryScopeCurrent(scope))return;
    if(recovery&&!result?.pending)throw new Error('当前没有未完成的全局历史维护，请关闭预览后重新读取历史。');
    globalHistoryMaintenance={...result,...scope,kind:recovery?'recovery':'retain-local',stale:false};
    renderGlobalHistoryMaintenance(globalHistoryMaintenance);
    if(previousChoice&&(!recovery&&previousChoice==='retain-local'||recovery&&(previousChoice==='continue'&&result.can_continue||previousChoice==='cancel'&&result.can_cancel)))$('#global-history-maintenance-choice').value=previousChoice;
    inlineError($('#global-history-maintenance-error'),'');
    if(!$('#global-history-maintenance-dialog').open)$('#global-history-maintenance-dialog').showModal();
  }catch(error){
    if(request===globalHistoryMaintenanceRequest){
      if(globalHistoryMaintenance)globalHistoryMaintenance.stale=true;
      $('#global-history-maintenance-confirm').checked=false;
      inlineError($('#global-history-error'),error.message);if($('#global-history-maintenance-dialog').open)inlineError($('#global-history-maintenance-error'),error.message);
    }
  }finally{globalHistoryBusy=false;renderGlobalHistoryControls();}
}
$('#global-history-archive-export').addEventListener('click',()=>exportGlobalHistory(null,null,null,'archive-export'));
$('#global-history-maintenance-open').addEventListener('click',()=>previewGlobalHistoryMaintenance(false));
$('#global-history-maintenance-pending').addEventListener('click',()=>previewGlobalHistoryMaintenance(true));
$('#global-history-maintenance-choice').addEventListener('change',()=>{$('#global-history-maintenance-confirm').checked=false;renderGlobalHistoryControls();});
$('#global-history-maintenance-confirm').addEventListener('change',renderGlobalHistoryControls);
$('#global-history-maintenance-repreview').addEventListener('click',()=>{if(globalHistoryMaintenance)previewGlobalHistoryMaintenance(globalHistoryMaintenance.kind==='recovery',true);});
function closeGlobalHistoryMaintenance(){if(!globalHistoryMaintaining){globalHistoryMaintenanceRequest++;globalHistoryMaintenance=null;$('#global-history-maintenance-dialog').close();}}
$('#global-history-maintenance-close').addEventListener('click',closeGlobalHistoryMaintenance);
$('#global-history-maintenance-dialog').addEventListener('cancel',event=>{if(globalHistoryMaintaining)event.preventDefault();else{globalHistoryMaintenanceRequest++;globalHistoryMaintenance=null;}});
$('#global-history-maintenance-form').addEventListener('submit',async event=>{
  event.preventDefault();renderGlobalHistoryControls();if($('#global-history-maintenance-submit').disabled)return;
  const preview=globalHistoryMaintenance,choice=$('#global-history-maintenance-choice').value,operation=++globalHistoryOperation;
  const action=preview.kind==='recovery'?choice==='continue'?'maintenance-continue':'maintenance-cancel':'maintenance';
  globalHistoryBusy=globalHistoryMaintaining=true;renderGlobalHistoryControls();
  try{
    const result=await post('/api/global-history',{action,...globalHistorySource(preview),expected:preview.expected,confirmed:true});
    if(operation!==globalHistoryOperation||!globalHistoryScopeCurrent(preview))throw new Error('连接或历史库已变化，本次回执属于原目标；请重新读取该目标核对维护结果。');
    $('#global-history-result').textContent=(result.message||'本次维护已完成。')+(result.archive_id?` ${result.direction==='cancel'?'已取消的维护记录':'保留归档'} ${result.archive_id}。`:'')+(result.records!=null?` 已保留 ${result.records} 份、${globalHistoryBytes(result.bytes)}。`:'')+(result.active_after?` 活动库现有 ${result.active_after.count} 份、${globalHistoryBytes(result.active_after.bytes)}。`:'')+' 磁盘释放 0 字节；本地保留内容继续占用磁盘。'+(result.health?` ${preview.current_library===false?'所选旧库状态':'当前保护结果'}：${globalProgressLabel(result.health)}。`:'');
    globalHistoryMaintenance=null;$('#global-history-maintenance-dialog').close();globalHistoryLoadedAt=0;
  }catch(error){
    preview.stale=true;$('#global-history-maintenance-confirm').checked=false;inlineError($('#global-history-maintenance-error'),error.message+' 请重新核对；所选操作与原件保留。');
  }finally{globalHistoryBusy=globalHistoryMaintaining=false;renderGlobalHistoryControls();}
  if(!globalHistoryMaintenance){await loadGlobalHistory(true);await poll();}
});
async function previewGlobalHistory(id,library=globalHistoryState?.library,archive=globalHistoryState?.archive){
  if(globalHistoryBusy||!globalHistoryState)return;
  const context=globalHistoryState.context,request=++globalHistoryPreviewRequest,scope={context,library,archive};
  const row=globalHistoryState.history.find(row=>row.id===id),selected=row?Object.entries(row.files).filter(([,item])=>item.valid).map(([name])=>name):null;
  globalHistoryBusy=true;renderGlobalHistoryControls();
  try{
    if(!globalHistoryScopeCurrent(scope))throw new Error('连接或历史库已变化，请重新读取后预览。');
    const result=await post('/api/global-history',{action:'restore-preview',...globalHistorySource(scope),id,...selected?{selected}:{}});
    if(request!==globalHistoryPreviewRequest||!globalHistoryScopeCurrent(scope))return;
    globalHistoryPreview={...result,archive:archive||null,selected:selected||result.files.filter(row=>row.valid).map(row=>row.name)};
    $('#global-history-target').textContent=`恢复目标：${result.target_root}\n${result.message}`;
    $('#global-history-choices').innerHTML=result.files.map(row=>`<label class="check"><input type="checkbox" data-global-restore-name="${escapeHTML(row.name)}" data-invalid="${!row.valid}" ${row.valid?'':'disabled'}>恢复${escapeHTML(globalFileNames[row.name])} · ${escapeHTML(globalSummary(row.name,row.source))} · ${row.target_exists?'当前文件存在，先保留原件':'目标尚无此文件'}${row.same_bytes?' · 与当前字节相同':''}${row.error?' · '+escapeHTML(row.error):''}</label>`).join('');
    $('#global-history-version').checked=false;$('#global-history-confirm').checked=false;
    for(const input of $$('[data-global-restore-name]'))input.addEventListener('change',renderGlobalHistoryControls);
    inlineError($('#global-history-restore-error'),'');if(!$('#global-history-dialog').open)$('#global-history-dialog').showModal();
  }catch(error){if(request===globalHistoryPreviewRequest){inlineError($('#global-history-error'),error.message);if($('#global-history-dialog').open)inlineError($('#global-history-restore-error'),error.message);}}
  finally{globalHistoryBusy=false;renderGlobalHistoryControls();}
}
$('#global-history-reload').addEventListener('click',()=>loadGlobalHistory(true));
function globalHistoryScopeChanged(){globalHistoryLimit=20;globalHistoryPreviewRequest++;globalHistoryMaintenanceRequest++;globalHistoryOperation++;globalHistoryRequest++;globalHistoryLoadedAt=0;invalidateGlobalHistoryDialogs();renderGlobalHistoryControls();loadGlobalHistory(true);}
$('#global-history-library').addEventListener('change',()=>{$('#global-history-archive').value='';globalHistoryScopeChanged();});
$('#global-history-archive').addEventListener('change',globalHistoryScopeChanged);
$('#global-history-more').addEventListener('click',()=>{globalHistoryLimit+=20;renderGlobalHistory();});
function globalHistoryFilterChanged(){globalHistoryLimit=20;renderGlobalHistory();}
$('#global-history-search').addEventListener('input',globalHistoryFilterChanged);
for(const id of ['global-history-file-filter','global-history-health-filter'])$('#'+id).addEventListener('change',globalHistoryFilterChanged);
$('#global-history-filter-reset').addEventListener('click',()=>{$('#global-history-search').value='';$('#global-history-file-filter').value='all';$('#global-history-health-filter').value='all';globalHistoryFilterChanged();});
$('#global-history-version').addEventListener('change',renderGlobalHistoryControls);
$('#global-history-confirm').addEventListener('change',renderGlobalHistoryControls);
$('#global-history-close').addEventListener('click',()=>{if(!globalHistoryRestoring){globalHistoryPreview=null;globalHistoryPreviewRequest++;$('#global-history-dialog').close();}});
$('#global-history-dialog').addEventListener('cancel',event=>{if(globalHistoryRestoring)event.preventDefault();else{globalHistoryPreview=null;globalHistoryPreviewRequest++;}});
$('#global-history-repreview').addEventListener('click',()=>{if(globalHistoryPreview)previewGlobalHistory(globalHistoryPreview.id,globalHistoryPreview.library,globalHistoryPreview.archive);});
$('#global-history-recovery').addEventListener('click',()=>{if(!globalHistoryRestoring){globalHistoryPreview=null;globalHistoryPreviewRequest++;$('#global-history-dialog').close();navigate('migration');}});
$('#global-history-restore-form').addEventListener('submit',async event=>{
  event.preventDefault();renderGlobalHistoryControls();if($('#global-history-restore').disabled)return;
  const preview=globalHistoryPreview,operation=++globalHistoryOperation,choices=Object.fromEntries($$('[data-global-restore-name]').filter(input=>preview.selected.includes(input.dataset.globalRestoreName)).map(input=>[input.dataset.globalRestoreName,input.checked&&!input.disabled?'replace':'keep']));
  globalHistoryBusy=globalHistoryRestoring=true;renderGlobalHistoryControls();
  try{
    const result=await post('/api/global-history',{action:'restore',...globalHistorySource(preview),id:preview.id,expected:preview.expected,
      choices,selected:preview.selected,version:'4.0.2',version_confirmed:$('#global-history-version').checked,confirmed:$('#global-history-confirm').checked});
    if(operation!==globalHistoryOperation||!globalHistoryScopeCurrent(preview))throw new Error('连接或历史库已变化，本次回执属于原目标；请重新读取该目标核对结果。');
    $('#global-history-result').textContent=result.message+' 原件保留于：'+result.retained_directory;
    globalHistoryPreview=null;$('#global-history-dialog').close();globalHistoryLoadedAt=0;await poll();
  }catch(error){inlineError($('#global-history-restore-error'),error.message);$('#global-history-confirm').checked=false;}
  finally{globalHistoryBusy=globalHistoryRestoring=false;renderGlobalHistoryControls();}
  if(!globalHistoryPreview)await loadGlobalHistory(true);
});
