'use strict';
let compareCatalog=[],compareItems=[],compareSignature='',compareRequest=0,compareStamp=null,compareDirty=false,compareError='';
async function initializeEquipmentComparison(){
  const lists=await Promise.all(['items.weapon.melee.','items.armor.'].map(async q=>{
    const r=await fetch('/api/library?'+new URLSearchParams({q,category:'物品'}));
    if(!r.ok)throw new Error('装备资料暂时不可用');return (await r.json()).entries;
  }));
  compareCatalog=lists.flat().filter(r=>!r.id.includes('$')&&!r.id.endsWith('.ability'));
  compareSignature='';
  renderEquipmentComparison();
}
function renderEquipmentComparison(){
  const form=$('#equipment-comparison');if(!form)return;
  const kind=$('#compare-kind').value, prefix=kind==='armor'?'items.armor.':'items.weapon.melee.';
  const owned=(state?.data?.items||[]).filter(i=>i.known&&i.available&&i.key.startsWith(prefix));
  const sig=JSON.stringify([kind,state?.started,state?.active_slot,owned]);
  if(sig!==compareSignature){
    compareSignature=sig;
    const old=compareItems,oldAugment={a:$('#compare-augment-a').value,b:$('#compare-augment-b').value};
    compareItems=[...owned.map((i,n)=>({...i,token:`own:${i.key}:${i.location}:${n}`,owned:true})),
      ...compareCatalog.filter(e=>e.id.startsWith(prefix)).map(e=>({key:e.id,name:e.name,level:0,owned:false,token:'book:'+e.id}))];
    for(const suffix of ['a','b']){
      const select=$('#compare-'+suffix),prior=old[Number(select.value)]?.token;
      select.innerHTML=compareItems.map((i,n)=>`<option value="${n}">${escapeHTML(i.owned?`${i.location} · ${i.name}${i.level===null?' · 等级未知':''}`:`手册 · ${i.name}`)}</option>`).join('');
      const index=compareItems.findIndex(i=>i.token===prior);select.value=String(index>=0?index:suffix==='b'&&owned.length>1?1:0);
      const augment=$('#compare-augment-'+suffix);
      augment.innerHTML=(kind==='armor'?[['NONE','无强化'],['EVASION','闪避'],['DEFENSE','防御']]:[['NONE','无强化'],['SPEED','速度'],['DAMAGE','伤害']]).map(([value,label])=>`<option value="${value}">${label}</option>`).join('');
      if(index>=0 && augment.dataset.manual)augment.value=oldAugment[suffix];
      fillCompareChoice(suffix,index>=0);
    }
    compareDirty=true;
  }
  const strength=$('#compare-strength'),latestStrength=String(state?.data?.hero?.strength||10);
  if(!strength.dataset.edited && String(strength.value)!==latestStrength){strength.value=latestStrength;compareDirty=true;}
  $('#compare-follow-strength').disabled=!state?.data;
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
  const allowed=$('#compare-kind').value==='armor'?['NONE','EVASION','DEFENSE']:['NONE','SPEED','DAMAGE'];
  if(!augment.dataset.manual)augment.value=allowed.includes(item?.augmentation)?item.augmentation:'NONE';
  $('#compare-origin-'+suffix).textContent=[level,mastery,augment,tier].some(i=>i.dataset.manual)?'手填条件保留，请按游戏画面核对':item?.owned?(item.level===null?'等级未知，先按+0试算':'已带入已知等级、精通/强化及原护甲阶数'):'手册示例，请填写要比较的等级与条件';
}
function refreshComparisonOrigin(){
  const target=$('#compare-status');if(!target)return;
  const changed=compareStamp&&(!state?.data||['modified','slot','mode','revision','started'].some(k=>compareStamp[k]!==calculationStamp()?.[k]));
  const old=compareStamp&&(changed||state?.stale);
  target.className=compareError||old||compareDirty?'rule-warning':'muted';
  target.textContent=compareError|| (compareDirty?($('#compare-result').childElementCount?'条件已变化，请点击比较；已有表格仍使用上次条件。':'请选择装备和条件，再点击比较。'):old?'角色快照已变化或过期，请核对力量与装备，再比较。':'按所填条件比较；请核对游戏面板。');
  target.textContent+=$('#compare-strength').dataset.edited?' 力量为手填值，保留你的输入。':state?.data?' 力量跟随当前快照的基础值；戒指和天赋加值请手填。':' 没有角色快照，力量10为示例，请填写游戏中的数值。';
}
$('#compare-kind').addEventListener('change',()=>{compareSignature='';compareError='';renderEquipmentComparison();});
$('#compare-follow-strength').addEventListener('click',()=>{
  if(!state?.data)return;
  delete $('#compare-strength').dataset.edited;delete $('#compare-strength').dataset.manual;
  compareDirty=true;compareError='';renderEquipmentComparison();
});
for(const suffix of ['a','b'])$('#compare-'+suffix).addEventListener('change',()=>{fillCompareChoice(suffix);compareError='';compareDirty=true;refreshComparisonOrigin();});
$('#equipment-comparison').addEventListener('input',e=>{compareDirty=true;compareError='';e.target.dataset.manual='true';if(/^compare-(level|augment|mastery|tier)-[ab]$/.test(e.target.id))fillCompareChoice(e.target.id.slice(-1),true);if(e.target.id==='compare-strength')e.target.dataset.edited='true';refreshComparisonOrigin();});
$('#equipment-comparison').addEventListener('submit',async event=>{
  event.preventDefault();const seq=++compareRequest,button=$('#compare-submit'),signature=compareSignature;compareError='';button.disabled=true;
  const args={strength:$('#compare-strength').value};
  for(const suffix of ['a','b']){
    const item=compareItems[Number($('#compare-'+suffix).value)];if(!item){button.disabled=false;return;}
    args['id_'+suffix]=item.key;args['level_'+suffix]=$('#compare-level-'+suffix).value;
    args['mastery_'+suffix]=$('#compare-mastery-'+suffix).checked?'1':'0';args['augment_'+suffix]=$('#compare-augment-'+suffix).value;
    args['tier_'+suffix]=$('#compare-tier-'+suffix).value;
  }
  const source=calculationStamp();
  $('#equipment-comparison').querySelectorAll('input,select').forEach(el=>el.disabled=true);
  try{
    const response=await fetch('/api/compare?'+new URLSearchParams(args)),result=await response.json();
    if(!response.ok)throw new Error(result.error);if(seq!==compareRequest)return;
    const [a,b]=result.choices;
    const columns=['数值',`${a.name} +${a.level}`,`${a.name} +${a.level+1}`,`${b.name} +${b.level}`,`${b.name} +${b.level+1}`,'B相对A（当前）'];
    $('#compare-result').innerHTML=exampleHTML({title:'现在装备谁，下一张升级用在哪',columns,rows:result.rows.map(r=>[r.label,...r.values,r.difference]),note:result.notice})+
      `<p class="muted">普通附魔升级损失风险：A ${escapeHTML(a.upgrade_risk)}%，B ${escapeHTML(b.upgrade_risk)}%。硬化、诅咒和护甲蜕变天赋分支请查升级卷轴。</p>`;
    compareDirty=signature!==compareSignature || args.strength!==String($('#compare-strength').value);compareStamp=source;refreshComparisonOrigin();
  }catch(error){compareError=error.message;refreshComparisonOrigin();}
  finally{if(seq===compareRequest){button.disabled=false;$('#equipment-comparison').querySelectorAll('input,select').forEach(el=>el.disabled=false);}}
});
initializeEquipmentComparison().catch(error=>{$('#compare-status').textContent=error.message;});
