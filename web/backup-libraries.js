'use strict';
const backupLibraries={context:null,selected:'',epoch:0,catalogRequest:0,detailRequest:0,catalog:null,data:null,
  selection:new Map(),limit:20,retainedLimit:20,preview:null,busy:false,receipts:[]};
const librarySize=value=>value==null?'尚未完整核对':flowSize(value);
function libraryTicket(){return {context:state?.backup_context,library_id:backupLibraries.selected,epoch:backupLibraries.epoch};}
function libraryCurrent(ticket){return !!ticket.context&&ticket.context===state?.backup_context&&ticket.context===backupLibraries.context&&ticket.library_id===backupLibraries.selected&&ticket.epoch===backupLibraries.epoch;}
function invalidateLibraryPreview(){
  backupLibraries.epoch++;backupLibraries.preview=null;
  $('#library-backup-review').hidden=true;$('#library-backup-confirm').checked=false;$('#library-backup-execute').disabled=true;
}
function resetBackupLibraries(context,load=true){
  ensureBackupLibraries();backupLibraries.context=context;backupLibraries.selected='';backupLibraries.catalog=null;backupLibraries.data=null;
  backupLibraries.catalogRequest++;backupLibraries.detailRequest++;backupLibraries.selection.clear();invalidateLibraryPreview();
  $('#library-backup-picker').replaceChildren();$('#library-backup-content').replaceChildren();$('#library-backup-summary').textContent='请读取现有备份库。';
  $('#library-backup-actions').hidden=true;$('#library-backup-folders').replaceChildren();inlineError($('#library-backup-error'),'');
  if(load&&context&&$('#backup-libraries').open)loadBackupLibraries();
}
function ensureBackupLibraries(){
  if($('#backup-libraries'))return;
  const panel=document.createElement('details');panel.id='backup-libraries';panel.className='panel retained-panel';
  panel.innerHTML=`<summary>全部备份库 · 包含以前连接的目录</summary>
    <p class="muted">换了游戏目录，旧备份仍在这里。选择库不会切换当前游戏连接；活动 ZIP 共用512 MiB额度，移入保留目录只调整额度，不释放磁盘空间。</p>
    <button id="library-backup-refresh" type="button" class="secondary">读取全部备份库</button>
    <p id="library-backup-quota" role="status"></p><label>要管理的备份库<select id="library-backup-picker" aria-label="要管理的备份库"></select></label>
    <p id="library-backup-summary" class="rule-path" role="status">请读取现有备份库。</p><div id="library-backup-folders" class="backup-actions"></div>
    <p id="library-backup-error" role="alert" class="rule-warning" hidden></p>
    <div id="library-backup-actions" hidden>
      <label>筛选记录名称、编号或槽位<input id="library-backup-query" type="search" autocomplete="off"></label>
      <p id="library-backup-selection" role="status"></p><div class="backup-actions">
        <button id="library-backup-clear" type="button" class="quiet">清空导出选择</button><button id="library-backup-export-preview" type="button" class="secondary">预览所选记录导出</button>
      </div><div id="library-backup-content"></div><button id="library-backup-more" type="button" class="quiet" hidden>显示更多活动记录</button>
      <form id="library-backup-policy"><fieldset><legend>手动整理所选库 · 默认全部保留</legend><div class="form-grid">
        <label>每槽至少保留最新几份<input id="library-backup-keep" type="number" min="1" max="5000" step="1" placeholder="全部保留"></label>
        <label>只整理超过多少天的记录<input id="library-backup-days" type="number" min="1" max="36500" step="1" placeholder="不限制"></label>
        <label>活动 ZIP 目标（MiB）<input id="library-backup-target" type="number" min="1" max="512" step="1" placeholder="不限制"></label>
      </div><p class="muted">固定记录、每槽最新记录和当前撤回关联目标始终保留。三个条件同时满足才移出；实际候选在下一步核对。</p><button type="submit" class="secondary">预览所选库整理候选</button></fieldset></form>
      <h3>移出后完整保留</h3><div id="library-backup-retained"></div><button id="library-backup-retained-more" type="button" class="quiet" hidden>显示更多保留副本</button>
    </div>
    <section id="library-backup-review" hidden aria-label="核对所选库操作"><h3 id="library-backup-review-title"></h3><p id="library-backup-review-summary" role="status"></p><div id="library-backup-review-rows"></div>
      <label id="library-backup-confirm-label" class="check"><input id="library-backup-confirm" type="checkbox">我已核对库编号和具体记录，确认执行上方操作。</label>
      <button id="library-backup-execute" type="button" class="primary" disabled>确认</button><button id="library-backup-cancel" type="button" class="quiet">取消这次核对</button>
    </section><section id="library-backup-receipts" aria-label="备份库操作回执"></section>`;
  $('#view-backups').append(panel);
  panel.addEventListener('toggle',()=>{if(panel.open&&!backupLibraries.catalog)loadBackupLibraries();});
  $('#library-backup-refresh').addEventListener('click',loadBackupLibraries);
  $('#library-backup-picker').addEventListener('change',()=>loadBackupLibrary($('#library-backup-picker').value));
  $('#library-backup-query').addEventListener('input',()=>{backupLibraries.limit=20;renderBackupLibrary();});
  $('#library-backup-more').addEventListener('click',()=>{backupLibraries.limit+=20;renderBackupLibrary();});
  $('#library-backup-retained-more').addEventListener('click',()=>{backupLibraries.retainedLimit+=20;renderBackupLibrary();});
  $('#library-backup-clear').addEventListener('click',()=>{backupLibraries.selection.clear();invalidateLibraryPreview();renderBackupLibrary();});
  $('#library-backup-content').addEventListener('change',event=>{
    const input=event.target;if(!input.matches('[data-flow-select]'))return;
    const row=backupLibraries.data?.groups[0].rows.find(row=>flowKey(row)===input.dataset.flowSelect);if(!row)return;
    if(input.checked&&backupLibraries.selection.size>=32){input.checked=false;inlineError($('#library-backup-error'),'一次最多选择32份，请分批导出；现有选择仍保留。');return;}
    if(input.checked)backupLibraries.selection.set(flowKey(row),{slot:row.slot,id:row.id});else backupLibraries.selection.delete(flowKey(row));
    invalidateLibraryPreview();updateLibrarySelection();
  });
  $('#library-backup-export-preview').addEventListener('click',()=>previewLibraryOperation('export-preview',{selected:[...backupLibraries.selection.values()]}));
  $('#library-backup-policy').addEventListener('input',invalidateLibraryPreview);
  $('#library-backup-policy').addEventListener('submit',event=>{
    event.preventDefault();if(!$('#library-backup-policy').reportValidity())return;
    const policy={};for(const [field,key] of [['keep','keep_per_slot'],['days','older_than_days'],['target','target_mib']]){
      const raw=$('#library-backup-'+field).value;if(raw!=='')policy[key]=Number(raw);
    }previewLibraryOperation('retention-preview',{policy});
  });
  $('#library-backup-confirm').addEventListener('change',()=>$('#library-backup-execute').disabled=!backupLibraries.preview||backupLibraries.busy||!$('#library-backup-confirm').checked);
  $('#library-backup-execute').addEventListener('click',executeLibraryOperation);
  $('#library-backup-cancel').addEventListener('click',invalidateLibraryPreview);
  renderLibraryReceipts();
}
async function loadBackupLibraries(){
  ensureBackupLibraries();const context=state?.backup_context;if(!context)return;
  if(context!==backupLibraries.context)resetBackupLibraries(context,false);
  const request=++backupLibraries.catalogRequest;
  inlineError($('#library-backup-error'),'');
  try{
    const response=await fetch('/api/backup-libraries?'+new URLSearchParams({context})),result=await response.json();
    if(request!==backupLibraries.catalogRequest||context!==state?.backup_context)return;
    if(!response.ok)throw new Error(result.error||'备份库暂不可读');if(result.context!==context)return;
    backupLibraries.catalog=result;
    const quota=result.quota;$('#library-backup-quota').textContent=`全部库活动 ZIP：${librarySize(quota.bytes)} / ${librarySize(quota.limit)}。${quota.unclassified_bytes?`另有未归类活动 ZIP ${librarySize(quota.unclassified_bytes)}。`:''}${quota.error||''}${result.discovery_errors.map(row=>row.error).join('；')}`;
    $('#library-backup-picker').innerHTML=result.libraries.map(row=>`<option value="${row.id}">${escapeHTML(libraryLabel(row))}</option>`).join('');
    const selected=result.libraries.some(row=>row.id===backupLibraries.selected)?backupLibraries.selected:result.current_library_id||result.libraries[0]?.id||'';
    $('#library-backup-picker').value=selected;await loadBackupLibrary(selected);
  }catch(error){if(context===state?.backup_context&&request===backupLibraries.catalogRequest)inlineError($('#library-backup-error'),error.message);}
}
function libraryLabel(row){
  const last=row.latest;return `${row.current?'当前连接库':'旧备份库'} · ${last?`${classNames[last.class]||last.class} / 槽位${last.slot} / 第${last.depth}层`:'暂无可读摘要'} · ${row.record_count??'未知'}份 · ${row.id}`;
}
async function loadBackupLibrary(identity){
  backupLibraries.selected=identity;backupLibraries.data=null;backupLibraries.selection.clear();backupLibraries.limit=backupLibraries.retainedLimit=20;
  $('#library-backup-query').value='';invalidateLibraryPreview();$('#library-backup-content').replaceChildren();$('#library-backup-actions').hidden=true;
  const row=backupLibraries.catalog?.libraries.find(row=>row.id===identity);$('#library-backup-folders').replaceChildren();
  if(!row){$('#library-backup-summary').textContent='暂无备份库。';return;}
  $('#library-backup-summary').textContent=`库编号：${identity}。${row.current?`当前连接目录：${row.source}`:'旧版未登记来源目录；请按库编号、角色、槽位及保存时间核对。'} 活动内容 ${librarySize(row.groups.active.bytes)}，移出保留 ${librarySize(row.groups.retained.bytes)}，损坏隔离 ${librarySize(row.groups.quarantine.bytes)}。${row.errors.map(error=>error.error).join('；')}`;
  for(const [kind,name] of [['active','活动库'],['retained','移出保留'],['quarantine','隔离原件']]){
    const button=document.createElement('button');button.type='button';button.className='quiet';button.textContent='打开'+name+'目录';button.title=row.groups[kind].directory;
    button.addEventListener('click',()=>runLibraryOperation(ticket=>libraryJSON('open-folder',{kind},ticket)));$('#library-backup-folders').append(button);
  }
  const ticket=libraryTicket(),request=++backupLibraries.detailRequest;inlineError($('#library-backup-error'),'');
  try{
    const response=await fetch('/api/backup-libraries?'+new URLSearchParams({context:ticket.context,id:identity})),result=await response.json();
    if(!libraryCurrent(ticket)||request!==backupLibraries.detailRequest)return;
    if(!response.ok)throw new Error(result.error||'所选库记录暂不可读');if(result.context!==ticket.context||result.library_id!==identity)return;
    backupLibraries.data=result;$('#library-backup-actions').hidden=false;renderBackupLibrary();
  }catch(error){if(libraryCurrent(ticket)&&request===backupLibraries.detailRequest)inlineError($('#library-backup-error'),error.message+'。原件仍保留，可打开所选库目录核对。');}
}
function updateLibrarySelection(){
  $('#library-backup-selection').textContent=`已选${backupLibraries.selection.size}份导出；筛选不会更改选择。每批最多32份、64 MiB。`;
}
function renderBackupLibrary(){
  const data=backupLibraries.data;if(!data)return;
  const query=$('#library-backup-query').value.trim().toLocaleLowerCase(),rows=data.groups[0].rows;
  const filtered=rows.filter(row=>[row.label,row.id,'槽位'+row.slot].join(' ').toLocaleLowerCase().includes(query)),shown=filtered.slice(0,backupLibraries.limit);
  $('#library-backup-content').innerHTML=`<p>显示 ${shown.length} / ${filtered.length} 项匹配记录（库内共${rows.length}项）；导出前会完整校验。</p>`+flowTable(shown,{select:'export',reason:true});
  for(const input of $$('#library-backup-content [data-flow-select]'))input.checked=backupLibraries.selection.has(input.dataset.flowSelect);
  $('#library-backup-more').hidden=shown.length>=filtered.length;updateLibrarySelection();
  const retained=data.groups.find(group=>group.kind==='retained').rows;
  $('#library-backup-retained').innerHTML=`<p>显示 ${Math.min(retained.length,backupLibraries.retainedLimit)} / ${retained.length} 份完整保留副本。</p>`;
  for(const row of retained.slice(0,backupLibraries.retainedLimit)){
    const article=document.createElement('div');article.className='retained-row';const text=document.createElement('span');
    text.textContent=`${row.label||'未命名副本'} · 槽位${row.slot??'未确认'} · ${fmtTime(row.time)} · ${librarySize(row.bytes)} · ${row.file}${row.metadata_error?' · '+row.metadata_error:''}`;
    const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='核对并重新加入此库';
    button.addEventListener('click',()=>previewLibraryOperation('rejoin-preview',{file:row.file}));article.append(text,button);$('#library-backup-retained').append(article);
  }$('#library-backup-retained-more').hidden=retained.length<=backupLibraries.retainedLimit;
}
async function libraryJSON(action,payload,ticket){
  const response=await fetch('/api/backup-libraries',{method:'POST',headers:{'Content-Type':'application/json','X-Companion-Token':token},body:JSON.stringify({...payload,action,context:ticket.context,library_id:ticket.library_id})});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'操作未完成，请重新读取所选库核对');return result;
}
async function runLibraryOperation(work){
  if(backupLibraries.busy)return;const ticket=libraryTicket();if(!libraryCurrent(ticket))return;
  backupLibraries.busy=true;$('#library-backup-execute').disabled=true;inlineError($('#library-backup-error'),'');
  try{await work(ticket);}catch(error){if(libraryCurrent(ticket))inlineError($('#library-backup-error'),error.message);else toast(error.message,true);}
  finally{backupLibraries.busy=false;$('#library-backup-execute').disabled=!backupLibraries.preview||!$('#library-backup-confirm').checked;}
}
async function previewLibraryOperation(action,payload){
  if(backupLibraries.busy)return;invalidateLibraryPreview();
  await runLibraryOperation(async ticket=>{
    const result=await libraryJSON(action,payload,ticket);if(!libraryCurrent(ticket)||result.context!==ticket.context||result.library_id!==ticket.library_id)return;
    backupLibraries.preview={action,payload,result,ticket};$('#library-backup-review').hidden=false;
    const titles={'export-preview':'核对要导出的记录','retention-preview':'核对要移入保留目录的记录','rejoin-preview':'核对要重新加入的副本'};
    $('#library-backup-review-title').textContent=titles[action];
    $('#library-backup-review-summary').textContent=`所选库：${ticket.library_id}。${action==='retention-preview'?`候选${result.candidates.length}份，保持${result.kept.length}份；所选库活动内容由${librarySize(result.current_bytes)}变为${librarySize(result.remaining_active_bytes)}。`:action==='export-preview'?`${result.count}份，${librarySize(result.bytes)}。`:''}${result.note||result.message||''}`;
    $('#library-backup-review-rows').innerHTML=action==='retention-preview'?'<h4>将移入保留目录</h4>'+flowTable(result.candidates,{reason:true})+'<h4>继续保持</h4>'+flowTable(result.kept,{reason:true}):action==='export-preview'?flowTable(result.rows):backupSummary(result.summary);
    $('#library-backup-execute').textContent=action==='retention-preview'?'确认移入保留目录':action==='export-preview'?'确认生成导出 ZIP':'确认重新加入此库';
  });
}
function recordLibraryReceipt(preview,result){
  const submitted=preview.result.candidates||preview.result.rows||[preview.result],names=new Map(submitted.map(row=>[flowKey(row),row]));
  const checked={...result,results:(result.results||[]).map(row=>({...names.get(flowKey(row)),...row}))};
  backupLibraries.receipts.push(freezeBackupReceipt(JSON.parse(JSON.stringify({finished:new Date().toISOString(),library_id:preview.ticket.library_id,context:preview.ticket.context,
    action:preview.action,submitted:preview.payload,changed:!libraryCurrent(preview.ticket),result:checked}))));renderLibraryReceipts();
}
function renderLibraryReceipts(){
  const holder=$('#library-backup-receipts');if(!holder)return;holder.innerHTML='<h3>备份库操作回执</h3>';
  if(!backupLibraries.receipts.length){holder.insertAdjacentHTML('beforeend','<p class="muted">已提交的实际结果会保留在这里，切换所选库或连接不会隐藏回执。</p>');return;}
  for(const receipt of [...backupLibraries.receipts].reverse()){
    const section=document.createElement('details');section.open=true;const title=document.createElement('summary');title.textContent=`${receipt.finished} · 库 ${receipt.library_id}`;
    const info=document.createElement('p');info.textContent=(receipt.result.message||'操作完成')+(receipt.changed?' 提交后选择或连接已变化；此回执仍属于上述库。':'');
    const rows=document.createElement('div');rows.innerHTML=flowTable(receipt.result.results||[],{result:true,successText:'已移入保留目录'});section.append(title,info,rows);holder.append(section);
  }
}
async function executeLibraryOperation(){
  const preview=backupLibraries.preview;if(!preview||!libraryCurrent(preview.ticket)||!$('#library-backup-confirm').checked)return;
  await runLibraryOperation(async ticket=>{
    const action={'export-preview':'batch-export','retention-preview':'archive-retention','rejoin-preview':'rejoin'}[preview.action];
    const payload={...preview.payload,expected:preview.result.expected,confirmed:true};let result;
    if(action==='batch-export'){
      const response=await fetch('/api/backup-libraries',{method:'POST',headers:{'Content-Type':'application/json','X-Companion-Token':token},body:JSON.stringify({...payload,action,context:ticket.context,library_id:ticket.library_id})});
      if(!response.ok)throw new Error((await response.json()).error||'导出未完成');
      const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=`灯火-备份库${ticket.library_id.slice(0,12)}.zip`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      result={count:preview.result.count,message:`已生成${preview.result.count}份记录的索引 ZIP；请核对浏览器下载结果，原件仍保留。`};
    }else result=await libraryJSON(action,payload,ticket);
    recordLibraryReceipt(preview,result);
    if(libraryCurrent(ticket)){
      invalidateLibraryPreview();backupLibraries.selection.clear();await loadBackupLibraries();
      if(view==='backups')await loadBackups();
    }
  });
}
ensureBackupLibraries();
