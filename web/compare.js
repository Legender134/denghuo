'use strict';
let compareCatalog=[],compareItems=[],compareSignature='',compareRequest=0,compareStamp=null,compareDirty=false,compareError='';
let compareResultArgs=null,compareSavedPlan=null,compareFixed=false;
let compareResultFields=null;
let comparePending=false,compareSessionUnsaved=false,compareImportUndo=null;
let compareContextSerial={a:0,b:0};
const comparisonPrefixes={weapon:'items.weapon.melee.',armor:'items.armor.',wand:'items.wands.',ring:'items.rings.'};
let compareBudgetOrigin='手填预算 · 未实际消耗资源',compareBudgetStamp=null;
function refreshBudgetOrigin(){
  const enabled=$('#compare-planning-enabled').checked;
  for(const key of ['upgrade','strength'])$('#compare-'+key+'-budget').disabled=comparePending||!enabled;
  $('#compare-use-resources').disabled=comparePending||!state?.data||!!state?.error;
  const changed=compareBudgetStamp&&JSON.stringify(compareBudgetStamp)!==JSON.stringify(calculationStamp());
  const strengthNote=typeof compareCharacterReference!=='undefined'&&compareCharacterReference?'拟投入力量药剂先增加基础力量，再按每侧戒指和力大无穷天赋重新计算总力量。':'有效力量为所填力量加拟投入力量药剂数。';
  $('#compare-budget-source').textContent=compareBudgetOrigin+(compareBudgetStamp?` · ${fmtTime(compareBudgetStamp.modified)}${changed||state?.stale?' · 旧快照，请重新核对':''}`:'')+'。A、B 独立使用同一可用预算，不表示同时花费；未实际消耗资源。'+strengthNote+'已计入当前条件的药剂不得重复投入。';
}
$('#compare-use-resources').addEventListener('click',()=>{rememberComparisonImport();compareSessionUnsaved=true;const items=(state?.data?.items||[]).filter(i=>i.known&&i.available===true);const quantity=key=>items.filter(i=>i.key===key).reduce((n,i)=>n+(Number.isInteger(i.quantity)&&i.quantity>0?i.quantity:0),0);$('#compare-upgrade-budget').value=String(Math.min(100,quantity('items.scrolls.scrollofupgrade')));$('#compare-strength-budget').value=String(Math.min(99,quantity('items.potions.potionofstrength')));$('#compare-planning-enabled').checked=true;compareBudgetStamp=calculationStamp();compareBudgetOrigin=compareBudgetStamp?.mode==='manual'?'手动局势已知可用资源':'快照中已知且可用资源';compareDirty=true;compareError='';refreshComparisonOrigin();});
async function initializeEquipmentComparison(){
  const lists=await Promise.all(Object.values(comparisonPrefixes).map(async q=>{
    const r=await fetch('/api/library?'+new URLSearchParams({q,category:'物品'}));
    if(!r.ok)throw new Error('装备资料暂时不可用');return (await r.json()).entries;
  }));
  compareCatalog=lists.flat().filter(r=>!r.id.includes('$')&&!r.id.endsWith('.ability'));
  compareSignature='';
  renderEquipmentComparison();
}
function renderEquipmentComparison(){
  const form=$('#equipment-comparison');if(!form)return;
  const kind=$('#compare-kind').value, prefix=comparisonPrefixes[kind];
  const owned=(state?.data?.items||[]).filter(i=>i.known&&i.available===true&&i.key.startsWith(prefix));
  const sig=JSON.stringify([kind,state?.started,state?.active_slot,owned]);
  if(sig!==compareSignature){
    compareSignature=sig;
    const old=compareItems,oldAugment={a:$('#compare-augment-a').value,b:$('#compare-augment-b').value};
    const previous={a:old[Number($('#compare-a').value)],b:old[Number($('#compare-b').value)]};
    const deliberate=side=>!!($('#compare-'+side).dataset.edited||['level','mastery','augment','tier','level-known','curse','pair','pair-level','pair-curse'].some(field=>$('#compare-'+field+'-'+side).dataset.manual)||$$('#compare-context-'+side+' input').some(input=>input.dataset.manual));
    compareItems=[...owned.map((i,n)=>({...i,token:`own:${i.key}:${i.location}:${n}`,owned:true})),
      ...compareCatalog.filter(e=>e.id.startsWith(prefix)).map(e=>({key:e.id,name:e.name,level:0,owned:false,token:'book:'+e.id}))];
    // A save has no durable item identity. An explicit comparison therefore
    // keeps its previous item and conditions as a reference, never rematches an
    // inventory index or an ambiguous same-type instance in a newer snapshot.
    const held={};
    for(const side of ['a','b']){const item=previous[side];if(item?.key.startsWith(prefix)&&(item.owned||item.reference)&&deliberate(side)){held[side]={...item,owned:false,reference:true,token:item.reference?item.token:'reference:'+side+':'+item.token};compareItems.push(held[side]);}}
    for(const suffix of ['a','b']){
      const select=$('#compare-'+suffix),prior=(held[suffix]||previous[suffix])?.token;
      select.innerHTML=compareItems.map((i,n)=>`<option value="${n}">${escapeHTML(i.reference?`固定装备参考 · ${i.location} · ${i.name}`:i.owned?`${i.location} · ${i.name}${i.level===null?' · 等级未知':''}`:`手册 · ${i.name}`)}</option>`).join('');
      const index=compareItems.findIndex(i=>i.token===prior);
      const edited=index>=0&&deliberate(suffix);
      const equipped=compareItems.findIndex(i=>i.owned&&i.location===(kind==='armor'?'护甲':'主武器'));
      const chosen=suffix==='a'&&!edited&&equipped>=0?equipped:index;
      const retained=chosen>=0&&chosen===index;
      select.value=String(chosen>=0?chosen:suffix==='b'&&owned.length>1?1:0);
      const augment=$('#compare-augment-'+suffix);
      augment.innerHTML=(kind==='armor'?[['NONE','无强化'],['EVASION','闪避'],['DEFENSE','防御']]:kind==='weapon'?[['NONE','无强化'],['SPEED','速度'],['DAMAGE','伤害']]:[['NONE','不适用']]).map(([value,label])=>`<option value="${value}">${label}</option>`).join('');
      if(retained && augment.dataset.manual)augment.value=oldAugment[suffix];
      fillCompareChoice(suffix,retained);
    }
    compareDirty=true;
  }
  const strength=$('#compare-strength'),latestStrength=String(typeof currentCharacterStrength==='function'?currentCharacterStrength():state?.data?.hero?.strength||10);
  if(!strength.dataset.edited&&!compareFixed&&typeof followComparisonCharacter==='function')followComparisonCharacter();
  if(!strength.dataset.edited && String(strength.value)!==latestStrength){strength.value=latestStrength;compareDirty=true;}
  $('#compare-follow-strength').disabled=!state?.data;
  const physical=['weapon','armor'].includes(kind);$('#compare-investment-mode').querySelector('option[value="min_strength"]').disabled=!physical;if(!physical)$('#compare-investment-mode').value='all';
  refreshComparisonOrigin();
}
function fillCompareChoice(suffix,preserveManual=false){
  const item=compareItems[Number($('#compare-'+suffix).value)];
  const level=$('#compare-level-'+suffix),mastery=$('#compare-mastery-'+suffix),augment=$('#compare-augment-'+suffix),tier=$('#compare-tier-'+suffix);
  if(!preserveManual)for(const input of [level,mastery,augment,tier])delete input.dataset.manual;
  if(!level.dataset.manual)level.value=item?.level??0;
  if(!mastery.dataset.manual)mastery.checked=!!item?.mastery;
  $('#compare-tier-label-'+suffix).hidden=!/^items\.armor\.(warrior|mage|rogue|huntress|duelist|cleric)armor$/.test(item?.key||'');
  if(!tier.dataset.manual)tier.value=item?.tier||3;
  const kind=$('#compare-kind').value,physical=['weapon','armor'].includes(kind);level.min=physical?'-100':'0';
  mastery.closest('label').hidden=!physical;augment.closest('label').hidden=!physical;
  $('#compare-conditional-'+suffix).hidden=physical;$('#compare-ring-pair-'+suffix).hidden=kind!=='ring';
  if(!physical){mastery.checked=false;augment.value='NONE';if(!preserveManual){$('#compare-pair-'+suffix).checked=false;$('#compare-pair-level-'+suffix).value='0';$('#compare-pair-curse-'+suffix).value='0';$('#compare-level-known-'+suffix).checked=!!item?.owned&&item.level!==null;$('#compare-curse-'+suffix).value=item?.owned?(item.cursed===true?'1':item.cursed===false?'0':'unknown'):'0';}loadComparisonContext(suffix,item);}
  const allowed=kind==='armor'?['NONE','EVASION','DEFENSE']:kind==='weapon'?['NONE','SPEED','DAMAGE']:['NONE'];
  if(!augment.dataset.manual)augment.value=allowed.includes(item?.augmentation)?item.augmentation:'NONE';
  $('#compare-origin-'+suffix).textContent=[level,mastery,augment,tier].some(i=>i.dataset.manual)?'手填条件保留，请按游戏画面核对':item?.reference?'来自先前存档的已知装备条件，请核对':item?.owned?(item.level===null?'等级未知，先按+0试算':'已带入已知等级、精通/强化及原护甲阶数'):'手册示例，请填写要比较的等级与条件';
  if(item?.reference)$('#compare-origin-'+suffix).textContent+='。固定装备参考；新快照不会替换这件装备或条件，需更新时请明确重新选择。';
  if(compareFixed&&Number(level.value)===compareSavedPlan?.params?.['level_'+suffix])$('#compare-origin-'+suffix).textContent=compareSavedPlan.origin?.fields?.['level_'+suffix]||'保存等级 · 固定参考';
}
function refreshComparisonOrigin(){
  refreshBudgetOrigin();
  for(const side of ['a','b']){const active=$('#compare-kind').value==='ring'&&$('#compare-pair-'+side).checked;$('#compare-pair-level-'+side).disabled=comparePending||!active;$('#compare-pair-curse-'+side).disabled=comparePending||!active;}
  const target=$('#compare-status');if(!target)return;
  const changed=compareStamp&&(!state?.data||['modified','slot','mode','revision','started'].some(k=>compareStamp[k]!==calculationStamp()?.[k]));
  const old=compareStamp&&(changed||state?.stale);
  target.className=compareError||old||compareDirty?'rule-warning':'muted';
  target.textContent=compareError|| (compareDirty?($('#compare-result').childElementCount?'条件已变化，请点击比较；已有表格仍使用上次条件。':'请选择装备和条件，再点击比较。'):old?'角色快照已变化或过期，请核对力量与装备，再比较。':'按所填条件比较；请核对游戏面板。');
  target.textContent+=(typeof compareCharacterReference!=='undefined'&&compareCharacterReference)?' 力量按所带入的共享角色条件逐侧计算。':$('#compare-strength').dataset.edited?' 力量为手填值，保留你的输入。':state?.data?' 力量使用当前公开角色条件；未确认的总力量需补全条件或明确手填。':' 没有角色快照，力量10为示例，请填写游戏中的数值。';
  if(typeof renderComparisonCharacterReference==='function')renderComparisonCharacterReference();
  if(compareFixed)target.textContent+=` 固定参考。${typeof originLabel==='function'?originLabel(compareCharacterReference?.source||compareSavedPlan?.origin):'使用保存参数，不跟随当前角色。'}`;
}
$('#compare-kind').addEventListener('change',()=>{compareSessionUnsaved=true;for(const side of ['a','b']){delete $('#compare-'+side).dataset.edited;for(const field of ['level','mastery','augment','tier','level-known','curse','pair','pair-level','pair-curse'])delete $('#compare-'+field+'-'+side).dataset.manual;for(const input of $$('#compare-context-'+side+' input'))delete input.dataset.manual;}compareSignature='';compareError='';renderEquipmentComparison();});
$('#compare-follow-strength').addEventListener('click',()=>{
  if(!state?.data)return;rememberComparisonImport();compareSessionUnsaved=true;
  delete $('#compare-strength').dataset.edited;delete $('#compare-strength').dataset.manual;
  compareFixed=false;
  compareDirty=true;compareError='';renderEquipmentComparison();
});
for(const suffix of ['a','b'])$('#compare-'+suffix).addEventListener('change',()=>{compareSessionUnsaved=true;$('#compare-'+suffix).dataset.edited='true';fillCompareChoice(suffix);compareError='';compareDirty=true;refreshComparisonOrigin();});
$('#equipment-comparison').addEventListener('input',e=>{compareSessionUnsaved=true;compareDirty=true;compareError='';e.target.dataset.manual='true';if(['compare-upgrade-budget','compare-strength-budget'].includes(e.target.id)){compareBudgetOrigin='手填预算';compareBudgetStamp=null;}if(/^compare-(level|augment|mastery|tier)-[ab]$/.test(e.target.id))fillCompareChoice(e.target.id.slice(-1),true);if(e.target.id==='compare-strength')e.target.dataset.edited='true';refreshComparisonOrigin();});
$('#equipment-comparison').addEventListener('submit',async event=>{
  event.preventDefault();const seq=++compareRequest,button=$('#compare-submit'),signature=compareSignature;compareError='';button.disabled=true;comparePending=true;
  let args;try{args=readComparisonArgs();}catch(error){comparePending=false;button.disabled=false;compareError=error.message;refreshComparisonOrigin();return;}
  const source=calculationStamp();
  $('#equipment-comparison').querySelectorAll('input,select').forEach(el=>el.disabled=true);
  try{
    const response=await fetch('/api/compare?'+new URLSearchParams(args)),result=await response.json();
    if(!response.ok)throw new Error(result.error);if(seq!==compareRequest)return;
    renderComparisonResult(result);compareResultArgs=result.params||canonicalComparisonParams(args);compareResultFields=comparisonFields();inlineError($('#compare-save-error'),'');
    compareDirty=signature!==compareSignature || args.strength!==String($('#compare-strength').value);compareStamp=source;refreshComparisonOrigin();
  }catch(error){if(seq===compareRequest){compareError=error.message;refreshComparisonOrigin();}}
  finally{if(seq===compareRequest){comparePending=false;button.disabled=false;$('#equipment-comparison').querySelectorAll('input,select').forEach(el=>el.disabled=false);refreshComparisonOrigin();}}
});
const comparisonReady=initializeEquipmentComparison().catch(error=>{compareError=error.message;refreshComparisonOrigin();});
function canonicalComparisonParams(args){return Object.fromEntries(Object.entries(args).map(([key,value])=>[key,key==='character_scene'?(typeof value==='string'?JSON.parse(value):characterClone(value)):key==='scene_ring_slot'?Number(value):key==='strength'||key.endsWith('_budget')||key.startsWith('level_')||key.startsWith('tier_')||/^(hp|max_hp|hero_level|depth|target_hp|target_max_hp|enemy_exp|minor|major|charges|ring_pair_level)_[ab]$/.test(key)?Number(value):String(value)]));}
function cellsText(cells){return (cells||[]).map(cell=>`${cell.label}：${displayNumber(cell.value)} ${cell.unit||''}${cell.condition?'；条件：'+cell.condition:''}`).join('\n');}
function renderComparisonResult(result){
  const signed=n=>n>=0?'+'+n:String(n),[a,b]=result.choices;
  const columns=['数值与单位',`${a.name} ${signed(a.level)}`,`${a.name} ${signed(a.level+1)}`,`${b.name} ${signed(b.level)}`,`${b.name} ${signed(b.level+1)}`,'B 相对 A（当前）'];
  const explanation=result.explanation;
  $('#compare-result').innerHTML=result.choices.map((choice,index)=>choice.character_scene?`<article class="resource-card"><h3>${index?'B':'A'} · 角色力量条件</h3><p>${escapeHTML(characterSummary(choice.character_scene))}</p><p>升级后：${escapeHTML(characterSummary(choice.upgraded_character_scene))}</p><p class="muted">${escapeHTML(choice.character_scene.replacement)}；${escapeHTML(choice.character_scene.assumption)}</p></article>`:'').join('')+(explanation?`<section class="comparison-explanation"><h3>按条件看当前与升级变化</h3><p>${escapeHTML(explanation.tradeoff)}</p><div class="restore-comparison">${explanation.choices.map(choice=>`<article class="resource-card"><h3>${escapeHTML(choice.choice)} · ${escapeHTML(choice.name)}</h3><p>${escapeHTML(choice.summary)}</p><p class="muted">${escapeHTML(choice.timing_and_accuracy)}</p><ul>${choice.upgrade_changes.map(change=>`<li>${escapeHTML(change.label)}：${escapeHTML(displayNumber(change.before))} → ${escapeHTML(displayNumber(change.after))} ${escapeHTML(change.unit||'')}${change.condition?`<small> · ${escapeHTML(change.condition)}</small>`:''}</li>`).join('')}</ul></article>`).join('')}</div><p class="muted">${escapeHTML(explanation.boundary)}</p></section>`:'')+
    exampleHTML({title:'当前与升级一次后的条件数值',columns,rows:result.rows.map(r=>[`${r.label}${r.unit?'（'+r.unit+'）':''}`,...r.values,r.difference]),note:result.notice})+
    `<details><summary>逐项生效条件与单位</summary>${result.rows.map(row=>`<p>${escapeHTML(row.label)}${row.unit?'（'+escapeHTML(row.unit)+'）':''}：${escapeHTML(row.condition||'见所填条件')}</p>`).join('')}</details>`+
    (['weapon','armor'].includes(result.family)?`<p class="muted">伤害和防御是随机范围；命中倍率不是最终命中概率。普通附魔升级损失风险：A ${escapeHTML(a.upgrade_risk??'—')}%，B ${escapeHTML(b.upgrade_risk??'—')}%。硬化、诅咒和护甲蜕变天赋分支请查升级卷轴。</p>`:'')+
    result.choices.map((choice,index)=>choice.after_curse_removed?exampleHTML({title:`${index?'B':'A'} · 升级后已解咒的条件分支（不保证成功）`,values:choice.after_curse_removed,note:'法杖/戒指每次升级有1/3概率解咒；上表使用保持诅咒分支，本表只在实际解除时适用。'}):'').join('')+renderPlanningResult(result.planning);
  const text=[`游戏资料 ${result.version}`,result.notice,...result.choices.flatMap((choice,index)=>[`${index?'B':'A'} ${choice.name} ${signed(choice.level)} 当前`,cellsText(choice.current_metrics),`升级一次 ${signed(choice.level+1)}`,cellsText(choice.upgraded_metrics),...(choice.after_curse_removed?['已解咒条件分支（不保证）',cellsText(choice.after_curse_removed)]:[])]),...result.rows.map(row=>`${row.label}：B-A ${row.difference} ${row.unit||''}；${row.condition||''}`)];
  for(const [index,choice] of result.choices.entries())if(choice.character_scene)text.push(`${index?'B':'A'} 角色条件：${characterSummary(choice.character_scene)}；${choice.character_scene.replacement}；升级后：${characterSummary(choice.upgraded_character_scene)}`);
  if(result.planning){text.push(`投入模式 ${result.planning.mode==='min_strength'?'最小力量门槛':'完整投入'}，卷轴预算 ${result.planning.upgrade_budget}，拟投入力量药剂 ${result.planning.strength_budget}，有效力量 ${result.planning.effective_strength}`,result.planning.notice);for(const choice of result.planning.choices)for(const row of choice.alternatives||[]){text.push(`${choice.name} 投入${row.upgrades}张卷轴，最终等级${row.level}，剩余${row.remaining_upgrades}张，拟投入力量药剂${row.spent_strength}瓶，剩余${row.remaining_strength}瓶`,cellsText(row.metric_rows),...(row.changes||[]).map(c=>`${c.label}变化：${c.before} → ${c.after}；Δ ${c.difference} ${c.unit||''}；${c.condition||''}`),...(row.after_curse_removed?['已解咒条件分支（不保证）',cellsText(row.after_curse_removed)]:[]));}}
  if(compareSavedPlan?.note)text.push('用户用途 / 假设（非游戏事实）：'+compareSavedPlan.note);
  $('#compare-copy-text').textContent=text.join('\n');$('#compare-copy-status').textContent='';
}
function renderPlanningResult(planning){
  if(!planning)return '';
  return `<section class="comparison-explanation"><h3>预算规划 · ${planning.mode==='min_strength'?'最小力量门槛':'完整投入 0 到预算'}</h3><p>升级卷轴预算 ${escapeHTML(planning.upgrade_budget)}；拟投入力量药剂 ${escapeHTML(planning.strength_budget)}；规划有效力量 ${escapeHTML(planning.effective_strength)}。未实际消耗资源。</p><div class="restore-comparison">${(planning.choices||[]).map((choice,index)=>{const alternatives=choice.alternatives||[],cells=choice.metric_rows||[],labels=cells.map(c=>c.label),notes=cells.map(c=>`${c.label}${c.unit?'（'+c.unit+'）':''}：${c.condition||'见条件'}`).join('；');return `<article class="resource-card"><h3>${index?'B':'A'} · ${escapeHTML(choice.name)}</h3>${choice.needed_upgrades!==undefined?`<p>最小力量门槛需 ${choice.needed_upgrades===null?'超出等级范围':escapeHTML(choice.needed_upgrades)+' 张卷轴'}；${choice.within_budget?'预算足够达标':'预算内仍有力量缺口'}。</p>`:''}<p>选定模式的最终等级 ${escapeHTML(choice.planned_level)}；投入 ${escapeHTML(choice.spent_upgrades)} 张卷轴；剩余 ${escapeHTML(choice.remaining_upgrades)} 张。</p>${exampleHTML({title:'选定模式的规划后数值',values:cells})}${alternatives.length?exampleHTML({title:'每个预算内投入的完整结果与相对当前变化',columns:['投入卷轴','最终等级','剩余卷轴','投入力量药剂','剩余拟投入药剂',...cells.map(c=>c.label+(c.unit?'（'+c.unit+'）':''))],rows:alternatives.map(row=>[row.upgrades,row.level,row.remaining_upgrades,row.spent_strength,row.remaining_strength,...labels.map(label=>{const c=row.metric_rows.find(c=>c.label===label),change=row.changes.find(c=>c.label===label);return c?`${c.value}${change?'；Δ '+change.difference:''}`:'不适用';})]),note:notes}):''}${alternatives.some(row=>row.after_curse_removed)?`<details><summary>各投入下已解咒的条件分支（非保证）</summary>${alternatives.filter(row=>row.after_curse_removed).map(row=>exampleHTML({title:`投入 ${row.upgrades} 张 · 等级 ${row.level} · 已解咒`,values:row.after_curse_removed})).join('')}</details>`:''}<p class="muted">${escapeHTML(choice.explanation)}</p>${alternatives.some(row=>row.character_scene)?`<details><summary>每个投入的角色力量来源</summary>${alternatives.filter(row=>row.character_scene).map(row=>`<p>投入 ${escapeHTML(row.upgrades)} 张：${escapeHTML(characterSummary(row.character_scene))}；${escapeHTML(row.character_scene.replacement)}</p>`).join('')}</details>`:''}</article>`;}).join('')}</div><p class="muted">${escapeHTML(planning.notice)}</p></section>`;
}
async function fillComparisonParams(params){
  const nav=navigationSerial;await comparisonReady;if(nav!==navigationSerial)return false;
  $('#compare-kind').value=Object.keys(comparisonPrefixes).find(kind=>params.id_a.startsWith(comparisonPrefixes[kind]));compareSignature='';renderEquipmentComparison();
  for(const suffix of ['a','b']){
    const index=compareItems.findIndex(i=>i.key===params['id_'+suffix]&&!i.owned);if(index<0)throw new Error('此装备没有普通比较入口；请查资料确认支持范围。');
    $('#compare-'+suffix).value=String(index);$('#compare-'+suffix).dataset.edited='true';fillCompareChoice(suffix);
    for(const field of ['level','tier','augment','mastery']){const input=$('#compare-'+field+'-'+suffix);input.dataset.manual='true';if(field==='mastery')input.checked=params['mastery_'+suffix]==='1';else input.value=String(params[field+'_'+suffix]);}fillCompareChoice(suffix,true);await loadComparisonContext(suffix,compareItems[index]);
    if(['wand','ring'].includes($('#compare-kind').value)){$('#compare-level-known-'+suffix).checked=params['level_known_'+suffix]==='1';$('#compare-curse-'+suffix).value=params['curse_'+suffix]||'0';$('#compare-pair-'+suffix).checked=params['ring_pair_'+suffix]==='1';$('#compare-pair-level-'+suffix).value=String(params['ring_pair_level_'+suffix]??0);$('#compare-pair-curse-'+suffix).value=params['ring_pair_curse_'+suffix]||'0';for(const input of $$('#compare-context-'+suffix+' input'))if(input.dataset.compareKey in params)input.value=String(params[input.dataset.compareKey]);}
  }
  $('#compare-investment-mode').value=params.investment_mode||(['weapon','armor'].includes($('#compare-kind').value)?'min_strength':'all');
  $('#compare-planning-enabled').checked=params.planning==='1';$('#compare-planning').open=params.planning==='1';
  $('#compare-upgrade-budget').value=String(params.upgrade_budget??0);$('#compare-strength-budget').value=String(params.strength_budget??0);compareBudgetOrigin='保存预算 · 固定参考';compareBudgetStamp=null;
  if(typeof compareCharacterReference!=='undefined')compareCharacterReference=params.character_scene?{params:characterClone(params.character_scene),source:{mode:'manual',snapshot_at:null,slot:null},stamp:null,label:'保存的共享角色条件',signature:JSON.stringify(params.character_scene)}:null;
  $('#compare-scene-slot').value=String(params.scene_ring_slot??0);
  $('#compare-strength').value=String(params.strength);$('#compare-strength').dataset.edited='true';compareRequest++;compareDirty=true;compareError='';$('.comparison-panel').open=true;refreshComparisonOrigin();return true;
}
async function openEquipmentPlan(plan,result,rulesChanged){
  try{if(!await fillComparisonParams(plan.params))return;compareSavedPlan=plan;compareFixed=true;compareStamp=null;if(compareCharacterReference){compareCharacterReference.source=cleanStoredOrigin(plan.origin);compareCharacterReference.label='方案「'+plan.name+'」的角色条件';}compareResultArgs=canonicalComparisonParams(plan.params);compareResultFields=plan.origin?.fields||{};for(const suffix of ['a','b'])$('#compare-origin-'+suffix).textContent=plan.origin?.fields?.['level_'+suffix]||'保存参数 · 固定参考';$('#compare-user-note').textContent=plan.note?'用户用途 / 假设（非游戏事实）：'+plan.note:'';$('#compare-user-note').hidden=!plan.note;renderComparisonResult(result);compareDirty=false;compareSessionUnsaved=false;compareError=rulesChanged?'规则版本已有变化；按保存参数和当前资料重新计算，请核对。':'';refreshComparisonOrigin();$('#compare-strength').focus();$('.comparison-panel').scrollIntoView({block:'start'});}catch(error){compareError=error.message;refreshComparisonOrigin();}
}
function comparisonFields(){
  const fields={strength:$('#compare-strength').dataset.edited?'手填有效力量':state?.data?(typeof currentCharacterStrengthLabel==='function'?currentCharacterStrengthLabel():'基础力量参考'):'力量10为示例'};
  if(compareCharacterReference)fields.strength='共享角色条件按A/B各自重新计算；见各列角色力量';
  if(compareFixed&&compareResultArgs?.strength===compareSavedPlan?.params?.strength&&compareSavedPlan.origin?.fields?.strength)fields.strength=compareSavedPlan.origin.fields.strength;
  for(const suffix of ['a','b']){const item=compareItems[Number($('#compare-'+suffix).value)];for(const key of ['id','level','tier','mastery','augment']){const input=key==='id'?$('#compare-'+suffix):$('#compare-'+key+'-'+suffix),field=key+'_'+suffix;fields[field]=(compareFixed&&compareResultArgs?.[field]===compareSavedPlan?.params?.[field]&&compareSavedPlan?.origin?.fields?.[field])|| (input.dataset.manual?'手填条件':item?.reference?'固定装备参考 · 先前存档条件，请核对':item?.owned?(key==='level'&&item.level===null?'等级未知 · +0示例':'已知可用装备记录'):'手册示例 · 请核对');}}
  if($('#compare-planning-enabled').checked){fields.planning='明确启用预算规划';for(const key of ['upgrade_budget','strength_budget'])fields[key]=(compareFixed&&compareResultArgs?.[key]===compareSavedPlan?.params?.[key]&&compareSavedPlan?.origin?.fields?.[key])||(compareBudgetOrigin+(compareBudgetStamp?' · '+fmtTime(compareBudgetStamp.modified)+(JSON.stringify(compareBudgetStamp)!==JSON.stringify(calculationStamp())||state?.stale?' · 旧快照，请核对':''):''));}
  if(compareCharacterReference)fields.character_scene=compareCharacterReference.label+'；固定角色条件';
  const args=readComparisonArgs();for(const key of Object.keys(args))if(!(key in fields))fields[key]=(compareFixed&&compareSavedPlan?.origin?.fields?.[key])||'手填场景假设 · 请按游戏核对';
  return fields;
}
async function compareRiskReference(reference){
  const nav=navigationSerial;await comparisonReady;if(nav!==navigationSerial)return;navigate('inventory');
  $('#compare-kind').value=reference.entry.startsWith('items.armor.')?'armor':'weapon';compareSignature='';renderEquipmentComparison();
  const index=compareItems.findIndex(i=>i.owned&&i.key===reference.entry&&(!reference.location||i.location===reference.location));
  if(index<0){compareError='已知可用装备记录已变化，请核对新快照后重新选择。';refreshComparisonOrigin();return;}
  $('#compare-a').value=String(index);$('#compare-a').dataset.edited='true';fillCompareChoice('a');compareSavedPlan=null;compareFixed=false;compareDirty=true;compareError='';$('.comparison-panel').open=true;refreshComparisonOrigin();$('#compare-level-a').focus();$('.comparison-panel').scrollIntoView({block:'start'});
}
$('#compare-save').addEventListener('click',()=>{
  if(!compareResultArgs||compareDirty||compareError){inlineError($('#compare-save-error'),'请先按当前条件比较成功，再命名保存。');return;}inlineError($('#compare-save-error'),'');openPlanSave({kind:'equipment',entry:null,params:compareResultArgs,source:{...(compareCharacterReference?cleanStoredOrigin(compareCharacterReference.source):compareFixed?cleanStoredOrigin(compareSavedPlan?.origin):planSource(compareStamp)),fields:compareResultFields||{}}},compareSavedPlan,'装备取舍');
});

function readComparisonArgs(){
  const args={strength:$('#compare-strength').value};
  const kind=$('#compare-kind').value;
  if(typeof compareCharacterReference!=='undefined'&&compareCharacterReference){args.character_scene=JSON.stringify(compareCharacterReference.params);if(kind==='ring')args.scene_ring_slot=$('#compare-scene-slot').value;}
  for(const side of ['a','b']){const item=compareItems[Number($('#compare-'+side).value)];if(!item)throw new Error('请选择两件同类别装备');
    args['id_'+side]=item.key;for(const key of ['level','tier','augment'])args[key+'_'+side]=$('#compare-'+key+'-'+side).value;args['mastery_'+side]=$('#compare-mastery-'+side).checked?'1':'0';
    if(['wand','ring'].includes(kind)){if($('#compare-context-'+side).dataset.identity!==item.key)throw new Error('上下文条件仍在载入；请稍后再比较，确认所有所需字段。');args['level_known_'+side]=$('#compare-level-known-'+side).checked?'1':'0';args['curse_'+side]=$('#compare-curse-'+side).value;for(const input of $$('#compare-context-'+side+' [data-compare-key]'))args[input.dataset.compareKey]=input.value;
      if(kind==='ring'){args['ring_pair_'+side]=$('#compare-pair-'+side).checked?'1':'0';if(args['ring_pair_'+side]==='1'){args['ring_pair_level_'+side]=$('#compare-pair-level-'+side).value;args['ring_pair_curse_'+side]=$('#compare-pair-curse-'+side).value;}}}
  }
  if($('#compare-planning-enabled').checked)Object.assign(args,{planning:'1',upgrade_budget:$('#compare-upgrade-budget').value,strength_budget:$('#compare-strength-budget').value,investment_mode:$('#compare-investment-mode').value});return args;
}
async function loadComparisonContext(side,item){
  const target=$('#compare-context-'+side),identity=item?.key||'';
  if(!/^(items.wands.|items.rings.)/.test(identity)){target.replaceChildren();target.dataset.identity='';return;}
  if(target.dataset.identity===identity)return;const serial=++compareContextSerial[side];target.dataset.identity='';
  try{const result=await getJSON('/api/values?'+new URLSearchParams({id:identity}));if(serial!==compareContextSerial[side])return;
    const fields=result.inputs.filter(f=>!['level','strength'].includes(f.key));if(identity.endsWith('wandoffireblast'))fields.push({key:'charges',label:'本次消耗充能',value:1,min:1,max:3,step:1});
    target.dataset.identity=identity;target.innerHTML=fields.map(f=>`<label>${escapeHTML(f.label)} · 示例，需手填核对<input type="number" data-compare-key="${f.key}_${side}" value="${f.value}" min="${f.min}" max="${f.max}" step="${f.step||1}" required></label>`).join('');
  }catch(error){if(serial===compareContextSerial[side]){target.dataset.identity='';compareError=error.message;refreshComparisonOrigin();}}
}
function captureComparisonRaw(){return Object.fromEntries($$('#equipment-comparison input, #equipment-comparison select').map(input=>[input.id||input.dataset.compareKey,{value:input.value,checked:input.checked,manual:input.dataset.manual||'',edited:input.dataset.edited||''}]));}
function rememberComparisonImport(){
  const contexts=Object.fromEntries(['a','b'].map(side=>[side,{
    identity:$('#compare-context-'+side).dataset.identity||'',html:$('#compare-context-'+side).innerHTML,
    augments:$('#compare-augment-'+side).innerHTML}]));
  compareImportUndo={contexts,signature:compareSignature,characterReference:typeof compareCharacterReference!=='undefined'?characterClone(compareCharacterReference):null,raw:captureComparisonRaw(),items:JSON.parse(JSON.stringify(compareItems)),stamp:compareStamp,budgetStamp:compareBudgetStamp,budgetOrigin:compareBudgetOrigin,dirty:compareDirty,fixed:compareFixed,saved:compareSavedPlan,args:compareResultArgs,fields:compareResultFields,error:compareError,result:$('#compare-result').innerHTML,text:$('#compare-copy-text').textContent,unsaved:compareSessionUnsaved};$('#compare-undo-import').hidden=false;
}
$('#compare-undo-import').addEventListener('click',()=>{
  const old=compareImportUndo;if(!old)return;
  compareRequest++;comparePending=false;$('#compare-submit').disabled=false;
  $('#equipment-comparison').querySelectorAll('input,select').forEach(el=>el.disabled=false);
  for(const side of ['a','b'])compareContextSerial[side]++;
  if(typeof compareCharacterReference!=='undefined')compareCharacterReference=old.characterReference||null;
  compareItems=old.items;compareSignature=old.signature;
  compareStamp=old.stamp;compareBudgetStamp=old.budgetStamp;compareBudgetOrigin=old.budgetOrigin;compareDirty=old.dirty;compareFixed=old.fixed;compareSavedPlan=old.saved;compareResultArgs=old.args;compareResultFields=old.fields;compareError=old.error;compareSessionUnsaved=old.unsaved;
  const restoreRaw=()=>{for(const input of $$('#equipment-comparison input, #equipment-comparison select')){
    const raw=old.raw[input.id||input.dataset.compareKey];if(raw){input.value=raw.value;input.checked=raw.checked;input.dataset.manual=raw.manual;input.dataset.edited=raw.edited;}
  }};
  for(const side of ['a','b']){
    $('#compare-'+side).innerHTML=compareItems.map((i,n)=>`<option value="${n}">${escapeHTML(i.name)}</option>`).join('');
    $('#compare-augment-'+side).innerHTML=old.contexts[side].augments;
  }
  restoreRaw();
  for(const side of ['a','b']){
    const saved=old.contexts[side],target=$('#compare-context-'+side),item=compareItems[Number($('#compare-'+side).value)];
    const ready=saved.identity&&saved.identity===item?.key;
    target.innerHTML=ready?saved.html:'';target.dataset.identity=ready?saved.identity:'';
    // Rebuild visibility and, if the old schema was still pending, reload it.
    fillCompareChoice(side,true);
  }
  restoreRaw();
  const physical=['weapon','armor'].includes($('#compare-kind').value);
  $('#compare-investment-mode').querySelector('option[value="min_strength"]').disabled=!physical;
  $('#compare-result').innerHTML=old.result;$('#compare-copy-text').textContent=old.text;
  compareImportUndo=null;$('#compare-undo-import').hidden=true;refreshComparisonOrigin();$('#compare-use-resources').focus();
});
$('#compare-copy-result').addEventListener('click',async()=>{try{if(!$('#compare-copy-text').textContent)throw new Error('先完成比较再复制');await navigator.clipboard.writeText($('#compare-copy-text').textContent);$('#compare-copy-status').textContent='已复制结果、单位与生效条件';}catch(error){$('#compare-copy-status').textContent='复制未完成；请在可选取文本中复制结果与条件。';$('#compare-copy-text').closest('details').open=true;}});

function updateComparisonSavedNote(){const note=compareSavedPlan?.note||'';$('#compare-user-note').textContent=note?'用户用途 / 假设（非游戏事实）：'+note:'';$('#compare-user-note').hidden=!note;const text=$('#compare-copy-text').textContent.split('\n用户用途 / 假设（非游戏事实）：')[0];$('#compare-copy-text').textContent=text+(note?'\n用户用途 / 假设（非游戏事实）：'+note:'');}
