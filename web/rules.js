'use strict';
let numericalRequest=0, numericalDetail=null;
const numericalDrafts=new Map();
const numericalFormDrafts=new Map();
const numericalCalculated=new Map();
const heroParameterKeys=['hero_level','max_hp','hp','depth','strength','current_shield'];
const healingParameterKeys=['power','healing_percent','healing_flat','vial'];
function currentParameterKeys(identity){return identity==='actors.buffs.healing'?[...heroParameterKeys,...healingParameterKeys]:identity?.startsWith('actors.hero.spells.')&&!identity.includes('$')?[...heroParameterKeys,'talent']:heroParameterKeys;}
const fixedNumericalDrafts=new Map();
function numericalDraftKey(detail=numericalDetail){return detail?.savedPlan?'plan:'+detail.savedPlan.id:detail?.identity;}
function sameNumericalParams(left,right){const keys=Object.keys(left||{}).sort(),other=Object.keys(right||{}).sort();return keys.length===other.length&&keys.every((key,index)=>key===other[index]&&Number(left[key])===Number(right[key]));}
function numericalSaveSignature(detail){return JSON.stringify({params:Object.fromEntries(detail.inputs.map(input=>[input.key,Number(input.value)])),origins:detail.origins,source:detail.source,levelSource:detail.levelSource,characterReference:detail.characterReference||null});}
function associateNumericalPlan(detail,plan,submitted,signature){
  const oldKey=numericalDraftKey(detail),newKey='plan:'+plan.id;
  // A copy keeps the original plan's local session; an entry draft moves to its new identity.
  rememberFixedNumericalDraft();
  const changed=!!detail.dirty||!!detail.pending||!sameNumericalParams(Object.fromEntries(detail.inputs.map(input=>[input.key,input.value])),submitted)||numericalSaveSignature(detail)!==signature;
  for(const map of [numericalFormDrafts,numericalDrafts,numericalCalculated]){
    const value=map.get(oldKey);
    if(changed&&value!==undefined)map.set(newKey,JSON.parse(JSON.stringify(value)));else map.delete(newKey);
    if(oldKey!==newKey&&!oldKey.startsWith('plan:'))map.delete(oldKey);
  }
  detail.savedPlan=plan;detail.userNote=plan.note;detail.sessionUnsaved=changed;
  if(!changed)detail.fixed=true;
  if(detail.calculated){detail.calculated={...detail.calculated,sessionUnsaved:changed};if(changed)numericalCalculated.set(newKey,detail.calculated);}
  if(detail.importUndo){
    const undo=detail.importUndo,prior=undo.detail;
    prior.savedPlan=plan;prior.userNote=plan.note;
    prior.sessionUnsaved=!!prior.dirty||!sameNumericalParams(Object.fromEntries(prior.inputs.map(input=>[input.key,input.value])),submitted)||numericalSaveSignature(prior)!==signature;
    if(!prior.sessionUnsaved)prior.fixed=true;
    if(prior.calculated)prior.calculated={...prior.calculated,sessionUnsaved:prior.sessionUnsaved};
    if(undo.calculated)undo.calculated={...undo.calculated,sessionUnsaved:prior.sessionUnsaved};
  }
  rememberFixedNumericalDraft();refreshNumericalOrigin();
}
function rememberFixedNumericalDraft(){const d=numericalDetail;if(!d?.savedPlan)return;fixedNumericalDrafts.set(d.savedPlan.id,JSON.parse(JSON.stringify({...d,pending:false,rawDraft:numericalFormDrafts.get('plan:'+d.savedPlan.id)||{}})));}
function currentSkillContext(identity){
  if(!identity?.startsWith('actors.hero.spells.')||identity.includes('$'))return null;
  const row=state?.error?null:state?.data?.hero?.skills?.[identity];
  const learned=row?.state==='learned'&&Number.isInteger(row.points)&&row.points>=0&&row.points<=4;
  const conditions=row?.conditions||'当前已学技能条件未确认；百科点数为独立示例。';
  return {state:row?.state||'unknown',conditions,params:learned&&row.talent&&row.points>0?{talent:row.points}:{},
    origin:learned?(state?.settings?.mode==='manual'?'手动局势':'快照')+` · 此技能已学 ${row.points} 点`:'示例 · '+conditions.split('；')[0]};
}
function heroInputOrigin(key,stamp=calculationStamp()){if(key==='talent'){const skill=currentSkillContext(numericalDetail?.identity);if(skill)return skill.origin;}return (stamp===null?'参考来源未确认':stamp?.mode==='manual'?'手动局势':'快照')+(key==='strength'?(typeof currentCharacterStrengthLabel==='function'?currentCharacterStrengthLabel():'基础力量参考'):key==='current_shield'?'公开当前护盾':'');}
function cancelNumericalDetail(){rememberFixedNumericalDraft();numericalRequest++;numericalDetail=null;}
$('#detail-dialog').addEventListener('close',cancelNumericalDetail);
function exampleHTML(example){
  const values=(example.values||[]).map(v=>`<div><dt>${escapeHTML(v.label)}</dt><dd>${escapeHTML(displayNumber(v.value))}<small>${escapeHTML(v.unit||'')}</small></dd>${v.condition?`<p class="numeric-condition">${escapeHTML(v.condition)}</p>`:''}</div>`).join('');
  const table=example.columns?`<div class="table-scroll" tabindex="0" aria-label="可横向滚动的数值表"><table><thead><tr>${example.columns.map(c=>`<th scope="col">${escapeHTML(c)}</th>`).join('')}</tr></thead><tbody>${example.rows.map((row,index)=>`<tr${example.selected_row===index?' class="selected-value-row" aria-current="true"':''}>${row.map(v=>`<td>${escapeHTML(displayNumber(v))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'';
  return `<section class="example-block"><h3>${escapeHTML(example.title)}</h3>${example.note?`<p class="muted">${escapeHTML(example.note)}</p>`:''}${values?`<dl class="numeric-values">${values}</dl>`:''}${table}</section>`;
}
// Presentation only; request parameters and backend arithmetic retain their precision.
function displayNumber(value){
  const format=number=>!Number.isFinite(number)?String(number):number!==0&&Math.abs(number)<1?String(Number(number.toPrecision(4))):Number.isInteger(number)?String(number):String(Number(number.toFixed(3)));
  if(typeof value==='number')return format(value);
  if(typeof value==='string'&&/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?%?$/i.test(value)){const percent=value.endsWith('%');return format(Number(percent?value.slice(0,-1):value))+(percent?'%':'');}
  return value;
}
function visibleCalculationContext(identity=numericalDetail?.identity){
  const hero=state?.data?.hero;
  if(!hero)return {};
  const barriers=(state.data.buffs||[]).filter(buff=>buff.kind==='Barrier'),shield=barriers.length===1?barriers[0].current_shield:null;
  const healing=(state.data.buffs||[]).filter(buff=>buff.kind==='Healing'),conditions={};
  if(identity==='actors.buffs.healing'&&healing.length===1){const buff=healing[0];for(const [field,key] of [['left','power'],['percent','healing_percent'],['flat','healing_flat'],['vial_level','vial']])if(typeof buff[field]==='number'&&Number.isFinite(buff[field]))conditions[key]=field==='percent'?buff[field]*100:buff[field];}
  return {hero_level:hero.level,max_hp:hero.ht,hp:hero.hp,depth:state.data.depth,strength:typeof currentCharacterStrength==='function'?currentCharacterStrength():hero.strength,...(Number.isInteger(shield)&&shield>=0&&shield<=10000?{current_shield:shield}:{}),...conditions,...currentSkillContext(identity)?.params};
}
function validNumericalInputs(inputs,detail){
  const invalid=inputs.find(input=>{
    const spec=detail.inputs?.find(field=>field.key===input.dataset.valueKey),raw=input.value.trim(),value=Number(raw);
    const syntax=/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(raw);
    const wrongStep=spec&&spec.step!=='any'&&Math.abs((value-(Number(spec.min)||0))/(Number(spec.step)||1)-Math.round((value-(Number(spec.min)||0))/(Number(spec.step)||1)))>1e-8;
    const bad=!syntax||!Number.isFinite(value)||!!spec&&(value<Number(spec.min)||value>Number(spec.max)||wrongStep);
    input.setCustomValidity?.(bad?'请填写范围内的完整数值；整数参数不能含小数。':'');
    return bad||!input.validity.valid;
  });
  if(!invalid)return true;
  detail.dirty=true;refreshNumericalOrigin();
  const warning=$('#values-freshness');
  if(warning){warning.className='rule-warning';warning.textContent='请先补全或修正数值参数；下方仍是修改前的结果。';}
  invalid.reportValidity();invalid.focus();return false;
}
async function loadNumericalDetail(identity,params={},levelOrigin='manual',options={}){
  const seq=++numericalRequest,container=$('#detail-rules');
  let restoredResult=null;
  const fixedDraft=options.fixed&&!options.ignoreDrafts&&fixedNumericalDrafts.get(options.savedPlan?.id);
  const savedId=options.savedPlan?.id||(numericalDetail?.identity===identity?numericalDetail?.savedPlan?.id:null);
  const draftKey=savedId?'plan:'+savedId:identity;
  if(typeof params==='number')params={level:params};
  if(options.fixed||options.ignoreDrafts||!numericalDetail || numericalDetail.identity!==identity){
    const skill=options.fixed||options.capturedContext?null:currentSkillContext(identity);
    const drafts=options.fixed||options.ignoreDrafts?{}:numericalDrafts.get(draftKey)||{};
    const source=options.fixed?null:options.sourceStamp!==undefined?options.sourceStamp:calculationStamp();
    numericalDetail={identity,levelOrigin,context:options.fixed?{...params}:{...(options.capturedContext?{}:visibleCalculationContext(identity)),...params,...drafts},
      origins:{},source,levelSource:source,unconfirmedSource:!options.fixed&&options.sourceStamp===null,fixed:!!options.fixed,savedPlan:options.savedPlan||null,rulesChanged:options.rulesChanged||false,
      skillConditions:options.skillConditions||skill?.conditions||'',skillState:options.skillState||skill?.state||null};
    for(const key of currentParameterKeys(identity))if(key in numericalDetail.context)numericalDetail.origins[key]=key in drafts?'手填保留':heroInputOrigin(key,numericalDetail.source);
    if('level' in params)numericalDetail.origins.level=keyOrigin(levelOrigin);
    if(levelOrigin==='unknown')numericalDetail.origins.level=keyOrigin(levelOrigin);
    if('tier' in params)numericalDetail.origins.tier=['known','unknown'].includes(levelOrigin)?'物品已知阶数':'示例 · 请核对';
    for(const key of Object.keys(drafts))numericalDetail.origins[key]='手填保留';
    if(skill&&!('talent' in drafts))numericalDetail.origins.talent=skill.origin;
    for(const [key,label] of Object.entries(options.fieldOrigins||{}))if(key in params&&!(key in drafts))numericalDetail.origins[key]=label;
    if(options.fixed)for(const key of Object.keys(params))numericalDetail.origins[key]=options.savedPlan?.origin?.fields?.[key]||'保存参数 · 固定参考';
    const calculated=!options.fixed&&!options.ignoreDrafts&&(numericalFormDrafts.has(draftKey)||numericalCalculated.get(draftKey)?.sessionUnsaved)&&numericalCalculated.get(draftKey);
    if(calculated){numericalDetail.sessionUnsaved=!!calculated.sessionUnsaved;numericalDetail.context={...calculated.params};numericalDetail.origins={...calculated.origins};numericalDetail.source=calculated.source;numericalDetail.levelSource=calculated.levelSource;if('skillConditions' in calculated){numericalDetail.skillConditions=calculated.skillConditions;numericalDetail.skillState=calculated.skillState;}restoredResult=calculated.result;}
    if(fixedDraft){numericalDetail={...fixedDraft,savedPlan:options.savedPlan,rulesChanged:!!options.rulesChanged||fixedDraft.result?.version!==options.result?.version};restoredResult=fixedDraft.result;numericalFormDrafts.set(draftKey,{...fixedDraft.rawDraft});}
  }else numericalDetail.context={...numericalDetail.context,...params};
  if(options.restoreSession){numericalDetail=JSON.parse(JSON.stringify(options.restoreSession.detail));restoredResult=numericalDetail.result;numericalDetail.importUndo=null;}

  const detail=numericalDetail,context=detail.context,currentDraftKey=()=>numericalDraftKey(detail);
  if(detail.skillConditions&&typeof showDetailContext==='function')showDetailContext(detail.skillConditions);
  detail.pending=true;
  for(const key of Object.keys(context))if(context[key]===undefined||context[key]===null)delete context[key];
  const previousForm=$('#value-calculator');
  const focused=previousForm?.contains(document.activeElement)?document.activeElement:null;
  const focusSelector=focused?.dataset.valueKey?`[data-value-key="${focused.dataset.valueKey}"]`:focused?.id?`#${focused.id}`:null;
  container.querySelector('.value-error')?.remove();
  if(previousForm)previousForm.querySelectorAll('input,button').forEach(el=>el.disabled=true);
  else container.innerHTML='<p role="status" class="muted">正在计算数值…</p>';
  try{
    const supplied=restoredResult||options.result;
    const response=supplied?{ok:true,json:async()=>supplied}:await fetch('/api/values?'+new URLSearchParams({id:identity,...context}));
    const result=await response.json();if(!response.ok)throw new Error(result.error||'数值暂时无法读取');
    if(seq!==numericalRequest||!$('#detail-dialog').open)return;
    if(result.status==='legacy'){container.innerHTML=`<p class="rule-warning">${escapeHTML(String(result.notice||'').replace('小数最多显示六位有效数字。','显示通常保留三位小数；微小非零值保留有效数字，计算使用原始精度。'))}</p>`;return;}
    const first=result.blocks[0];
    const lead=first?.values?.length<=6&&!first?.columns&&/^(当前 |按你的|命中概率|技能具体效果|当前治疗状态)/.test(first.title);
    detail.inputs=result.inputs;detail.result=result;
    if(options.commitPending)detail.sessionUnsaved=true;
    if(options.commitPending)numericalFormDrafts.delete(currentDraftKey());
    detail.dirty=!!result.missing_inputs?.length||(options.restoreSession?!!options.restoreSession.detail.dirty:!!fixedDraft?.dirty);
    for(const key of result.missing_inputs||[])detail.origins[key]='未确认 · 请填写';
    if(!options.restoreSession)detail.calculated=result.missing_inputs?.length?null:{params:Object.fromEntries(result.inputs.map(field=>[field.key,Number(field.value)])),origins:{...detail.origins},source:detail.source,levelSource:detail.levelSource,result,sessionUnsaved:!!detail.sessionUnsaved,skillConditions:detail.skillConditions,skillState:detail.skillState};
    if(detail.calculated&&!detail.fixed&&!restoredResult&&(!options.ignoreDrafts||!numericalFormDrafts.has(currentDraftKey()))&&(!options.ignoreDrafts||!numericalCalculated.get(currentDraftKey())?.sessionUnsaved)){numericalCalculated.set(currentDraftKey(),detail.calculated);if(numericalCalculated.size>64){const clean=Array.from(numericalCalculated).find(([,item])=>!item.sessionUnsaved);if(clean)numericalCalculated.delete(clean[0]);}}
    if(options.commitPending&&!detail.fixed){const drafts={};for(const input of result.inputs)if((detail.origins[input.key]||'').startsWith('手填'))drafts[input.key]=Number(input.value);numericalDrafts.set(currentDraftKey(),drafts);}
    const restoreFocus=focusSelector&&(document.activeElement===document.body||previousForm.contains(document.activeElement));
    const scrollTop=$('#detail-dialog').scrollTop;
    const formHTML=result.inputs.length?`<form id="value-calculator" class="value-calculator" novalidate><div class="form-grid">${result.inputs.map(input=>`<label>${escapeHTML(input.label)}<small data-origin-key="${escapeHTML(input.key)}">${escapeHTML(detail.origins[input.key]||'示例 · 请核对')}</small><input data-value-key="${escapeHTML(input.key)}" type="text" inputmode="${input.step==='any'?'decimal':'numeric'}" step="${input.step||1}" min="${input.min}" max="${input.max}" value="${input.value}" required></label>`).join('')}</div><div class="backup-actions"><button class="primary" type="submit">重新计算</button><button class="secondary" id="values-use-latest" type="button">带入最新角色状态</button><button class="secondary" id="values-use-character" type="button" ${result.inputs.some(input=>input.key==='strength')?'':'disabled'}>带入共享角色条件的总力量</button>${detail.importUndo?'<button class="secondary" id="values-undo-import" type="button">撤回本次带入</button>':''}${detail.savedPlan?'<button class="secondary" id="values-reload-saved" type="button">重新读取最新已保存方案 / 放弃会话草稿</button>':''}</div><p id="values-source" role="status"></p><p class="muted">力量优先带入已知角色条件的总力量；未确认时只提供基础参考。支线等效层数及其他战斗效果请另行核对。示例参数不会被当作已确认的实战状态。</p></form>`:'';
    container.innerHTML=`<div class="values-heading"><h3>具体数值</h3><span class="pill">${escapeHTML(result.version)}</span></div>${result.inputs.length?'<p id="values-freshness" role="status"></p>':''}${lead?exampleHTML(first):''}${formHTML}<p class="muted">${escapeHTML(String(result.notice||'').replace('小数最多显示六位有效数字。','显示通常保留三位小数；微小非零值保留有效数字，计算使用原始精度。'))}</p>${result.blocks.slice(lead?1:0).map(exampleHTML).join('')}${result.no_fixed_values?(result.non_numeric?'<p class="muted">这是阅读资料或场景标记，没有独立的伤害、生命或概率属性。</p>':'<p class="rule-warning">此条目的具体数值尚在核对，目前不提供未经确认的结果。</p>'):''}${provenanceHTML(result)}`;
    $('#values-use-character')?.addEventListener('click',()=>{try{applyCharacterToNumeric();}catch(error){toast(error.message,true);}});
    $$('[data-value-key]').forEach(input=>input.addEventListener('input',()=>{
      detail.origins[input.dataset.valueKey]='手填 · 尚未重新计算';
      $(`[data-origin-key="${input.dataset.valueKey}"]`).textContent=detail.origins[input.dataset.valueKey];
      detail.dirty=true;refreshNumericalOrigin();
      input.setCustomValidity?.('');
      {const key=currentDraftKey(),raw={...numericalFormDrafts.get(key),[input.dataset.valueKey]:input.value};numericalFormDrafts.set(key,raw);}
    }));
    $('#value-calculator')?.addEventListener('submit',event=>{
      event.preventDefault();if(!validNumericalInputs(Array.from($$('[data-value-key]')),detail))return;
      const next={...context};
      $$('[data-value-key]').forEach(input=>{
        const key=input.dataset.valueKey;next[key]=Number(input.value);
        if((detail.origins[key]||'').startsWith('手填'))detail.origins[key]='手填';
      });
      if(next.max_hp!==undefined&&next.hp===undefined)next.hp=Math.min(32,next.max_hp);
      if(next.target_max_hp!==undefined&&next.target_hp===undefined)next.target_hp=Math.min(40,next.target_max_hp);
      loadNumericalDetail(identity,next,detail.levelOrigin,{commitPending:true});
    });
    $('#values-use-latest')?.addEventListener('click',()=>{
      if(!state?.data || !detail.inputs)return;
      const key=currentDraftKey();
      const oldDetail=JSON.parse(JSON.stringify({...detail,importUndo:null,pending:false}));
      detail.importUndo={detail:oldDetail,raw:Object.fromEntries($$('[data-value-key]').map(input=>[input.dataset.valueKey,input.value])),formDraft:numericalFormDrafts.has(key)?{...numericalFormDrafts.get(key)}:null,draft:numericalDrafts.has(key)?{...numericalDrafts.get(key)}:null,calculated:numericalCalculated.get(key)||null};
      const latest=visibleCalculationContext();
      const skill=currentSkillContext(identity);
      const currentKeys=currentParameterKeys(identity);
      const retainedInputs=Array.from($$('[data-value-key]')).filter(input=>!currentKeys.includes(input.dataset.valueKey)||!(input.dataset.valueKey in latest));
      for(const input of retainedInputs)if(currentKeys.includes(input.dataset.valueKey)){detail.origins[input.dataset.valueKey]='手填保留 · 最新快照未确认'+(input.dataset.valueKey==='talent'&&skill?' · '+skill.conditions.split('；')[0]:'');$(`[data-origin-key="${input.dataset.valueKey}"]`).textContent=detail.origins[input.dataset.valueKey];}
      const raw={...numericalFormDrafts.get(key)};
      for(const input of $$('[data-value-key]'))if(currentKeys.includes(input.dataset.valueKey)&&input.dataset.valueKey in latest){input.value=String(latest[input.dataset.valueKey]);input.setCustomValidity?.('');raw[input.dataset.valueKey]=input.value;detail.origins[input.dataset.valueKey]=heroInputOrigin(input.dataset.valueKey);$(`[data-origin-key="${input.dataset.valueKey}"]`).textContent=detail.origins[input.dataset.valueKey];}
      if(skill){detail.skillState=skill.state;detail.skillConditions=skill.conditions+(!('talent' in latest)&&retainedInputs.some(input=>input.dataset.valueKey==='talent')?' 本次保留原填写点数作为独立参考。':'');if(typeof showDetailContext==='function')showDetailContext(detail.skillConditions);}
      numericalFormDrafts.set(key,raw);detail.dirty=true;
      if(!validNumericalInputs(retainedInputs,detail))return;
      const next={...context,...visibleCalculationContext()};
      retainedInputs.forEach(input=>{const key=input.dataset.valueKey;
        next[key]=Number(input.value);
        if(key!=='talent'&&(detail.origins[key]||'').startsWith('手填'))detail.origins[key]='手填';
      });
      for(const key of currentKeys)if(key in latest)detail.origins[key]=heroInputOrigin(key);
      detail.source=calculationStamp();detail.unconfirmedSource=false;
      detail.fixed=false;
      loadNumericalDetail(identity,next,detail.levelOrigin,{commitPending:true});
    });
    if(!options.ignoreDrafts){const raw=options.restoreSession?options.restoreSession.raw:numericalFormDrafts.get(currentDraftKey());for(const input of $$('[data-value-key]'))if(raw&&input.dataset.valueKey in raw){input.value=raw[input.dataset.valueKey];if(!options.restoreSession)detail.origins[input.dataset.valueKey]='手填 · 尚未重新计算';$(`[data-origin-key="${input.dataset.valueKey}"]`).textContent=detail.origins[input.dataset.valueKey];if(!options.restoreSession)detail.dirty=true;}}
    $('#values-undo-import')?.addEventListener('click',()=>{const snapshot=detail.importUndo;if(!snapshot)return;const key=currentDraftKey();for(const [map,value] of [[numericalFormDrafts,snapshot.formDraft],[numericalDrafts,snapshot.draft],[numericalCalculated,snapshot.calculated]]){if(value===null)map.delete(key);else map.set(key,value);}loadNumericalDetail(identity,snapshot.detail.context,snapshot.detail.levelOrigin,{restoreSession:snapshot});});
    $('#values-reload-saved')?.addEventListener('click',()=>confirmReloadSavedPlan(detail.savedPlan.id));
    refreshNumericalOrigin();
    if(typeof renderDetailTools==='function')renderDetailTools();
    $('#values-copy-basis')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(provenanceText(result));$('#values-copy-status').textContent='已复制依据与适用范围';}catch(error){$('#values-copy-status').textContent='复制不可用；请在下方可选文本中选取并复制。';}});
    if(restoreFocus)($(focusSelector)||$('#values-use-latest'))?.focus({preventScroll:true});
    $('#detail-dialog').scrollTop=scrollTop;
  }catch(error){if(seq===numericalRequest&&$('#detail-dialog').open){detail.dirty=true;refreshNumericalOrigin();const message=`<p role="alert" class="rule-warning value-error">${escapeHTML(error.message)}</p>`;if(previousForm?.isConnected)previousForm.insertAdjacentHTML('afterend',message);else container.innerHTML=message;}}
  finally{if(seq===numericalRequest){detail.pending=false;rememberFixedNumericalDraft();}if(seq===numericalRequest&&previousForm?.isConnected){
    previousForm.querySelectorAll('input,button').forEach(el=>el.disabled=false);
    if(focusSelector&&(document.activeElement===document.body||previousForm.contains(document.activeElement)))($(focusSelector)||$('#values-use-latest'))?.focus({preventScroll:true});
  }}
}
function keyOrigin(origin){return origin==='known'?'物品已知等级':origin==='unknown'?'等级未知 · +0示例':'示例';}
function calculationStamp(){return state?.data?{modified:state.modified,slot:state.active_slot,mode:state.settings.mode,save_root:state.settings.save_root,revision:state.revision,started:state.started}:null;}
function refreshNumericalOrigin(){
  const d=numericalDetail,freshness=$('#values-freshness'),source=$('#values-source');
  if(!d || !freshness || !source)return;
  const now=calculationStamp(),stamp=d.dirty&&d.calculated?d.calculated.source:d.source;
  const snapshotUsed=d.inputs?.some(i=>/^(快照|手动局势)/.test(d.origins[i.key]||'')||['物品已知等级','物品已知阶数'].includes(d.origins[i.key]));
  const changed=stamp&&(!now||['modified','slot','mode','save_root','revision','started'].some(k=>stamp[k]!==now[k]));
  const levelOld=(d.origins.level==='物品已知等级'||d.origins.tier==='物品已知阶数')&&d.levelSource&&(!now||['modified','slot','mode','save_root','revision','started'].some(k=>d.levelSource[k]!==now[k]));
  const old=snapshotUsed&&(!now||state.stale||changed||levelOld);
  freshness.className=old||d.dirty||d.unconfirmedSource?'rule-warning':'muted';
  freshness.textContent=d.dirty?'输入已修改，尚未计算；下方仍是修改前的结果，请重新计算。':d.unconfirmedSource?'参考来源未确认；请核对原参数或明确带入最新状态。':levelOld?'物品等级来自较早快照，无法唯一确认现在是哪件装备；请核对等级后手填。':old?(changed?'游戏快照已经变化；下方结果仍按原参数计算，请带入最新状态或核对后手填。':'这些结果含旧快照参数，请按游戏画面核对。'):'按下列参数计算；随机范围和生效条件见各表。';
  if(d.sessionUnsaved&&!d.fixed&&!d.dirty)freshness.textContent+=' 本次会话试算尚未命名保存。';
  source.className='muted';source.textContent=stamp?`首次带入：${stamp.mode==='manual'?'手动局势':`槽位 ${stamp.slot}`} · ${fmtTime(stamp.modified)}。手填保留项不会自动跟随游戏。`:d.unconfirmedSource?'参考来源未确认；保留带入时的参数。':'没有角色快照；参数为示例或手填。';
  if(d.characterReference){source.textContent+=' '+numericCharacterLabel(d.characterReference)+(d.characterReference.signature!==JSON.stringify(characterResult?.params)?'；当前共享条件已有变化，此处保留带入时的力量。':'');}
  const button=$('#values-use-latest');if(button)button.disabled=!now;
  if(d.fixed){source.textContent=`固定保存参数。${typeof originLabel==='function'?originLabel(d.savedPlan?.origin):'过去来源只用于追溯，不绑定当前角色。'}`;freshness.textContent=d.dirty?'会话草稿已修改，尚未保存；下方仍是修改前的结果，请重新计算。':`${d.sessionUnsaved?'会话计算草稿尚未保存。':'按保存参数计算，'}不跟随最新快照。${d.rulesChanged?'资料规则已更新；请重新计算并核对保留结果与当前规则的差异。':''}`;freshness.className=d.dirty||d.rulesChanged?'rule-warning':'muted';}
}
function provenanceText(result){
  const p=result.provenance||{};
  const sources=p.sources||p.links||[];
  return [`游戏资料版本：${result.version||p.version||'见条目版本'}`,...(p.revision?[`固定官方源码版本：${p.revision}`]:[]),p.summary||p.notice||'玩法说明来自游戏；具体数值是灯火按所填参数计算。',p.scope||p.boundary||result.notice||'适用于所填条件；不包含未填写的戒指、天赋、敌方防御或临时状态。',...(Array.isArray(p.limits)?p.limits:[]),...sources.map(s=>typeof s==='string'?s:`${s.label||s.title||'官方来源'}：${s.url||''}`)].join('\n').replace('小数最多显示六位有效数字。','显示通常保留三位小数；微小非零值保留有效数字，计算使用原始精度。');
}
function sourceURL(value){try{const url=new URL(value);return url.protocol==='https:'&&['github.com','raw.githubusercontent.com','shatteredpixel.com'].includes(url.hostname)?url.href:null;}catch(error){return null;}}
function provenanceHTML(result){
  const p=result.provenance||{},sources=p.sources||p.links||[];
  return `<details class="provenance"><summary>依据与适用范围 · 游戏资料 ${escapeHTML(result.version||p.version||'')}</summary><p>玩法说明来自游戏资料；具体数值是灯火按所填条件计算。请核对游戏版本、随机范围与生效条件。</p>${sources.map(s=>{const url=sourceURL(typeof s==='string'?s:s.url);return url?`<a href="${escapeHTML(url)}" target="_blank" rel="noreferrer">${escapeHTML(typeof s==='string'?'固定官方来源':s.label||s.title||'固定官方来源')}</a>`:'';}).join(' ')}<pre tabindex="0" aria-label="可离线复制的计算依据">${escapeHTML(provenanceText(result))}</pre><button type="button" id="values-copy-basis" class="secondary">复制依据与适用范围</button><p id="values-copy-status" role="status"></p></details>`;
}
