'use strict';
let backupState, backupLoading=false, restoreTarget=null, backupHistoryLimit=20,backupRetainedLimit=20;
const nodeLabel=seconds=>seconds>=60?`${seconds/60} 分钟前`:`${seconds} 秒前`;
const classNames={WARRIOR:'战士',MAGE:'法师',ROGUE:'盗贼',HUNTRESS:'女猎手',DUELIST:'决斗家',CLERIC:'牧师'};
const healthNames={paused:'自动备份已暂停',blocked:'自动备份受阻',waiting:'等待新的游戏保存',protected:'最近保存已备份'};
const ageLabel=seconds=>seconds<60?`${Math.floor(Math.max(0,seconds))}秒`:seconds<3600?`${Math.floor(seconds/60)}分钟`:seconds<86400?`${Math.floor(seconds/3600)}小时${Math.floor(seconds%3600/60)}分钟`:`${Math.floor(seconds/86400)}天`;
function renderBackupHealth(){
  const h=state?.backup_health, el=$('#backup-health');
  el.className='connection-banner'+(h?.state==='blocked'?' error':'');
  el.textContent=h?`${h.slot?`槽位 ${h.slot}：`:''}${healthNames[h.state] || '正在检查备份'}${h.saved?` · 游戏保存距今 ${ageLabel(Date.now()/1000-h.saved)}`:''}${h.last_success?` · 最近检查成功 ${shortTime(h.last_success)}`:''}${h.error?` · ${h.error}`:''}${h.other_errors?` · 其他槽位：${h.other_errors}`:''}`:'自动备份状态尚未确认';
}
function backupSummary(row){
  if(!row || row.empty)return '<p>当前槽位没有可读取的完整进度</p>';
  const items=(row.equipment||[]).map(i=>`${escapeHTML(i.location)}：${escapeHTML(i.name)} ${escapeHTML((i.details||[]).join(' · '))}`).join('<br>');
  return `<p><strong>${escapeHTML(classNames[row.class]||row.class)} Lv.${escapeHTML(row.level??'未知')} · 第 ${escapeHTML(row.depth)} 层${row.branch?'（支线）':''}</strong><br>生命 ${escapeHTML(row.hp??'未知')}/${escapeHTML(row.ht??'未知')} · 金币 ${escapeHTML(row.gold??'未知')} · 基础力量 ${escapeHTML(row.strength??'未知')}${row.duration!=null?`<br>本局行动时间 ${escapeHTML(row.duration)} 回合`:''}<br>游戏保存 ${fmtTime(row.saved)}${items?`<br>${items}`:''}</p>`;
}
async function loadBackups(){
  if(backupLoading)return;backupLoading=true;
  try{
    const response=await fetch('/api/backups');if(!response.ok)throw new Error('备份状态暂时无法读取');
    backupState=await response.json();$('#backup-enabled').checked=backupState.enabled;
    $('#backup-status').textContent=`${healthNames[backupState.health]||'正在检查'}。${backupState.error||''} ${backupState.notice||''}`;
    $('#backup-storage').textContent=`活动备份 ${(backupState.storage_bytes/1048576).toFixed(2)} / ${(backupState.storage_limit/1048576).toFixed(0)} MiB · ${backupState.history.length} 份不同进度。达到上限会停止新增，固定的记录不能移出。`;
    const sizes=backupState.storage_breakdown;
    if(sizes)$('#backup-storage').textContent+=` 总占用 ${(sizes.total/1048576).toFixed(2)} MiB（活动库含索引 ${(sizes.active/1048576).toFixed(2)}、移出副本 ${(sizes.retained/1048576).toFixed(2)}、损坏隔离 ${(sizes.quarantine/1048576).toFixed(2)}、本存档目录回档前副本 ${(sizes.before_restore/1048576).toFixed(2)}）。保留副本不会自动删除。`;
    const selected=$('#backup-slot').value;
    $('#backup-slot').innerHTML=backupState.slots.map(row=>`<option value="${row.slot}">槽位 ${row.slot}</option>`).join('');
    if(!backupState.slots.length){const slot=state?.active_slot||1;$('#backup-slot').innerHTML=`<option value="${slot}">槽位 ${slot}（暂无活动备份）</option>`;$('#backup-slot').value=String(slot);}
    if(backupState.slots.some(row=>String(row.slot)===selected))$('#backup-slot').value=selected;
    renderBackups();
  }catch(error){$('#backup-status').textContent=error.message;$('#backup-nodes').textContent='备份信息不可用，请恢复连接后重试。';}
  finally{backupLoading=false;}
}
function backupCard(row, labels='', mode='history'){
  const invalid=row.integrity?.valid===false;
  const tags=Array.isArray(labels)?`<div class="node-tags">${labels.map(label=>`<span>${escapeHTML(label)}</span>`).join('')}</div>`:'';
  return `<article class="panel backup-card"><span class="tiny-label">${escapeHTML(row.label||'未命名进度')}${row.locked?' · 已固定':''}</span>${tags}<p class="restore-age">将回到 ${ageLabel(Date.now()/1000-row.saved)}前保存的进度</p>${backupSummary(row)}<p class="muted">${mode==='history'?'最近观察':'观察时间'} ${fmtTime(mode==='history'?row.last_seen:row.time)}<br>版本码 ${escapeHTML(row.version??'未知')}${row.version<850?' · 当前4.0.1不能继续此旧档':''}${invalid?`<br>不可用：${escapeHTML(row.integrity.error)}`:''}</p><div class="backup-actions"><button class="secondary" data-restore="${row.id}" ${invalid?'disabled':''}>预览并恢复</button><button class="quiet" data-manage="${row.id}">命名 / 固定</button><button class="quiet" data-export="${row.id}" ${invalid?'disabled':''}>导出</button><button class="quiet" data-remove="${row.id}" ${row.locked?'disabled':''}>移出</button></div></article>`;
}
function renderBackups(){
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
  $('#backup-nodes').innerHTML=grouped.size?[...grouped.values()].map(r=>backupCard(r.backup,r.labels,'node')).join(''):'<p class="no-results">尚无时间节点；请在游戏中保存，让助手积累记录。</p>';
  const missing=(row?.nodes||[3600,1800,600,300,120,60,50,40,30,20,10].map(seconds=>({seconds,backup:null}))).filter(n=>!n.backup).map(n=>nodeLabel(n.seconds));
  $('#backup-node-gaps').textContent=missing.length?`尚未积累：${missing.join('、')}。节点按助手观察时间选择；卡片突出真正可恢复的游戏保存时间。`:'节点按助手观察时间选择；同一份游戏保存只显示一张卡片，无法回到尚未保存的画面。';
  const own=backupState?.history.filter(r=>r.slot===slot)||[];
  const terms=$('#backup-search').value.toLowerCase().split(/\s+/).filter(Boolean),filter=$('#backup-filter').value;
  const filtered=own.filter(r=>(filter!=='locked'||r.locked)&&(filter!=='named'||r.label)&&terms.every(term=>`${r.label} ${classNames[r.class]||r.class} 第${r.depth}层 ${fmtTime(r.saved)} ${fmtTime(r.time)} ${fmtTime(r.last_seen)}`.toLowerCase().includes(term)));
  let lastGroup='';
  $('#backup-history').innerHTML=filtered.length?filtered.slice(0,backupHistoryLimit).map(r=>{
    const group=fmtTime(r.time).split(' ')[0]+' · '+(classNames[r.class]||r.class),heading=group!==lastGroup?`<h3 class="history-group">${escapeHTML(group)} · 记录时段</h3>`:'';lastGroup=group;
    return heading+backupCard(r);
  }).join(''):'<p>没有符合筛选的记录；试试其他名称或取消筛选。</p>';
  $('#backup-history-count').textContent=`槽位 ${slot}：${filtered.length} / ${own.length} 份进度。重开同一种子、同职业时请按保存时间与行动进度核对。`;
  $('#backup-more').hidden=filtered.length<=backupHistoryLimit;
  $('#backup-more').textContent=`显示更多历史（已显示 ${Math.min(backupHistoryLimit,filtered.length)} / ${filtered.length}）`;
  const retained=backupState?.retained||[];
  $('#backup-retained').innerHTML=retained.slice(0,backupRetainedLimit).map(r=>`<div class="retained-row"><span>${escapeHTML(r.label||'未命名保留副本')}${r.slot?` · 槽位 ${r.slot}`:''}<br>移出 ${fmtTime(r.time)} · ${(r.bytes/1024).toFixed(1)} KiB · ${escapeHTML(r.file.slice(0,8))}${r.metadata_error?`<br>${escapeHTML(r.metadata_error)}`:''}</span><button class="secondary" data-rejoin="${escapeHTML(r.file)}">校验并重新加入</button></div>`).join('')||'<p>暂无移出的备份。</p>';
  $('#backup-retained-more').hidden=retained.length<=backupRetainedLimit;
  $('#backup-retained-more').textContent=`显示更多保留副本（${Math.min(backupRetainedLimit,retained.length)} / ${retained.length}）`;
  $$('[data-rejoin]').forEach(b=>b.addEventListener('click',()=>action(async()=>{await post('/api/backups',{action:'rejoin',file:b.dataset.rejoin});await loadBackups();toast(backupState.notice);})));
  $('#backup-undo').innerHTML=(backupState?.undo||[]).filter(r=>r.slot===slot).map(r=>`<article class="panel"><h3>可撤回上次回档 · ${fmtTime(r.time)}</h3>${backupSummary(r.before)}<button class="secondary" data-undo="${r.id}">撤回上次回档</button></article>`).join('');
  const find=id=>own.find(r=>r.id===id)||[...grouped.values()].find(r=>r.backup.id===id)?.backup;
  $$('[data-restore]').forEach(b=>b.addEventListener('click',()=>action(()=>openRestore(find(b.dataset.restore)))));
  $$('[data-manage]').forEach(b=>b.addEventListener('click',()=>openManage(find(b.dataset.manage))));
  $$('[data-export]').forEach(b=>b.addEventListener('click',()=>action(async()=>{
    const r=find(b.dataset.export),response=await fetch(`/api/backups/export?slot=${r.slot}&id=${r.id}`);
    if(!response.ok)throw new Error((await response.json()).error);
    const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');
    link.href=url;link.download=`灯火-槽位${r.slot}-${r.label||r.id.slice(0,12)}.zip`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  })));
  $$('[data-remove]').forEach(b=>b.addEventListener('click',()=>openConfirm(find(b.dataset.remove),'remove')));
  $$('[data-undo]').forEach(b=>b.addEventListener('click',()=>openConfirm(backupState.undo.find(r=>r.id===b.dataset.undo),'undo')));
}
async function openRestore(row){
  const response=await fetch(`/api/backups/preview?slot=${row.slot}&id=${row.id}`),preview=await response.json();
  if(!response.ok)throw new Error(preview.error);
  openConfirm(row,'restore');
  $('#restore-description').innerHTML=`<div class="restore-comparison"><section><h3>现在的进度</h3>${backupSummary(preview.current)}</section><section><h3>将恢复的进度</h3>${backupSummary(preview.target)}</section></div><p>${preview.same_run?'种子和职业一致，请核对是否同一局冒险。':'不同冒险或无法确认是否同一局，请核对目标。'}${row.version<850?' 此旧档当前4.0.1无法继续。':''}</p>`;
}
function openConfirm(row, operation){
  restoreTarget={...row,operation};
  const phrase={restore:'恢复槽位',undo:'撤回槽位',remove:'移出备份'}[operation];
  $('#restore-title').textContent={restore:'恢复前，核对这份进度',undo:'撤回上次回档',remove:'移出活动备份库'}[operation];
  $('#restore-description').innerHTML=operation==='undo'?`<h3>撤回后回到</h3>${backupSummary(row.before)}<p>当前进度会另行完整保留。请先完全退出游戏。</p>`:operation==='remove'?`${backupSummary(row)}<p>文件会移到本机备份保留目录；可重新导入。此操作可释放活动备份库容量。</p>`:backupSummary(row);
  $('#restore-confirm').checked=false;$('#restore-error').hidden=true;
  $('#restore-phrase').textContent=`我确认${phrase} ${row.slot}，并已核对上方进度${operation==='remove'?'':'、完全退出游戏'}。`;
  $('#restore-submit').textContent={restore:'确认恢复',undo:'确认撤回',remove:'确认移出'}[operation];
  $('#restore-dialog').showModal();
}
function openManage(row){
  $('#manage-error').hidden=true;
  $('#manage-form').dataset.id=row.id;$('#manage-form').dataset.slot=row.slot;
  $('#backup-label').value=row.label||'';$('#backup-locked').checked=!!row.locked;$('#manage-dialog').showModal();
}
function initializeBackups(){
  $('#backup-slot').addEventListener('change',()=>{backupHistoryLimit=20;renderBackups();});
  for(const id of ['#backup-search','#backup-filter'])$(id).addEventListener('input',()=>{backupHistoryLimit=20;renderBackups();});
  $('#backup-more').addEventListener('click',()=>{backupHistoryLimit+=20;renderBackups();});
  $('#backup-retained-more').addEventListener('click',()=>{backupRetainedLimit+=20;renderBackups();});
  $('#backup-enabled').addEventListener('change',()=>action(async()=>{try{await post('/api/backups',{action:'enable',enabled:$('#backup-enabled').checked});await loadBackups();}catch(error){$('#backup-enabled').checked=!!backupState?.enabled;throw error;}}));
  $('#capture-backup').addEventListener('click',()=>action(async()=>{await post('/api/backups',{action:'capture'});await loadBackups();toast('已备份当前磁盘存档');}));
  $('#validate-backups').addEventListener('click',()=>action(async()=>{await post('/api/backups',{action:'validate'});await loadBackups();toast(backupState.notice);}));
  $('#import-backup').addEventListener('change',()=>action(async()=>{
    const input=$('#import-backup'),file=input.files[0];if(!file)return;
    try{if(file.size>64*1048576)throw new Error('备份需要小于64 MiB');const response=await fetch('/api/backups/import',{method:'POST',headers:{'Content-Type':'application/zip','X-Companion-Token':token},body:file});const result=await response.json();if(!response.ok)throw new Error(result.error);await loadBackups();toast('导入完成；请选择对应槽位预览，尚未恢复游戏存档');}finally{input.value='';}
  }));
  $('#close-restore').addEventListener('click',()=>{$('#restore-dialog').close();restoreTarget=null;});
  $('#restore-form').addEventListener('submit',event=>{
    event.preventDefault();if(!restoreTarget)return;const target=restoreTarget;
    (async()=>{const button=$('#restore-submit');button.disabled=true;$('#restore-error').hidden=true;try{
      if(!$('#restore-confirm').checked)throw new Error('请先勾选目标槽位确认');
      const phrase={restore:'恢复槽位',undo:'撤回槽位',remove:'移出备份'}[target.operation];
      await post('/api/backups',{action:target.operation,slot:target.slot,id:target.id,confirm:`${phrase} ${target.slot}`});
      $('#restore-dialog').close();restoreTarget=null;await loadBackups();toast(backupState.notice);
    }catch(error){$('#restore-error').hidden=false;$('#restore-error').textContent=error.message+'。操作未完成，请核对后重试。';}finally{button.disabled=false;}})();
  });
  $('#close-manage').addEventListener('click',()=>$('#manage-dialog').close());
  $('#manage-form').addEventListener('submit',event=>{event.preventDefault();(async()=>{
    try{await post('/api/backups',{action:'manage',id:event.target.dataset.id,slot:Number(event.target.dataset.slot),label:$('#backup-label').value,locked:$('#backup-locked').checked});$('#manage-dialog').close();await loadBackups();toast('已保存备份名称与保留设置');}
    catch(error){$('#manage-error').hidden=false;$('#manage-error').textContent=error.message;}
  })();});
}
