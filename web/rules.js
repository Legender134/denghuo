'use strict';
function setNumericalRaw(input,value){if(input.tagName==='SELECT'&&!Array.from(input.options).some(option=>option.value===String(value))){const option=document.createElement('option');option.value=String(value);option.textContent='需核对原始输入：'+value;input.append(option);}input.value=value;}
let numericalRequest=0, numericalDetail=null;
const numericalDrafts=new Map();
const numericalFormDrafts=new Map();
const numericalCalculated=new Map();
const heroParameterKeys=['hero_level','max_hp','hp','depth','strength','current_shield'];
const healingParameterKeys=['power','healing_percent','healing_flat','vial'];
const healingPotionIds=new Set(['items.potions.potionofhealing','items.potions.elixirs.elixirofhoneyedhealing']);
const bossReferenceIds=new Set(['goo','tengu','dm300','dwarfking','yogdzewa','pylon'].map(name=>'actors.mobs.'+name));
function currentParameterKeys(identity){return bossReferenceIds.has(identity)?[...heroParameterKeys,'stronger_bosses']:identity==='actors.buffs.corrosion'?[...heroParameterKeys,'power','remaining_turns','corrosion_public']:identity==='items.armor.glyphs.viscosity$defereddamage'?[...heroParameterKeys,'damage']:identity==='actors.buffs.healing'?[...heroParameterKeys,...healingParameterKeys]:healingPotionIds.has(identity)?[...heroParameterKeys,'vial']:['items.waterskin','items.dewdrop'].includes(identity)?[...heroParameterKeys,'shielding_dew','vial','dew_volume']:identity?.startsWith('actors.hero.talent.')||identity?.startsWith('actors.hero.spells.')&&!identity.includes('$')?[...heroParameterKeys,'talent']:heroParameterKeys;}
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
  if(typeof showPlanNote==='function')showPlanNote(plan.note);
  showNumericalSkillContext(detail);
}
function showNumericalSkillContext(detail){if(typeof showDetailContext!=='function')return;if(detail.seedReference)showDetailContext((detail.seedAccess||'独立种子参考')+' · 修正未计入');else if(detail.skillConditions)showDetailContext((detail.fixed?'保存时的技能参考：':'')+detail.skillConditions);}
function rememberFixedNumericalDraft(){const d=numericalDetail;if(!d?.savedPlan)return;fixedNumericalDrafts.set(d.savedPlan.id,JSON.parse(JSON.stringify({...d,pending:false,rawDraft:numericalFormDrafts.get('plan:'+d.savedPlan.id)||{}})));}
function currentSkillContext(identity){
  const spell=identity?.startsWith('actors.hero.spells.')&&!identity.includes('$'),talent=identity?.startsWith('actors.hero.talent.'),resource=['items.waterskin','items.dewdrop'].includes(identity),ability=identity?.startsWith('actors.hero.abilities.');
  if(!spell&&!talent&&!resource&&!ability)return null;
  const hero=state?.error?null:state?.data?.hero,build=hero?.build;
  if(ability)return {state:build?.ability?.id===identity?'selected':'unknown',params:{},conditions:build?.ability?.id===identity?build.ability.conditions:'未确认当前选择此护甲能力；以下为独立参考。',origin:'所选护甲能力参考'};
  const target=resource?'actors.hero.talent.shielding_dew':identity;
  const row=spell?hero?.skills?.[identity]:build?.talents?.[target]||(build?.state==='known'?{state:'not_applicable',points:0,conditions:'当前职业与转职不提供此天赋，按未投入 0 点参考。'}:null);
  const learned=(spell?row?.state==='learned':!!row)&&Number.isInteger(row.points)&&row.points>=0&&row.points<=4;
  const conditions=row?.conditions||'当前已学技能条件未确认；百科点数为独立示例。';
  return {state:row?.state||'unknown',conditions,params:learned&&(!spell||row.talent&&row.points>0)?{[resource?'shielding_dew':'talent']:row.points}:{},
    origin:learned?(state?.settings?.mode==='manual'?'手动局势':'快照')+` · ${spell?'此技能已学':'此天赋已投入'} ${row.points} 点`:'示例 · '+conditions.split('；')[0]};
}
function heroInputOrigin(key,stamp=calculationStamp()){if(key==='talent'||key==='shielding_dew'){const skill=currentSkillContext(numericalDetail?.identity);if(skill)return skill.origin;}const dotLabels={damage:'游戏公开的当前延缓池（整数）',power:'游戏公开的当前酸蚀强度（取整）',remaining_turns:'游戏公开的酸蚀剩余时长（最多两位小数）',corrosion_public:'公开显示精度范围；隐藏小数未带入'};return (stamp===null?'参考来源未确认':stamp?.mode==='manual'?'手动局势':'快照')+(key in currentDotContext(numericalDetail?.identity)?' · '+dotLabels[key]:key==='strength'?(typeof currentCharacterStrengthLabel==='function'?currentCharacterStrengthLabel():'基础力量参考'):key==='current_shield'?'公开当前护盾':'');}
function cancelNumericalDetail(){
  rememberFixedNumericalDraft();
  const detail=numericalDetail,key=numericalDraftKey(detail);
  // Closing keeps the whole editable form, including untouched blanks and field provenance.
  if(detail&&!detail.savedPlan&&detail.result&&numericalFormDrafts.has(key)){
    numericalFormDrafts.set(key,Object.fromEntries($$('[data-value-key]').map(input=>[input.dataset.valueKey,input.value])));
    numericalCalculated.set(key,{params:{...(detail.calculated?.params||detail.context)},origins:{...detail.origins},source:detail.source,
      levelSource:detail.levelSource,result:detail.result,sessionUnsaved:true,characterReference:detail.characterReference||null,
      skillConditions:detail.skillConditions,skillState:detail.skillState,seedReference:detail.seedReference,seedAccess:detail.seedAccess,seedConditions:detail.seedConditions,unconfirmedSource:detail.unconfirmedSource});
  }
  numericalRequest++;numericalDetail=null;
}
$('#detail-dialog').addEventListener('close',cancelNumericalDetail);
function exampleHTML(example){
  const values=(example.values||[]).map(v=>`<div><dt>${escapeHTML(v.label)}</dt><dd>${escapeHTML(displayNumber(v.value))}<small>${escapeHTML(v.unit||'')}</small></dd>${v.condition&&!example.compact_conditions?`<p class="numeric-condition">${escapeHTML(v.condition)}</p>`:''}</div>`).join('');
  // Collapse only byte-identical conditions shared by every normal loot row.
  const sharedCondition=example.title==='掉落物、数量与概率'&&example.columns?.at(-1)==='条件'&&example.rows?.length>1&&typeof example.rows[0].at(-1)==='string'&&example.rows[0].at(-1)&&example.rows.every(row=>row.length===example.columns.length&&row.at(-1)===example.rows[0].at(-1))?example.rows[0].at(-1):'';
  const columns=sharedCondition?example.columns.slice(0,-1):example.columns,rows=sharedCondition?example.rows.map(row=>row.slice(0,-1)):example.rows;
  const common=sharedCondition?`<details class="numeric-note-details"><summary>查看共同掉落条件（全部${example.rows.length}项）</summary><p class="muted">${escapeHTML(sharedCondition)}</p></details>`:'';
  const table=example.columns?`<div class="table-scroll" tabindex="0" aria-label="可横向滚动的数值表"><table><thead><tr>${columns.map(c=>`<th scope="col">${escapeHTML(c)}</th>`).join('')}</tr></thead><tbody>${rows.map((row,index)=>`<tr${example.selected_row===index?' class="selected-value-row" aria-current="true"':''}>${row.map((v,column)=>`<td>${column===0&&typeof referenceTextHTML==='function'?referenceTextHTML(displayNumber(v)):escapeHTML(displayNumber(v))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'';
  const noteText=example.note_summary||example.note;
  const note=example.note?`<p class="muted">${escapeHTML(sharedCondition?noteText.replace('按条件列查看概率','按共同条件查看概率'):noteText)}</p>`:'';
  const detail=example.note&&example.note_summary?`<details class="numeric-note-details"><summary>展开计算规则与适用范围</summary><p class="muted">${escapeHTML(example.note)}</p></details>`:'';
  return `<section class="example-block">${example.omit_heading?'':`<h3>${escapeHTML(example.title)}</h3>`}${note}${values?`<dl class="numeric-values">${values}</dl>`:''}${common}${table}${detail}${example.compact_conditions?comparisonConditionsHTML(example.values||[]):''}</section>`;
}
// Presentation only; request parameters and backend arithmetic retain their precision.
function displayNumber(value){
  const format=number=>!Number.isFinite(number)?String(number):number!==0&&Math.abs(number)<1?String(Number(number.toPrecision(4))):Number.isInteger(number)?String(number):String(Number(number.toFixed(3)));
  if(typeof value==='number')return format(value);
  if(typeof value==='string'&&/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?%?$/i.test(value)){const percent=value.endsWith('%');return format(Number(percent?value.slice(0,-1):value))+(percent?'%':'');}
  return value;
}
function currentDotContext(identity){
  if(state?.error||!['actors.buffs.corrosion','items.armor.glyphs.viscosity$defereddamage'].includes(identity))return {};
  const buffs=(state?.data?.buffs||[]).filter(buff=>buff.reference_id===identity);
  if(buffs.length!==1)return {};
  const fields=buffs[0].public_dot||{},keys=identity==='actors.buffs.corrosion'?['power','remaining_turns','corrosion_public']:['damage'];
  return Object.fromEntries(keys.filter(key=>typeof fields[key]==='number'&&Number.isFinite(fields[key])).map(key=>[key,fields[key]]));
}
function visibleCalculationContext(identity=numericalDetail?.identity,{includeBoss=false}={}){
  const hero=state?.error?null:state?.data?.hero;
  if(!hero)return {};
  const barriers=(state.data.buffs||[]).filter(buff=>buff.kind==='Barrier'),shield=barriers.length===1?barriers[0].current_shield:barriers.length===0&&state.data.buffs_known===true&&hero.build?.state==='known'?0:null;
  const healing=(state.data.buffs||[]).filter(buff=>buff.kind==='Healing'),conditions={};
  const mask=state.data.challenges_mask;
  if(includeBoss&&bossReferenceIds.has(identity)&&state.data.challenges_known===true&&Number.isInteger(mask)&&mask>=0&&mask<=511)conditions.stronger_bosses=Number(!!(mask&256));
  if(identity==='actors.buffs.healing'&&healing.length===1){const buff=healing[0];for(const [field,key] of [['left','power'],['percent','healing_percent'],['flat','healing_flat'],['vial_level','vial']])if(typeof buff[field]==='number'&&Number.isFinite(buff[field]))conditions[key]=field==='percent'?buff[field]*100:buff[field];}
  if(healingPotionIds.has(identity)||['items.waterskin','items.dewdrop'].includes(identity)){
    const items=state.data.items||[],vials=items.filter(item=>item.kind==='VialOfBlood'),water=items.filter(item=>item.key==='items.waterskin'&&item.known&&item.available);
    if(!vials.length&&hero.build?.state==='known'&&(!healingPotionIds.has(identity)||state.settings?.mode==='save'))conditions.vial=-1;
    else if(vials.length===1&&vials[0].known&&vials[0].available&&vials[0].level_known&&Number.isInteger(vials[0].level)&&vials[0].level>=-1&&vials[0].level<=3)conditions.vial=vials[0].level;
    if(identity==='items.waterskin'&&water.length===1&&Number.isInteger(water[0].volume))conditions.dew_volume=water[0].volume;
  }
  return {hero_level:hero.level,max_hp:hero.ht,hp:hero.hp,depth:state.data.depth,strength:typeof currentCharacterStrength==='function'?currentCharacterStrength():hero.strength,...(Number.isInteger(shield)&&shield>=0&&shield<=10000?{current_shield:shield}:{}),...conditions,...currentDotContext(identity),...currentSkillContext(identity)?.params};
}
function numericalAnswerBasis(detail,result){
  const key=healingPotionIds.has(detail.identity)?'vial':['actors.buffs.poison','actors.buffs.bleeding'].includes(detail.identity)?'power':detail.identity==='items.waterskin'?'dew_volume':bossReferenceIds.has(detail.identity)?'stronger_bosses':null;
  const input=result.inputs.find(field=>field.key===key);if(!input)return '';
  const label=key==='vial'?`凝血试管 ${Number(input.value)<0?'无效果（−1）':'+'+displayNumber(input.value)}`:key==='power'?`${detail.identity==='actors.buffs.poison'?'剩余中毒':'当前流血强度'} ${displayNumber(input.value)}${detail.identity==='actors.buffs.poison'?' 回合':''}`:key==='dew_volume'?`露珠 ${displayNumber(input.value)} 滴`:Number(input.value)===1?'绝命头目':'普通首领';
  return `${label}（${detail.origins[key]||'示例 · 请核对'}）`;
}
function equipmentAnswer(detail,first){
  const values=first?.values||[],[low,high]=values;
  if(!detail.identity.startsWith('items.weapon.')||!/^当前 [+-]\d+ 装备数值$/.test(first?.title||'')||low?.label!=='最低基础伤害'||high?.label!=='最高基础伤害'||low.unit!==high.unit||low.condition!==high.condition)return null;
  const strength=values.find(value=>value.label==='力量需求');
  const grade=first.title.match(/^当前 ([+-]\d+) 装备数值$/)[1],origin=detail.origins?.level||'',unknown=detail.levelOrigin==='unknown'||origin.includes('等级未知');
  const basis=`${grade} ${origin.startsWith('手填')?'手填假设':unknown?'示例':'级参考'}${unknown?' · 等级未鉴定':''}`;
  return {...first,basis,primary_values:[{...low,label:'基础伤害',value:`${displayNumber(low.value)}–${displayNumber(high.value)}`},...(strength?[{...strength,label:'基础力量需求',condition:''}]:[])],summary_note:detail.seedReference?'':'基础数值 · 修正未计入'};
}
function validNumericalInputs(inputs,detail){
  const invalid=inputs.find(input=>{
    const spec=detail.inputs?.find(field=>field.key===input.dataset.valueKey),raw=input.value.trim(),value=Number(raw);
    const syntax=/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(raw);
    const corrosionExact=detail.identity==='actors.buffs.corrosion'&&$('[data-value-key="corrosion_public"]')?.value==='0';
    const step=corrosionExact&&['power','remaining_turns'].includes(input.dataset.valueKey)?'any':spec?.step;
    const wrongStep=spec&&step!=='any'&&Math.abs((value-(Number(spec.min)||0))/(Number(step)||1)-Math.round((value-(Number(spec.min)||0))/(Number(step)||1)))>1e-8;
    const bad=!syntax||!Number.isFinite(value)||!!spec&&(value<Number(spec.min)||value>Number(spec.max)||wrongStep);
    input.setCustomValidity?.(bad?'请填写范围内的完整数值；整数参数不能含小数。':'');
    return bad||!input.validity.valid;
  });
  if(!invalid)return true;
  detail.dirty=true;refreshNumericalOrigin();
  const warning=$('#values-freshness');
  if(warning){warning.className='rule-warning';warning.textContent='参数有误 · 请修正后重新计算';}
  invalid.reportValidity();invalid.focus();return false;
}
async function loadNumericalDetail(identity,params={},levelOrigin='manual',options={}){
  // A captured reference must not replace unfinished work for the same entry.
  const retainedDraft=options.capturedContext&&options.ignoreDrafts&&!options.fixed&&
    (numericalFormDrafts.has(identity)||numericalCalculated.get(identity)?.sessionUnsaved);
  if(retainedDraft){options={...options,ignoreDrafts:false};if(typeof showDetailContext==='function')showDetailContext('已打开此条目的未完成试算；可继续编辑，或明确带入最新角色状态。');}
  const seq=++numericalRequest,container=$('#detail-rules');
  const sameIdentity=numericalDetail?.identity===identity;
  let restoredResult=null;
  const fixedDraft=options.fixed&&!options.ignoreDrafts&&fixedNumericalDrafts.get(options.savedPlan?.id);
  const savedId=options.savedPlan?.id||(numericalDetail?.identity===identity?numericalDetail?.savedPlan?.id:null);
  const draftKey=savedId?'plan:'+savedId:identity;
  if(typeof params==='number')params={level:params};
  if(options.fixed||options.ignoreDrafts||!numericalDetail || numericalDetail.identity!==identity){
    const skill=options.fixed||options.capturedContext||options.exactContext?null:currentSkillContext(identity);
    const drafts=options.fixed||options.ignoreDrafts?{}:numericalDrafts.get(draftKey)||{};
    const source=options.fixed?null:options.sourceStamp!==undefined?options.sourceStamp:calculationStamp();
    const seedReference=!options.fixed&&options.capturedContext&&options.sourceStamp===null&&typeof options.seedReference==='string'?options.seedReference:null;
    if(!options.fixed&&options.capturedContext&&healingPotionIds.has(identity)&&!('vial' in params)){
      const latest=calculationStamp();
      if(source&&latest&&['started','save_root','mode','slot','revision','modified'].every(key=>source[key]===latest[key])){
        const vial=visibleCalculationContext(identity).vial;
        if(vial!==undefined)params={...params,vial};
      }
    }
    numericalDetail={identity,levelOrigin,context:options.fixed?{...params}:{...(options.capturedContext||options.exactContext?{}:visibleCalculationContext(identity)),...params,...drafts},
      origins:{},source,levelSource:source,seedReference,seedAccess:seedReference?options.seedAccess||'':null,seedConditions:seedReference?options.seedConditions||'':null,unconfirmedSource:!options.fixed&&options.sourceStamp===null&&!seedReference,fixed:!!options.fixed,savedPlan:options.savedPlan||null,rulesChanged:options.rulesChanged||false,
      skillConditions:options.skillConditions||skill?.conditions||'',skillState:options.skillState||skill?.state||null,
      foodReference:identity.startsWith('items.food.')&&options.capturedContext&&options.foodReference?JSON.parse(JSON.stringify(options.foodReference)):null};
    for(const key of currentParameterKeys(identity))if(key in numericalDetail.context)numericalDetail.origins[key]=key in drafts?'手填保留':heroInputOrigin(key,numericalDetail.source);
    if('level' in params)numericalDetail.origins.level=keyOrigin(levelOrigin);
    if(levelOrigin==='unknown')numericalDetail.origins.level=keyOrigin(levelOrigin);
    if('tier' in params)numericalDetail.origins.tier=levelOrigin==='revealed'?'存档物品阶数 · 主动揭示模式':['known','unknown'].includes(levelOrigin)?'物品已知阶数':'示例 · 请核对';
    for(const key of Object.keys(drafts))numericalDetail.origins[key]='手填保留';
    if(skill&&!('talent' in drafts))numericalDetail.origins.talent=skill.origin;
    for(const [key,label] of Object.entries(options.fieldOrigins||{}))if(key in params&&!(key in drafts))numericalDetail.origins[key]=label;
    if(options.fixed)for(const key of Object.keys(params))numericalDetail.origins[key]=options.savedPlan?.origin?.fields?.[key]||'保存参数 · 固定参考';
    const calculated=!options.fixed&&!options.ignoreDrafts&&(numericalFormDrafts.has(draftKey)||numericalCalculated.get(draftKey)?.sessionUnsaved)&&numericalCalculated.get(draftKey);
    if(calculated){numericalDetail.sessionUnsaved=!!calculated.sessionUnsaved;numericalDetail.context={...calculated.params};numericalDetail.origins={...calculated.origins};numericalDetail.source=calculated.source;numericalDetail.levelSource=calculated.levelSource;numericalDetail.seedReference=calculated.seedReference||null;numericalDetail.seedAccess=calculated.seedAccess||null;numericalDetail.seedConditions=calculated.seedConditions||null;numericalDetail.unconfirmedSource=!!calculated.unconfirmedSource;numericalDetail.characterReference=calculated.characterReference||null;if('skillConditions' in calculated){numericalDetail.skillConditions=calculated.skillConditions;numericalDetail.skillState=calculated.skillState;}restoredResult=calculated.result;}
    if(fixedDraft){numericalDetail={...fixedDraft,savedPlan:options.savedPlan,rulesChanged:!!options.rulesChanged||fixedDraft.result?.version!==options.result?.version};restoredResult=fixedDraft.result;numericalFormDrafts.set(draftKey,{...fixedDraft.rawDraft});}
  }else numericalDetail.context={...numericalDetail.context,...params};
  if(options.restoreSession){numericalDetail=JSON.parse(JSON.stringify(options.restoreSession.detail));restoredResult=numericalDetail.result;numericalDetail.importUndo=null;}

  const detail=numericalDetail,context=detail.context,currentDraftKey=()=>numericalDraftKey(detail);
  showNumericalSkillContext(detail);
  detail.pending=true;
  for(const key of Object.keys(context))if(context[key]===undefined||context[key]===null)delete context[key];
  const previousForm=$('#value-calculator');
  const advancedOpen=sameIdentity&&previousForm?.querySelector('.numeric-advanced')?.open;
  const focused=previousForm?.contains(document.activeElement)?document.activeElement:null;
  const focusSelector=focused?.dataset.valueKey?`[data-value-key="${focused.dataset.valueKey}"]`:focused?.id?`#${focused.id}`:null;
  const selection=focused?.dataset.valueKey&&Number.isInteger(focused.selectionStart)?{start:focused.selectionStart,end:focused.selectionEnd,direction:focused.selectionDirection}:null;
  const restoreEditingFocus=()=>{
    const target=$(focusSelector)||$('#values-use-latest');target?.focus({preventScroll:true});
    if(selection&&target?.dataset.valueKey===focused.dataset.valueKey){
      const length=target.value.length;
      target.setSelectionRange?.(Math.min(selection.start,length),Math.min(selection.end,length),selection.direction||'none');
    }
  };
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
    const combat=first?.title==='常规战斗数值';
    const npc=identity.startsWith('actors.mobs.npcs.')&&!combat;
    $('#detail-dialog').classList.toggle('monster-detail',combat);
    $('#detail-dialog').classList.toggle('npc-detail',npc);
    if(!previousForm&&result.blocks.length)$('#detail-dialog .game-description').open=npc;
    const intro=$('#detail-intro');if(intro)intro.hidden=npc||!result.blocks.length||!intro.textContent;
    const fixedEffect=!result.inputs.length&&first?.values?.length&&!first.columns;
    const lead=!npc&&!result.missing_inputs?.length&&(fixedEffect||combat||first?.values?.length<=6&&!first?.columns&&/^(当前 |按你的|命中概率|技能具体效果|当前治疗状态|当前酸蚀状态|当前延缓伤害池)/.test(first.title));
    detail.inputs=result.inputs;detail.result=result;
    if(options.commitPending)detail.sessionUnsaved=true;
    if(options.commitPending)numericalFormDrafts.delete(currentDraftKey());
    detail.dirty=!!result.missing_inputs?.length||(options.restoreSession?!!options.restoreSession.detail.dirty:!!fixedDraft?.dirty);
    if(!restoredResult&&!options.restoreSession)for(const key of result.missing_inputs||[])detail.origins[key]='未确认 · 请填写';
    if(!options.restoreSession)detail.calculated=result.missing_inputs?.length?null:{params:Object.fromEntries(result.inputs.map(field=>[field.key,Number(field.value)])),origins:{...detail.origins},source:detail.source,levelSource:detail.levelSource,result,sessionUnsaved:!!detail.sessionUnsaved,characterReference:detail.characterReference||null,skillConditions:detail.skillConditions,skillState:detail.skillState,seedReference:detail.seedReference,seedAccess:detail.seedAccess,seedConditions:detail.seedConditions,unconfirmedSource:detail.unconfirmedSource};
    if(detail.calculated&&!detail.fixed&&!restoredResult&&(!options.ignoreDrafts||!numericalFormDrafts.has(currentDraftKey()))&&(!options.ignoreDrafts||!numericalCalculated.get(currentDraftKey())?.sessionUnsaved)){numericalCalculated.set(currentDraftKey(),detail.calculated);if(numericalCalculated.size>64){const clean=Array.from(numericalCalculated).find(([,item])=>!item.sessionUnsaved);if(clean)numericalCalculated.delete(clean[0]);}}
    if(options.commitPending&&!detail.fixed){const drafts={};for(const input of result.inputs)if((detail.origins[input.key]||'').startsWith('手填'))drafts[input.key]=Number(input.value);numericalDrafts.set(currentDraftKey(),drafts);}
    const restoreFocus=focusSelector&&(document.activeElement===document.body||previousForm.contains(document.activeElement));
    const scrollTop=$('#detail-dialog').scrollTop;
    const inputHTML=inputs=>inputs.map(input=>`<label>${escapeHTML(input.key==='corrosion_public'?'酸蚀计算依据':input.label)}<small data-origin-key="${escapeHTML(input.key)}">${escapeHTML(detail.origins[input.key]||'示例 · 请核对')}</small>${input.key==='corrosion_public'?`<select data-value-key="corrosion_public" aria-describedby="corrosion-precision-help"><option value="1" ${Number(input.value)===1?'selected':''}>游戏显示值（给范围）</option><option value="0" ${Number(input.value)===0?'selected':''}>手填精确假设</option></select><small id="corrosion-precision-help">游戏显示值使用公开精度范围；精确值仅代表你明确填写的假设。</small>`:`<input data-value-key="${escapeHTML(input.key)}" type="text" inputmode="${input.step==='any'?'decimal':'numeric'}" step="${input.step||1}" min="${input.min}" max="${input.max}" value="${input.value}" required>`}</label>`).join('');
    const basic=combat?result.inputs.filter(input=>['depth','hero_level','stronger_bosses'].includes(input.key)):result.inputs;
    const advanced=combat?result.inputs.filter(input=>!['depth','hero_level','stronger_bosses'].includes(input.key)):[];
    const formHTML=result.inputs.length?`<form id="value-calculator" class="value-calculator" novalidate><div class="form-grid">${inputHTML(basic)}</div>${advanced.length?`<details class="numeric-advanced"${advancedOpen?' open':''}><summary>掉落与其他条件（${advanced.length}项，可调整）</summary><div class="form-grid">${inputHTML(advanced)}</div></details>`:''}<div class="backup-actions"><button class="primary" id="values-recalculate" type="submit">重新计算</button><button class="secondary" id="values-use-latest" type="button">带入最新角色状态</button>${result.inputs.some(input=>input.key==='strength')?'<button class="secondary" id="values-use-character" type="button">带入共享角色条件的总力量</button>':''}${detail.importUndo?'<button class="secondary" id="values-undo-import" type="button">撤回本次带入</button>':''}${detail.savedPlan?'<button class="secondary" id="values-reload-saved" type="button">重新读取最新已保存方案 / 放弃会话草稿</button>':''}</div><p id="values-source" role="status"></p>${result.inputs.some(input=>input.key==='strength')?'<details class="numeric-note-details"><summary>力量条件说明</summary><p class="muted">力量优先带入已知角色条件的总力量；未确认时只提供基础参考。支线等效层数及其他战斗效果请另行核对。</p></details>':''}</form>`:'';
    const ordinaryLabels=['基础伤害范围','基础减伤范围','基础速度倍率'];
    const ordinary=combat&&['actors.mobs.rat','actors.mobs.gnoll','actors.mobs.crab'].includes(identity)&&!result.blocks.some(block=>block.title==='特殊攻击与机制')&&ordinaryLabels.every(label=>first.values.some(value=>value.label===label));
    const readingNotes=combat&&!ordinary?(first.reading_notes||[]).filter(note=>typeof note==='string'&&note.trim()):[];
    const equipment=equipmentAnswer(detail,first);
    const summaryBlock=detail.foodReference||equipment||(npc||readingNotes.length?null:ordinary?{...first,primary_values:ordinaryLabels.map(label=>first.values.find(value=>value.label===label))}:result.blocks.find(block=>block.primary_values?.length));
    const basisText=equipment?equipment.basis:numericalAnswerBasis(detail,result),basis=basisText?`<p class="numeric-basis">${escapeHTML(basisText)}</p>`:'';
    const answer=readingNotes.length?`<section id="values-answer" class="numeric-answer mechanism-answer" ${detail.dirty?'hidden':''}>${basis}<ul>${readingNotes.map(note=>`<li>${escapeHTML(note)}</li>`).join('')}</ul>${first.summary_note?`<p class="muted">${escapeHTML(first.summary_note)}</p>`:''}</section>`:summaryBlock?`<section id="values-answer" class="numeric-answer${ordinary?' ordinary-combat-answer':''}" ${detail.dirty?'hidden':''}>${basis}<dl>${summaryBlock.primary_values.slice(0,ordinary?3:2).map(value=>`<div><dt>${escapeHTML(ordinary?({'基础伤害范围':'普通攻击','基础减伤范围':'基础减伤','基础速度倍率':'移动速度'}[value.label]||value.label):value.label)}</dt><dd>${escapeHTML(displayNumber(value.value))} <small>${escapeHTML(value.unit||'')}</small></dd>${value.condition?`<p class="numeric-condition">${escapeHTML(value.condition)}</p>`:''}</div>`).join('')}</dl>${(summaryBlock.summary_note??summaryBlock.note)?`<p class="muted">${escapeHTML(summaryBlock.summary_note??summaryBlock.note)}</p>`:''}</section>`:'';
    if(intro&&(summaryBlock||readingNotes.length))intro.hidden=true;
    const compactFirst=!!equipment||summaryBlock===first||ordinary||readingNotes.length||detail.foodReference;
    const leading=lead?(compactFirst?'':exampleHTML({...first,omit_heading:first.title==='效果数值',...(combat?{compact_conditions:true}:{})})):'';
    const detailBlocks=(detail.foodReference?exampleHTML(detail.foodReference):'')+(compactFirst?result.blocks:result.blocks.slice(lead?1:0)).map(exampleHTML).join('');
    // Keep the complete original tables and the editor in the DOM; only their reading order changes.
    const editor=formHTML?`<details class="numeric-editor"${detail.dirty||focusSelector?' open':''}><summary>调整计算条件${result.inputs.length?`（${result.inputs.length}项）`:''}</summary>${formHTML}</details>`:'';
    const full=detailBlocks?`<details class="numeric-note-details numeric-full"><summary>${npc?'完整原始数值与条件':result.alchemy_recipes?.length?'完整数值与炼金明细':'完整数值与条件'}</summary>${detailBlocks}</details>`:'';
    const seedSource=detail.seedReference?`<details class="numeric-note-details"><summary>来源与取得条件</summary><p>${escapeHTML(detail.seedReference)}</p><p>${escapeHTML(detail.seedConditions||'')}</p><p>${escapeHTML(detail.skillConditions||'')}</p></details>`:'';
    const content=npc?`${editor}${seedSource}${full}`:`${answer}${leading}${editor}${seedSource}${full}`;
    container.innerHTML=`${result.inputs.length||detail.foodReference?'<p id="values-freshness" role="status"></p>':''}${content}${result.no_fixed_values?(result.non_numeric?'':'<p class="rule-warning">此条目的具体数值尚在核对，目前不提供未经确认的结果。</p>'):''}${provenanceHTML(result)}`;
    $('#values-use-character')?.addEventListener('click',()=>{try{applyCharacterToNumeric();}catch(error){toast(error.message,true);}});
    $$('[data-value-key]').forEach(input=>input.addEventListener('input',()=>{
      if(input.dataset.valueKey==='strength')detail.characterReference=null;
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
      const latest=visibleCalculationContext(identity,{includeBoss:true});
      const skill=currentSkillContext(identity);
      const currentKeys=currentParameterKeys(identity);
      const retainedInputs=Array.from($$('[data-value-key]')).filter(input=>!currentKeys.includes(input.dataset.valueKey)||!(input.dataset.valueKey in latest));
      for(const input of retainedInputs)if(currentKeys.includes(input.dataset.valueKey)){const key=input.dataset.valueKey;detail.origins[key]=key==='vial'&&healingPotionIds.has(identity)?(detail.origins[key]||'示例 · 请核对').replace(/ · (?:最新快照未确认|尚未重新计算)/g,'')+' · 最新快照未确认':'手填保留 · 最新快照未确认'+(['talent','shielding_dew'].includes(key)&&skill?' · '+skill.conditions.split('；')[0]:'');$(`[data-origin-key="${key}"]`).textContent=detail.origins[key];}
      const raw={...numericalFormDrafts.get(key)};
      for(const input of $$('[data-value-key]'))if(currentKeys.includes(input.dataset.valueKey)&&input.dataset.valueKey in latest){input.value=String(latest[input.dataset.valueKey]);input.setCustomValidity?.('');raw[input.dataset.valueKey]=input.value;detail.origins[input.dataset.valueKey]=heroInputOrigin(input.dataset.valueKey);$(`[data-origin-key="${input.dataset.valueKey}"]`).textContent=detail.origins[input.dataset.valueKey];}
      if(skill){detail.skillState=skill.state;detail.skillConditions=skill.conditions+(retainedInputs.some(input=>['talent','shielding_dew'].includes(input.dataset.valueKey)&&!(input.dataset.valueKey in latest))?' 本次保留原填写点数作为独立参考。':'');if(typeof showDetailContext==='function')showDetailContext(detail.skillConditions);}
      numericalFormDrafts.set(key,raw);detail.dirty=true;
      if('strength' in latest)detail.characterReference=null;
      if(!validNumericalInputs(retainedInputs,detail))return;
      const next={...context,...latest};
      retainedInputs.forEach(input=>{const key=input.dataset.valueKey;
        next[key]=Number(input.value);
        if(!currentKeys.includes(key)&&(detail.origins[key]||'').startsWith('手填'))detail.origins[key]='手填';
      });
      for(const key of currentKeys)if(key in latest)detail.origins[key]=heroInputOrigin(key);
      detail.source=calculationStamp();detail.unconfirmedSource=false;
      detail.fixed=false;
      loadNumericalDetail(identity,next,detail.levelOrigin,{commitPending:true});
    });
    if(!options.ignoreDrafts){const raw=options.restoreSession?options.restoreSession.raw:numericalFormDrafts.get(currentDraftKey());for(const input of $$('[data-value-key]'))if(raw&&input.dataset.valueKey in raw){setNumericalRaw(input,raw[input.dataset.valueKey]);if(!options.restoreSession&&!restoredResult)detail.origins[input.dataset.valueKey]='手填 · 尚未重新计算';$(`[data-origin-key="${input.dataset.valueKey}"]`).textContent=detail.origins[input.dataset.valueKey];if(!options.restoreSession)detail.dirty=true;}}
    $('#values-undo-import')?.addEventListener('click',()=>{const snapshot=detail.importUndo;if(!snapshot)return;const key=currentDraftKey();for(const [map,value] of [[numericalFormDrafts,snapshot.formDraft],[numericalDrafts,snapshot.draft],[numericalCalculated,snapshot.calculated]]){if(value===null)map.delete(key);else map.set(key,value);}loadNumericalDetail(identity,snapshot.detail.context,snapshot.detail.levelOrigin,{restoreSession:snapshot});});
    $('#values-reload-saved')?.addEventListener('click',()=>confirmReloadSavedPlan(detail.savedPlan.id));
    refreshNumericalOrigin();
    if(typeof renderDetailTools==='function')renderDetailTools();
    $('#values-copy-basis')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(provenanceText(result));$('#values-copy-status').textContent='已复制依据与适用范围';}catch(error){$('#values-copy-status').textContent='复制不可用；请在下方可选文本中选取并复制。';}});
    if(restoreFocus)restoreEditingFocus();
    $('#detail-dialog').scrollTop=scrollTop;
  }catch(error){if(seq===numericalRequest&&$('#detail-dialog').open){detail.dirty=true;refreshNumericalOrigin();const message=`<p role="alert" class="rule-warning value-error">${escapeHTML(error.message)}</p>`;if(previousForm?.isConnected)previousForm.insertAdjacentHTML('afterend',message);else container.innerHTML=message;}}
  finally{if(seq===numericalRequest){detail.pending=false;rememberFixedNumericalDraft();}if(seq===numericalRequest&&previousForm?.isConnected){
    previousForm.querySelectorAll('input,button').forEach(el=>el.disabled=false);
    if(focusSelector&&(document.activeElement===document.body||previousForm.contains(document.activeElement)))restoreEditingFocus();
  }}
}
function keyOrigin(origin){return origin==='known'?'物品已知等级':origin==='revealed'?'已主动揭示的存档等级':origin==='unknown'?'等级未知 · +0示例':'示例';}
function calculationStamp(){return state?.data?{modified:state.modified,slot:state.active_slot,mode:state.settings.mode,save_root:state.settings.save_root,revision:state.revision,started:state.started}:null;}
function refreshNumericalOrigin(){
  const d=numericalDetail,freshness=$('#values-freshness'),source=$('#values-source');
  if(!d || !freshness)return;
  const answer=$('#values-answer');if(answer)answer.hidden=!!d.dirty;
  const now=calculationStamp(),stamp=d.dirty&&d.calculated?d.calculated.source:d.source;
  const snapshotUsed=!!d.foodReference||d.inputs?.some(i=>/^(快照|手动局势)/.test(d.origins[i.key]||'')||['物品已知等级','物品已知阶数','已主动揭示的存档等级','存档物品阶数 · 主动揭示模式'].includes(d.origins[i.key]));
  const changed=stamp&&(!now||['modified','slot','mode','save_root','revision','started'].some(k=>stamp[k]!==now[k]));
  const levelOld=(['物品已知等级','已主动揭示的存档等级'].includes(d.origins.level)||['物品已知阶数','存档物品阶数 · 主动揭示模式'].includes(d.origins.tier))&&d.levelSource&&(!now||['modified','slot','mode','save_root','revision','started'].some(k=>d.levelSource[k]!==now[k]));
  const old=snapshotUsed&&(!now||state.error||state.stale||changed||levelOld);
  freshness.className=old||d.dirty||d.unconfirmedSource?'rule-warning':'muted';
  freshness.textContent=d.dirty?(d.calculated?'条件已修改 · 待重新计算':'条件待补全 · 请填写后计算'):d.unconfirmedSource?'参考来源未确认；请核对原参数或明确带入最新状态。':levelOld?'物品等级来自较早快照，无法唯一确认现在是哪件装备；请核对等级后手填。':old?(changed?'游戏快照已经变化；下方结果仍按原参数计算，请带入最新状态或核对后手填。':'这些结果含旧快照参数，请按游戏画面核对。'):d.seedReference?`独立种子 · 未持有 · ${stamp?'已带入角色条件':'未绑定当前角色'}`:'按下列参数计算；随机范围和生效条件见各表。';
  if(d.dirty&&old&&!d.fixed)freshness.textContent+=!now||state.error?' 当前快照不可用；已带入条件保留，请核对。':changed||levelOld?' 游戏快照已变化；已带入条件保留，请核对。':' 已带入条件来自旧快照，请核对。';
  if(d.sessionUnsaved&&!d.fixed&&!d.dirty)freshness.textContent+=' 本次会话试算尚未命名保存。';
  if(d.foodReference&&!d.dirty)freshness.textContent=d.unconfirmedSource?'进食参考来源未确认，请核对条件。':old?'旧快照进食参考；请核对游戏，或从当前局势重新打开。':`${stamp?.mode==='manual'?'手填局势':'捕获的进食参考'}${stamp?' · '+fmtTime(stamp.modified):''}`;
  if(source){
  source.className='muted';source.textContent=stamp?`首次带入：${stamp.mode==='manual'?'手动局势':`槽位 ${stamp.slot}`} · ${fmtTime(stamp.modified)}。手填保留项不会自动跟随游戏。`:d.unconfirmedSource?'参考来源未确认；保留带入时的参数。':d.seedReference?d.seedReference:'没有角色快照；参数为示例或手填。';
  if(d.characterReference){source.textContent+=' '+numericCharacterLabel(d.characterReference)+(d.characterReference.signature!==JSON.stringify(characterResult?.params)?'；当前共享条件已有变化，此处保留带入时的力量。':'');}
  }
  const button=$('#values-use-latest');if(button)button.disabled=!now;
  if(d.fixed){if(source)source.textContent=`固定保存参数。${typeof originLabel==='function'?originLabel(d.savedPlan?.origin):'过去来源只用于追溯，不绑定当前角色。'}`;freshness.textContent=d.dirty?'草稿尚未保存 · 待重新计算':`${d.sessionUnsaved?'会话计算草稿尚未保存。':'按保存参数计算，'}不跟随最新快照。${d.rulesChanged?'资料规则已更新；请重新计算并核对保留结果与当前规则的差异。':''}`;freshness.className=d.dirty||d.rulesChanged?'rule-warning':'muted';}
  if(typeof itemDisclosure!=='undefined'&&itemDisclosure?.expired){freshness.className='rule-warning';freshness.textContent='这件物品的主动揭示已过期；下方仅按旧参数试算，请重新从背包选择并主动揭示。'+(d.dirty?'手填草稿仍保留，尚未计算。':'');if(button)button.disabled=true;}
  freshness.hidden=freshness.textContent==='按下列参数计算；随机范围和生效条件见各表。';
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
