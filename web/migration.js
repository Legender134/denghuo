'use strict';
let migrationState=null,migrationExportPreview=null,migrationImportPreview=null,migrationFile=null;
let migrationExportSelection=new Set(),migrationImportSelection=new Set(),migrationDirty=false,migrationGeneration=0,migrationBusy=false,migrationLoaded=false;
let migrationRestoredFile='',migrationImportTouched=false,migrationLastResult=null,migrationExportDirty=false,migrationImportDirty=false;
const migrationReceipts=[],migrationReceiptFiles=new Map();let migrationReceiptSequence=0,migrationRuntimeStatus=null;
const migrationGroups={backup:'游戏进度备份',plan:'命名方案',favorite:'收藏资料',draft:'已保存未完成草稿',preference:'可携偏好'};
function migrationDraftLabel(){return migrationDirty;}
function migrationDraftNotice(){$('#migration-draft-status').textContent=migrationDirty?'选择已修改；切换页面、网络错误和重新连接后保留。结束会话可明确保存选择草稿；ZIP须重新选择。':'本次提交已完成；原包仍保留。继续操作前重新预览，磁盘保存和本会话实际状态见结果。';}
function captureMigrationDraft(){
  if(!migrationDirty)return null;
  return {format:1,export_selected:[...migrationExportSelection],import_selected:[...migrationImportSelection],file_name:migrationFile?.name||migrationRestoredFile,needs_reselect:true,export_dirty:migrationExportDirty,import_dirty:migrationImportDirty};
}
async function restoreMigrationDraft(raw){
  if(raw?.format!==1||!Array.isArray(raw.export_selected)||!Array.isArray(raw.import_selected)||typeof raw.file_name!=='string'||raw.file_name.length>300||[...raw.export_selected,...raw.import_selected].some(v=>typeof v!=='string'||v.length>400)||raw.export_selected.length+raw.import_selected.length>600)throw new Error('搬机迁移草稿格式不正确');
  migrationExportSelection=new Set(raw.export_selected);migrationImportSelection=new Set(raw.import_selected);migrationImportTouched=true;migrationRestoredFile=raw.file_name;migrationFile=null;migrationExportPreview=migrationImportPreview=null;migrationExportDirty=raw.export_dirty!==false;migrationImportDirty=raw.import_dirty!==false;migrationDirty=migrationExportDirty||migrationImportDirty;migrationGeneration++;
  navigate('migration');await loadMigration();$('#migration-import-info').textContent=`已找回选择草稿。${raw.file_name?'请重新选择原迁移包「'+raw.file_name+'」':'请重新选择迁移包'}，再预览本机目标。草稿不包含大文件字节，也不能沿用旧确认。`;
}
function migrationEdited(type){if(type==='export')migrationExportDirty=true;else migrationImportDirty=true;migrationDirty=migrationExportDirty||migrationImportDirty;migrationGeneration++;if(type==='export'){migrationExportPreview=null;$('#migration-export-download').disabled=true;}$('#migration-confirm').checked=false;migrationDraftNotice();}
function migrationError(error){inlineError($('#migration-error'),error?.message||String(error));$('#migration-error').tabIndex=-1;$('#migration-error').focus();}
function migrationRows(target,rows,selection,interactive){
  target.replaceChildren();
  for(const [group,label] of Object.entries(migrationGroups)){
    const own=rows.filter(row=>row.group===group);if(!own.length)continue;
    const section=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent=label;section.append(legend);
    for(const row of own){
      const article=document.createElement('article');article.className='support-step';
      const line=document.createElement('label');line.className='check';const input=document.createElement('input');input.type='checkbox';input.dataset.migrationChoice=interactive;input.dataset.key=row.key;input.checked=selection.has(row.key);input.disabled=!row.valid;line.append(input,document.createTextNode(row.label));article.append(line);
      const detail=document.createElement('p');detail.textContent=row.detail+(row.error?' · '+row.error:'');article.append(detail);
      if(row.target){const path=document.createElement('p');path.className='muted';path.textContent='本机目标：'+row.target;article.append(path);}
      if(row.content||row.summary){const more=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent='预览具体内容与来源';pre.textContent=JSON.stringify(row.content||row.summary,null,2);more.append(summary,pre);article.append(more);}
      section.append(article);
    }target.append(section);
  }
  if(!rows.length)target.textContent='当前没有可迁移项目。';
}
async function loadMigration(){
  const generation=migrationGeneration;
  try{const response=await fetch('/api/migration');const result=await response.json();if(!response.ok)throw new Error(result.error||'迁移清单暂不可读');migrationState=result;
    // A response may update evidence, but cannot replace edits made while it was pending.
    if(!migrationLoaded&&!migrationDirty&&generation===migrationGeneration)migrationExportSelection=new Set(result.rows.filter(row=>row.valid&&row.group!=='backup').map(row=>row.key));
    migrationLoaded=true;migrationRows($('#migration-export-list'),result.rows,migrationExportSelection,'export');
    $('#migration-local-target').textContent=`本机游戏存档连接：${result.save_root}。助手档案：${result.backup_target}。${result.note}`;
    $('#migration-source-version').textContent=`本机灯火 ${result.application_version} · 规则资料 ${result.rules_version}`;
    inlineError($('#migration-error'),[result.knowledge_error,result.preferences_error].filter(Boolean).join(' '));
  }catch(error){migrationError(error);}
}
function migrationSetBusy(busy){migrationBusy=busy;for(const id of ['migration-reload','migration-export-preview','migration-export-download','migration-preview','migration-import'])$('#'+id).disabled=busy||(id==='migration-export-download'&&!migrationExportPreview);$('#migration-pending').textContent=busy?'正在读取或保存；选择仍可编辑，提交时的结果会单独显示。':'';}
async function migrationUpload(action,file,payload={}){
  if(!file)throw new Error('请重新选择原迁移 ZIP，再预览；选择草稿仍保留');
  if(!token)throw new Error('助手还未连接，原选择仍保留');
  if(file.size>64*1024*1024)throw new Error('迁移包需要小于64 MiB');
  const response=await fetch('/api/migration/'+action,{method:'POST',headers:{'Content-Type':'application/zip','X-Companion-Token':token,'X-Companion-Migration-Digest':payload.expected||'','X-Companion-Migration-Selection':JSON.stringify(payload.selected||[]),'X-Companion-Migration-Confirmed':String(payload.confirmed===true)},body:file});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'迁移操作未完成');return result;
}
function renderMigrationImport(result){
  migrationRows($('#migration-import-list'),result.rows,migrationImportSelection,'import');
  $('#migration-import-info').textContent=`来源灯火 ${result.source.application_version} · 规则 ${result.source.rules_version} → 本机 ${result.current_application_version} / ${result.current_rules_version}。${result.version_difference?'版本不同：旧方案按来源保存，重开前核对本版可用条件。':'版本一致。'} ${result.note} 本机游戏存档：${result.save_root}${result.config_error?' · '+result.config_error:''}`;
  $('#migration-import-panel').hidden=false;
}
function freezeMigrationReceipt(value){if(value&&typeof value==='object'){for(const child of Object.values(value))freezeMigrationReceipt(child);Object.freeze(value);}return value;}
function recordMigrationReceipt(result,submission,file){
  const labelled={...result,results:result.results.map(row=>({...row,label:row.label||submission.rows.find(item=>item.key===row.key)?.label||migrationGroups[row.key.split(':',1)[0]]||'所选项目'}))};
  const receipt=freezeMigrationReceipt(JSON.parse(JSON.stringify({id:++migrationReceiptSequence,finished:new Date().toISOString(),submission,result:labelled})));
  migrationReceipts.push(receipt);migrationReceiptFiles.set(receipt.id,file);migrationLastResult=receipt.result;migrationRuntimeStatus=null;renderMigrationResults();return receipt;
}
function renderMigrationResults(){
  const target=$('#migration-results'),retryPanels=new Map(migrationReceipts.map(receipt=>[receipt.id,$('#migration-retry-'+receipt.id)]).filter(([,panel])=>panel));target.replaceChildren();
  for(const receipt of [...migrationReceipts].reverse()){
    const result=receipt.result,details=document.createElement('details'),title=document.createElement('summary');details.open=receipt===migrationReceipts.at(-1);title.textContent=`已提交迁移 ${receipt.id} · ${receipt.finished}`;details.append(title);
    const summary=document.createElement('p');summary.textContent=`提交文件：${receipt.submission.file_name} · 本机目标：${receipt.submission.root}。磁盘成功 ${result.success_count} 项，失败 ${result.failure_count} 项。未恢复游戏存档。${result.note}`;details.append(summary);
    for(const row of result.results){const p=document.createElement('p');p.textContent=`${row.ok?'已保存':'未完成'} · ${row.label}：${row.error||row.message}`;details.append(p);}
    if(result.failure_count){const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='仅重新预览这次失败项目（保留当前选择）';button.addEventListener('click',()=>retryMigrationReceipt(receipt));details.append(button);}
    const retry=retryPanels.get(receipt.id)||document.createElement('div');retry.id='migration-retry-'+receipt.id;details.append(retry);target.append(details);
  }
  const result=migrationLastResult,runtime=migrationRuntimeStatus||result?.preferences_runtime,caps=runtime?.desktop_status||{};
  if(runtime&&result?.results.some(row=>row.key.startsWith('preference:')&&row.ok)){
    const p=document.createElement('p');const applied=runtime.desktop_available&&caps.applied_revision===runtime.revision;p.textContent='本会话应用状态：'+(applied?'桌面窗口已确认应用当前偏好。':runtime.desktop_available?'等待桌面窗口确认应用。':'没有可用的原生游玩窗口，已保存供后续使用。');target.append(p);
    for(const [key,chord] of Object.entries(runtime.settings.bindings||{})){const unavailable=(caps.hotkeys_unavailable||[]).some(item=>typeof item==='string'?[key,chord].includes(item):[item.action,item.name,item.key].includes(key));const p=document.createElement('p');p.textContent=`${typeof bindingLabels==='object'?bindingLabels[key]||key:key}：${!chord?'已禁用':unavailable?'注册失败或被占用':applied&&caps.hotkeys_ready===true&&caps.bindings?.[key]===chord?'已确认注册 '+chord:'已配置 '+chord+'；本会话注册未确认'}`;target.append(p);}
  }
  target.tabIndex=-1;target.focus();
}
async function retryMigrationReceipt(receipt){
  if(migrationBusy)return;const file=migrationReceiptFiles.get(receipt.id),failed=receipt.result.results.filter(row=>!row.ok).map(row=>row.key),target=$('#migration-retry-'+receipt.id);migrationSetBusy(true);
  try{
    const preview=await migrationUpload('preview',file);if(preview.save_root!==receipt.submission.root)throw new Error('这次回执属于其他存档目录，请返回原目录重新核对；当前选择保持。');
    const rows=preview.rows.filter(row=>failed.includes(row.key)),selected=rows.filter(row=>row.valid).map(row=>row.key);target.replaceChildren();
    const info=document.createElement('p');info.textContent=`这次失败 ${failed.length} 项，目前可重试 ${selected.length} 项。只处理下面这些项目；当前文件与选择保持。`;target.append(info);
    for(const row of rows){const p=document.createElement('p');p.textContent=row.label+'：'+(row.error||row.detail);target.append(p);}
    if(!selected.length)return;
    const label=document.createElement('label'),confirm=document.createElement('input');confirm.type='checkbox';label.append(confirm,document.createTextNode('我已核对这些失败项目和本机目标，确认仅重试此清单。'));target.append(label);
    const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='确认重试这次失败项目';button.disabled=true;confirm.addEventListener('change',()=>button.disabled=!confirm.checked);target.append(button);
    button.addEventListener('click',async()=>{if(migrationBusy||!confirm.checked)return;migrationSetBusy(true);button.disabled=true;try{const result=await migrationUpload('import',file,{selected,expected:preview.expected,confirmed:true});recordMigrationReceipt(result,{file_name:file.name,root:preview.save_root,selected,rows,retry_of:receipt.id},file);await loadMigration();}catch(error){confirm.checked=false;migrationError(error);}finally{migrationSetBusy(false);}});
  }catch(error){migrationError(error);}finally{migrationSetBusy(false);}
}
$('#migration-reload').addEventListener('click',loadMigration);
$('#migration-rebind').addEventListener('click',()=>navigate('settings'));
$('#view-migration').addEventListener('change',event=>{const input=event.target;if(input.dataset.migrationChoice){const type=input.dataset.migrationChoice,selection=type==='export'?migrationExportSelection:migrationImportSelection;if(type==='export'&&input.checked&&input.dataset.key.startsWith('backup:')&&[...selection].filter(key=>key.startsWith('backup:')).length>=30){input.checked=false;migrationError(new Error('每包最多30份进度，请分批选择；现有选择保留'));return;}input.checked?selection.add(input.dataset.key):selection.delete(input.dataset.key);if(type==='import')migrationImportTouched=true;migrationEdited(type);}});
for(const [id,type,all] of [['migration-export-all','export',true],['migration-export-none','export',false],['migration-import-all','import',true],['migration-import-none','import',false]])$('#'+id).addEventListener('click',()=>{
  const rows=type==='export'?migrationState?.rows:migrationImportPreview?.rows;if(!rows)return;if(type==='export'&&all&&rows.filter(row=>row.valid&&row.group==='backup').length>30){migrationError(new Error('可用进度超过每包30份上限，请分批选择；原选择保留'));return;}const selection=new Set(all?rows.filter(row=>row.valid).map(row=>row.key):[]);if(type==='export')migrationExportSelection=selection;else{migrationImportSelection=selection;migrationImportTouched=true;}migrationEdited(type);migrationRows($('#migration-'+type+'-list'),rows,selection,type);
});
$('#migration-export-preview').addEventListener('click',async()=>{if(migrationBusy)return;const selected=[...migrationExportSelection],generation=migrationGeneration;migrationSetBusy(true);try{const result=await post('/api/migration/export-preview',{selected});if(generation!==migrationGeneration){$('#migration-export-info').textContent='预览期间选择已修改，新草稿仍保留，请重新预览。';return;}migrationExportPreview={...result,selected};$('#migration-export-info').textContent=`将完整导出 ${result.count} 项 · ${result.bytes} 字节。${result.note}`;inlineError($('#migration-error'),'');}catch(error){migrationError(error);}finally{migrationSetBusy(false);}});
$('#migration-export-download').addEventListener('click',async()=>{if(migrationBusy||!migrationExportPreview)return;const submitted=migrationExportPreview,generation=migrationGeneration;migrationSetBusy(true);try{const response=await fetch('/api/migration/export',{method:'POST',headers:{'Content-Type':'application/json','X-Companion-Token':token},body:JSON.stringify({selected:submitted.selected,expected:submitted.expected})});if(!response.ok){const r=await response.json();throw new Error(r.error||'导出失败');}const raw=await response.blob(),url=URL.createObjectURL(raw),link=document.createElement('a');link.href=url;link.download='denghuo-portable-bundle.zip';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$('#migration-export-info').textContent='已生成并交给浏览器下载；请核对下载文件。原备份和资料保持。'+(generation!==migrationGeneration?'操作期间的新选择仍保留。':'');if(generation===migrationGeneration){migrationExportDirty=false;migrationDirty=migrationImportDirty;}migrationDraftNotice();inlineError($('#migration-error'),'');}catch(error){migrationError(error);}finally{migrationSetBusy(false);}});
$('#migration-file').addEventListener('change',()=>{migrationFile=$('#migration-file').files[0]||null;migrationRestoredFile=migrationFile?.name||'';migrationImportPreview=null;migrationEdited('import');$('#migration-import-panel').hidden=true;$('#migration-import-info').textContent=migrationFile?'已选择「'+migrationFile.name+'」。点击预览，不会立即导入。':'未选择文件；之前的选择草稿仍保留。';});
$('#migration-preview').addEventListener('click',async()=>{if(migrationBusy)return;const file=migrationFile,generation=migrationGeneration;migrationSetBusy(true);try{const result=await migrationUpload('preview',file);if(generation!==migrationGeneration||file!==migrationFile){$('#migration-import-info').textContent='读取期间选择已修改；草稿保留，请重新预览原包。';return;}migrationImportPreview=result;if(!migrationImportTouched)migrationImportSelection=new Set(result.rows.filter(row=>row.valid).map(row=>row.key));renderMigrationImport(result);inlineError($('#migration-error'),'');}catch(error){migrationError(error);}finally{migrationSetBusy(false);}});
$('#migration-import').addEventListener('click',async()=>{if(migrationBusy)return;if(!migrationImportPreview||!$('#migration-confirm').checked){migrationError(new Error('请先真实预览内容与本机目标，并勾选确认；尚未导入'));return;}const file=migrationFile,selected=[...migrationImportSelection],generation=migrationGeneration,submitted=migrationImportPreview,expected=submitted.expected;migrationSetBusy(true);try{const result=await migrationUpload('import',file,{selected,expected,confirmed:true});recordMigrationReceipt(result,{file_name:file.name,root:submitted.save_root,selected,rows:submitted.rows},file);if(generation===migrationGeneration){if(result.failure_count===0){migrationImportDirty=false;migrationDirty=migrationExportDirty;}$('#migration-confirm').checked=false;migrationImportPreview=null;$('#migration-import-panel').hidden=true;$('#migration-import-info').textContent='本次提交已处理，逐项结果见下方。选择草稿仍保留；继续导入或重试前请重新预览当前本机资料。';}migrationDraftNotice();inlineError($('#migration-error'),'');await loadMigration();}catch(error){$('#migration-confirm').checked=false;migrationError(error);}finally{migrationSetBusy(false);}});
$('#migration-cancel').addEventListener('click',()=>{migrationGeneration++;migrationExportPreview=migrationImportPreview=null;$('#migration-confirm').checked=false;$('#migration-import-panel').hidden=true;$('#migration-import-info').textContent=migrationBusy?'已取消后续确认。已提交的写入不能撤销，请等候逐项结果；原选择草稿保留。':'已取消预览和确认；没有导入，选择草稿与原包保留。';$('#migration-preview').focus();});
$('#migration-runtime-refresh').addEventListener('click',async()=>{if(!migrationLastResult)return;try{const response=await fetch('/api/play-settings'),result=await response.json();if(!response.ok)throw new Error(result.error||'实际应用状态暂不可读');migrationRuntimeStatus=result;renderMigrationResults();}catch(error){migrationError(error);}});
if(view==='migration')loadMigration();
