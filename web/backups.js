'use strict';
let backupState, backupLoading=false, restoreTarget=null, backupHistoryLimit=20,backupRetainedLimit=20;
let backupContext=null,manageTarget=null,repairTarget=null,historyRepairTarget=null,restorePreview=0;
const backupViewKeys=new Map(),backupMetadataDrafts=new Map();
let manageEditRevision=0;
const nodeLabel=seconds=>seconds>=60?`${seconds/60} 分钟前`:`${seconds} 秒前`;
const classNames={WARRIOR:'战士',MAGE:'法师',ROGUE:'盗贼',HUNTRESS:'女猎手',DUELIST:'决斗家',CLERIC:'牧师'};
const healthNames={paused:'自动备份已暂停',blocked:'自动备份受阻',waiting:'等待新的游戏保存',protected:'最近保存已备份'};
const healthName=(health)=>health.state==='waiting'&&health.last_save_protected?'上次保存已备份 · 等待新保存':healthNames[health.state]||'正在检查备份';
const ageLabel=seconds=>seconds<60?`${Math.floor(Math.max(0,seconds))}秒`:seconds<3600?`${Math.floor(seconds/60)}分钟`:seconds<86400?`${Math.floor(seconds/3600)}小时${Math.floor(seconds%3600/60)}分钟`:`${Math.floor(seconds/86400)}天`;
function renderBackupHealth(){
  const h=state?.backup_health, el=$('#backup-health');
  if(!state){el.className='connection-banner error';el.textContent='服务未连接 · 自动备份状态尚未确认';return;}
  el.className='connection-banner'+(h?.state==='blocked'?' error':'');
  el.textContent=h?`${h.slot?`槽位 ${h.slot}：`:''}${healthName(h)}${h.saved?` · 游戏保存距今 ${ageLabel(Date.now()/1000-h.saved)}`:''}${h.last_success?` · 最近检查成功 ${shortTime(h.last_success)}`:''}${h.error?` · ${h.error}`:''}${h.other_errors?` · 其他槽位：${h.other_errors}`:''}`:'自动备份状态尚未确认';
}
function syncBackupContext(context){
  if(context===backupContext)return;
  rememberBackupMetadataDraft();
  const changed=!!backupContext;
  backupContext=context;backupState=null;manageTarget=null;repairTarget=null;historyRepairTarget=null;restorePreview++;backupViewKeys.clear();
  if(typeof resetBackupWorkflows==='function')resetBackupWorkflows(context);
  $('#backup-slot').value='';$('#backup-slot').innerHTML='';
  $('#backup-history-count').textContent=context?'正在读取当前目录的历史记录…':'服务未连接，历史数量暂不可确认。';
  $('#backup-node-gaps').textContent=context?'正在读取当前目录的时间节点…':'服务未连接，时间节点暂不可确认。';backupHistoryLimit=20;backupRetainedLimit=20;
  $('#repair-timeline').hidden=true;
  $('#repair-history').hidden=true;$('#history-repair-dialog').close();
  $('#backup-storage').textContent=context?'正在读取当前目录的备份占用…':'服务未连接，备份占用暂不可确认。';
  $('#restore-dialog').close();restoreTarget=null;$('#manage-dialog').close();$('#repair-dialog').close();
  $('#manage-form').dataset.context='';$('#repair-form').dataset.context='';
  for(const selector of ['#backup-history','#backup-retained','#backup-undo','#backup-nodes'])$(selector).replaceChildren();
  renderBackupMetadataDrafts();
  if(changed&&context)toast('存档历史的确认状态已更新，请重新选择备份并预览。');
}
function backupSummary(row){
  if(!row || row.empty)return `<p>没有可读取的完整进度</p>${row?.warning?`<p>${escapeHTML(row.warning)}</p>`:''}`;
  const items=(row.equipment||[]).map(i=>`${escapeHTML(i.location)}：${escapeHTML(i.name)} ${escapeHTML((i.details||[]).join(' · '))}`).join('<br>');
  return `<p><strong>${escapeHTML(classNames[row.class]||row.class)} Lv.${escapeHTML(row.level??'未知')} · 第 ${escapeHTML(row.depth)} 层${row.branch?'（支线）':''}</strong><br>生命 ${escapeHTML(row.hp??'未知')}/${escapeHTML(row.ht??'未知')} · 金币 ${escapeHTML(row.gold??'未知')} · 基础力量 ${escapeHTML(row.strength??'未知')}${row.duration!=null?`<br>本局行动时间 ${escapeHTML(row.duration)} 回合`:''}<br>游戏保存 ${fmtTime(row.saved)}${items?`<br>${items}`:''}</p>`;
}
async function loadBackups(){
  const context=state?.backup_context;
  if(backupLoading||!context)return;backupLoading=true;
  try{
    const response=await fetch('/api/backups?'+new URLSearchParams({context}));if(!response.ok)throw new Error((await response.json()).error||'备份状态暂时无法读取');
    const result=await response.json();if(context!==state?.backup_context||result.context!==context)return;
    backupState=result;$('#backup-enabled').checked=backupState.enabled;
    $('#backup-status').textContent=`${healthName({...backupState,state:backupState.health})}。${backupState.error||''} ${backupState.notice||''}`;
    const amount=backupState.storage_bytes==null?'暂时无法读取':`${(backupState.storage_bytes/1048576).toFixed(2)} MiB`;
    $('#backup-storage').textContent=`活动备份 ${amount} / ${(backupState.storage_limit/1048576).toFixed(0)} MiB · ${backupState.records_available===false?'历史记录暂不可读取':`${backupState.history.length} 份不同进度`}。达到上限会停止新增，固定的记录不能移出。`;
    const sizes=backupState.storage_breakdown;
    if(sizes)$('#backup-storage').textContent+=` 总占用 ${(sizes.total/1048576).toFixed(2)} MiB（活动库含索引 ${(sizes.active/1048576).toFixed(2)}、移出副本 ${(sizes.retained/1048576).toFixed(2)}、损坏隔离 ${(sizes.quarantine/1048576).toFixed(2)}、本存档目录回档前副本 ${(sizes.before_restore/1048576).toFixed(2)}、中断暂存 ${((sizes.interrupted_stage||0)/1048576).toFixed(2)}）。保留副本不会自动删除。`;
    const selected=$('#backup-slot').value;
    const slots=backupState.slots.map(row=>row.slot),active=state?.active_slot;
    if(active&&!slots.includes(active))slots.push(active);
    if(!slots.length)slots.push(1);
    slots.sort((a,b)=>a-b);
    $('#backup-slot').innerHTML=slots.map(slot=>`<option value="${slot}">槽位 ${slot}${backupState.slots.some(row=>row.slot===slot)?'':'（暂无活动备份）'}</option>`).join('');
    $('#backup-slot').value=slots.includes(Number(selected))&&selected?selected:String(active||slots[0]);
    $('#repair-timeline').hidden=!backupState.repair_timeline_available;
    $('#repair-history').hidden=!backupState.repair_history_available;
    renderBackups();
    if(typeof renderBackupWorkflows==='function')renderBackupWorkflows();
  }catch(error){if(context===state?.backup_context){$('#backup-status').textContent=error.message;$('#backup-nodes').textContent='备份信息不可用，请恢复连接后重试。';backupViewKeys.delete('#backup-nodes');}}
  finally{backupLoading=false;}
}
function backupCard(row, labels='', mode='history'){
  const invalid=row.integrity?.valid===false;
  const tags=Array.isArray(labels)?`<div class="node-tags">${labels.map(label=>`<span>${escapeHTML(label)}</span>`).join('')}</div>`:'';
  const recovered=row.metadata_recovered?'原名称和固定状态无法确认；恢复时默认全部固定，请逐份核对。':'';
  const imported=row.imported_at?`<br>导入登记 ${fmtTime(row.imported_at)}`:'';
  return `<article class="panel backup-card"><span class="tiny-label">${escapeHTML(row.label||'未命名进度')}${row.locked?' · 已固定':''}</span>${tags}<p class="restore-age" data-backup-saved="${row.saved}">将回到 ${ageLabel(Date.now()/1000-row.saved)}前保存的进度</p>${backupSummary(row)}<p class="muted">${row.recovered_at?'原观察时间未知 · 最近登记':mode==='history'?'最近观察':'观察时间'} <span data-backup-observed="${row.id}" data-backup-mode="${mode}">${fmtTime(mode==='history'?row.last_seen:row.time)}</span>${imported}${recovered?`<br>${recovered}`:''}<br>版本码 ${escapeHTML(row.version??'未知')}${row.version<850?` · 当前${escapeHTML(state?.catalog_version||'参考游戏')}不能继续此旧档`:''}${invalid?`<br>不可用：${escapeHTML(row.integrity.error)}`:''}</p><div class="backup-actions"><button class="secondary" data-restore="${row.id}" ${invalid?'disabled':''}>预览并恢复</button><button class="quiet" data-manage="${row.id}">命名 / 固定</button><button class="quiet" data-export="${row.id}" ${invalid?'disabled':''}>导出</button><button class="quiet" data-remove="${row.id}" ${row.locked?'disabled':''}>移出</button></div></article>`;
}
function setBackupContent(selector,key,html){
  if(backupViewKeys.get(selector)===key)return false;
  const holder=$(selector),active=document.activeElement;
  const focused=active&&holder.contains(active)?Object.entries(active.dataset).find(([name])=>['restore','manage','export','remove','rejoin','undo'].includes(name)):null;
  holder.innerHTML=html;backupViewKeys.set(selector,key);
  if(focused){const [name,value]=focused;const next=[...holder.querySelectorAll('button')].find(button=>button.dataset[name]===value);next?.focus({preventScroll:true});}
  return true;
}
function renderBackups(){
  const context=backupState?.context;
  if(!backupState||context!==state?.backup_context)return;
  const recordsUnavailable=backupState.records_available===false;
  const previousFocus=document.activeElement;
  const focusHolder=previousFocus&&['#backup-nodes','#backup-history','#backup-retained','#backup-undo'].map(selector=>$(selector)).find(holder=>holder.contains(previousFocus));
  const focusAction=focusHolder&&Object.entries(previousFocus.dataset).find(([name])=>['restore','manage','export','remove','rejoin','undo'].includes(name));
  const focusRect=focusAction&&previousFocus.getBoundingClientRect();
  // Browser scrolling can round a visible edge by a fraction of a pixel.
  const keepFocusVisible=focusRect&&focusRect.top>=-1&&focusRect.bottom<=window.innerHeight+1;
  const slot=Number($('#backup-slot').value), row=backupState?.slots.find(r=>r.slot===slot);
  const grouped=new Map();
  for(const node of row?[{seconds:0,backup:row.latest},...row.nodes]:[]){
    if(!node.backup)continue;
    const key=node.backup.id, historyRow=backupState.history.find(r=>r.id===key && r.slot===slot);
    const prior=grouped.get(key)||{backup:{...historyRow,...node.backup,
      label:historyRow?.label||'',locked:!!historyRow?.locked,integrity:historyRow?.integrity}, labels:[]};
    let label=node.seconds?nodeLabel(node.seconds):'最近备份';
    if(node.seconds && Date.now()/1000-node.backup.time-node.seconds>30)label+='（记录有间隔）';
    prior.labels.push(label);grouped.set(key,prior);
  }
  const changed=[];
  const nodes=[...grouped.values()];
  const nodeKey=JSON.stringify(nodes.map(r=>({...r,backup:{...r.backup,time:0,last_seen:0}})));
  if(setBackupContent('#backup-nodes',nodeKey,nodes.length?nodes.map(r=>backupCard(r.backup,r.labels,'node')).join(''):recordsUnavailable?'<p class="no-results">记录暂不可读取，备份文件仍保留。请查看上方原因，校验并恢复记录。</p>':'<p class="no-results">尚无时间节点；请在游戏中保存，让助手积累记录。</p>'))changed.push($('#backup-nodes'));
  const missing=(row?.nodes||[3600,1800,600,300,120,60,50,40,30,20,10].map(seconds=>({seconds,backup:null}))).filter(n=>!n.backup).map(n=>nodeLabel(n.seconds));
  $('#backup-node-gaps').textContent=recordsUnavailable?'旧时间节点暂不可确认；恢复记录后将重新积累。':missing.length?`尚未积累：${missing.join('、')}。节点按助手观察时间选择；卡片突出真正可恢复的游戏保存时间。`:'节点按助手观察时间选择；同一份游戏保存只显示一张卡片，无法回到尚未保存的画面。';
  const own=backupState?.history.filter(r=>r.slot===slot)||[];
  const terms=$('#backup-search').value.toLowerCase().split(/\s+/).filter(Boolean),filter=$('#backup-filter').value;
  const filtered=own.filter(r=>(filter!=='locked'||r.locked)&&(filter!=='named'||r.label)&&terms.every(term=>`${r.label} ${classNames[r.class]||r.class} 第${r.depth}层 ${fmtTime(r.saved)} ${fmtTime(r.time)} ${fmtTime(r.last_seen)}`.toLowerCase().includes(term)));
  let lastGroup='';
  const visibleHistory=filtered.slice(0,backupHistoryLimit);
  const historyKey=JSON.stringify(visibleHistory.map(r=>({...r,last_seen:0})));
  const historyHTML=visibleHistory.length?visibleHistory.map(r=>{
    const group=fmtTime(r.time).split(' ')[0]+' · '+(classNames[r.class]||r.class),heading=group!==lastGroup?`<h3 class="history-group">${escapeHTML(group)} · 记录时段</h3>`:'';lastGroup=group;
    return heading+backupCard(r);
  }).join(''):recordsUnavailable?'<p>历史记录暂不可读取；原备份文件仍保留，请先处理上方记录错误。</p>':'<p>没有符合筛选的记录；试试其他名称或取消筛选。</p>';
  if(setBackupContent('#backup-history',historyKey,historyHTML))changed.push($('#backup-history'));
  for(const age of $$('[data-backup-saved]'))age.textContent=`将回到 ${ageLabel(Date.now()/1000-Number(age.dataset.backupSaved))}前保存的进度`;
  for(const observed of $$('[data-backup-observed]')){const item=observed.dataset.backupMode==='history'?own.find(r=>r.id===observed.dataset.backupObserved):grouped.get(observed.dataset.backupObserved)?.backup;if(item)observed.textContent=fmtTime(observed.dataset.backupMode==='history'?item.last_seen:item.time);}
  $('#backup-history-count').textContent=recordsUnavailable?`槽位 ${slot}：记录暂不可读取，数量尚未确认。`:`槽位 ${slot}：${filtered.length} / ${own.length} 份进度。重开同一种子、同职业时请按保存时间与行动进度核对。`;
  $('#backup-more').hidden=filtered.length<=backupHistoryLimit;
  $('#backup-more').textContent=`显示更多历史（已显示 ${Math.min(backupHistoryLimit,filtered.length)} / ${filtered.length}）`;
  const retained=backupState?.retained||[];
  const visibleRetained=retained.slice(0,backupRetainedLimit);
  if(setBackupContent('#backup-retained',JSON.stringify(visibleRetained),visibleRetained.map(r=>`<div class="retained-row"><span>${escapeHTML(r.label||'未命名保留副本')}${r.slot?` · 槽位 ${r.slot}`:''}<br>移出 ${fmtTime(r.time)} · ${(r.bytes/1024).toFixed(1)} KiB · ${escapeHTML(r.file.slice(0,8))}${r.metadata_error?`<br>${escapeHTML(r.metadata_error)}`:''}</span><button class="secondary" data-rejoin="${escapeHTML(r.file)}">校验并重新加入</button></div>`).join('')||'<p>暂无移出的备份。</p>'))changed.push($('#backup-retained'));
  $('#backup-retained-more').hidden=retained.length<=backupRetainedLimit;
  $('#backup-retained-more').textContent=`显示更多保留副本（${Math.min(backupRetainedLimit,retained.length)} / ${retained.length}）`;
  const buttons=selector=>changed.flatMap(holder=>[...holder.querySelectorAll(selector)]);
  buttons('[data-rejoin]').forEach(b=>b.addEventListener('click',()=>action(async()=>{await post('/api/backups',{action:'rejoin',file:b.dataset.rejoin,context});await loadBackups();toast(backupState?.notice||'已重新加入');})));
  const undo=(backupState?.undo||[]).filter(r=>r.slot===slot);
  if(setBackupContent('#backup-undo',JSON.stringify(undo),undo.map(r=>`<article class="panel"><h3>可撤回上次回档 · ${fmtTime(r.time)}</h3>${backupSummary(r.before)}<button class="secondary" data-undo="${r.id}">撤回上次回档</button></article>`).join('')))changed.push($('#backup-undo'));
  const find=id=>own.find(r=>r.id===id)||[...grouped.values()].find(r=>r.backup.id===id)?.backup;
  buttons('[data-restore]').forEach(b=>b.addEventListener('click',()=>action(()=>openRestore(find(b.dataset.restore),context))));
  buttons('[data-manage]').forEach(b=>b.addEventListener('click',()=>openManage(find(b.dataset.manage),context)));
  buttons('[data-export]').forEach(b=>b.addEventListener('click',()=>action(async()=>{
    const r=find(b.dataset.export),response=await fetch('/api/backups/export?'+new URLSearchParams({slot:r.slot,id:r.id,context}));
    if(!response.ok)throw new Error((await response.json()).error);
    const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');
    link.href=url;link.download=`灯火-槽位${r.slot}-${r.label||r.id.slice(0,12)}.zip`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  })));
  buttons('[data-remove]').forEach(b=>b.addEventListener('click',()=>openConfirm(find(b.dataset.remove),'remove',context)));
  buttons('[data-undo]').forEach(b=>b.addEventListener('click',()=>action(()=>openRestore(backupState.undo.find(r=>r.id===b.dataset.undo),context,'undo'))));
  const currentFocus=document.activeElement;
  if(keepFocusVisible&&focusHolder.contains(currentFocus)&&currentFocus.dataset[focusAction[0]]===focusAction[1]){
    const rect=currentFocus.getBoundingClientRect();
    if(rect.top<0||rect.bottom>window.innerHeight)currentFocus.scrollIntoView({block:'center',inline:'nearest'});
  }
}
async function openRestore(row,context,operation='restore'){
  const request=++restorePreview;
  const endpoint=operation==='undo'?'undo-preview':'preview';
  const response=await fetch('/api/backups/'+endpoint+'?'+new URLSearchParams({slot:row.slot,id:row.id,context})),preview=await response.json();
  if(!response.ok)throw new Error(preview.error);
  if(context!==state?.backup_context||preview.context!==context)throw new Error('存档连接已变化，请重新选择备份并预览');
  if(request!==restorePreview)return;
  openConfirm({...row,expected_current:preview.expected_current},operation,preview.context);
  const targetTitle=operation==='undo'?'撤回后回到的进度':'将恢复的进度';
  const target=operation==='undo'&&preview.original_existed===false?'<p>回档前槽位为空；撤回后当前进度会完整保留，活动槽位将恢复为空。</p>':backupSummary(preview.target);
  $('#restore-description').innerHTML=`<div class="restore-comparison"><section><h3>现在的进度</h3>${backupSummary(preview.current)}</section><section><h3>${targetTitle}</h3>${target}</section></div><p>${preview.same_run?'种子和职业一致，请核对是否同一局冒险。':'不同冒险或无法确认是否同一局，请核对目标。'}${row.version<850?` 此旧档当前${escapeHTML(state?.catalog_version||'参考游戏')}无法继续。`:''}</p>`;
}
function openConfirm(row, operation,context){
  if(context!==state?.backup_context){toast('存档连接已变化，请重新选择备份。',true);return;}
  restorePreview++;restoreTarget={...row,operation,context};
  $('#restore-repreview').hidden=!['restore','undo'].includes(operation);
  const phrase={restore:'恢复槽位',undo:'撤回槽位',remove:'移出备份'}[operation];
  $('#restore-title').textContent={restore:'恢复前，核对这份进度',undo:'撤回上次回档',remove:'移出活动备份库'}[operation];
  $('#restore-description').innerHTML=operation==='undo'?`<h3>撤回后回到</h3>${backupSummary(row.before)}<p>当前进度会另行完整保留。请先完全退出游戏。</p>`:operation==='remove'?`${backupSummary(row)}<p>文件会移到本机备份保留目录；可重新导入。此操作可释放活动备份库容量。</p>`:backupSummary(row);
  $('#restore-confirm').checked=false;$('#restore-error').hidden=true;
  $('#restore-submit').disabled=false;
  $('#restore-warning').textContent=operation==='remove'?'只移出所选备份，不改动当前游戏进度；保留副本可在下方重新加入。':operation==='undo'?'请先完全退出游戏。撤回前的当前进度也会完整保留；保存发生变化时需要重新预览。':'请先完全退出游戏。当前槽位会完整保留，再换成选中的备份；保存发生变化时需要重新预览。';
  $('#close-restore').setAttribute('aria-label',{restore:'取消恢复',undo:'取消撤回',remove:'取消移出'}[operation]);
  $('#restore-directory').textContent='存档目录：'+(backupState?.save_root||state.settings.save_root);
  $('#restore-phrase').textContent=`我确认${phrase} ${row.slot}，并已核对上方进度${operation==='remove'?'':'、完全退出游戏'}。`;
  $('#restore-submit').textContent={restore:'确认恢复',undo:'确认撤回',remove:'确认移出'}[operation];
  $('#restore-dialog').showModal();
}
function backupMetadataKey(record){return JSON.stringify([record.save_root,record.slot,record.id]);}
function backupMetadataRaw(){return {label:$('#backup-label').value,locked:$('#backup-locked').checked};}
function sameBackupMetadata(a,b){return a?.label===b?.label&&a?.locked===b?.locked;}
function rememberBackupMetadataDraft(){
  if(!manageTarget)return;
  const raw=backupMetadataRaw(),key=backupMetadataKey(manageTarget);
  if(sameBackupMetadata(raw,manageTarget.baseline))backupMetadataDrafts.delete(key);
  else backupMetadataDrafts.set(key,{format:1,id:manageTarget.id,slot:manageTarget.slot,save_root:manageTarget.save_root,
    expected_metadata_revision:manageTarget.expected_metadata_revision,baseline:{...manageTarget.baseline},raw});
}
function captureBackupMetadataDrafts(){rememberBackupMetadataDraft();return Array.from(backupMetadataDrafts.values(),record=>({...record,raw:{...record.raw},baseline:{...record.baseline}}));}
function backupMetadataDraftLabel(){return captureBackupMetadataDrafts().length?'备份名称 / 固定标记':'';}
function checkedBackupMetadataDrafts(records){
  if(!Array.isArray(records)||records.length>200)throw new Error('备份编辑草稿数量不正确；原副本仍保留。');
  const keys=new Set();
  for(const record of records){
    if(!record||record.format!==1||Object.keys(record).some(key=>!['format','id','slot','save_root','expected_metadata_revision','baseline','raw'].includes(key))||typeof record.id!=='string'||! /^[a-f0-9]{64}$/.test(record.id)||!Number.isInteger(record.slot)||record.slot<1||record.slot>6||typeof record.save_root!=='string'||record.save_root.length>16384||/[\u0000-\u001f]/.test(record.save_root)||typeof record.expected_metadata_revision!=='string'||! /^[a-f0-9]{64}$/.test(record.expected_metadata_revision))throw new Error('备份编辑草稿身份或版本不正确；原副本仍保留。');
    for(const value of [record.baseline,record.raw])if(!value||Object.keys(value).length!==2||typeof value.label!=='string'||value.label.length>80||/[\u0000-\u001f]/.test(value.label)||typeof value.locked!=='boolean')throw new Error('备份名称或固定标记草稿格式不正确；原副本仍保留。');
    const key=backupMetadataKey(record);if(keys.has(key))throw new Error('备份编辑草稿包含重复记录；原副本仍保留。');keys.add(key);
    const existing=backupMetadataDrafts.get(key);if(existing&&JSON.stringify(existing)!==JSON.stringify(record))throw new Error('当前已有这份备份的不同编辑；双方均保留，请先保存当前草稿。');
  }
  return records;
}
function restoreBackupMetadataDrafts(records){
  checkedBackupMetadataDrafts(records);
  for(const record of records)backupMetadataDrafts.set(backupMetadataKey(record),{...record,raw:{...record.raw},baseline:{...record.baseline}});
  renderBackupMetadataDrafts();
}
function renderBackupMetadataDrafts(){
  const holder=$('#backup-metadata-drafts');if(!holder)return;
  const rows=Array.from(backupMetadataDrafts.values());
  const html=rows.length?`<h3>未保存的备份编辑 · ${rows.length} 份</h3><p>关闭弹窗会保留编辑；退出时可保存为会话草稿副本。载入后请重新核对目录和备份。</p>`+rows.map((row,index)=>`<div class="retained-row"><span>槽位 ${row.slot} · ${escapeHTML(row.raw.label||'未命名进度')} · ${row.raw.locked?'固定保留':'未固定'}<br>${escapeHTML(row.save_root)} · ${row.id.slice(0,12)}</span><button type="button" class="secondary" data-metadata-resume="${index}">继续编辑</button></div>`).join(''):'';
  const revision=JSON.stringify(rows);
  if(holder.dataset.revision===revision)return;holder.dataset.revision=revision;holder.innerHTML=html;holder.hidden=!rows.length;
  holder.querySelectorAll('[data-metadata-resume]').forEach(button=>button.addEventListener('click',()=>action(()=>resumeBackupMetadataDraft(rows[Number(button.dataset.metadataResume)]))));
}
function showManageTarget(target){
  manageTarget=target;manageEditRevision++;$('#manage-latest')?.remove();$('#manage-error').hidden=true;
  $('#manage-form').dataset.id=target.id;$('#manage-form').dataset.slot=target.slot;$('#manage-form').dataset.context=target.context||'';
  $('#backup-label').value=target.raw.label;$('#backup-locked').checked=target.raw.locked;
  $('#manage-directory').textContent=`槽位 ${target.slot} · 备份 ${target.id.slice(0,12)} · 原目录：${target.save_root}`;
  $('#manage-submit').disabled=!target.context;$('#manage-dialog').showModal();
}
function openManage(row,context){
  if(context!==state?.backup_context){toast('存档连接已变化，请重新选择备份。',true);return;}
  rememberBackupMetadataDraft();
  const target={id:row.id,slot:row.slot,save_root:backupState?.save_root||state.settings.save_root,context,
    expected_metadata_revision:row.metadata_revision,baseline:{label:row.label||'',locked:!!row.locked},raw:{label:row.label||'',locked:!!row.locked}};
  const previous=backupMetadataDrafts.get(backupMetadataKey(target));
  showManageTarget(previous?{...previous,context}:target);renderBackupMetadataDrafts();
}
async function resumeBackupMetadataDraft(record){
  rememberBackupMetadataDraft();const generation=manageEditRevision,context=state?.backup_context;
  if(!context)throw new Error('请先恢复连接；备份编辑仍保留。');
  const response=await fetch('/api/backups?'+new URLSearchParams({context})),latest=await response.json();
  if(!response.ok)throw new Error(latest.error||'备份暂时无法读取');
  if(context!==state?.backup_context||latest.context!==context||generation!==manageEditRevision)throw new Error('读取期间连接或编辑有变化；草稿仍保留，请重试。');
  const row=latest.history.find(row=>row.id===record.id&&row.slot===record.slot);
  if(!row)throw new Error('当前目录没有这份备份；请切换至原目录，或先导入对应备份。原始编辑仍保留。');
  const matched=latest.save_root===record.save_root;
  showManageTarget({...record,context:matched?context:null});
  if(!matched)showBackupMetadataRebind(manageTarget,latest,row);else if(row.metadata_revision!==record.expected_metadata_revision)await showLatestBackupMetadata(manageTarget);
}
function showBackupMetadataRebind(target,latest,row){
  const panel=document.createElement('section');panel.id='manage-latest';panel.className='support-step';
  const info=document.createElement('p');info.textContent=`草稿来自不同目录或搬机副本，尚未关联。当前目录：${latest.save_root}；槽位 ${row.slot}；同一备份 ${row.id.slice(0,12)}；当前名称：${row.label||'未命名进度'}；固定保留：${row.locked?'已开启':'未开启'}。请核对后再关联。`;panel.append(info);
  const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='已确认是这份备份，将编辑关联到当前目录';
  button.addEventListener('click',()=>{
    if(manageTarget!==target||latest.context!==state?.backup_context)return;
    rememberBackupMetadataDraft();const raw=backupMetadataRaw(),next={...target,context:latest.context,save_root:latest.save_root,expected_metadata_revision:row.metadata_revision,baseline:{label:row.label||'',locked:!!row.locked},raw};
    const existing=backupMetadataDrafts.get(backupMetadataKey(next));if(existing&&!sameBackupMetadata(existing.raw,raw)){toast('当前目录已有不同编辑；双方均保留，请先处理该草稿。',true);return;}
    backupMetadataDrafts.delete(backupMetadataKey(target));manageTarget=next;manageEditRevision++;rememberBackupMetadataDraft();renderBackupMetadataDrafts();panel.remove();$('#manage-submit').disabled=false;
    $('#manage-directory').textContent=`槽位 ${next.slot} · 备份 ${next.id.slice(0,12)} · 已关联目录：${next.save_root}`;toast('已关联，尚未保存；请核对后点击保存。');
  });panel.append(button);$('#manage-form').append(panel);
}
async function showLatestBackupMetadata(target){
  const response=await fetch('/api/backups?'+new URLSearchParams({context:target.context}));
  const latest=await response.json();if(!response.ok)throw new Error(latest.error||'最新备份信息暂不可读');
  if(manageTarget!==target||latest.context!==target.context||state?.backup_context!==target.context)return;
  const row=latest.history.find(row=>row.id===target.id&&row.slot===target.slot);
  $('#manage-latest')?.remove();const panel=document.createElement('section');panel.id='manage-latest';panel.className='support-step';
  const info=document.createElement('p');info.textContent=row?`最新名称：${row.label||'未命名进度'}；永久保留：${row.locked?'已开启':'未开启'}。上方仍是你原来的编辑，请对照核对。`:'这份备份已不在当前活动历史。编辑仍保留；请核对空间清单。';panel.append(info);
  if(row){const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='已核对最新信息，保留上方编辑并重新确认';
    button.addEventListener('click',()=>{if(manageTarget!==target||state?.backup_context!==target.context)return;manageTarget={...target,expected_metadata_revision:row.metadata_revision,baseline:{label:row.label||'',locked:!!row.locked}};manageEditRevision++;rememberBackupMetadataDraft();renderBackupMetadataDrafts();panel.remove();$('#manage-error').hidden=true;toast('最新信息已核对；尚未保存，请点击保存。');});panel.append(button);}
  $('#manage-form').append(panel);
}
function initializeBackups(){
  $('#repair-history').addEventListener('click',async()=>{
    const context=backupState?.context;if(!context||context!==state?.backup_context)return;
    const target=historyRepairTarget={context};
    $('#history-repair-submit').disabled=true;$('#history-repair-confirm').checked=false;
    $('#history-repair-error').hidden=true;$('#history-repair-preview').textContent='正在逐份校验备份…';
    $('#history-repair-dialog').showModal();
    try{
      const result=await post('/api/backups',{action:'repair_history_preview',context});
      if(historyRepairTarget!==target||context!==state?.backup_context)return;
      const preview=result.preview;target.expected=preview.expected;
      $('#history-repair-preview').innerHTML=`<p>已校验 ${preview.valid_archives} 份有效备份，将恢复 ${preview.records_count} 条历史记录。${escapeHTML(preview.message)}</p>`+
        (preview.unavailable.length?'<p>以下原件会保留，无法作为有效备份恢复：</p><ul>'+preview.unavailable.map(row=>`<li>${escapeHTML(row.file)}：${escapeHTML(row.error)}</li>`).join('')+'</ul>':'<p>本次检查未发现不可用ZIP。</p>');
      $('#history-repair-submit').disabled=false;
    }catch(error){if(historyRepairTarget===target){$('#history-repair-error').hidden=false;$('#history-repair-error').textContent=error.message;}}
  });
  $('#close-history-repair').addEventListener('click',()=>{historyRepairTarget=null;$('#history-repair-dialog').close();});
  $('#history-repair-dialog').addEventListener('cancel',()=>{historyRepairTarget=null;});
  $('#history-repair-form').addEventListener('submit',async event=>{
    event.preventDefault();const target=historyRepairTarget;if(!target?.expected)return;
    const button=$('#history-repair-submit');button.disabled=true;$('#history-repair-error').hidden=true;
    try{
      if(!$('#history-repair-confirm').checked)throw new Error('请先确认保留原件并将恢复记录全部固定');
      const result=await post('/api/backups',{action:'repair_history',context:target.context,expected:target.expected,confirm:'恢复备份历史'});
      if(historyRepairTarget!==target)return;
      historyRepairTarget=null;$('#history-repair-dialog').close();await poll();await loadBackups();
      toast('备份历史已恢复；原记录已保留，恢复的备份默认全部固定。');
    }catch(error){if(historyRepairTarget===target){$('#history-repair-error').hidden=false;$('#history-repair-error').textContent=error.message;}}
    finally{if(historyRepairTarget===target)button.disabled=false;}
  });
  $('#backup-slot').addEventListener('change',()=>{backupHistoryLimit=20;renderBackups();});
  for(const id of ['#backup-search','#backup-filter'])$(id).addEventListener('input',()=>{backupHistoryLimit=20;renderBackups();});
  $('#backup-more').addEventListener('click',()=>{backupHistoryLimit+=20;renderBackups();});
  $('#backup-retained-more').addEventListener('click',()=>{backupRetainedLimit+=20;renderBackups();});
  $('#backup-enabled').addEventListener('change',()=>action(async()=>{try{await post('/api/backups',{action:'enable',enabled:$('#backup-enabled').checked});await loadBackups();}catch(error){$('#backup-enabled').checked=!!backupState?.enabled;throw error;}}));
  $('#capture-backup').addEventListener('click',()=>action(async()=>{await post('/api/backups',{action:'capture'});await loadBackups();toast('已备份当前磁盘存档');}));
  $('#validate-backups').addEventListener('click',()=>action(async()=>{await post('/api/backups',{action:'validate',context:backupState?.context});await loadBackups();toast(backupState?.notice||'检查完成');}));
  $('#repair-timeline').addEventListener('click',()=>{
    const context=backupState?.context;if(!context||context!==state?.backup_context)return;
    repairTarget={context};$('#repair-submit').disabled=false;
    $('#repair-form').dataset.context=context;$('#repair-confirm').checked=false;$('#repair-error').hidden=true;$('#repair-dialog').showModal();
  });
  $('#close-repair').addEventListener('click',()=>{repairTarget=null;$('#repair-dialog').close();});
  $('#repair-dialog').addEventListener('cancel',()=>{repairTarget=null;});
  $('#repair-form').addEventListener('submit',event=>{
    event.preventDefault();const target=repairTarget;if(!target)return;const context=target.context;
    (async()=>{const button=$('#repair-submit');button.disabled=true;$('#repair-error').hidden=true;
      try{if(!$('#repair-confirm').checked)throw new Error('请先确认保留原记录并校验恢复');
        await post('/api/backups',{action:'repair_timeline',context,confirm:'恢复时间记录'});
        if(repairTarget!==target)return;
        $('#repair-dialog').close();repairTarget=null;await poll();await loadBackups();toast(backupState?.notice||'时间记录已恢复，旧时间节点将重新积累');
      }catch(error){if(repairTarget===target){$('#repair-error').hidden=false;$('#repair-error').textContent=error.message;}}finally{if(repairTarget===target||repairTarget===null)button.disabled=false;}
    })();
  });
  $('#import-backup').addEventListener('change',()=>action(async()=>{
    const input=$('#import-backup'),file=input.files[0],context=backupState?.context;if(!file)return;
    const ticket=backupFlowTicket();
    try{if(!context)throw new Error('请等待存档历史连接后再导入');if(file.size>64*1048576)throw new Error('备份需要小于64 MiB');const response=await fetch('/api/backups/import',{method:'POST',headers:{'Content-Type':'application/zip','X-Companion-Token':token,'X-Companion-Backup-Context':context},body:file});const result=await response.json();if(!response.ok)throw new Error(result.error);recordBackupReceipt('single-import',ticket,{results:[{...result,file:file.name,ok:true}],success_count:1,failure_count:0,restored:false},{file_name:file.name},!backupFlowCurrent(ticket)||input.files[0]!==file);await refreshBackupReceiptScope(ticket);toast('导入完成；请选择对应槽位预览，尚未恢复游戏存档');}finally{if(input.files[0]===file)input.value='';}
  }));
  $('#restore-repreview').addEventListener('click',()=>{const target=restoreTarget;if(['restore','undo'].includes(target?.operation))action(()=>openRestore(target,target.context,target.operation));});
  $('#close-restore').addEventListener('click',()=>{$('#restore-dialog').close();restoreTarget=null;restorePreview++;});
  $('#restore-dialog').addEventListener('cancel',()=>{restoreTarget=null;restorePreview++;});
  $('#restore-form').addEventListener('submit',event=>{
    event.preventDefault();if(!restoreTarget)return;const target=restoreTarget;
    (async()=>{const button=$('#restore-submit');button.disabled=true;$('#restore-error').hidden=true;try{
      if(!$('#restore-confirm').checked)throw new Error('请先勾选目标槽位确认');
      const phrase={restore:'恢复槽位',undo:'撤回槽位',remove:'移出备份'}[target.operation];
      await post('/api/backups',{action:target.operation,slot:target.slot,id:target.id,context:target.context,expected_current:target.expected_current,confirm:`${phrase} ${target.slot}`});
      if(restoreTarget!==target)return;
      $('#restore-dialog').close();restoreTarget=null;await loadBackups();toast(backupState.notice);
    }catch(error){if(restoreTarget===target){$('#restore-confirm').checked=false;$('#restore-error').hidden=false;$('#restore-error').textContent=error.message+'。操作未完成，请核对后重试。';}}finally{if(restoreTarget===target||restoreTarget===null)button.disabled=false;}})();
  });
  const closeManage=()=>{rememberBackupMetadataDraft();manageTarget=null;manageEditRevision++;renderBackupMetadataDrafts();};
  $('#close-manage').addEventListener('click',()=>{closeManage();$('#manage-dialog').close();});
  $('#manage-dialog').addEventListener('cancel',closeManage);
  for(const id of ['#backup-label','#backup-locked'])$(id).addEventListener('input',()=>{manageEditRevision++;rememberBackupMetadataDraft();renderBackupMetadataDrafts();});
  $('#manage-form').addEventListener('submit',event=>{
    event.preventDefault();const target=manageTarget;if(!target)return;
    if(!target.context||target.context!==state?.backup_context){$('#manage-error').hidden=false;$('#manage-error').textContent='连接已变化；编辑仍保留，请从未保存编辑中重新核对。';return;}
    rememberBackupMetadataDraft();const raw=backupMetadataRaw(),generation=manageEditRevision,key=backupMetadataKey(target);
    const payload={action:'manage',id:target.id,slot:target.slot,context:target.context,expected_metadata_revision:target.expected_metadata_revision,...raw};
    $('#manage-submit').disabled=true;
    (async()=>{try{const result=await post('/api/backups',payload),saved=result.metadata;
      if(!saved||saved.id!==target.id||saved.slot!==target.slot||typeof saved.label!=='string'||typeof saved.locked!=='boolean'||! /^[a-f0-9]{64}$/.test(saved.metadata_revision)||result.context!==target.context||result.save_root!==target.save_root)throw new Error('保存回执无法核对；编辑仍保留，请读取最新信息。');
      const pending=backupMetadataDrafts.get(key);
      if(pending&&pending.expected_metadata_revision===target.expected_metadata_revision){
        const baseline={label:saved.label,locked:saved.locked};
        if(sameBackupMetadata(pending.raw,raw)||sameBackupMetadata(pending.raw,baseline))backupMetadataDrafts.delete(key);
        else backupMetadataDrafts.set(key,{...pending,baseline,expected_metadata_revision:saved.metadata_revision});
      }
      if(manageTarget!==target){renderBackupMetadataDrafts();return;}
      manageTarget={...target,baseline:{label:saved.label,locked:saved.locked},expected_metadata_revision:saved.metadata_revision};
      if(generation===manageEditRevision&&sameBackupMetadata(backupMetadataRaw(),raw)){
        $('#backup-label').value=saved.label;$('#backup-locked').checked=saved.locked;rememberBackupMetadataDraft();manageTarget=null;$('#manage-dialog').close();toast('已保存备份名称与保留设置');
      }else{rememberBackupMetadataDraft();$('#manage-error').hidden=false;$('#manage-error').textContent='本次提交已保存；之后的新编辑仍未保存。';}
      renderBackupMetadataDrafts();await loadBackups();
    }catch(error){if(manageTarget===target){$('#manage-error').hidden=false;$('#manage-error').textContent=error.message+'。原编辑保留；请先核对最新名称与保护状态。';try{await showLatestBackupMetadata(target);}catch(readError){if(manageTarget===target)$('#manage-error').textContent+=' 最新信息读取失败：'+readError.message;}}}
    finally{if(manageTarget?.context===state?.backup_context)$('#manage-submit').disabled=false;}})();
  });
}
