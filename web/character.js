'use strict';
let characterLatest=null,characterCatalog=[],characterResult=null,characterSavedPlan=null;
let characterSource={mode:'example',snapshot_at:null,slot:null},characterStamp=null;
let characterDirty=false,characterUnsaved=false,characterRequest=0,characterImportUndo=null;
let manualCharacterReference=null,manualCharacterUndo=null,compareCharacterReference=null;
let characterCatalogLoading=false;
const characterClone=value=>value==null?null:JSON.parse(JSON.stringify(value));
function blankCharacterScene(){return {format:1,base_strength:10,rings:[],strongman:0,adrenaline:0,magic_immune:false,spirit_form:false,spirit_ring:null,spirit_level:null,spirit_cursed:null};}
function characterOptionalInteger(value,label,min,max){
  const raw=String(value).trim();if(!raw)return null;
  if(!/^[+-]?\d{1,7}$/.test(raw)||Number(raw)<min||Number(raw)>max)throw new Error(`${label}需要 ${min}–${max} 的整数，未确认请留空。`);
  return Number(raw);
}
function characterBoolean(value){if(value==='unknown')return null;if(value==='yes')return true;if(value==='no')return false;throw new Error('角色状态选项不正确');}
function readCharacterScene(){
  const optional=(id,label,min,max)=>characterOptionalInteger($('#character-'+id).value,label,min,max);
  const params={format:1,base_strength:optional('base','基础力量',1,1000),strongman:optional('strongman','力大无穷天赋',0,3),adrenaline:optional('adrenaline','激素涌动力量',0,1000),
    magic_immune:characterBoolean($('#character-immune').value),spirit_form:characterBoolean($('#character-spirit').value),
    spirit_ring:$('#character-spirit-ring').value==='unknown'?null:$('#character-spirit-ring').value,
    spirit_level:optional('spirit-level','精神形态戒指等级',0,4),spirit_cursed:characterBoolean($('#character-spirit-curse').value),rings:[]};
  for(let index=0;index<2;index++){
    const identity=$('#character-ring-'+index).value;if(identity==='absent')continue;
    if(index!==params.rings.length)throw new Error('先填写戒指条件1，再填写条件2；未装备时请选择无戒指。');
    params.rings.push({identity:identity==='unknown'?null:identity,
      level:optional('ring-level-'+index,'戒指等级',-100,100),cursed:characterBoolean($('#character-ring-curse-'+index).value)});
  }
  return params;
}
function fillCharacterScene(params){
  const boolean=value=>value===null?'unknown':value?'yes':'no';
  for(const [key,id] of [['base_strength','base'],['strongman','strongman'],['adrenaline','adrenaline'],['spirit_level','spirit-level']])$('#character-'+id).value=params[key]??'';
  for(const [key,id] of [['magic_immune','immune'],['spirit_form','spirit'],['spirit_cursed','spirit-curse']])$('#character-'+id).value=boolean(params[key]);
  ensureCharacterIdentity($('#character-spirit-ring'),params.spirit_ring);$('#character-spirit-ring').value=params.spirit_ring??'unknown';
  for(let index=0;index<2;index++){
    const ring=params.rings[index],select=$('#character-ring-'+index);ensureCharacterIdentity(select,ring?.identity);
    select.value=ring?(ring.identity??'unknown'):'absent';$('#character-ring-level-'+index).value=ring?.level??'';$('#character-ring-curse-'+index).value=boolean(ring?.cursed??null);
  }
}
function ensureCharacterIdentity(select,identity){
  if(identity&&!Array.from(select.options).some(option=>option.value===identity)){
    const option=document.createElement('option');option.value=identity;option.textContent=characterCatalog.find(row=>row.id===identity)?.name||identity;select.append(option);
  }
}
async function loadCharacterCatalog(){
  try{const result=await getJSON('/api/library?'+new URLSearchParams({q:'items.rings.ringof',category:'物品'}));characterCatalog=result.entries.filter(row=>/^items\.rings\.ringof[a-z]+$/.test(row.id));
    for(const select of [$('#character-ring-0'),$('#character-ring-1'),$('#character-spirit-ring')]){
      const current=select.value;for(const row of characterCatalog)ensureCharacterIdentity(select,row.id);select.value=current;
    }
  }catch(error){inlineError($('#character-error'),'戒指资料暂时未读取，已有身份和草稿保留；可以重新刷新资料库。');}
}
function initializeCharacterScene(context){characterLatest=context||null;if(!characterCatalogLoading){characterCatalogLoading=true;loadCharacterCatalog();}renderCharacterOrigin();}
function characterContextLabel(source=characterSource,stamp=characterStamp){
  const prefix=source.mode==='save'?`槽位 ${source.slot??'—'} 已知快照`:source.mode==='manual'?'手填角色条件':'手填示例条件';
  return prefix+(source.snapshot_at?' · '+fmtTime(source.snapshot_at):'')+(stamp&&(state?.stale||JSON.stringify(stamp)!==JSON.stringify(calculationStamp()))?' · 原快照已变化或过期，请核对':'')+'；固定参考';
}
function characterSummary(result){
  if(!result)return '尚未计算。';const strength=result.strength;
  if(!strength.usable)return strength.state==='pending'?'总力量待确认：'+strength.missing.join('、'):'总力量超出当前计算支持范围。';
  const values=strength.components;return `总力量 ${strength.effective} = 基础 ${values.base} + 根骨之戒 ${values.might_rings} + 力大无穷天赋 ${values.strongman} + 激素涌动 ${values.adrenaline}`;
}
function renderCharacterOrigin(){
  if(!$('#character-status'))return;
  $('#character-status').textContent=characterContextLabel()+(characterSavedPlan?' · 方案「'+characterSavedPlan.name+'」':'')+(characterDirty?'；表单已修改，下方结果属于修改前条件。':'；条件保持固定，快照刷新不会覆盖。');
  $('#character-use-current').disabled=!state?.data?.character_scene;
  $('#character-save').disabled=!characterResult||characterDirty;
  for(const id of ['character-to-manual','character-to-comparison','character-to-numeric'])$('#'+id).disabled=!characterResult||characterDirty||(id!=='character-to-manual'&&!characterResult.strength.usable);
  $('#character-to-numeric').disabled||=!numericalDetail?.result?.inputs?.some(field=>field.key==='strength');
  $('#character-reload-saved').hidden=!characterSavedPlan;
  $('#character-undo').disabled=!characterImportUndo;
  renderManualCharacterReference();renderComparisonCharacterReference();
}
function renderCharacterResult(){
  const target=$('#character-result');target.replaceChildren();
  const summary=document.createElement('p');summary.textContent=characterSummary(characterResult);summary.className=characterResult&&!characterResult.strength.usable?'rule-warning':'';target.append(summary);
  if(characterResult){const note=document.createElement('p');note.className='muted';note.textContent=characterResult.boundary+' 未确认的状态保留为待确认，不用0替代。';target.append(note);}
  renderCharacterOrigin();
}
function characterReference(){
  if(!characterResult||characterDirty)throw new Error('先按当前表单计算角色条件。');
  return {params:characterClone(characterResult.params),source:characterClone(characterSource),stamp:characterClone(characterStamp),saved:characterClone(characterSavedPlan),label:characterSavedPlan?'共享方案「'+characterSavedPlan.name+'」':'共享角色条件',signature:JSON.stringify(characterResult.params)};
}
function characterDraftLabel(){return characterUnsaved?'共享角色条件':'';}
function captureCharacterDraft(){
  if(!characterUnsaved)return null;
  return {format:1,form:captureNamedForm('#character-form'),source:characterClone(characterSource),stamp:characterClone(characterStamp),undo:characterImportUndo?{...characterClone(characterImportUndo),result:null,dirty:true,unsaved:true}:null,saved:characterSavedPlan?{id:characterSavedPlan.id,record_revision:characterSavedPlan.record_revision,name:characterSavedPlan.name,note:characterSavedPlan.note||'',origin:characterSavedPlan.origin}:null};
}
function showCharacterEditor(){
  $('#character-disclosure').open=true;
  $('#character-editor').scrollIntoView({block:'start'});
  $('#character-base').focus();
}
$('#workspace-character-open').addEventListener('click',showCharacterEditor);
$('#character-back-to-plans').addEventListener('click',()=>{
  $('#character-disclosure').open=false;
  $('#workspace-plans').scrollIntoView({block:'start'});
  if(typeof returnWorkspaceDetailFocus==='function'&&workspaceDetailReturn)returnWorkspaceDetailFocus();
  else $('#workspace-search').focus({preventScroll:true});
});
async function restoreCharacterDraft(raw,checkRecovery=()=>{}){
  if(!raw||raw.format!==1)throw new Error('角色条件草稿格式不正确');
  const serial=characterRequest;await loadCharacterCatalog();checkRecovery();
  if(serial!==characterRequest)throw new Error('载入期间角色条件已修改；当前输入和原副本都保留。');
  let saved=null;
  if(raw.saved){if(!/^[a-f0-9]{32}$/.test(raw.saved.id)||raw.saved.record_revision&&!/^[a-f0-9]{64}$/.test(raw.saved.record_revision))throw new Error('角色条件关联版本不正确');
    try{const latest=(await getJSON('/api/workspace/plan?'+new URLSearchParams({id:raw.saved.id}))).plan;if(latest.kind==='character')saved={...latest,...raw.saved,record_revision:raw.saved.record_revision||''};}catch(error){toast('原角色条件方案不可用，原始输入按独立草稿保留。',true);}
  }
  checkRecovery();if(serial!==characterRequest)throw new Error('载入期间角色条件已修改；当前输入和原副本都保留。');
  restoreNamedForm('#character-form',raw.form);characterRequest++;characterSource=raw.source||{mode:'manual',snapshot_at:null,slot:null};characterStamp=raw.stamp||null;characterSavedPlan=saved;
  characterImportUndo=raw.undo||null;characterResult=null;characterDirty=true;characterUnsaved=true;renderCharacterResult();$('#character-disclosure').open=true;
}
async function openCharacterPlan(plan,result,rulesChanged){
  const serial=++characterRequest,nav=navigationSerial;await loadCharacterCatalog();
  if(serial!==characterRequest||nav!==navigationSerial){if(nav===navigationSerial)inlineError($('#character-error'),'读取期间角色条件已有新编辑；当前输入仍保留，请核对后重新打开方案。');return false;}
  fillCharacterScene(plan.params);characterSavedPlan=plan;characterSource=cleanStoredOrigin(plan.origin);characterStamp=null;
  characterResult=result;characterDirty=false;characterUnsaved=false;characterImportUndo=null;renderCharacterResult();
  inlineError($('#character-error'),rulesChanged?'规则版本已有变化；当前资料按保存条件重新计算，请核对。':'');
  navigate('workspace');showCharacterEditor();return true;
}
function characterPlanSaved(plan,payload){
  if(characterSavedPlan&&characterSavedPlan.id!==plan.id&&characterSavedPlan.id!==planDraft?.existing?.id)return;
  characterSavedPlan=plan;characterUnsaved=characterDirty||JSON.stringify(characterResult?.params)!==JSON.stringify(payload.params);renderCharacterOrigin();
}
function rememberCharacterImport(){characterImportUndo={form:captureNamedForm('#character-form'),result:characterClone(characterResult),saved:characterClone(characterSavedPlan),source:characterClone(characterSource),stamp:characterClone(characterStamp),dirty:characterDirty,unsaved:characterUnsaved};}
$('#character-form').addEventListener('input',()=>{characterRequest++;characterDirty=true;characterUnsaved=true;characterSource={...characterSource,mode:'manual'};renderCharacterOrigin();});
$('#character-form').addEventListener('submit',async event=>{
  event.preventDefault();const serial=++characterRequest;let params;
  try{params=readCharacterScene();inlineError($('#character-error'),'');const result=await post('/api/workspace',{action:'character-calculate',params});if(serial!==characterRequest)return;
    characterResult=result;characterDirty=false;characterUnsaved=true;renderCharacterResult();
  }catch(error){if(serial===characterRequest)inlineError($('#character-error'),error.message);}
});
$('#character-use-current').addEventListener('click',()=>{
  const scene=state?.data?.character_scene;if(!scene)return;rememberCharacterImport();characterRequest++;fillCharacterScene(scene.params);
  characterSource=planSource();characterStamp=calculationStamp();characterResult=characterClone(scene);characterSavedPlan=null;characterDirty=false;characterUnsaved=true;renderCharacterResult();
});
$('#character-new').addEventListener('click',()=>{rememberCharacterImport();characterRequest++;fillCharacterScene(blankCharacterScene());characterResult=null;characterSource={mode:'example',snapshot_at:null,slot:null};characterStamp=null;characterSavedPlan=null;characterDirty=true;characterUnsaved=true;renderCharacterResult();$('#character-base').focus();});
$('#character-undo').addEventListener('click',()=>{const old=characterImportUndo;if(!old)return;characterRequest++;restoreNamedForm('#character-form',old.form);characterResult=old.result;characterSavedPlan=old.saved;characterSource=old.source;characterStamp=old.stamp;characterDirty=old.dirty;characterUnsaved=old.unsaved;characterImportUndo=null;renderCharacterResult();});
$('#character-save').addEventListener('click',()=>{if(!characterResult||characterDirty)return;openPlanSave({kind:'character',entry:null,params:characterResult.params,source:characterSource},characterSavedPlan,'角色力量条件');});
$('#character-reload-saved').addEventListener('click',()=>{if(characterSavedPlan)confirmReloadSavedPlan(characterSavedPlan.id);});
function renderManualCharacterReference(){
  const target=$('#manual-character-status');if(!target)return;
  target.textContent=manualCharacterReference?`${manualCharacterReference.label} · ${characterContextLabel(manualCharacterReference.source,manualCharacterReference.stamp)}。基础力量单独填写，提交时重新计算总力量，不重复相加。`:'尚未带入共享角色条件；基础力量只作基础参考。';
  $('#manual-character-clear').hidden=!manualCharacterReference;$('#manual-character-undo').hidden=!manualCharacterUndo;
}
function setManualCharacterReference(reference){manualCharacterReference=characterClone(reference);renderManualCharacterReference();}
$('#character-to-manual').addEventListener('click',()=>{try{const reference=characterReference();manualCharacterUndo={reference:characterClone(manualCharacterReference),base:$('#manual-form').elements.namedItem('strength').value};setManualCharacterReference(reference);$('#manual-form').elements.namedItem('strength').value=String(reference.params.base_strength??'');manualUnsaved=true;manualFormGeneration++;navigate('manual');$('#manual-character-status').scrollIntoView({block:'center'});}catch(error){inlineError($('#character-error'),error.message);}});
function editAttachedCharacter(reference,baseRaw){
  if(reference){rememberCharacterImport();characterRequest++;fillCharacterScene(reference.params);
    characterSource=characterClone(reference.source)||{mode:'manual',snapshot_at:null,slot:null};characterStamp=characterClone(reference.stamp);characterSavedPlan=characterClone(reference.saved);characterResult=null;characterDirty=true;characterUnsaved=true;
    if(baseRaw!==undefined){$('#character-base').value=baseRaw;if(baseRaw!==String(reference.params.base_strength))characterSource.mode='manual';}
    renderCharacterResult();
  }
  navigate('workspace');showCharacterEditor();
}
$('#manual-character-open').addEventListener('click',()=>editAttachedCharacter(manualCharacterReference,$('#manual-form').elements.namedItem('strength').value));
$('#manual-character-clear').addEventListener('click',()=>{manualCharacterUndo={reference:characterClone(manualCharacterReference),base:$('#manual-form').elements.namedItem('strength').value};setManualCharacterReference(null);manualUnsaved=true;manualFormGeneration++;});
$('#manual-character-undo').addEventListener('click',()=>{const old=manualCharacterUndo;if(!old)return;manualCharacterReference=old.reference;$('#manual-form').elements.namedItem('strength').value=old.base;manualCharacterUndo=null;manualUnsaved=true;manualFormGeneration++;renderManualCharacterReference();});
function currentCharacterStrength(){const value=state?.data?.character_scene?.strength;return value?.usable?value.effective:state?.data?.hero?.strength??10;}
function currentCharacterStrengthLabel(){const value=state?.data?.character_scene?.strength;return value?.usable?'角色条件已知总力量':value?.state==='pending'?'基础力量参考；总力量待确认：'+value.missing.join('、'):'基础力量参考；额外条件未确认';}
function renderComparisonCharacterReference(){
  const target=$('#compare-character-status');if(!target)return;
  target.textContent=compareCharacterReference?`${compareCharacterReference.label} · ${characterContextLabel(compareCharacterReference.source,compareCharacterReference.stamp)}。戒指比较按选定条件替换；其余比较共用角色力量。`:'独立有效力量输入。可从「收藏与方案」带入共享角色条件。';
  $('#compare-character-clear').hidden=!compareCharacterReference;$('#compare-scene-slot-label').hidden=!compareCharacterReference||$('#compare-kind').value!=='ring';
  $('#compare-strength').readOnly=!!compareCharacterReference;
  if(compareCharacterReference&&$('#compare-kind').value==='ring'){
    const slot=Number($('#compare-scene-slot').value),other=compareCharacterReference.params.rings.find((ring,index)=>index!==slot);
    for(const side of ['a','b']){
      const identity=compareItems[Number($('#compare-'+side).value)]?.key,pair=!!other&&!!identity&&other.identity===identity;
      $('#compare-pair-'+side).checked=!!pair;$('#compare-pair-'+side).disabled=true;
      $('#compare-pair-level-'+side).value=pair?(other.level??''):'0';$('#compare-pair-level-'+side).disabled=true;
      $('#compare-pair-curse-'+side).value=pair?(other.cursed===null?'unknown':other.cursed?'1':'0'):'0';$('#compare-pair-curse-'+side).disabled=true;
    }
  }else for(const side of ['a','b'])$('#compare-pair-'+side).disabled=comparePending;
}
function followComparisonCharacter(){
  const scene=state?.data?.character_scene;if(!scene){compareCharacterReference=null;renderComparisonCharacterReference();return;}
  compareCharacterReference={params:characterClone(scene.params),source:planSource(),stamp:calculationStamp(),label:'当前角色公开条件',signature:JSON.stringify(scene.params)};renderComparisonCharacterReference();
}
$('#character-to-comparison').addEventListener('click',()=>{try{const reference=characterReference();compareEditGeneration++;rememberComparisonImport();compareCharacterReference=reference;$('#compare-strength').value=String(characterResult.strength.effective);$('#compare-strength').dataset.edited='true';compareFixed=true;compareDirty=true;compareSessionUnsaved=true;compareError='';navigate('inventory');$('.comparison-panel').open=true;renderComparisonCharacterReference();refreshComparisonOrigin();$('#compare-submit').focus();}catch(error){inlineError($('#character-error'),error.message);}});
$('#compare-character-clear').addEventListener('click',()=>{compareEditGeneration++;rememberComparisonImport();compareCharacterReference=null;$('#compare-strength').dataset.edited='true';compareDirty=true;compareSessionUnsaved=true;renderComparisonCharacterReference();refreshComparisonOrigin();$('#compare-strength').focus();});
$('#compare-character-open').addEventListener('click',()=>editAttachedCharacter(compareCharacterReference));
function numericCharacterLabel(reference){return (reference.label+' · '+characterContextLabel(reference.source,reference.stamp)).slice(0,120);}
function applyCharacterToNumeric(){
  const detail=numericalDetail;if(!detail?.result?.inputs?.some(input=>input.key==='strength'))throw new Error('先打开一个含力量参数的数值试算，再带入共享条件。');
  const reference=characterReference();if(!characterResult.strength.usable)throw new Error('总力量尚未确认。');
  const key=detail.savedPlan?'plan:'+detail.savedPlan.id:detail.identity;
  const oldDetail=characterClone({...detail,importUndo:null});
  detail.importUndo={detail:oldDetail,raw:Object.fromEntries($$('[data-value-key]').map(input=>[input.dataset.valueKey,input.value])),formDraft:numericalFormDrafts.has(key)?{...numericalFormDrafts.get(key)}:null,draft:numericalDrafts.has(key)?{...numericalDrafts.get(key)}:null,calculated:numericalCalculated.get(key)||null};
  const input=$('[data-value-key="strength"]');input.value=String(characterResult.strength.effective);input.setCustomValidity?.('');
  detail.origins.strength=numericCharacterLabel(reference);detail.characterReference=reference;detail.dirty=true;detail.sessionUnsaved=true;
  numericalFormDrafts.set(key,Object.fromEntries($$('[data-value-key]').map(input=>[input.dataset.valueKey,input.value])));
  $('[data-origin-key="strength"]').textContent=detail.origins.strength;refreshNumericalOrigin();
  if(!$('#values-undo-import')){const button=document.createElement('button');button.id='values-undo-import';button.className='secondary';button.type='button';button.textContent='撤回本次带入';button.addEventListener('click',()=>restoreCharacterNumericImport());$('#value-calculator .backup-actions').append(button);}
  if(!$('#detail-dialog').open)$('#detail-dialog').showModal();toast('共享总力量已带入；其他原始参数保留，点击重新计算后使用。');
}
function restoreCharacterNumericImport(){
  const detail=numericalDetail,old=detail?.importUndo;if(!old)return;
  const key=detail.savedPlan?'plan:'+detail.savedPlan.id:detail.identity;
  numericalDetail={...old.detail,importUndo:null};
  for(const [store,value] of [[numericalFormDrafts,old.formDraft],[numericalDrafts,old.draft],[numericalCalculated,old.calculated]]){if(value===null)store.delete(key);else store.set(key,value);}
  for(const input of $$('[data-value-key]'))if(input.dataset.valueKey in old.raw)input.value=old.raw[input.dataset.valueKey];
  for(const cell of $$('[data-origin-key]'))cell.textContent=numericalDetail.origins[cell.dataset.originKey]||'手填参考';
  $('#values-undo-import')?.remove();refreshNumericalOrigin();
}
$('#character-to-numeric').addEventListener('click',()=>{try{applyCharacterToNumeric();}catch(error){inlineError($('#character-error'),error.message);}});
fillCharacterScene(blankCharacterScene());renderCharacterResult();
