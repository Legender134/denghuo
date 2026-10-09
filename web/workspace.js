'use strict';
let workspaceState=null,workspaceRequest=0,workspaceSeenRevision=null,planRequest=0,planDialogSerial=0,planDraft=null,workspaceConfirmation=null,workspaceConfirmSerial=0,manualSavedPlan=null;
let workspaceSeenContext='';
let decisionRequest=0,decisionSignature='',decisionState=null;
const planLabels={numeric:'数值计算',equipment:'装备比较',manual:'手动局势草稿',alchemy:'炼金规划',character:'共享角色条件'};
const planNameDrafts=new Map(),planNoteDrafts=new Map(),planMetaOriginals=new Map();
let workspaceDetailReturn=null,manualUnsaved=false,manualAppliedRaw=null;
function planDraftKey(payload,existing){return existing?.id||payload.kind+':'+(payload.entry||'draft');}
function planSource(stamp=calculationStamp()){
  return {mode:stamp?.mode||'example',snapshot_at:stamp?.modified||null,slot:stamp?.slot??null};
}
function originLabel(origin){
  if(!origin||origin.mode==='example')return '过去来源：示例或手填参数';
  return `过去来源：${origin.mode==='manual'?'手动局势':`槽位 ${origin.slot??'—'} 的快照`}${origin.snapshot_at?' · '+fmtTime(origin.snapshot_at):''}；固定参考，不绑定当前角色`;
}
async function getJSON(path){const response=await fetch(path),result=await response.json();if(!response.ok)throw new Error(result.error||'本地资料暂时不可用');return result;}
async function loadWorkspace(){
  const seq=++workspaceRequest,context=workspaceContextKey();
  try{const result=await getJSON('/api/workspace');if(seq!==workspaceRequest)return;workspaceState=result;workspaceSeenRevision=result.revision;workspaceSeenContext=context;renderWorkspace();}
  catch(error){if(seq!==workspaceRequest)return;inlineError($('#workspace-error'),error.message);inlineError($('#library-home-error'),error.message);}
}
function workspaceContextKey(){return JSON.stringify([state?.started,state?.revision,state?.modified,state?.settings?.mode,state?.active_slot,state?.error]);}
function lookupCalculationOptions(context){
  const params=context.params||{},fieldOrigins={};
  for(const key of ['dew_volume','vial','current_shield'])if(key in params)fieldOrigins[key]=(context.source?.mode||calculationStamp()?.mode)==='manual'?'手动局势记录':'快照记录 · '+(key==='dew_volume'?'水袋露珠量':key==='current_shield'?'公开当前护盾':'凝血试管条件');
  const stamp=context.stamp,source=context.source;
  const sourceStamp=Array.isArray(stamp)?{started:stamp[0],mode:stamp[2],slot:stamp[3],revision:stamp[4],modified:stamp[5]}:source?{...calculationStamp(),mode:source.mode,slot:source.slot,modified:source.snapshot_at}:undefined;
  return {fieldOrigins,sourceStamp};
}
function referenceList(target,rows,empty){
  const signature=JSON.stringify([rows,empty]);if(target.dataset.references===signature)return;target.dataset.references=signature;
  target.replaceChildren();if(!rows?.length){target.innerHTML=`<p class="muted">${escapeHTML(empty)}</p>`;return;}
  for(const row of rows){const button=document.createElement('button');button.className='workspace-reference';button.innerHTML=`<span><strong>${escapeHTML(row.name||row.id||row.entry)}</strong><small>${escapeHTML(row.lookup_context?.source_label||row.type_label||row.category||'资料参考')}${row.opened?' · '+escapeHTML(fmtTime(row.opened)):''}</small>${row.lookup_context?.conditions?`<small>${escapeHTML(Array.isArray(row.lookup_context.conditions)?row.lookup_context.conditions.join('；'):row.lookup_context.conditions)}</small>`:''}</span><span aria-hidden="true">→</span>`;button.addEventListener('click',()=>showReference({...row,id:row.id||row.entry},state?.catalog_version));target.append(button);}
}
function filterWorkspacePlans(plans,query='',kind='all',sort='updated'){
  query=query.trim().toLocaleLowerCase();
  const byName=(a,b)=>a.name.localeCompare(b.name,'zh-CN')||a.id.localeCompare(b.id);
  return plans.filter(plan=>(!query||(plan.name+'\n'+(plan.note||'')).toLocaleLowerCase().includes(query))&&(kind==='all'||plan.kind===kind)).sort((a,b)=>sort==='name'?byName(a,b):b.updated-a.updated||byName(a,b));
}
function renderWorkspace(){
  const ws=workspaceState;if(!ws)return;
  try{if(typeof initializeAlchemy==='function')initializeAlchemy(ws.alchemy);}catch(error){inlineError($('#alchemy-error'),'炼金表单暂时不可用：'+error.message);}
  try{if(typeof initializeCharacterScene==='function')initializeCharacterScene(ws.character_scene);}catch(error){inlineError($('#character-error'),'角色条件表单暂时不可用：'+error.message);}
  inlineError($('#workspace-error'),ws.error||'');inlineError($('#library-home-error'),ws.error||'');
  $('#workspace-repair').hidden=ws.available!==false;
  $('#workspace-status').textContent=ws.available===false?'资料查询仍可使用；收藏和方案写入暂停，原文件保留。':`${ws.plans?.length||0} 个方案 · ${ws.favorite_ids?.length||0} 项收藏。和桌面速查使用同一资料库。`;
  const emptyQuery=!$('#library-search').value.trim()&&$('#library-category').value==='全部';
  $('#library-home').hidden=!emptyQuery;$('#library-results').hidden=emptyQuery;if(emptyQuery){$('#library-more').hidden=true;$('#library-results-label').textContent='从当前已知资料、常用决策或收藏开始';}
  for(const prefix of ['library','workspace']){
    referenceList($('#'+prefix+'-favorites'),ws.favorites,'尚无收藏；在资料详情中点击收藏。');
    referenceList($('#'+prefix+'-recent'),ws.recent,'打开资料后会显示最近查看。');
  }
  referenceList($('#library-current'),ws.current,'当前没有已确认的资料上下文。可以先查常用决策或搜索。');
  referenceList($('#library-common'),ws.common,'请使用上方搜索查找资料。');
  const plans=$('#workspace-plans');plans.replaceChildren();
  const query=$('#workspace-search').value.trim().toLocaleLowerCase(),kind=$('#workspace-kind').value,sort=$('#workspace-sort').value;
  const filtered=filterWorkspacePlans(ws.plans||[],query,kind,sort);
  $('#workspace-results-status').textContent=`显示 ${filtered.length} / ${ws.plans?.length||0} 个方案；筛选不会删除记录。`;
  if(ws.plans?.length&&!filtered.length)plans.innerHTML='<p class="muted">没有匹配的方案。可修改名称或类型条件，或重置筛选。</p>';
  if(!ws.plans?.length)plans.innerHTML='<p class="muted">还没有命名方案。计算之后保存，或先填写并保存局势草稿。</p>';
  for(const plan of filtered){const row=document.createElement('article');row.className='plan-row';row.dataset.planId=plan.id;row.innerHTML=`<div><span class="tiny-label">${escapeHTML(planLabels[plan.kind])} · 规则 ${escapeHTML(plan.rules_version)}</span><h3>${escapeHTML(plan.name)}</h3><p class="muted">${escapeHTML(originLabel(plan.origin))}</p><small>更新于 ${escapeHTML(fmtTime(plan.updated))}</small>${plan.note?`<p class="user-note">用户用途 / 假设：${escapeHTML(plan.note)}</p>`:''}</div><div class="backup-actions"><button class="secondary" data-open>打开${plan.kind==='manual'?'草稿':'固定参考'}</button><button class="secondary" data-copy>另存副本</button><button class="danger-button" data-remove>删除方案</button></div>`;
    row.querySelector('[data-open]').addEventListener('click',()=>openPlan(plan.id,{trigger:true}));
    row.querySelector('[data-copy]').addEventListener('click',()=>openPlanSave({kind:plan.kind,entry:plan.entry,params:plan.params,source:cleanStoredOrigin(plan.origin),note:plan.note||''},null,plan.name+' 副本'));
    row.querySelector('[data-remove]').addEventListener('click',()=>openWorkspaceConfirmation({action:'remove',id:plan.id,expected_record_revision:plan.record_revision,confirmed:true},'删除命名方案',`确认删除「${plan.name}」？这只删除资料库中的方案，不修改游戏、已打开的参数或备份。`));plans.append(row);
  }
  renderDetailTools();
}
function cleanStoredOrigin(origin){return {mode:origin?.mode||'example',snapshot_at:origin?.snapshot_at??null,slot:origin?.slot??null,...(origin?.fields?{fields:{...origin.fields}}:{})};}
function setDetailEntry(entry){detailEntry=entry;renderDetailTools();post('/api/workspace',{action:'remember',entry}).then(()=>{if(view==='library'||view==='workspace')loadWorkspace();}).catch(error=>{if(detailEntry===entry)inlineError($('#detail-workspace-error'),error.message);});}
function renderDetailTools(){
  const target=$('#detail-tools');if(!target||!detailEntry)return;const entry=detailEntry,favorite=workspaceState?.favorite_ids?.includes(entry)||false;
  const alchemy=numericalDetail?.identity===entry?numericalDetail.result?.alchemy_recipes||[]:[];
  const signature=JSON.stringify([entry,favorite,alchemy.map(r=>r.id)]);if(target.dataset.tools===signature&&target.childElementCount)return;target.dataset.tools=signature;
  target.innerHTML=`<button class="secondary" id="detail-favorite" aria-pressed="${favorite}">${favorite?'★ 已收藏 · 点击取消':'☆ 收藏资料'}</button><button class="secondary" id="detail-save-numeric" type="button">命名保存计算</button><p id="detail-workspace-error" class="rule-warning" role="alert" hidden></p>`;
  $('#detail-favorite').addEventListener('click',async()=>{const button=$('#detail-favorite');button.disabled=true;try{await post('/api/workspace',{action:'favorite',entry,enabled:!favorite});await loadWorkspace();}catch(error){if(detailEntry===entry)inlineError($('#detail-workspace-error'),error.message);}finally{if(button.isConnected)button.disabled=false;}});
  $('#detail-save-numeric').addEventListener('click',()=>{
    const d=numericalDetail;if(!d?.inputs?.length||!d.result){inlineError($('#detail-workspace-error'),'这个条目还没有可保存的计算条件；可以先收藏资料。');return;}
    if(d.pending||d.dirty){inlineError($('#detail-workspace-error'),'请先完成重新计算，再保存此次结果的实际参数。');return;}
    openPlanSave({kind:'numeric',entry:d.identity,params:actualNumericalParams(d),source:{...(d.fixed?cleanStoredOrigin(d.savedPlan?.origin):planSource(d.source)),fields:Object.fromEntries(d.inputs.map(input=>[input.key,d.origins[input.key]||'示例 · 请核对']))}},d.savedPlan,$('#detail-title').textContent);
  });
  for(const recipe of alchemy){const button=document.createElement('button');button.className='secondary';button.type='button';button.textContent='规划炼金：'+recipe.name;button.addEventListener('click',async()=>{await loadAlchemy();addAlchemyTarget(recipe.id);$('#detail-dialog').close();navigate('alchemy');$('#alchemy-targets')?.focus();});target.append(button);}
}
function actualNumericalParams(detail){return Object.fromEntries(detail.inputs.map(input=>[input.key,input.value]));}
function openPlanSave(payload,existing=null,name=''){
  planDialogSerial++;planDraft={payload:JSON.parse(JSON.stringify(payload)),existing};
  $('#plan-title').textContent=existing?'另存或明确更新方案':'命名保存方案';$('#plan-name').value=planNameDrafts.get(planDraftKey(payload,existing))||existing?.name||name;
  planMetaOriginals.set(planDraftKey(payload,existing),{name:existing?.name||name,note:existing?.note||payload.note||''});
  $('#plan-note').value=planNoteDrafts.get(planDraftKey(payload,existing))??existing?.note??payload.note??'';
  $('#plan-description').textContent=`${planLabels[payload.kind]}。${originLabel(payload.source)}。保存只包含此次实际使用的参数。`;
  $('#plan-reload').hidden=!existing;$('#plan-update').hidden=!existing;$('#plan-update').disabled=false;$('#plan-submit').disabled=false;$('#plan-submit').textContent=existing?'另存为新方案':'保存新方案';inlineError($('#plan-error'),'');if(!$('#plan-dialog').open)$('#plan-dialog').showModal();$('#plan-name').focus();
}
async function savePlan(update=false){
  if(!planDraft||!$('#plan-form').reportValidity())return;const serial=planDialogSerial,draft=planDraft,name=$('#plan-name').value,note=$('#plan-note').value;
  const payload={action:'save',...draft.payload,name,note,...(update?{record_id:draft.existing.id,expected_record_revision:draft.existing.record_revision}:{})};
  $('#plan-submit').disabled=true;$('#plan-update').disabled=true;
  try{const result=await post('/api/workspace',payload);if(serial!==planDialogSerial)return;
    const priorId=draft.existing?.id;
    if(draft.payload.kind==='numeric'&&numericalDetail?.identity===draft.payload.entry&&(!priorId||numericalDetail.savedPlan?.id===priorId)){numericalDetail.savedPlan=result.plan;numericalDetail.userNote=result.plan.note;numericalDetail.sessionUnsaved=!!numericalDetail.dirty;for(const key of [numericalDetail.identity,'plan:'+priorId,'plan:'+result.plan.id]){numericalDrafts.delete(key);numericalCalculated.delete(key);if(!numericalDetail.dirty)numericalFormDrafts.delete(key);}rememberFixedNumericalDraft();}
    if(draft.payload.kind==='equipment'&&(!priorId||compareSavedPlan?.id===priorId)){compareSavedPlan=result.plan;compareSessionUnsaved=false;updateComparisonSavedNote();}
    if(draft.payload.kind==='manual'&&(!priorId||manualSavedPlan?.id===priorId)){manualSavedPlan=result.plan;manualUnsaved=false;manualAppliedRaw=captureNamedForm('#manual-form');}
    if(draft.payload.kind==='character'&&typeof characterPlanSaved==='function')characterPlanSaved(result.plan,draft.payload);
    if(draft.payload.kind==='alchemy'&&typeof alchemyPlanSaved==='function')alchemyPlanSaved(result.plan,draft.payload);
    if($('#plan-name').value!==name||$('#plan-note').value!==note){const oldKey=planDraftKey(draft.payload,draft.existing);draft.existing=result.plan;const newKey=planDraftKey(draft.payload,draft.existing);if(oldKey!==newKey){planNameDrafts.delete(oldKey);planNoteDrafts.delete(oldKey);planMetaOriginals.delete(oldKey);}planNameDrafts.set(newKey,$('#plan-name').value);planNoteDrafts.set(newKey,$('#plan-note').value);planMetaOriginals.set(newKey,{name:result.plan.name,note:result.plan.note||''});if(draft.payload.kind==='alchemy'){clearAlchemyPlanMetadata(oldKey);rememberAlchemyPlanMetadata(draft,$('#plan-name').value,$('#plan-note').value);}$('#plan-update').hidden=false;$('#plan-reload').hidden=false;inlineError($('#plan-error'),'已保存提交时的内容；新修改的名称或备注仍是本地草稿。');await loadWorkspace();return;}
    if(draft.payload.kind==='alchemy'&&typeof clearAlchemyPlanMetadata==='function')clearAlchemyPlanMetadata(planDraftKey(draft.payload,draft.existing));
    planNameDrafts.delete(planDraftKey(draft.payload,draft.existing));planNoteDrafts.delete(planDraftKey(draft.payload,draft.existing));planDraft=null;$('#plan-dialog').close();toast(update?'原方案已明确更新':'已保存独立方案');await loadWorkspace();}
  catch(error){if(serial===planDialogSerial)inlineError($('#plan-error'),error.message);}
  finally{if(serial===planDialogSerial){$('#plan-submit').disabled=false;$('#plan-update').disabled=false;}}
}
async function confirmReloadSavedPlan(id){
  openWorkspaceConfirmation({localReload:id},'重新读取最新已保存方案','确认放弃此方案的本地参数、计算结果和名称 / 备注草稿，读取最新已保存版本？尚未保存的内容不会写入资料库。');
}
function rememberWorkspaceDetailFocus(id){
  const rows=Array.from($('#workspace-plans').children),row=rows.find(el=>el.dataset.planId===id);
  workspaceDetailReturn={id,index:Math.max(0,rows.indexOf(row)),action:'open'};
}
function returnWorkspaceDetailFocus(){
  const saved=workspaceDetailReturn;if(!saved)return;workspaceDetailReturn=null;
  window.requestAnimationFrame(()=>{if(document.querySelector('dialog[open]')||view!=='workspace')return;
    const rows=Array.from($('#workspace-plans').children),row=rows.find(el=>el.dataset.planId===saved.id)||rows[Math.min(saved.index,rows.length-1)];
    (row?.querySelector('[data-open]')||$('#workspace-search')).focus({preventScroll:true});
  });
}
$('#detail-dialog').addEventListener('close',returnWorkspaceDetailFocus);
async function openPlan(id,preloaded=null,allowReplace=false){
  if(preloaded?.trigger){rememberWorkspaceDetailFocus(id);preloaded=null;}
  else if(view==='workspace')rememberWorkspaceDetailFocus(id);
  const seq=++planRequest,nav=navigationSerial;
  try{
    const opened=preloaded||await getJSON('/api/workspace/plan?'+new URLSearchParams({id}));if(seq!==planRequest||nav!==navigationSerial)return;
    const plan=opened.plan;
    if(!allowReplace&&((plan.kind==='equipment'&&compareSessionUnsaved)||(plan.kind==='manual'&&manualUnsaved)||(plan.kind==='character'&&typeof characterDraftLabel==='function'&&characterDraftLabel())||(plan.kind==='alchemy'&&typeof alchemyDraftLabel==='function'&&alchemyDraftLabel()))){openWorkspaceConfirmation({localOpenPlan:{id,opened}},'保留当前草稿，再打开所选方案','当前对应表单有尚未保存的编辑。勾选并确认后，先保存全部未完成原始表单副本，再打开所选方案。取消则继续保留当前表单。副本可在「未完成的会话草稿」中找回，不会应用到游戏或设置。');return;}
    if(plan.kind!=='numeric'&&$('#detail-dialog').open)$('#detail-dialog').close();
    if($('#plan-dialog').open)$('#plan-dialog').close();
    if(plan.kind==='numeric'){
      showDetail(plan.name,'这是按保存参数重新计算的固定参考。确认适用条件后，再决定是否带入最新角色状态。','保存的数值方案',originLabel(plan.origin));setDetailEntry(plan.entry);
      showDetailContext(plan.note?'用户用途 / 假设（自行记录，非已确认游戏事实）：'+plan.note:'');
      await loadNumericalDetail(plan.entry,plan.params,'saved',{fixed:true,savedPlan:plan,result:opened.result,rulesChanged:opened.rules_changed});
    }else if(plan.kind==='equipment'){
      navigate('inventory');await openEquipmentPlan(plan,opened.result,opened.rules_changed);
    }else if(plan.kind==='character'){
      await openCharacterPlan(plan,opened.result,opened.rules_changed);
    }else if(plan.kind==='alchemy'){
      navigate('alchemy');await openAlchemyPlan(plan,opened.result,opened.rules_changed);
    }else if(plan.kind==='manual'){
      fillManualDraft(plan.params);manualSavedPlan=plan;manualUnsaved=true;navigate('manual');$('#manual-draft-status').textContent=`已打开「${plan.name}」草稿。${originLabel(plan.origin)}。还没有提交，不改变当前局势。${plan.note?' 用户用途 / 假设：'+plan.note:''}`;$('#manual-form').querySelector('input,select')?.focus();
    }
  }catch(error){if(seq===planRequest)inlineError($('#workspace-error'),error.message);$('#workspace-refresh').focus();}
}
function manualPayload(){
  const form=new FormData($('#manual-form')),payload={class:form.get('class'),buffs:form.getAll('buff'),challenges:form.getAll('challenge').reduce((a,b)=>a|Number(b),0)};
  for(const key of ['hp','ht','depth','branch','level','strength','healing'])payload[key]=Number(form.get(key));payload.hunger=form.get('hunger')==='unknown'?null:Number(form.get('hunger'));if(typeof manualCharacterReference!=='undefined'&&manualCharacterReference){payload.character_scene=characterClone(manualCharacterReference.params);payload.character_scene.base_strength=payload.strength;}return payload;
}
function fillManualDraft(params){
  if(typeof manualFormGeneration!=='undefined')manualFormGeneration++;
  if(typeof setManualCharacterReference==='function')setManualCharacterReference(params.character_scene?{params:params.character_scene,source:{mode:'manual',snapshot_at:null,slot:null},stamp:null,label:'保存的共享角色条件'}:null);
  const form=$('#manual-form');for(const key of ['class','hp','ht','depth','branch','level','strength','healing','hunger'])form.elements.namedItem(key).value=params[key]===null?'unknown':String(params[key]);
  $$('#manual-form input[name="buff"]').forEach(input=>input.checked=(params.buffs||[]).includes(input.value));$$('#manual-form input[name="challenge"]').forEach(input=>input.checked=!!(params.challenges&Number(input.value)));
}
function openWorkspaceConfirmation(payload,title,description){
  workspaceConfirmSerial++;workspaceConfirmation=payload;$('#workspace-confirm-title').textContent=title;$('#workspace-confirm-description').textContent=description;$('#workspace-confirm-check').checked=false;inlineError($('#workspace-confirm-error'),'');$('#workspace-confirm-submit').disabled=false;$('#workspace-confirm').showModal();
}
$('#workspace-confirm-form').addEventListener('submit',async event=>{event.preventDefault();if(!$('#workspace-confirm-check').checked||!workspaceConfirmation)return;const serial=workspaceConfirmSerial,payload=workspaceConfirmation;$('#workspace-confirm-submit').disabled=true;try{if(payload.localOpenPlan){const captured=currentWebDraft();await post('/api/session-exit',{action:'save-draft',surface_id:webSurfaceId,kind:'web-session',label:'打开其他方案前的未完成草稿',draft:captured.draft});if(serial!==workspaceConfirmSerial)return;const pending=payload.localOpenPlan;$('#workspace-confirm').close();await openPlan(pending.id,pending.opened,true);toast('原有草稿副本已保留；所选方案已打开。');return;}if(payload.localReload){const id=payload.localReload;const opened=await getJSON('/api/workspace/plan?'+new URLSearchParams({id}));if(serial!==workspaceConfirmSerial)return;if(numericalDetail?.savedPlan?.id===id)cancelNumericalDetail();fixedNumericalDrafts.delete(id);numericalFormDrafts.delete('plan:'+id);planNameDrafts.delete(id);planNoteDrafts.delete(id);if(typeof clearAlchemyPlanMetadata==='function')clearAlchemyPlanMetadata(id);planDraft=null;$('#plan-dialog').close();$('#workspace-confirm').close();await openPlan(id,opened,true);return;}const result=await post('/api/workspace',payload);if(serial!==workspaceConfirmSerial)return;$('#workspace-confirm').close();toast(result.preserved_file?'已保留原件并重建空资料库':'方案已删除');await loadWorkspace();}catch(error){if(serial===workspaceConfirmSerial)inlineError($('#workspace-confirm-error'),error.message);}finally{if(serial===workspaceConfirmSerial)$('#workspace-confirm-submit').disabled=false;}});
$('#workspace-confirm-close').addEventListener('click',()=>$('#workspace-confirm').close());$('#workspace-confirm').addEventListener('close',()=>{workspaceConfirmSerial++;workspaceConfirmation=null;});
$('#workspace-repair').addEventListener('click',async()=>{const serial=workspaceConfirmSerial;try{const preview=await post('/api/workspace',{action:'repair-preview'});if(serial!==workspaceConfirmSerial||view!=='workspace')return;openWorkspaceConfirmation({action:'repair',expected:preview.expected,confirmed:true},'保留原文件后重建',`${preview.message}。原件 ${preview.bytes} 字节；预览后原文件变化会停止重建。`);}catch(error){inlineError($('#workspace-error'),error.message);}});
$('#workspace-import').addEventListener('change',async event=>{const file=event.target.files[0];if(!file)return;try{if(file.size>1048576)throw new Error('资料库文件不能超过 1 MiB');if(!token)throw new Error('助手未连接，请恢复后重试');const response=await fetch('/api/workspace/import',{method:'POST',headers:{'Content-Type':'application/json','X-Companion-Token':token},body:await file.text()}),result=await response.json();if(!response.ok)throw new Error(result.error||'导入失败');await loadWorkspace();toast(`已合并 ${result.plans_added||0} 个方案、${result.favorites_added||0} 项收藏；冲突另存 ${result.conflicting_plans_kept_as_copies||0} 个副本。`);}catch(error){inlineError($('#workspace-error'),error.message);}finally{event.target.value='';}});
$('#workspace-refresh').addEventListener('click',loadWorkspace);
for(const id of ['workspace-search','workspace-kind','workspace-sort'])$('#'+id).addEventListener(id==='workspace-search'?'input':'change',renderWorkspace);
$('#workspace-reset').addEventListener('click',()=>{$('#workspace-search').value='';$('#workspace-kind').value='all';$('#workspace-sort').value='updated';renderWorkspace();$('#workspace-search').focus();});
$('#workspace-search').addEventListener('keydown',event=>{if(event.key==='ArrowDown'){event.preventDefault();$('#workspace-plans button')?.focus();}});
$('#plan-reload').addEventListener('click',()=>{if(planDraft?.existing){planNameDrafts.set(planDraft.existing.id,$('#plan-name').value);confirmReloadSavedPlan(planDraft.existing.id);}});
$('#plan-form').addEventListener('submit',event=>{event.preventDefault();savePlan();});$('#plan-update').addEventListener('click',()=>savePlan(true));$('#plan-close').addEventListener('click',()=>$('#plan-dialog').close());$('#plan-dialog').addEventListener('close',()=>{if(planDraft){const key=planDraftKey(planDraft.payload,planDraft.existing);planNameDrafts.set(key,$('#plan-name').value);planNoteDrafts.set(key,$('#plan-note').value);if(typeof rememberAlchemyPlanMetadata==='function')rememberAlchemyPlanMetadata(planDraft,$('#plan-name').value,$('#plan-note').value);}planDialogSerial++;planDraft=null;});
$('#manual-save').addEventListener('click',()=>{if(!$('#manual-form').reportValidity())return;openPlanSave({kind:'manual',entry:null,params:manualPayload(),source:manualSavedPlan?cleanStoredOrigin(manualSavedPlan.origin):{mode:'manual',snapshot_at:null,slot:null}},manualSavedPlan,'手动局势');});
$('#manual-form').addEventListener('input',()=>{manualUnsaved=true;$('#manual-draft-status').textContent='局势草稿已修改，尚未提交；切换页面、错误或重连后仍保留。';});
async function loadDecisions(force=false){
  if(view!=='overview'||!state)return;
  const signature=JSON.stringify([state.started,state.revision,state.modified,state.error,state.settings.mode,state.stale]);if(!force&&signature===decisionSignature)return;
  const seq=++decisionRequest;decisionSignature=signature;
  try{const result=await getJSON('/api/decisions');if(seq!==decisionRequest||signature!==decisionSignature)return;decisionState=result;renderDecisions();inlineError($('#decision-error'),'');}catch(error){if(seq===decisionRequest){decisionSignature='';inlineError($('#decision-error'),error.message);}}
}
function renderDecisions(){
  const result=decisionState;if(!result)return;$('#decision-message').textContent=result.message;
  const target=$('#decision-options');target.replaceChildren();if(!result.options?.length)target.innerHTML='<p class="muted">当前没有已确认可用的相关资源；阅读资料与示例计算仍可使用。</p>';
  for(const option of result.options||[]){const card=document.createElement('article');card.className='resource-card';card.innerHTML=`<h3>${escapeHTML(option.name)} <small>×${escapeHTML(option.quantity)}</small></h3><p class="muted">${escapeHTML(option.source?.label||'资料参考')} · ${option.source?.snapshot_at?escapeHTML(fmtTime(option.source.snapshot_at)):''}</p>${option.restriction?`<p class="rule-warning">主动行动限制：${escapeHTML(option.restriction)}</p>`:''}${option.calculation_missing?`<p>计算前需核对：${escapeHTML(option.calculation_missing)}</p>`:''}${option.values?.length?exampleHTML({title:'已核对条件下的数值',values:option.values}):''}<p>${escapeHTML(option.note)}</p><button class="secondary">${escapeHTML(option.purpose)} · 阅读与计算</button>`;card.querySelector('button').addEventListener('click',()=>openDecisionReference({...option,source_label:option.source?.label},'resource'));target.append(card);}
  const tips=state?.data?.tips||[];
  $$('#advice-list .advice').forEach((card,index)=>{card.querySelector('.risk-links')?.remove();const risk=result.risks?.find(r=>r.id===tips[index]?.id);if(!risk?.references?.length)return;const links=document.createElement('div');links.className='backup-actions risk-links';for(const ref of risk.references){const equipmentRisk=risk.id.startsWith('strength_')&&/^(items\.weapon\.melee\.|items\.armor\.)/.test(ref.entry);const b=document.createElement('button');b.className='secondary';b.textContent=equipmentRisk?'带入此装备比较':`查 ${ref.name}`;b.addEventListener('click',()=>equipmentRisk?compareRiskReference({...ref,location:risk.id.slice('strength_'.length)}):openDecisionReference(ref,'reference'));links.append(b);}card.append(links);});
  $$('#hero-tags .tag.warn').forEach((tag,index)=>{const buff=state?.data?.buffs?.[index];if(!buff)return;tag.tabIndex=0;tag.setAttribute('role','button');tag.setAttribute('aria-label',`查看${buff.name}资料`);const open=()=>openBuffReference(buff);tag.addEventListener('click',open);tag.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open();}});});
}
async function openBuffReference(buff){
  const nav=navigationSerial,detailSeq=numericalRequest;
  try{const result=await getJSON('/api/library?'+new URLSearchParams({q:buff.kind,category:'状态'}));if(nav!==navigationSerial||detailSeq!==numericalRequest)return;const row=result.entries.find(r=>r.name===buff.name)||result.entries.find(r=>r.id==='actors.buffs.'+buff.kind.toLowerCase());if(!row){navigate('library');$('#library-search').value=buff.name;$('#library-category').value='状态';searchLibrary();return;}showReference(row,result.version);}catch(error){inlineError($('#decision-error'),error.message);}
}
function openDecisionReference(ref,kind='reference'){
  showDetail(ref.name,kind==='resource'?(ref.note||'核对当前游戏画面中的资源与条件；阅读不会执行游戏行动。'):'参考相关游戏机制；资源是否可用需要另行核对。','当前局势的资料入口',ref.source_label||'资料参考');
  showDetailContext([ref.restriction?'主动行动限制：'+ref.restriction:'',ref.calculation_missing?'未确认条件：'+ref.calculation_missing:'',kind==='resource'?'以下是资料与所填条件的参考计算，阅读入口不会确认此刻可用或执行游戏行动。':''].filter(Boolean).join('；'));
  setDetailEntry(ref.entry);loadNumericalDetail(ref.entry,ref.params||{},ref.level_origin||'example',{ignoreDrafts:true,...lookupCalculationOptions(ref)});
}
function refreshWorkspaceViews(){
  if((view==='workspace'||view==='library')&&(state?.workspace_revision!==workspaceSeenRevision||view==='library'&&workspaceSeenContext!==workspaceContextKey()))loadWorkspace();
  if(typeof renderCharacterOrigin==='function')renderCharacterOrigin();
  if(view==='alchemy'&&typeof renderAlchemyOrigin==='function')renderAlchemyOrigin();
  if(view==='overview')loadDecisions();if(view==='play-settings'&&typeof refreshPlaySettings==='function')refreshPlaySettings();
}
if(view==='workspace'||view==='library')loadWorkspace();

$('#plan-form').addEventListener('input',()=>{if(planDraft){const key=planDraftKey(planDraft.payload,planDraft.existing);planNameDrafts.set(key,$('#plan-name').value);planNoteDrafts.set(key,$('#plan-note').value);if(typeof rememberAlchemyPlanMetadata==='function')rememberAlchemyPlanMetadata(planDraft,$('#plan-name').value,$('#plan-note').value);}});

// Only declared own forms are persisted. No status response, authentication, or evaluated result is stored.
const webSurfaceId='web-'+panelClient.replace(/-/g,'');
let webDraftRevision=0,webDraftFingerprint='',webExitState=null,webExitBusy=false,webExitHandling=false,webEditingFrozen=false;
let webExitCompletionWatch=null;
const webFrozenControls=new Map();
function captureNamedForm(selector){
  const form=$(selector),raw={};if(!form)return raw;
  for(const input of form.querySelectorAll('input,select,textarea')){const key=input.id|| (input.dataset.binding?'binding.'+input.dataset.binding:input.name);if(!key)continue;
    (raw[key]??=[]).push({value:input.value,checked:!!input.checked});}
  return raw;
}
function restoreNamedForm(selector,raw){
  if(!raw||typeof raw!=='object'||Array.isArray(raw))throw new Error('草稿表单格式不正确');
  const controls=Array.from($(selector).querySelectorAll('input,select,textarea')),keys=new Set(controls.map(input=>input.id||(input.dataset.binding?'binding.'+input.dataset.binding:input.name)));
  if(Object.keys(raw).some(key=>!keys.has(key)))throw new Error('这份草稿含当前表单不支持的字段；原副本保留。');
  const offsets={};for(const input of controls){const key=input.id||(input.dataset.binding?'binding.'+input.dataset.binding:input.name),index=offsets[key]||0;offsets[key]=index+1;const cell=raw[key]?.[index];if(cell===undefined)continue;
    if(typeof cell.value!=='string'||cell.value.length>4000||typeof cell.checked!=='boolean')throw new Error('草稿字段格式不正确，原副本保留。');
    if(input.tagName==='SELECT'&&!Array.from(input.options).some(option=>option.value===cell.value))throw new Error('草稿中的选项在当前版本不受支持，原副本保留。');
  }
  const used={};for(const input of controls){const key=input.id||(input.dataset.binding?'binding.'+input.dataset.binding:input.name),index=used[key]||0;used[key]=index+1;const cell=raw[key]?.[index];if(cell){input.value=cell.value;input.checked=cell.checked;}}
}
function compactNumeric(detail,key){
  if(!detail)return null;
  const raw={...(detail.rawDraft||numericalFormDrafts.get(key)||{})};
  if(detail===numericalDetail)for(const input of $$('[data-value-key]'))raw[input.dataset.valueKey]=input.value;
  return {identity:detail.identity,key,params:{...(detail.calculated?.params||detail.context||{})},raw,origins:{...detail.origins},source:detail.source||null,
    levelSource:detail.levelSource||null,character_reference:detail.characterReference||null,fixed:!!detail.fixed,levelOrigin:detail.levelOrigin||'manual',saved_id:detail.savedPlan?.id||null,saved_revision:detail.savedPlan?.record_revision||null,saved_name:detail.savedPlan?.name||null,saved_origin:detail.savedPlan?.origin||null,note:detail.userNote??detail.savedPlan?.note??'',dirty:!!detail.dirty,sessionUnsaved:!!detail.sessionUnsaved};
}
function webDirtySummary(){
  const labels=[];
  const numericRaw=Array.from(numericalFormDrafts.values()).some(raw=>Object.keys(raw).length);
  const numericCalculated=Array.from(numericalCalculated.values()).some(item=>item.sessionUnsaved);
  const numericCommitted=Array.from(numericalDrafts).some(([key,raw])=>!key.startsWith('plan:')&&Object.keys(raw).length);
  if(numericRaw||numericCommitted||numericCalculated||numericalDetail?.dirty||numericalDetail?.sessionUnsaved||Array.from(fixedNumericalDrafts.values()).some(d=>d.dirty||d.sessionUnsaved))labels.push('数值试算');
  if(compareSessionUnsaved)labels.push('装备比较');
  if(manualUnsaved)labels.push('局势表单');
  if(typeof characterDraftLabel==='function'&&characterDraftLabel())labels.push('共享角色条件');
  if(settingsDrafts.size)labels.push('连接设置');
  if(typeof playDirty!=='undefined'&&playDirty)labels.push('游玩设置');
  if(typeof alchemyDraftLabel==='function'&&alchemyDraftLabel())labels.push('炼金规划');
  if(typeof migrationDraftLabel==='function'&&migrationDraftLabel())labels.push('搬机迁移');
  if(Array.from(planNameDrafts.keys()).some(key=>{const baseline=planMetaOriginals.get(key);return !baseline||planNameDrafts.get(key)!==baseline.name||(planNoteDrafts.get(key)||'')!==baseline.note;}))labels.push('方案名称 / 备注');
  return labels;
}
function collectWebDraft(){
  const labels=webDirtySummary(),numeric=new Map();
  for(const [key,detail] of fixedNumericalDrafts)if(detail.dirty||detail.sessionUnsaved||Object.keys(numericalFormDrafts.get('plan:'+key)||{}).length)numeric.set('plan:'+key,compactNumeric(detail,'plan:'+key));
  for(const key of new Set([...numericalDrafts.keys(),...numericalFormDrafts.keys(),...Array.from(numericalCalculated).filter(([,item])=>item.sessionUnsaved).map(([key])=>key)]))if(!numeric.has(key)&&!key.startsWith('plan:')){const calculated=numericalCalculated.get(key);numeric.set(key,{identity:key,key,params:{...(calculated?.params||numericalDrafts.get(key)||{})},raw:{...(numericalFormDrafts.get(key)||{})},origins:calculated?.origins||{},source:calculated?.source||null,levelSource:calculated?.levelSource||null,fixed:false,levelOrigin:'manual',dirty:true,sessionUnsaved:true});}
  if(numericalDetail&&(numericalDetail.dirty||numericalDetail.sessionUnsaved||labels.includes('数值试算'))){const key=numericalDetail.savedPlan?'plan:'+numericalDetail.savedPlan.id:numericalDetail.identity;numeric.set(key,compactNumeric(numericalDetail,key));}
  const draft={format:1,schema:'denghuo-web-session',numeric:Array.from(numeric.values()),
    manual:manualUnsaved?captureNamedForm('#manual-form'):null,
    manual_character:manualUnsaved&&typeof manualCharacterReference!=='undefined'?characterClone(manualCharacterReference):null,
    character:typeof captureCharacterDraft==='function'?captureCharacterDraft():null,
    comparison:compareSessionUnsaved?{form:captureComparisonRaw(),choices:{a:compareItems[Number($('#compare-a').value)]?.key,b:compareItems[Number($('#compare-b').value)]?.key},fixed:compareFixed,saved_id:compareSavedPlan?.id||null,saved_revision:compareSavedPlan?.record_revision||null,saved_name:compareSavedPlan?.name||null,saved_origin:compareSavedPlan?.origin||null,note:compareSavedPlan?.note||'',budget_origin:compareBudgetOrigin,budget_stamp:compareBudgetStamp,stamp:compareStamp,character_reference:typeof compareCharacterReference!=='undefined'?characterClone(compareCharacterReference):null}:null,
    settings:settingsDrafts.size?captureNamedForm('#settings-form'):null,
    play:typeof playDirty!=='undefined'&&playDirty?captureNamedForm('#play-form'):null,
    alchemy:typeof captureAlchemyDraft==='function'?captureAlchemyDraft():null,
    alchemy_plan_meta:typeof captureAlchemyPlanMetadata==='function'?captureAlchemyPlanMetadata():[],
    migration:typeof captureMigrationDraft==='function'?captureMigrationDraft():null,
    plan_meta:Array.from(planNameDrafts,([key,name])=>({key,name,note:planNoteDrafts.get(key)||'',original:planMetaOriginals.get(key)||null})),
    open_plan:planDraft?{payload:planDraft.payload,existing_id:planDraft.existing?.id||null,existing_revision:planDraft.existing?.record_revision||null,existing_name:planDraft.existing?.name||null,existing_note:planDraft.existing?.note||'',existing_origin:planDraft.existing?.origin||null,name:$('#plan-name').value,note:$('#plan-note').value}:null};
  return {draft,dirty:labels.length>0,labels};
}
function currentWebDraft(){const captured=collectWebDraft(),fingerprint=JSON.stringify(captured.draft);if(fingerprint!==webDraftFingerprint){webDraftFingerprint=fingerprint;webDraftRevision++;}return {...captured,revision:webDraftRevision};}
function freezeWebEditing(frozen){
  webEditingFrozen=frozen;
  if(frozen){for(const input of $$('form input,form select,form textarea,form button')){if(!webFrozenControls.has(input))webFrozenControls.set(input,input.disabled);input.disabled=true;}}
  else {for(const [input,disabled] of webFrozenControls)if(input.isConnected)input.disabled=disabled;webFrozenControls.clear();}
}
async function watchWebExitCompletion(){
  if(webExitCompletionWatch)return webExitCompletionWatch;
  webExitCompletionWatch=(async()=>{
    const deadline=Date.now()+10000;
    while(webExitState?.phase==='backing-up'&&Date.now()<deadline){
      await new Promise(resolve=>setTimeout(resolve,200));
      try{const current=await getJSON('/api/status');if(current.exit?.id!==webExitState.id)return;await handleWebExitState(current.exit);}
      catch(error){toast('连接中断，结束结果暂未确认；已明确保存的草稿可在下次启动后读取。',true);return;}
    }
    if(webExitState?.phase==='backing-up')toast('结束结果仍在等待；已保存草稿保持保留，请核对下次启动的最后备份回执。',true);
  })();
  try{await webExitCompletionWatch;}finally{webExitCompletionWatch=null;}
}
async function reportWebExitSurface(){
  if(['backing-up','finished'].includes(webExitState?.phase)){
    if(state?.exit?.id===webExitState.id)await handleWebExitState(state.exit);
    return;
  }

  if(!token||webExitBusy)return;webExitBusy=true;
  try{const captured=currentWebDraft();const result=await post('/api/session-exit',{action:'report',surface_id:webSurfaceId,kind:'web',label:'完整网页面板',revision:captured.revision,dirty:captured.dirty,draft:captured.draft});await handleWebExitState(result.exit);}
  catch(error){if(webEditingFrozen)inlineError($('#session-exit-error'),error.message);}
  finally{webExitBusy=false;}
}
async function requestWebSessionExit(){
  try{await reportWebExitSurface();const result=await post('/api/session-exit',{action:'request',surface_id:webSurfaceId,reason:'网页结束本次辅助'});await handleWebExitState(result.exit);}
  catch(error){toast(error.message,true);}
}
async function handleWebExitState(exit){
  if(!exit||webExitHandling)return;if(exit.id&&exit.id===webExitState?.id&&(webExitState.phase==='finished'||webExitState.phase==='backing-up'&&exit.phase==='confirming'))return;webExitState=exit;
  if(exit.phase!=='confirming'){freezeWebEditing(exit.phase==='backing-up'||exit.phase==='finished');if($('#session-exit-dialog').open)$('#session-exit-dialog').close();if(exit.phase==='cancelled')toast('已取消退出，全部草稿仍保留');if(exit.phase==='finished')toast(exit.error||'本次辅助已结束；明确保存的未完成草稿可在下次启动后找回',!!exit.error);if(exit.phase==='backing-up')void watchWebExitCompletion();return;}
  webExitHandling=true;freezeWebEditing(true);
  try{const captured=currentWebDraft();const reported=await post('/api/session-exit',{action:'report',surface_id:webSurfaceId,kind:'web',label:'完整网页面板',revision:captured.revision,dirty:captured.dirty,draft:captured.draft});webExitState=reported.exit;
    const own=webExitState.participants.find(p=>p.surface_id===webSurfaceId);
    if(!captured.dirty&&!own?.ack){const acknowledged=await post('/api/session-exit',{action:'ack',request_id:exit.id,surface_id:webSurfaceId,decision:'clean',revision:captured.revision});webExitState=acknowledged.exit;}
    $('#session-exit-description').textContent=captured.dirty?`当前窗口有未保存的 ${captured.labels.join('、')}。保存副本保留原始输入（含无效输入），下次载入仍需重新核对，不会提交局势或应用设置。`:'本窗口草稿已确认；等待其他窗口。可以取消退出，或处理已离线窗口最近上报的草稿。';
    $('#session-exit-save').disabled=!captured.dirty||!!own?.ack;$('#session-exit-discard').disabled=!captured.dirty||!!own?.ack;$('#session-exit-cancel').disabled=false;
    $('#session-exit-status').textContent=own?.ack==='saved'?'本窗口未完成草稿副本已保存。等待其他窗口确认。':own?.ack==='discard'?'你已明确放弃本窗口草稿。等待其他窗口确认。':webExitState.error||'全部窗口确认后才结束服务并尝试最后备份。';
    renderExitParticipants();
    if(webExitState.phase==='confirming'){if(!$('#session-exit-dialog').open)$('#session-exit-dialog').showModal();}
    else if($('#session-exit-dialog').open)$('#session-exit-dialog').close();
  }finally{webExitHandling=false;}
}
function renderExitParticipants(){
  const target=$('#session-exit-participants'),participants=(webExitState?.participants||[]).filter(p=>p.surface_id!==webSurfaceId);
  const signature=JSON.stringify([webExitState?.id,participants.map(p=>[p.surface_id,p.label,p.ack,p.online,p.dirty,p.revision])]);
  const seenText=p=>`最近上报 ${fmtTime(p.last_seen)}。离线副本仅含最近已上报内容，不能保证包含最后尚未上报的编辑。`;
  if(target.dataset.renderSignature===signature){for(const row of target.children){const p=participants.find(p=>p.surface_id===row.dataset.exitSurface);if(p)row.querySelector('small').textContent=seenText(p);}return;}
  target.dataset.renderSignature=signature;target.replaceChildren();
  for(const participant of participants){const row=document.createElement('article');row.dataset.exitSurface=participant.surface_id;row.innerHTML=`<p>${escapeHTML(participant.label)}：${participant.ack?'已确认':participant.online?'等待该窗口确认':'离线 / 暂未响应'}${participant.dirty?' · 有未保存草稿':''}</p><small>${escapeHTML(seenText(participant))}</small>`;
    if(!participant.online&&!participant.ack){for(const [decision,label] of [['save','保存其最近上报草稿并继续退出'],['discard','明确放弃其最近上报草稿']]){const button=document.createElement('button');button.className=decision==='save'?'secondary':'danger-button';button.textContent=label;button.addEventListener('click',async()=>{button.disabled=true;try{const result=await post('/api/session-exit',{action:'resolve-offline',request_id:webExitState.id,surface_id:participant.surface_id,revision:participant.revision,decision});await handleWebExitState(result.exit);}catch(error){inlineError($('#session-exit-error'),error.message);}finally{button.disabled=false;}});row.append(button);}}
    target.append(row);
  }
}
async function decideWebExit(decision){
  if(!webExitState||webExitState.phase!=='confirming')return;
  const captured=currentWebDraft(),requestId=webExitState.id;
  for(const id of ['session-exit-save','session-exit-discard','session-exit-cancel'])$('#'+id).disabled=true;
  try{await post('/api/session-exit',{action:'report',surface_id:webSurfaceId,kind:'web',label:'完整网页面板',revision:captured.revision,dirty:captured.dirty,draft:captured.draft});
    if(decision==='saved'){await post('/api/session-exit',{action:'save-draft',surface_id:webSurfaceId,kind:'web-session',label:'网页未完成会话草稿',draft:captured.draft});if(currentWebDraft().revision!==captured.revision)throw new Error('保存期间草稿已变化；新编辑保留，请重新选择保存。');}
    const result=await post('/api/session-exit',{action:'ack',request_id:requestId,surface_id:webSurfaceId,decision,revision:captured.revision});await handleWebExitState(result.exit);
  }catch(error){inlineError($('#session-exit-error'),error.message);for(const id of ['session-exit-save','session-exit-discard','session-exit-cancel'])$('#'+id).disabled=false;}
}
$('#session-exit-save').addEventListener('click',()=>decideWebExit('saved'));$('#session-exit-discard').addEventListener('click',()=>decideWebExit('discard'));$('#session-exit-cancel').addEventListener('click',()=>decideWebExit('cancel'));
$('#session-exit-dialog').addEventListener('cancel',event=>{event.preventDefault();decideWebExit('cancel');});
window.addEventListener('beforeunload',event=>{if(webDirtySummary().length&&webExitState?.phase!=='finished'){event.preventDefault();event.returnValue='';}});
window.addEventListener('pagehide',()=>{if(!token||webExitState?.phase==='finished')return;const captured=currentWebDraft();fetch('/api/session-exit',{method:'POST',keepalive:true,headers:{'Content-Type':'application/json','X-Companion-Token':token},body:JSON.stringify({action:'unregister',surface_id:webSurfaceId,revision:captured.revision,dirty:captured.dirty,draft:captured.draft})}).catch(()=>{});});
for(const name of ['input','change','submit','click'])document.addEventListener(name,event=>{if(webEditingFrozen&&event.target.closest?.('form')){event.preventDefault();event.stopImmediatePropagation();}},true);
async function loadExitDrafts(){
  try{const result=await post('/api/session-exit',{action:'draft-list'}),target=$('#session-drafts');target.replaceChildren();
    if(!result.drafts.length)target.innerHTML='<p class="muted">尚无明确保存的未完成草稿副本。</p>';
    for(const record of result.drafts){const row=document.createElement('article');row.className='plan-row';row.innerHTML=`<div><h3>${escapeHTML(record.label||'无法读取的草稿')}</h3><small>${escapeHTML(record.draft_kind||'')} · ${escapeHTML(fmtTime(record.saved))}</small>${record.error?`<p>${escapeHTML(record.error)}；原件保留。</p>`:''}</div>`;if(!record.error){const button=document.createElement('button');button.className='secondary';button.textContent='载入为未提交草稿';button.addEventListener('click',()=>loadUnfinishedDraft(record.id));row.append(button);}target.append(row);}inlineError($('#draft-error'),'');
  }catch(error){inlineError($('#draft-error'),error.message);}
}
async function restoreNumericSession(item){
  if(!item||typeof item.identity!=='string'||!/^[a-z0-9_.\-$]{1,300}$/.test(item.identity)||!item.raw||typeof item.raw!=='object')throw new Error('数值草稿身份或原始参数不正确');
  if(item.note!==undefined&&(typeof item.note!=='string'||item.note.length>1200||/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(item.note)))throw new Error('草稿用户备注格式不正确，原副本保留。');
  if(item.saved_name!=null&&(typeof item.saved_name!=='string'||item.saved_name.length>80))throw new Error('草稿关联方案名称格式不正确');
  const reference=await getJSON('/api/values?'+new URLSearchParams({id:item.identity})),keys=new Set(reference.inputs.map(input=>input.key));
  if(Object.keys(item.raw).some(key=>!keys.has(key)||typeof item.raw[key]!=='string'||item.raw[key].length>200))throw new Error('数值草稿含当前条目不支持的字段；原副本保留。');
  const key=item.identity;

  let saved=null;if(item.saved_id){try{saved=(await getJSON('/api/workspace/plan?'+new URLSearchParams({id:item.saved_id}))).plan;}catch(error){toast('关联方案已变化；原始草稿仍按独立参考恢复',true);}}
  if(saved){if(item.saved_revision&&!/^[a-f0-9]{64}$/.test(item.saved_revision))throw new Error('关联方案版本格式不正确；原副本保留。');saved={...saved,record_revision:item.saved_revision||'',name:item.saved_name||saved.name,note:item.note||'',origin:item.saved_origin||saved.origin};}
  showDetail('找回的数值草稿','原始输入已保留；下方先显示当前规则的示例结果，修改后的输入尚未计算。','未完成会话草稿','载入不会更新保存方案或当前游戏。');setDetailEntry(item.identity);
  const params=Object.fromEntries(Object.entries(item.params||{}).filter(([key,value])=>keys.has(key)&&typeof value==='number'&&Number.isFinite(value)));
  let calculated=reference;try{calculated=await getJSON('/api/values?'+new URLSearchParams({id:item.identity,...params}));}catch(error){showDetailContext('上次有效参数无法在当前版本计算；下面是当前规则示例，原始输入仍保留且尚未计算。');}
  await loadNumericalDetail(item.identity,params,'manual',{ignoreDrafts:true,result:calculated});
  for(const input of $$('[data-value-key]'))if(input.dataset.valueKey in item.raw)input.value=item.raw[input.dataset.valueKey];
  numericalDetail.characterReference=item.character_reference||null;
  numericalDetail.savedPlan=saved;numericalDetail.fixed=!!saved&&!!item.fixed;numericalDetail.source=item.source||null;numericalDetail.levelSource=item.levelSource||null;
  numericalDetail.origins=Object.fromEntries(reference.inputs.map(input=>[input.key,item.origins?.[input.key]||'找回的原始输入 · 尚未计算']));
  numericalDetail.dirty=true;numericalDetail.sessionUnsaved=true;numericalDetail.userNote=item.note||'';if(item.note)showDetailContext('用户用途 / 假设（非游戏事实）：'+item.note);
  {const metaKey=saved?.id||'numeric:'+item.identity;planNoteDrafts.set(metaKey,item.note||'');}
  if(saved){numericalFormDrafts.set('plan:'+saved.id,{...item.raw});rememberFixedNumericalDraft();}else {numericalFormDrafts.set(item.identity,{...item.raw});numericalCalculated.set(item.identity,{...numericalDetail.calculated,origins:{...numericalDetail.origins},source:numericalDetail.source,levelSource:numericalDetail.levelSource,sessionUnsaved:true});}refreshNumericalOrigin();return numericalDetail;
}
async function loadUnfinishedDraft(id){
  try{if(webDirtySummary().length)throw new Error('当前有未保存草稿；请先命名保存，或保存会话草稿副本后再载入，避免覆盖本地编辑。');
    const result=await post('/api/session-exit',{action:'draft-load',id}),record=result.draft,draft=record.draft;
    if(draft?.schema!=='denghuo-web-session'||draft.format!==1){
      if(record.draft_kind==='numeric'&&draft.entry&&draft.raw_params){await restoreNumericSession({identity:draft.entry,raw:draft.raw_params,params:draft.calculated||{},origins:draft.origins||{},saved_id:draft.saved_plan?.id||null,saved_revision:draft.saved_plan?.record_revision||null,saved_name:draft.saved_plan?.name||null,saved_origin:draft.saved_plan?.origin||null,fixed:!!draft.saved_plan,note:draft.note||'',source:lookupCalculationOptions({stamp:draft.context?.stamp,source:draft.context?.source}).sourceStamp||null});return;}
      throw new Error('此副本使用原生窗口的草稿格式，请在原生管理窗口选择「载入未完成草稿」。原件保留。');
    }
    if(draft.character&&typeof restoreCharacterDraft==='function')await restoreCharacterDraft(draft.character);
    if(draft.manual&&typeof setManualCharacterReference==='function')setManualCharacterReference(draft.manual_character||null);
    if(draft.manual){restoreNamedForm('#manual-form',draft.manual);manualFormGeneration++;manualUnsaved=true;$('#manual-draft-status').textContent='找回了尚未提交的原始局势草稿；请核对后再提交。';}
    if(draft.settings){restoreNamedForm('#settings-form',draft.settings);for(const key of Object.keys(draft.settings))settingsDrafts.add(key);settingsDraftNotice();}
    if(draft.play){await loadPlaySettings();restoreNamedForm('#play-form',draft.play);playDirty=true;playDraftGeneration++;renderPlayDraftNotice();}
    if(draft.alchemy&&typeof restoreAlchemyDraft==='function')await restoreAlchemyDraft(draft.alchemy);
    if(draft.alchemy_plan_meta&&typeof restoreAlchemyPlanMetadata==='function')restoreAlchemyPlanMetadata(draft.alchemy_plan_meta);
    if(draft.migration&&typeof restoreMigrationDraft==='function')await restoreMigrationDraft(draft.migration);
    if(draft.comparison){const c=draft.comparison,kind=c.form['compare-kind']?.value;if(!comparisonPrefixes[kind])throw new Error('比较草稿类型不正确');await comparisonReady;$('#compare-kind').value=kind;compareSignature='';renderEquipmentComparison();
      for(const side of ['a','b']){const index=compareItems.findIndex(item=>item.key===c.choices?.[side]&&!item.owned);if(index<0)throw new Error('草稿装备在当前资料中不存在');$('#compare-'+side).value=String(index);fillCompareChoice(side);await loadComparisonContext(side,compareItems[index]);}
      for(const input of $$('#equipment-comparison input,#equipment-comparison select')){if(['compare-a','compare-b'].includes(input.id))continue;const cell=c.form[input.id||input.dataset.compareKey];if(!cell)continue;if(typeof cell.value!=='string'||cell.value.length>200)throw new Error('比较草稿字段格式不正确');input.value=cell.value;input.checked=!!cell.checked;input.dataset.manual='true';input.dataset.edited='true';}
      if(c.note!==undefined&&(typeof c.note!=='string'||c.note.length>1200))throw new Error('比较草稿用户备注格式不正确');
      let saved=null;if(c.saved_id){try{saved=(await getJSON('/api/workspace/plan?'+new URLSearchParams({id:c.saved_id}))).plan;if(saved.kind!=='equipment')saved=null;}catch(error){toast('关联装备方案已变化，原始草稿按独立参考恢复',true);}if(saved){if(c.saved_revision&&!/^[a-f0-9]{64}$/.test(c.saved_revision))throw new Error('关联装备方案版本格式不正确');saved={...saved,record_revision:c.saved_revision||'',name:c.saved_name||saved.name,note:c.note||'',origin:c.saved_origin||saved.origin};}}
      if(typeof compareCharacterReference!=='undefined')compareCharacterReference=c.character_reference||null;
      compareSessionUnsaved=true;compareDirty=true;compareFixed=!!saved&&!!c.fixed;compareStamp=c.stamp||null;compareBudgetOrigin=c.budget_origin||'找回的手填预算';compareBudgetStamp=c.budget_stamp||null;compareResultArgs=null;compareSavedPlan=saved;updateComparisonSavedNote();$('#compare-result').replaceChildren();$('#compare-copy-text').textContent='';$('.comparison-panel').open=true;refreshComparisonOrigin();}
    for(const meta of draft.plan_meta||[]){if(typeof meta.key!=='string'||typeof meta.name!=='string'||meta.name.length>80||typeof meta.note!=='string'||meta.note.length>1200)throw new Error('方案备注草稿格式不正确');planNameDrafts.set(meta.key,meta.name);planNoteDrafts.set(meta.key,meta.note);if(meta.original)planMetaOriginals.set(meta.key,meta.original);}
    if(draft.numeric?.length){for(const item of draft.numeric)await restoreNumericSession(item);}
    else if(draft.character)navigate('workspace');else if(draft.alchemy||draft.alchemy_plan_meta?.length)navigate('alchemy');else if(draft.migration)navigate('migration');else if(draft.manual)navigate('manual');else if(draft.comparison)navigate('inventory');else if(draft.settings)navigate('settings');else if(draft.play)navigate('play-settings');
    if(draft.open_plan){const old=draft.open_plan;let existing=null,conflict=false;if(old.existing_revision!=null&&!/^[a-f0-9]{64}$/.test(old.existing_revision))throw new Error('命名草稿关联版本格式不正确；原始副本仍保留');if(old.existing_id){try{const latest=(await getJSON('/api/workspace/plan?'+new URLSearchParams({id:old.existing_id}))).plan;if(latest.kind!==old.payload.kind)throw new Error('关联方案类型已经变化');conflict=latest.record_revision!==old.existing_revision;existing={...latest,record_revision:old.existing_revision||'',name:old.existing_name||old.name||latest.name,note:old.existing_note??old.note??'',origin:old.existing_origin||old.payload.source||latest.origin};}catch(error){conflict=true;/* Keep as a new independent draft. */}}openPlanSave(old.payload,existing,old.name);$('#plan-name').value=old.name;$('#plan-note').value=old.note||'';if(conflict)inlineError($('#plan-error'),'关联方案已变化；原始条件、名称和备注按旧版本保留。可另存副本，或明确重新读取最新方案；旧草稿不能覆盖新内容。');}
    toast('已找回原始草稿；未计算、未提交局势、未应用设置。');inlineError($('#draft-error'),'');
  }catch(error){inlineError($('#draft-error'),error.message);toast(error.message,true);}
}
$('#draft-refresh').addEventListener('click',loadExitDrafts);
manualAppliedRaw=captureNamedForm('#manual-form');
