'use strict';
// Every preview belongs to a connection and a specific user draft.
const backupFlow={context:null,epoch:0,selection:new Map(),exportRevision:0,exportDraft:null,
  policyRevision:0,retentionDraft:null,importRevision:0,importDraft:null,importFile:null,
  importSelection:new Set(),importSelectionRevision:0,importResults:[],storageRequest:0,storageKey:'',storageSeen:false,storageDirty:true,historyKey:'',busy:new Set()};
Object.assign(backupFlow,{reclaimSelection:new Map(),reclaimRevision:0,reclaimDraft:null,stageRevision:0,stageDraft:null,receipts:[],receiptFiles:new Map(),operationSequence:0,lastImportReceipt:null});
const flowSize=bytes=>`${Number(bytes||0).toLocaleString('zh-CN')} 字节（${(Number(bytes||0)/1048576).toFixed(2)} MiB）`;
const flowKey=row=>`${row.slot}:${row.id}`;
const flowRowName=row=>`${row.label||'未命名进度'} · 槽位 ${row.slot??'未知'}`;
function ensureBackupWorkflows(){
  if($('#backup-workflows'))return;
  const section=document.createElement('section');section.id='backup-workflows';section.className='workspace-section';
  section.setAttribute('aria-label','备份空间与迁移');
  section.innerHTML=`<details id="backup-flow-storage-panel" class="panel retained-panel"><summary>备份空间 · 保留与手动整理</summary>
    <p class="muted">默认保留全部。活动历史、移出副本、损坏隔离与回档前目录均不会自动删除。移出仅调整活动额度；外部归档核验后可自愿回收明确选择的原件。</p>
    <p class="muted">导出保留副本只把原件存档到 ZIP，便于自行保管和排查；这类原件包不能直接导入或恢复为游戏进度。</p>
    <button id="backup-flow-storage-refresh" class="secondary" type="button">重新读取空间清单</button>
    <p id="backup-flow-storage-status" class="muted" role="status"></p><p id="backup-flow-storage-error" class="rule-warning" role="alert" hidden></p>
    <div id="backup-flow-storage"></div>
    <section id="backup-stage-review" hidden aria-label="检查中断回档暂存"><h3>中断暂存检查与重试</h3><p id="backup-stage-status" role="status"></p><div id="backup-stage-content"></div></section>
    <form id="backup-retention-form"><fieldset><legend>手动选择整理条件 · 留空保留全部</legend><div class="form-grid">
      <label>每槽位至少保留最新几份<input id="backup-keep-per-slot" type="number" min="1" max="5000" step="1" placeholder="全部保留"></label>
      <label>仅整理最近观察超过几天的记录<input id="backup-older-than-days" type="number" min="1" max="36500" step="1" placeholder="不限观察年龄"></label>
      <label>当前目录活动 ZIP 目标（MiB）<input id="backup-target-mib" type="number" min="1" max="512" step="1" placeholder="不设目标"></label>
    </div><p class="muted">组合条件同时生效，按最近观察时间从旧到新选择。固定、每槽位最新记录和当前撤回关联记录始终保留；条件留空时不产生候选。</p>
    <button class="secondary" id="backup-retention-preview" type="submit">预览整理清单</button></fieldset></form>
    <p id="backup-retention-error" class="rule-warning" role="alert" hidden></p><div id="backup-retention-review" hidden>
      <p id="backup-retention-summary" role="status"></p><div id="backup-retention-rows"></div>
      <div class="checks"><label><input id="backup-retention-confirm" type="checkbox">我已核对全部候选，仅将这些记录移入可恢复的保留目录，不删除副本。</label></div>
      <button id="backup-retention-archive" class="secondary" type="button" disabled>确认移入保留目录</button>
    </div><p id="backup-retention-result" role="status"></p><div id="backup-retention-results"></div>
  </details>
  <details id="backup-reclaim-panel" class="panel retained-panel"><summary>可选收尾 · 外部归档后回收原件空间</summary>
    <p class="muted">默认保留全部。先在上方空间清单选择可回收的移出、隔离或旧回档前副本，再预览完整原件。固定、每槽位最新、当前撤回关联目标和目录受保护；归属不完整的对象保持原件。外部原件 ZIP 不能直接导入或恢复，损坏原件存档不代表可恢复。</p>
    <p id="backup-reclaim-selection" role="status">尚未选择原件。</p>
    <label>外部 ZIP 完整绝对路径<input id="backup-reclaim-path" type="text" autocomplete="off" placeholder="例如 E:&#92;归档&#92;灯火原件.zip"></label>
    <p class="muted">填写已有外部目录中的新 ZIP 文件名；应用不会覆盖已有文件。路径不能位于助手数据或游戏存档目录。由本机应用写入、重新读取并逐文件核验真实位置；浏览器下载位置不能作为核验证据。</p>
    <button id="backup-reclaim-preview" class="secondary" type="button">预览确切回收目标</button>
    <p id="backup-reclaim-error" class="rule-warning" role="alert" hidden></p>
    <div id="backup-reclaim-review" hidden><p id="backup-reclaim-summary" role="status"></p><div id="backup-reclaim-rows"></div>
      <button id="backup-reclaim-export" class="secondary" type="button">写入外部 ZIP 并核验原件</button>
      <p id="backup-reclaim-verified" class="rule-path" role="status"></p>
      <div id="backup-reclaim-confirmation" hidden><label>按提示输入确认短语<input id="backup-reclaim-phrase" type="text" autocomplete="off"></label>
        <label class="check-inline"><input id="backup-reclaim-confirm" type="checkbox">我已核对这些确切名称、完整路径和数量，确认外部原件已核验，回收所选原件内容空间。</label>
        <button id="backup-reclaim-execute" class="secondary" type="button" disabled>明确确认并回收所选原件</button>
      </div>
    </div><p id="backup-reclaim-result" class="rule-path" role="status"></p><div id="backup-reclaim-results"></div>
  </details>
  <details class="panel retained-panel"><summary>跨槽位迁移 · 选择多份完整历史</summary>
    <p class="muted">这里列出当前目录的全部历史，不受上方槽位、搜索或显示数量影响。一次最多 32 份、迁移包最多 64 MiB；超限会提示，不会省略记录。</p>
    <p id="backup-batch-selection-status" class="muted" role="status"></p>
    <div class="backup-actions"><button id="backup-batch-select-all" class="secondary" type="button">选择全部历史</button><button id="backup-batch-clear" class="quiet" type="button">清空选择</button><button id="backup-batch-export-preview" class="secondary" type="button">预览所选导出</button></div>
    <div id="backup-batch-history"></div><p id="backup-batch-export-error" class="rule-warning" role="alert" hidden></p>
    <div id="backup-batch-export-review" hidden><h3>将导出的确切清单</h3><p id="backup-batch-export-summary" role="status"></p><div id="backup-batch-export-rows"></div><button id="backup-batch-export" class="primary" type="button">导出这份索引 ZIP</button></div>
    <fieldset><legend>导入索引迁移包 · 先预览，再确认所选记录</legend>
      <label>选择批量迁移 ZIP<input id="backup-batch-import-file" type="file" accept=".zip,application/zip"></label>
      <button id="backup-batch-import-preview" class="secondary" type="button">预览迁移包</button>
      <p id="backup-batch-import-error" class="rule-warning" role="alert" hidden></p>
      <div id="backup-batch-import-review" hidden><p id="backup-batch-import-summary" role="status"></p><div id="backup-batch-import-rows"></div>
        <div class="backup-actions"><button id="backup-batch-import-select-valid" class="secondary" type="button">选择全部可用记录</button><button id="backup-batch-import-clear" class="quiet" type="button">清空导入选择</button></div>
        <p id="backup-batch-import-selection" role="status" class="muted"></p><div class="checks"><label><input id="backup-batch-import-confirm" type="checkbox">我确认仅登记所选记录到备份历史，不恢复或覆盖游戏存档。</label></div>
        <button id="backup-batch-import" class="primary" type="button" disabled>确认导入所选记录</button>
      </div><p id="backup-batch-import-result" role="status"></p><div id="backup-batch-import-results"></div><button id="backup-batch-import-retry" class="secondary" type="button" hidden>重新预览失败记录</button>
    </fieldset>
  </details>`;
  $('#view-backups').append(section);
  const receipts=document.createElement('section');receipts.id='backup-operation-receipts';receipts.className='panel retained-panel';receipts.setAttribute('aria-label','已提交操作回执');section.prepend(receipts);renderBackupReceipts();
  setupBackupReclaim();
  $('#backup-flow-storage-panel').addEventListener('toggle',()=>{if($('#backup-flow-storage-panel').open)loadBackupFlowStorage();});
  $('#backup-flow-storage-refresh').addEventListener('click',()=>loadBackupFlowStorage());
  $('#backup-retention-form').addEventListener('submit',event=>{event.preventDefault();previewBackupRetention();});
  for(const id of ['backup-keep-per-slot','backup-older-than-days','backup-target-mib'])$('#'+id).addEventListener('input',()=>{
    backupFlow.policyRevision++;backupFlow.retentionDraft=null;$('#backup-retention-review').hidden=true;$('#backup-retention-confirm').checked=false;
  });
  $('#backup-retention-confirm').addEventListener('change',()=>$('#backup-retention-archive').disabled=!$('#backup-retention-confirm').checked||!backupFlow.retentionDraft);
  $('#backup-retention-archive').addEventListener('click',()=>archiveBackupRetention());
  $('#backup-batch-history').addEventListener('change',event=>{const input=event.target;if(!input.matches('[data-flow-select]'))return;
    const row=backupState?.history.find(row=>flowKey(row)===input.dataset.flowSelect);if(!row)return;
    if(input.checked)backupFlow.selection.set(flowKey(row),{slot:row.slot,id:row.id});else backupFlow.selection.delete(flowKey(row));
    invalidateBackupExport();updateBackupExportSelection();
  });
  $('#backup-batch-select-all').addEventListener('click',()=>{
    const rows=backupState?.history||[];
    if(rows.length>32){inlineError($('#backup-batch-export-error'),`全部历史有 ${rows.length} 份，超过每批 32 份。请逐份选择；没有省略任何记录。`);return;}
    for(const row of rows)backupFlow.selection.set(flowKey(row),{slot:row.slot,id:row.id});invalidateBackupExport();updateBackupExportSelection();
  });
  $('#backup-batch-clear').addEventListener('click',()=>{backupFlow.selection.clear();invalidateBackupExport();updateBackupExportSelection();});
  $('#backup-batch-export-preview').addEventListener('click',()=>previewBackupBatchExport());
  $('#backup-batch-export').addEventListener('click',()=>exportBackupBatch());
  $('#backup-batch-import-file').addEventListener('change',()=>{
    backupFlow.importFile=$('#backup-batch-import-file').files[0]||null;resetBackupImportDraft();
    backupFlow.importResults=[];$('#backup-batch-import-result').textContent='';$('#backup-batch-import-results').replaceChildren();$('#backup-batch-import-retry').hidden=true;
  });
  $('#backup-batch-import-preview').addEventListener('click',()=>previewBackupBatchImport());
  $('#backup-batch-import-rows').addEventListener('change',event=>{const input=event.target;if(!input.matches('[data-flow-import]'))return;
    if(input.checked)backupFlow.importSelection.add(input.dataset.flowImport);else backupFlow.importSelection.delete(input.dataset.flowImport);updateBackupImportSelection();
  });
  $('#backup-batch-import-select-valid').addEventListener('click',()=>{
    backupFlow.importSelection=new Set((backupFlow.importDraft?.rows||[]).filter(row=>row.valid).map(row=>row.file));updateBackupImportSelection();
  });
  $('#backup-batch-import-clear').addEventListener('click',()=>{backupFlow.importSelection.clear();updateBackupImportSelection();});
  $('#backup-batch-import-confirm').addEventListener('change',()=>$('#backup-batch-import').disabled=!$('#backup-batch-import-confirm').checked||!backupFlow.importSelection.size||!backupFlow.importDraft);
  $('#backup-batch-import').addEventListener('click',()=>importBackupBatch());
  $('#backup-batch-import-retry').addEventListener('click',()=>retryBackupImportReceipt(backupFlow.lastImportReceipt));
}
function resetBackupWorkflows(context){
  ensureBackupWorkflows();
  backupFlow.stageRevision++;backupFlow.stageDraft=null;$('#backup-stage-review').hidden=true;
  backupFlow.reclaimSelection.clear();invalidateBackupReclaim();$('#backup-reclaim-path').value='';$('#backup-reclaim-results').replaceChildren();$('#backup-reclaim-result').textContent='';backupFlow.context=context;backupFlow.epoch++;backupFlow.storageRequest++;
  backupFlow.selection.clear();backupFlow.storageKey='';backupFlow.storageSeen=false;backupFlow.storageDirty=true;backupFlow.historyKey='';invalidateBackupExport();
  backupFlow.policyRevision++;backupFlow.retentionDraft=null;backupFlow.importFile=null;resetBackupImportDraft();backupFlow.importResults=[];
  $('#backup-batch-import-file').value='';$('#backup-retention-confirm').checked=false;$('#backup-retention-review').hidden=true;
  for(const id of ['backup-keep-per-slot','backup-older-than-days','backup-target-mib'])$('#'+id).value='';
  for(const id of ['backup-flow-storage','backup-batch-history','backup-retention-rows','backup-retention-results','backup-batch-import-results'])$('#'+id).replaceChildren();
  for(const id of ['backup-retention-result','backup-batch-import-result'])$('#'+id).textContent='';
  for(const id of ['backup-flow-storage-error','backup-retention-error','backup-batch-export-error','backup-batch-import-error'])inlineError($('#'+id),'');
  $('#backup-flow-storage-status').textContent=context?'正在读取当前连接目录的空间清单…':'连接中断，空间清单尚未确认。';
  $('#backup-batch-import-retry').hidden=true;updateBackupExportSelection();
}
function backupFlowTicket(){return {context:backupFlow.context,epoch:backupFlow.epoch,root:backupState?.save_root||state?.settings?.save_root||''};}
function backupFlowCurrent(ticket){return !!ticket.context&&ticket.context===state?.backup_context&&ticket.context===backupFlow.context&&ticket.epoch===backupFlow.epoch;}
function freezeBackupReceipt(value){if(value&&typeof value==='object'){for(const child of Object.values(value))freezeBackupReceipt(child);Object.freeze(value);}return value;}
function recordBackupReceipt(kind,ticket,result,submitted,changed=false,file=null){
  const receipt=freezeBackupReceipt(JSON.parse(JSON.stringify({id:++backupFlow.operationSequence,kind,context:ticket.context,root:ticket.root,finished:new Date().toISOString(),submitted,result,changed})));
  backupFlow.receipts.push(receipt);if(file)backupFlow.receiptFiles.set(receipt.id,file);if(kind==='import')backupFlow.lastImportReceipt=receipt;renderBackupReceipts();return receipt;
}
function renderBackupReceipts(){
  const target=$('#backup-operation-receipts');if(!target)return;
  const retryPanels=new Map(backupFlow.receipts.map(receipt=>[receipt.id,$('#backup-receipt-retry-'+receipt.id)]).filter(([,panel])=>panel));
  target.replaceChildren();const title=document.createElement('h3');title.textContent='已提交操作回执';target.append(title);
  if(!backupFlow.receipts.length){const p=document.createElement('p');p.textContent='提交后的实际逐项结果会独立保留在这里；修改选择、取消后续确认和切换连接不会隐藏已发生的操作。';target.append(p);return;}
  const names={import:'批量导入','single-import':'单份备份导入',retention:'移入保留目录',reclaim:'回收原件',stage:'重新尝试回档',restore:'恢复存档',undo:'撤回上次回档',remove:'移出活动备份'};
  for(const receipt of [...backupFlow.receipts].reverse()){
    const details=document.createElement('details');details.className='rule-section';details.open=receipt===backupFlow.receipts.at(-1);const summary=document.createElement('summary');summary.textContent=`操作 ${receipt.id} · ${names[receipt.kind]||receipt.kind} · ${receipt.finished}`;details.append(summary);
    const result=receipt.result,rows=result.results||[],success=rows.filter(row=>row.ok).length,failed=rows.filter(row=>!row.ok).length;
    const info=document.createElement('p');info.className='rule-path';info.textContent=`提交目录：${receipt.root}。已完成 ${success} 项，未完成 ${failed} 项。${result.message||result.note||''}${receipt.changed?' 提交后选择、草稿或连接已变化；这些结果属于本次提交，新编辑保持，继续操作须重新预览。':''}`;details.append(info);
    const table=document.createElement('div');table.innerHTML=flowTable(rows,{result:true,successText:{import:'已导入，未回档',retention:'已移入保留目录',reclaim:'已回收；外部原件保持',stage:'已回档；原暂存保持',restore:'已恢复；回档前进度保持',undo:'已撤回；撤回前进度保持',remove:'已移入保留目录，未改游戏'}[receipt.kind]});details.append(table);
    if(failed&&receipt.kind==='import'){const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='仅重新预览本次失败记录（保留当前选择）';button.addEventListener('click',()=>retryBackupImportReceipt(receipt));details.append(button);}
    const retry=retryPanels.get(receipt.id)||document.createElement('div');retry.id='backup-receipt-retry-'+receipt.id;details.append(retry);target.append(details);
  }
}
async function refreshBackupReceiptScope(ticket){
  // An old operation must never install its history into a new connection's view.
  if(backupFlowCurrent(ticket)){backupFlow.storageDirty=true;await loadBackups();if($('#backup-flow-storage-panel').open)await loadBackupFlowStorage();}
}
async function retryBackupImportReceipt(receipt){
  if(!receipt||receipt.kind!=='import')return;
  const target=$('#backup-receipt-retry-'+receipt.id),file=backupFlow.receiptFiles.get(receipt.id),failed=receipt.result.results.filter(row=>!row.ok).map(row=>row.file);
  if(!target)return;
  target.textContent='正在重新检查本次失败项；当前文件和选择保持。';
  return backupFlowRun('import-retry','backup-batch-import-error',async ticket=>{
    if(ticket.root!==receipt.root)throw new Error('这份回执属于先前的连接目录；请返回该目录，重新读取后核对。');
    if(!file)throw new Error('本次原迁移包暂不可用，请重新选择原包；当前选择保持。');
    const preview=await backupFlowUpload('batch-preview',file,ticket);if(!backupFlowCurrent(ticket))return;
    const selected=preview.rows.filter(row=>row.valid&&failed.includes(row.file)).map(row=>row.file);
    target.replaceChildren();const info=document.createElement('p');info.textContent=`本次失败 ${failed.length} 份，目前可重试 ${selected.length} 份。只处理这些失败项；其他草稿保持。`;target.append(info);
    const table=document.createElement('div');table.innerHTML=flowTable(preview.rows.filter(row=>failed.includes(row.file)),{result:true});target.append(table);
    if(!selected.length)return;
    const label=document.createElement('label'),confirm=document.createElement('input');confirm.type='checkbox';label.append(confirm,document.createTextNode('我确认仅导入上列可用的本次失败记录，不恢复游戏存档。'));target.append(label);
    const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='确认重试本次失败记录';button.disabled=true;confirm.addEventListener('change',()=>button.disabled=!confirm.checked);target.append(button);
    button.addEventListener('click',()=>backupFlowRun('import-retry','backup-batch-import-error',async current=>{
      if(!confirm.checked||!backupFlowCurrent(ticket)||current.context!==ticket.context)throw new Error('连接或确认已变化，请重新预览本次失败项。');
      button.disabled=true;const result=await backupFlowUpload('batch-import',file,ticket,{'X-Companion-Transfer-Digest':preview.expected,'X-Companion-Transfer-Selection':JSON.stringify(selected),'X-Companion-Transfer-Confirmed':'true'});
      recordBackupReceipt('import',ticket,result,{retry_of:receipt.id,selected,file_name:file.name},true,file);await refreshBackupReceiptScope(ticket);
    }));
  });
}
function invalidateBackupExport(){backupFlow.exportRevision++;backupFlow.exportDraft=null;$('#backup-batch-export-review').hidden=true;}
function resetBackupImportDraft(){backupFlow.importRevision++;backupFlow.importDraft=null;backupFlow.importSelection.clear();$('#backup-batch-import-review').hidden=true;$('#backup-batch-import-confirm').checked=false;}
async function backupFlowRun(key,errorId,work){
  if(backupFlow.busy.has(key))return;const ticket=backupFlowTicket();if(!backupFlowCurrent(ticket)){inlineError($('#'+errorId),'请等待当前存档连接后再操作。');return;}
  backupFlow.busy.add(key);inlineError($('#'+errorId),'');
  try{await work(ticket);}catch(error){if(backupFlowCurrent(ticket))inlineError($('#'+errorId),error.message);}finally{backupFlow.busy.delete(key);}
}
function flowTable(rows,{select='',reason=false,result=false,successText='已导入'}={}){
  if(!rows.length)return '<p class="muted">没有记录。</p>';
  const progress=row=>row.summary?.empty?'空槽位（没有活动进度）':row.summary?`${row.summary.class||'未知角色'} · 等级 ${row.summary.level??'—'} · 第 ${row.summary.depth??'—'} 层 · 生命 ${row.summary.hp??'—'}/${row.summary.ht??'—'}`:row.class?`${row.class} · 等级 ${row.level??'—'} · 第 ${row.depth??'—'} 层`:row.valid===false?'摘要不可验证':'未提供进度摘要';
  const sourceTime=row=>`${row.summary?.empty?'空槽位，无游戏保存时间':(row.saved??row.summary?.saved)!=null?`游戏保存 ${fmtTime(row.saved??row.summary?.saved)}`:'源保存时间未提供'}${row.first_observed!=null?` · 源首次观察 ${fmtTime(row.first_observed)}`:''}${row.last_observed!=null?` · 源最近观察 ${fmtTime(row.last_observed)}`:''}${row.time!=null?` · 副本记录 ${fmtTime(row.time)}`:''}`;
  return `<div class="table-scroll"><table><thead><tr>${select?'<th scope="col">选择</th>':''}<th scope="col">名称 / 文件</th><th scope="col">槽位</th><th scope="col">游戏保存 / 副本时间</th><th scope="col">大小</th>${reason||result?'<th scope="col">原因 / 状态</th>':''}</tr></thead><tbody>${rows.map(row=>{
    const name=row.label||row.file||row.id||'未命名进度',key=select==='export'?flowKey(row):row.file;
    const selectable=select!=='import'||row.valid;
    return `<tr>${select?`<td><label class="check-inline"><input type="checkbox" data-flow-${select==='export'?'select':'import'}="${escapeHTML(key)}" aria-label="选择${escapeHTML(flowRowName(row))}" ${!selectable?'disabled':''}>选择</label></td>`:''}<td>${escapeHTML(name)}${row.id?`<br><small>${escapeHTML(row.id)}</small>`:''}${row.source_id?`<br><small>源编号 ${escapeHTML(row.source_id)}</small>`:''}${row.target_id?`<br><small>成功目标 ${escapeHTML(row.target_id)}</small>`:''}${row.path?`<p class="rule-path">${escapeHTML(row.path)}</p>`:''}<br><small>${escapeHTML(progress(row))}</small>${row.label&&row.file?`<br><small>${escapeHTML(row.file)}</small>`:''}</td><td>${escapeHTML(row.slot??'—')}</td><td>${escapeHTML(sourceTime(row))}</td><td>${row.bytes==null?'—':flowSize(row.bytes)}</td>${reason||result?`<td>${escapeHTML(result?(row.ok===true?successText:row.ok===false?row.error||'失败':row.valid?'可用，等待选择':row.error||'不可用'):row.reason||'完整保留')}${row.protected?'<br>受保护':''}${row.released_bytes!=null?`<br>本项实际释放原件内容 ${flowSize(row.released_bytes)}<br>已删文件：${escapeHTML((row.deleted_files||[]).join('、')||'无')}<br>已重建原件：${escapeHTML((row.restored_files||[]).join('、')||'无')}${row.rollback_errors?.length?`<br>原件重建未完成，请核对外部归档：${escapeHTML(row.rollback_errors.join('；'))}`:''}`:''}${row.undo_id?`<br>当前撤回 ${escapeHTML(row.undo_id)}`:''}</td>`:''}</tr>`;
  }).join('')}</tbody></table></div>`;
}
function renderBackupWorkflows(){
  ensureBackupWorkflows();if(!backupState||backupState.context!==state?.backup_context)return;
  if(backupFlow.context!==backupState.context)resetBackupWorkflows(backupState.context);
  const rows=backupState.history||[];
  const signature=JSON.stringify(rows.map(row=>[row.slot,row.id,row.label,row.saved,row.integrity?.valid]));
  if(signature!==backupFlow.historyKey){
    backupFlow.storageDirty=true;
    const focused=document.activeElement?.dataset.flowSelect;
    const present=new Set(rows.map(flowKey));let removed=false;
    for(const key of backupFlow.selection.keys())if(!present.has(key)){backupFlow.selection.delete(key);removed=true;}
    if(backupFlow.historyKey||removed)invalidateBackupExport();backupFlow.historyKey=signature;
    $('#backup-batch-history').innerHTML=flowTable(rows,{select:'export'});updateBackupExportSelection();
    if(focused)[...$('#backup-batch-history').querySelectorAll('input')].find(input=>input.dataset.flowSelect===focused)?.focus({preventScroll:true});
  }
  if(!backupFlow.storageSeen||($('#backup-flow-storage-panel').open&&backupFlow.storageDirty))loadBackupFlowStorage();
}
function updateBackupExportSelection(){
  for(const input of $('#backup-batch-history').querySelectorAll('[data-flow-select]'))input.checked=backupFlow.selection.has(input.dataset.flowSelect);
  const total=backupState?.history?.length??0,count=backupFlow.selection.size;
  $('#backup-batch-selection-status').textContent=`全部历史 ${total} 份 · 已选 ${count} 份${count>32?'，超过每批 32 份，请减少选择':''}。选择跨槽位保留。`;
}
async function loadBackupFlowStorage(){
  return backupFlowRun('storage','backup-flow-storage-error',async ticket=>{
    backupFlow.storageSeen=true;const historyKey=backupFlow.historyKey;
    const request=++backupFlow.storageRequest,response=await fetch('/api/backups/storage?'+new URLSearchParams({context:ticket.context}));
    const result=await response.json();if(!response.ok)throw new Error(result.error||'空间清单无法读取');
    if(!backupFlowCurrent(ticket)||request!==backupFlow.storageRequest||result.context!==ticket.context)return;
    backupFlow.storageDirty=historyKey!==backupFlow.historyKey;
    $('#backup-flow-storage-status').textContent=`总占用 ${flowSize(result.totals.total)} · 活动 ${flowSize(result.totals.active)} · 移出 ${flowSize(result.totals.retained)} · 隔离 ${flowSize(result.totals.quarantine)} · 本目录回档前 ${flowSize(result.totals.before_restore)} · 中断暂存 ${flowSize(result.totals.interrupted_stage)}。${result.scope_note||''}`;
    // Observation timestamps can change every poll; do not disturb focus for that alone.
    const signature=JSON.stringify(result.groups.map(group=>[group.kind,group.directory,group.rows.map(row=>[row.file,row.label,row.bytes,row.reason,row.protected,row.undo_id,row.reclaimable,row.reclaim_reason,row.verification,row.retryable,row.error])]));
    if(signature===backupFlow.storageKey)return;backupFlow.storageKey=signature;invalidateBackupReclaim();
    const focused=document.activeElement,focusKey=focused?.dataset.flowStorageAction,focusKind=focused?.dataset.kind,focusFile=focused?.dataset.file;
    const expanded=new Set([...$('#backup-flow-storage').querySelectorAll('details[open]')].map(details=>details.dataset.kind));
    $('#backup-flow-storage').innerHTML=result.groups.map(group=>`<details class="rule-section" data-kind="${escapeHTML(group.kind)}" ${expanded.has(group.kind)?'open':''}><summary>${escapeHTML(group.title)} · ${group.rows.length} 项 · ${flowSize(group.rows.reduce((n,row)=>n+row.bytes,0))}</summary><p class="rule-path">${escapeHTML(group.directory)}</p><button class="secondary" type="button" data-flow-storage-action="open" data-kind="${escapeHTML(group.kind)}">${['before','stage'].includes(group.kind)?'打开当前连接目录（所选子目录在其中）':'打开'+escapeHTML(group.title)+'目录'}</button>${flowTable(group.rows,{reason:true})}${group.kind==='stage'?group.rows.map(row=>`<div class="support-step"><p>${escapeHTML(row.file)} · ${escapeHTML(row.verification||'尚未检查')} ${escapeHTML(row.error||'')}</p><button class="secondary" type="button" data-stage-inspect="${escapeHTML(row.file)}">检查此暂存</button><button class="secondary" type="button" data-stage-preview="${escapeHTML(row.file)}" ${row.owned?'':'disabled'}>重新校验并预览重试</button></div>`).join(''):''}${group.kind!=='active'?group.rows.map(row=>`<label class="check-inline"><input type="checkbox" data-flow-reclaim="${escapeHTML(group.kind+':'+row.file)}" data-kind="${escapeHTML(group.kind)}" data-file="${escapeHTML(row.file)}" ${row.reclaimable?'':'disabled'} ${backupFlow.reclaimSelection.has(group.kind+':'+row.file)?'checked':''}>回收候选：${escapeHTML(row.label||row.file)} · ${escapeHTML(row.reclaim_reason||'保持原件')}</label>`).join(''):''}${group.kind!=='active'?group.rows.map(row=>`<div class="retained-row"><span>${escapeHTML(row.label||row.file)} · ${flowSize(row.bytes)}</span><button class="secondary" type="button" data-flow-storage-action="export" data-kind="${escapeHTML(group.kind)}" data-file="${escapeHTML(row.file)}">导出此保留副本</button></div>`).join(''):''}</details>`).join('');
    for(const button of $('#backup-flow-storage').querySelectorAll('[data-stage-inspect]'))button.addEventListener('click',()=>inspectBackupStage(button.dataset.stageInspect));
    for(const button of $('#backup-flow-storage').querySelectorAll('[data-stage-preview]'))button.addEventListener('click',()=>inspectBackupStage(button.dataset.stagePreview,true));
    for(const button of $('#backup-flow-storage').querySelectorAll('[data-flow-storage-action]'))button.addEventListener('click',()=>backupFlowRun('preserved','backup-flow-storage-error',async current=>{
      if(!backupFlowCurrent(ticket))throw new Error('目录已变化，请重新读取清单。');
      const payload={action:button.dataset.flowStorageAction==='open'?'open-storage':'preserved-export',kind:button.dataset.kind,context:current.context};
      if(button.dataset.file)payload.file=button.dataset.file;
      if(payload.action==='open-storage'){const opened=await post('/api/backups/workflow',payload);if(backupFlowCurrent(current)&&opened.context===current.context)toast('已打开所选目录');}
      else await backupFlowDownload(payload,current,'灯火-保留副本.zip');
    }));
    if(focusKey)[...$('#backup-flow-storage').querySelectorAll('button')].find(button=>button.dataset.flowStorageAction===focusKey&&button.dataset.kind===focusKind&&button.dataset.file===focusFile)?.focus({preventScroll:true});
  });
}
async function backupFlowDownload(payload,ticket,filename,isDraftCurrent=()=>true){
  if(!backupFlowCurrent(ticket)||!isDraftCurrent())throw new Error('连接或选择已变化，请重新预览。');
  const response=await fetch('/api/backups/workflow',{method:'POST',headers:{'Content-Type':'application/json','X-Companion-Token':token},body:JSON.stringify(payload)});
  if(!response.ok)throw new Error((await response.json()).error||'导出失败');
  const blob=await response.blob();if(!backupFlowCurrent(ticket)||!isDraftCurrent())return;
  const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function inspectBackupStage(file,preview=false){
  return backupFlowRun('stage','backup-flow-storage-error',async ticket=>{
    const revision=++backupFlow.stageRevision;backupFlow.stageDraft=null;
    const result=await post('/api/backups/workflow',{action:preview?'stage-preview':'stage-inspect',file,context:ticket.context});
    if(!backupFlowCurrent(ticket)||revision!==backupFlow.stageRevision||result.context!==ticket.context)return;
    const panel=$('#backup-stage-review'),target=$('#backup-stage-content');panel.hidden=false;target.replaceChildren();
    $('#backup-stage-status').textContent=`${result.path} · ${flowSize(result.bytes)} · ${result.verification}。${result.reason||''} ${result.error||result.note||''}`;
    if(preview){
      backupFlow.stageDraft={...result,revision};
      const evidence=document.createElement('div');evidence.innerHTML='<h4>当前槽位进度</h4>'+backupSummary(result.current)+'<h4>将恢复的原备份进度</h4>'+backupSummary(result.target);target.append(evidence);
      const phraseLabel=document.createElement('label'),phrase=document.createElement('input');phrase.type='text';phrase.autocomplete='off';phraseLabel.textContent='核对当前与目标进度后输入：'+result.confirm_phrase;phraseLabel.append(phrase);target.append(phraseLabel);
      const label=document.createElement('label'),confirm=document.createElement('input');confirm.type='checkbox';label.append(confirm,document.createTextNode('我已关闭游戏，明确确认重新尝试这个暂存对应的回档；原暂存、原备份和回档前进度均保留。'));target.append(label);
      const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='确认重新尝试回档';button.disabled=true;target.append(button);
      const update=()=>button.disabled=!confirm.checked||phrase.value!==result.confirm_phrase;confirm.addEventListener('change',update);phrase.addEventListener('input',update);
      const draft=backupFlow.stageDraft;
      button.addEventListener('click',()=>backupFlowRun('stage','backup-flow-storage-error',async current=>{
        if(!backupFlowCurrent(ticket)||backupFlow.stageDraft!==draft||draft.revision!==backupFlow.stageRevision||!confirm.checked||phrase.value!==draft.confirm_phrase)throw new Error('暂存选择、连接或确认已变化，请重新预览。');
        button.disabled=true;const applied=await post('/api/backups/workflow',{action:'stage-retry',file:draft.file,expected:draft.expected,confirmed:true,confirm:phrase.value,context:current.context});
        recordBackupReceipt('stage',current,{...applied,results:[{...draft.source,...applied}]},{file:draft.file,expected:draft.expected},!backupFlowCurrent(current)||backupFlow.stageDraft!==draft);
        if(backupFlow.stageDraft===draft){backupFlow.stageDraft=null;panel.hidden=true;}await refreshBackupReceiptScope(current);
      }));
    }
    panel.tabIndex=-1;panel.focus();backupFlow.storageDirty=true;await loadBackupFlowStorage();
  });
}
async function previewBackupBatchExport(){
  return backupFlowRun('export','backup-batch-export-error',async ticket=>{
    const revision=++backupFlow.exportRevision;backupFlow.exportDraft=null;$('#backup-batch-export-review').hidden=true;
    const selected=[...backupFlow.selection.values()];if(!selected.length||selected.length>32)throw new Error('请选择 1–32 份历史记录。不会省略超限记录。');
    const result=await post('/api/backups/workflow',{action:'export-preview',selected,context:ticket.context});
    if(!backupFlowCurrent(ticket)||revision!==backupFlow.exportRevision||result.context!==ticket.context)return;
    backupFlow.exportDraft={...result,selected,revision};$('#backup-batch-export-summary').textContent=`${result.count} 份 · ${flowSize(result.bytes)}。${result.message||''}`;
    $('#backup-batch-export-rows').innerHTML=flowTable(result.rows);$('#backup-batch-export-review').hidden=false;
  });
}
async function exportBackupBatch(){
  return backupFlowRun('export','backup-batch-export-error',async ticket=>{
    const draft=backupFlow.exportDraft;if(!draft)throw new Error('请先预览所选导出清单。');
    await backupFlowDownload({action:'batch-export',selected:draft.selected,expected:draft.expected,context:ticket.context},ticket,'灯火-备份迁移包.zip',()=>backupFlow.exportDraft===draft&&draft.revision===backupFlow.exportRevision);
  });
}
function backupRetentionPolicy(){
  return Object.fromEntries([['keep_per_slot','backup-keep-per-slot',5000],['older_than_days','backup-older-than-days',36500],['target_mib','backup-target-mib',512]].map(([key,id,max])=>{
    const value=$('#'+id).value;if(value==='')return [key,null];const number=Number(value);
    if(!Number.isInteger(number)||number<1||number>max)throw new Error('整理条件需要填写范围内的正整数，或留空。');return [key,number];
  }));
}
async function previewBackupRetention(){
  return backupFlowRun('retention','backup-retention-error',async ticket=>{
    const revision=++backupFlow.policyRevision,policy=backupRetentionPolicy();backupFlow.retentionDraft=null;$('#backup-retention-review').hidden=true;
    const result=await post('/api/backups/workflow',{action:'retention-preview',policy,context:ticket.context});
    if(!backupFlowCurrent(ticket)||revision!==backupFlow.policyRevision||result.context!==ticket.context)return;
    backupFlow.retentionDraft={...result,revision};$('#backup-retention-confirm').checked=false;$('#backup-retention-archive').disabled=true;
    $('#backup-retention-summary').textContent=`候选 ${result.candidates.length} 份 · 当前目录活动 ZIP ${flowSize(result.current_bytes)} → ${flowSize(result.remaining_active_bytes)}（不含索引与其他目录） · 当前统计总占用 ${flowSize(result.total_bytes_current)}；整理后重新统计。${result.note}`;
    const protectedRows=result.kept.filter(row=>row.protected),kept=result.kept.filter(row=>!row.protected);
    $('#backup-retention-rows').innerHTML=`<h3>将移入保留目录 · ${result.candidates.length} 份</h3>${flowTable(result.candidates,{reason:true})}<details class="rule-section"><summary>受保护 · ${protectedRows.length} 份</summary>${flowTable(protectedRows,{reason:true})}</details><details class="rule-section"><summary>继续保留在活动库 · ${kept.length} 份</summary>${flowTable(kept,{reason:true})}</details>`;
    $('#backup-retention-review').hidden=false;
  });
}
async function archiveBackupRetention(){
  return backupFlowRun('retention','backup-retention-error',async ticket=>{
    const draft=backupFlow.retentionDraft;if(!draft||draft.revision!==backupFlow.policyRevision||!$('#backup-retention-confirm').checked)throw new Error('请重新预览并确认具体候选。');
    $('#backup-retention-archive').disabled=true;
    const result=await post('/api/backups/workflow',{action:'archive-retention',policy:draft.policy,expected:draft.expected,confirmed:true,context:ticket.context});
    const rows=result.results.map(resultRow=>({...draft.candidates.find(row=>row.id===resultRow.id&&row.slot===resultRow.slot),...resultRow}));
    const changed=!backupFlowCurrent(ticket)||backupFlow.retentionDraft!==draft||draft.revision!==backupFlow.policyRevision;
    recordBackupReceipt('retention',ticket,{...result,results:rows},{policy:draft.policy,selected:draft.selected},changed);
    if(backupFlowCurrent(ticket)){
      if(!changed){backupFlow.retentionDraft=null;$('#backup-retention-review').hidden=true;$('#backup-retention-confirm').checked=false;}
      $('#backup-retention-result').textContent=`已移入 ${result.archived} 份 · 删除 ${result.deleted} 份。${result.message}${changed?' 新整理条件保持；已提交结果见操作回执。':''}`;
      $('#backup-retention-results').innerHTML=flowTable(rows,{result:true,successText:'已移入保留目录'});
    }await refreshBackupReceiptScope(ticket);
  });
}
async function backupFlowUpload(endpoint,file,ticket,extra={}){
  if(!backupFlowCurrent(ticket))throw new Error('连接已变化，请重新选择迁移包。');
  const response=await fetch('/api/backups/'+endpoint,{method:'POST',headers:{'Content-Type':'application/zip','X-Companion-Token':token,'X-Companion-Backup-Context':ticket.context,...extra},body:file});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'迁移包操作失败');return result;
}
async function previewBackupBatchImport(retryFiles=null){
  return backupFlowRun('import','backup-batch-import-error',async ticket=>{
    const file=backupFlow.importFile;resetBackupImportDraft();const revision=backupFlow.importRevision;
    if(!file)throw new Error('请先选择灯火导出的批量迁移 ZIP。');if(file.size>64*1048576)throw new Error('迁移包需要小于 64 MiB。');
    const result=await backupFlowUpload('batch-preview',file,ticket);
    if(!backupFlowCurrent(ticket)||revision!==backupFlow.importRevision||file!==backupFlow.importFile||result.context!==ticket.context)return;
    backupFlow.importDraft={...result,file,revision};
    if(retryFiles)backupFlow.importSelection=new Set(result.rows.filter(row=>row.valid&&retryFiles.includes(row.file)).map(row=>row.file));
    $('#backup-batch-import-summary').textContent=`${file.name} · ${flowSize(file.size)} · ${result.count} 份 · ${result.valid_count} 份可用 · ${result.count-result.valid_count} 份校验失败。${result.message||''}`;
    $('#backup-batch-import-rows').innerHTML=flowTable(result.rows,{select:'import',result:true});$('#backup-batch-import-review').hidden=false;updateBackupImportSelection();
  });
}
function updateBackupImportSelection(){
  backupFlow.importSelectionRevision++;
  for(const input of $('#backup-batch-import-rows').querySelectorAll('[data-flow-import]'))input.checked=backupFlow.importSelection.has(input.dataset.flowImport);
  $('#backup-batch-import-selection').textContent=`已选 ${backupFlow.importSelection.size} 份。每次更改选择后需要重新确认。`;
  $('#backup-batch-import-confirm').checked=false;$('#backup-batch-import').disabled=true;
}
async function importBackupBatch(){
  return backupFlowRun('import','backup-batch-import-error',async ticket=>{
    const draft=backupFlow.importDraft,selected=[...backupFlow.importSelection],selectionRevision=backupFlow.importSelectionRevision;
    if(!draft||draft.revision!==backupFlow.importRevision||draft.file!==backupFlow.importFile||!selected.length||!$('#backup-batch-import-confirm').checked)throw new Error('请预览迁移包、选择具体记录并确认。');
    $('#backup-batch-import').disabled=true;
    const result=await backupFlowUpload('batch-import',draft.file,ticket,{'X-Companion-Transfer-Digest':draft.expected,'X-Companion-Transfer-Selection':JSON.stringify(selected),'X-Companion-Transfer-Confirmed':'true'});
    const changed=!backupFlowCurrent(ticket)||backupFlow.importDraft!==draft||selectionRevision!==backupFlow.importSelectionRevision;
    recordBackupReceipt('import',ticket,result,{selected,file_name:draft.file.name},changed,draft.file);
    backupFlow.importResults=result.results;
    if(backupFlowCurrent(ticket)){
      if(!changed)resetBackupImportDraft();else $('#backup-batch-import-confirm').checked=false;
      $('#backup-batch-import-result').textContent=`成功 ${result.success_count} 份 · 失败 ${result.failure_count} 份 · 未恢复游戏。成功记录已登记到历史。${changed?' 新文件与选择保持；已提交结果独立见操作回执。':''}`;
      $('#backup-batch-import-results').innerHTML=flowTable(result.results,{result:true});$('#backup-batch-import-retry').hidden=!result.failure_count;
    }await refreshBackupReceiptScope(ticket);
  });
}

function invalidateBackupReclaim(){
  backupFlow.reclaimRevision++;backupFlow.reclaimDraft=null;
  $('#backup-reclaim-review').hidden=true;$('#backup-reclaim-confirmation').hidden=true;
  $('#backup-reclaim-confirm').checked=false;$('#backup-reclaim-phrase').value='';$('#backup-reclaim-execute').disabled=true;
  $('#backup-reclaim-selection').textContent=`已选 ${backupFlow.reclaimSelection.size} 项原件。选择、路径或清单变化后须重新预览。`;
}
function setupBackupReclaim(){
  $('#backup-flow-storage').addEventListener('change',event=>{
    const input=event.target;if(!input.matches('[data-flow-reclaim]'))return;
    if(input.checked)backupFlow.reclaimSelection.set(input.dataset.flowReclaim,{kind:input.dataset.kind,file:input.dataset.file});
    else backupFlow.reclaimSelection.delete(input.dataset.flowReclaim);invalidateBackupReclaim();
  });
  $('#backup-reclaim-path').addEventListener('input',invalidateBackupReclaim);
  $('#backup-reclaim-preview').addEventListener('click',()=>backupFlowRun('reclaim','backup-reclaim-error',async ticket=>{
    invalidateBackupReclaim();const revision=backupFlow.reclaimRevision,selected=[...backupFlow.reclaimSelection.values()],external_path=$('#backup-reclaim-path').value.trim();
    if(!selected.length)throw new Error('请在空间清单中选择可回收的具体原件。');
    const result=await post('/api/backups/workflow',{action:'reclaim-preview',selected,context:ticket.context});
    if(!backupFlowCurrent(ticket)||revision!==backupFlow.reclaimRevision||result.context!==ticket.context)return;
    backupFlow.reclaimDraft={...result,revision,external_path};
    $('#backup-reclaim-summary').textContent=`确切目标 ${result.count} 项 · 可释放原件内容 ${flowSize(result.bytes)} · 活动额度释放 ${flowSize(result.active_bytes_released)}。${result.note}`;
    $('#backup-reclaim-rows').innerHTML=flowTable(result.rows.map(row=>({...row,reason:row.reclaim_reason})),{reason:true});
    $('#backup-reclaim-verified').textContent='外部位置尚未核验；尚未回收。';$('#backup-reclaim-review').hidden=false;
  }));
  $('#backup-reclaim-export').addEventListener('click',()=>backupFlowRun('reclaim','backup-reclaim-error',async ticket=>{
    const draft=backupFlow.reclaimDraft;if(!draft||draft.revision!==backupFlow.reclaimRevision)throw new Error('请重新预览确切原件。');
    const result=await post('/api/backups/workflow',{action:'reclaim-export',selected:draft.selected,expected:draft.expected,external_path:draft.external_path,context:ticket.context});
    if(!backupFlowCurrent(ticket)||backupFlow.reclaimDraft!==draft||result.context!==ticket.context)return;
    Object.assign(draft,{external_path:result.external_path,archive_sha256:result.archive_sha256,verified:result.verified});
    $('#backup-reclaim-verified').textContent=`已核验真实外部位置：${result.external_path} · SHA-256 ${result.archive_sha256}。${result.message}`;
    $('#backup-reclaim-phrase').placeholder=draft.confirm_phrase;$('#backup-reclaim-confirmation').hidden=false;
  }));
  const update=()=>{$('#backup-reclaim-execute').disabled=!backupFlow.reclaimDraft?.verified||!$('#backup-reclaim-confirm').checked||$('#backup-reclaim-phrase').value!==backupFlow.reclaimDraft?.confirm_phrase;};
  $('#backup-reclaim-confirm').addEventListener('change',update);$('#backup-reclaim-phrase').addEventListener('input',update);
  $('#backup-reclaim-execute').addEventListener('click',()=>backupFlowRun('reclaim','backup-reclaim-error',async ticket=>{
    const draft=backupFlow.reclaimDraft;
    if(!draft?.verified||draft.revision!==backupFlow.reclaimRevision||!$('#backup-reclaim-confirm').checked||$('#backup-reclaim-phrase').value!==draft.confirm_phrase)throw new Error('请先核验外部归档，并明确确认数量和短语。');
    $('#backup-reclaim-execute').disabled=true;
    const result=await post('/api/backups/workflow',{action:'reclaim-execute',selected:draft.selected,expected:draft.expected,external_path:draft.external_path,archive_sha256:draft.archive_sha256,exact_targets:draft.selected,count:draft.count,confirm:$('#backup-reclaim-phrase').value,confirmed:true,context:ticket.context});
    const rows=result.results.map(row=>({...draft.rows.find(source=>source.kind===row.kind&&source.file===row.file),...row}));
    const changed=!backupFlowCurrent(ticket)||backupFlow.reclaimDraft!==draft||draft.revision!==backupFlow.reclaimRevision;
    recordBackupReceipt('reclaim',ticket,{...result,results:rows},{selected:draft.selected,external_path:draft.external_path},changed);
    if(backupFlowCurrent(ticket)){
      $('#backup-reclaim-result').textContent=`完成 ${result.success_count} 项 · 未完成 ${result.failure_count} 项 · 实际释放原件内容 ${flowSize(result.released_bytes)} · 外部归档 ${result.external_path} 保持。${result.message}${changed?' 新选择与路径保持；已提交结果见操作回执。':''}`;
      $('#backup-reclaim-results').innerHTML=flowTable(rows,{result:true,successText:'所选原件已回收；外部归档保持'});
      if(!changed){backupFlow.reclaimSelection.clear();invalidateBackupReclaim();}else $('#backup-reclaim-confirm').checked=false;
    }await refreshBackupReceiptScope(ticket);
  }));
}
