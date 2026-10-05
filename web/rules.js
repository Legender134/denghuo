'use strict';
let numericalRequest=0, numericalDetail=null;
const numericalDrafts=new Map();
const heroParameterKeys=['hero_level','max_hp','hp','depth','strength'];
function cancelNumericalDetail(){numericalRequest++;numericalDetail=null;}
$('#detail-dialog').addEventListener('close',cancelNumericalDetail);
function exampleHTML(example){
  const values=(example.values||[]).map(v=>`<div><dt>${escapeHTML(v.label)}</dt><dd>${escapeHTML(v.value)}<small>${escapeHTML(v.unit||'')}</small></dd>${v.condition?`<p class="numeric-condition">${escapeHTML(v.condition)}</p>`:''}</div>`).join('');
  const table=example.columns?`<div class="table-scroll" tabindex="0" aria-label="可横向滚动的数值表"><table><thead><tr>${example.columns.map(c=>`<th scope="col">${escapeHTML(c)}</th>`).join('')}</tr></thead><tbody>${example.rows.map((row,index)=>`<tr${example.selected_row===index?' class="selected-value-row" aria-current="true"':''}>${row.map(v=>`<td>${escapeHTML(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'';
  return `<section class="example-block"><h3>${escapeHTML(example.title)}</h3>${example.note?`<p class="muted">${escapeHTML(example.note)}</p>`:''}${values?`<dl class="numeric-values">${values}</dl>`:''}${table}</section>`;
}
function visibleCalculationContext(){
  const hero=state?.data?.hero;
  if(!hero)return {};
  return {hero_level:hero.level,max_hp:hero.ht,hp:hero.hp,depth:state.data.depth,strength:hero.strength};
}
function validNumericalInputs(inputs,detail){
  const invalid=inputs.find(input=>input.value.trim()==='' || !input.validity.valid || !Number.isFinite(Number(input.value)));
  if(!invalid)return true;
  detail.dirty=true;refreshNumericalOrigin();
  const warning=$('#values-freshness');
  if(warning){warning.className='rule-warning';warning.textContent='请先补全或修正数值参数；下方仍是修改前的结果。';}
  invalid.reportValidity();invalid.focus();return false;
}
async function loadNumericalDetail(identity,params={},levelOrigin='manual'){
  const seq=++numericalRequest,container=$('#detail-rules');
  if(typeof params==='number')params={level:params};
  if(!numericalDetail || numericalDetail.identity!==identity){
    const drafts=numericalDrafts.get(identity)||{};
    numericalDetail={identity,levelOrigin,context:{...visibleCalculationContext(),...params,...drafts},
      origins:{},source:calculationStamp(),levelSource:calculationStamp()};
    for(const key of heroParameterKeys)if(key in numericalDetail.context)numericalDetail.origins[key]=key in drafts?'手填保留':key==='strength'?'快照基础值':'快照';
    if('level' in params)numericalDetail.origins.level=keyOrigin(levelOrigin);
    if('tier' in params)numericalDetail.origins.tier=['known','unknown'].includes(levelOrigin)?'物品已知阶数':'示例 · 请核对';
    for(const key of Object.keys(drafts))numericalDetail.origins[key]='手填保留';
  }else numericalDetail.context={...numericalDetail.context,...params};
  const detail=numericalDetail,context=detail.context;
  for(const key of Object.keys(context))if(context[key]===undefined||context[key]===null)delete context[key];
  const previousForm=$('#value-calculator');
  container.querySelector('.value-error')?.remove();
  if(previousForm)previousForm.querySelectorAll('input,button').forEach(el=>el.disabled=true);
  else container.innerHTML='<p role="status" class="muted">正在计算数值…</p>';
  try{
    const response=await fetch('/api/values?'+new URLSearchParams({id:identity,...context}));
    const result=await response.json();if(!response.ok)throw new Error(result.error||'数值暂时无法读取');
    if(seq!==numericalRequest||!$('#detail-dialog').open)return;
    if(result.status==='legacy'){container.innerHTML=`<p class="rule-warning">${escapeHTML(result.notice)}</p>`;return;}
    const first=result.blocks[0];
    const lead=first?.values?.length<=6&&!first?.columns&&/^(当前 |按你的|命中概率|技能具体效果|当前治疗状态)/.test(first.title);
    detail.inputs=result.inputs;
    const formHTML=result.inputs.length?`<form id="value-calculator" class="value-calculator"><div class="form-grid">${result.inputs.map(input=>`<label>${escapeHTML(input.label)}<small data-origin-key="${escapeHTML(input.key)}">${escapeHTML(detail.origins[input.key]||'示例 · 请核对')}</small><input data-value-key="${escapeHTML(input.key)}" type="number" step="${input.step||1}" min="${input.min}" max="${input.max}" value="${input.value}" required></label>`).join('')}</div><div class="backup-actions"><button class="primary" type="submit">重新计算</button><button class="secondary" id="values-use-latest" type="button">带入最新角色状态</button></div><p id="values-source" role="status"></p><p class="muted">力量带入基础值；戒指、天赋和支线等效层数请按游戏面板核对。示例参数不会被当作已确认的实战状态。</p></form>`:'';
    container.innerHTML=`<div class="values-heading"><h3>具体数值</h3><span class="pill">${escapeHTML(result.version)}</span></div>${result.inputs.length?'<p id="values-freshness" role="status"></p>':''}${lead?exampleHTML(first):''}${formHTML}<p class="muted">${escapeHTML(result.notice)}</p>${result.blocks.slice(lead?1:0).map(exampleHTML).join('')}${result.no_fixed_values?(result.non_numeric?'<p class="muted">这是阅读资料或场景标记，没有独立的伤害、生命或概率属性。</p>':'<p class="rule-warning">此条目的具体数值尚在核对，目前不提供未经确认的结果。</p>'):''}`;
    $$('[data-value-key]').forEach(input=>input.addEventListener('input',()=>{
      detail.origins[input.dataset.valueKey]='手填 · 尚未重新计算';
      $(`[data-origin-key="${input.dataset.valueKey}"]`).textContent=detail.origins[input.dataset.valueKey];
      detail.dirty=true;refreshNumericalOrigin();
    }));
    $('#value-calculator')?.addEventListener('submit',event=>{
      event.preventDefault();if(!validNumericalInputs(Array.from($$('[data-value-key]')),detail))return;
      const next={...context};
      const drafts={...numericalDrafts.get(identity)};
      $$('[data-value-key]').forEach(input=>{
        const key=input.dataset.valueKey;next[key]=Number(input.value);
        if((detail.origins[key]||'').startsWith('手填')){drafts[key]=next[key];detail.origins[key]='手填';}
      });
      numericalDrafts.set(identity,drafts);
      if(numericalDrafts.size>64)numericalDrafts.delete(numericalDrafts.keys().next().value);
      detail.dirty=false;
      if(next.max_hp!==undefined&&next.hp===undefined)next.hp=Math.min(32,next.max_hp);
      if(next.target_max_hp!==undefined&&next.target_hp===undefined)next.target_hp=Math.min(40,next.target_max_hp);
      loadNumericalDetail(identity,next,detail.levelOrigin);
    });
    $('#values-use-latest')?.addEventListener('click',()=>{
      if(!state?.data || !detail.inputs)return;
      const retainedInputs=Array.from($$('[data-value-key]')).filter(input=>!heroParameterKeys.includes(input.dataset.valueKey));
      if(!validNumericalInputs(retainedInputs,detail))return;
      const next={...context,...visibleCalculationContext()},drafts={...numericalDrafts.get(identity)};
      retainedInputs.forEach(input=>{const key=input.dataset.valueKey;
        next[key]=Number(input.value);
        if((detail.origins[key]||'').startsWith('手填')){drafts[key]=next[key];detail.origins[key]='手填';}
      });
      for(const key of heroParameterKeys){delete drafts[key];detail.origins[key]=key==='strength'?'快照基础值':'快照';}
      if(detail.origins.level==='物品已知等级'){
        const items=(state.data.items||[]).filter(i=>i.key===identity&&i.known&&i.level!==null&&i.available);
        if(items.length===1){next.level=items[0].level;delete drafts.level;detail.levelSource=calculationStamp();}
      }
      if(detail.origins.tier==='物品已知阶数'){
        const items=(state.data.items||[]).filter(i=>i.key===identity&&i.known&&i.tier&&i.available);
        if(items.length===1){next.tier=items[0].tier;delete drafts.tier;detail.levelSource=calculationStamp();}
      }
      numericalDrafts.set(identity,drafts);detail.source=calculationStamp();detail.dirty=false;
      loadNumericalDetail(identity,next,detail.levelOrigin);
    });
    refreshNumericalOrigin();
  }catch(error){if(seq===numericalRequest&&$('#detail-dialog').open){const message=`<p role="alert" class="rule-warning value-error">${escapeHTML(error.message)}</p>`;if(previousForm?.isConnected)previousForm.insertAdjacentHTML('afterend',message);else container.innerHTML=message;}}
  finally{if(seq===numericalRequest&&previousForm?.isConnected)previousForm.querySelectorAll('input,button').forEach(el=>el.disabled=false);}
}
function keyOrigin(origin){return origin==='known'?'物品已知等级':origin==='unknown'?'等级未知 · +0示例':'示例';}
function calculationStamp(){return state?.data?{modified:state.modified,slot:state.active_slot,mode:state.settings.mode,revision:state.revision,started:state.started}:null;}
function refreshNumericalOrigin(){
  const d=numericalDetail,freshness=$('#values-freshness'),source=$('#values-source');
  if(!d || !freshness || !source)return;
  const now=calculationStamp(),stamp=d.source;
  const snapshotUsed=d.inputs?.some(i=>(d.origins[i.key]||'').startsWith('快照')||['物品已知等级','物品已知阶数'].includes(d.origins[i.key]));
  const changed=stamp&&(!now||['modified','slot','mode','revision','started'].some(k=>stamp[k]!==now[k]));
  const levelOld=(d.origins.level==='物品已知等级'||d.origins.tier==='物品已知阶数')&&d.levelSource&&(!now||['modified','slot','mode','revision','started'].some(k=>d.levelSource[k]!==now[k]));
  const old=snapshotUsed&&(!now||state.stale||changed||levelOld);
  freshness.className=old||d.dirty?'rule-warning':'muted';
  freshness.textContent=levelOld?'物品等级来自较早快照，无法唯一确认现在是哪件装备；请核对等级后手填。':d.dirty?'输入已修改；下方仍是修改前的结果，请重新计算。':old?(changed?'游戏快照已经变化；下方结果仍按原参数计算，请带入最新状态或核对后手填。':'这些结果含旧快照参数，请按游戏画面核对。'):'按下列参数计算；随机范围和生效条件见各表。';
  source.className='muted';source.textContent=stamp?`首次带入：${stamp.mode==='manual'?'手动局势':`槽位 ${stamp.slot}`} · ${fmtTime(stamp.modified)}。手填保留项不会自动跟随游戏。`:'没有角色快照；参数为示例或手填。';
  const button=$('#values-use-latest');if(button)button.disabled=!now;
}
