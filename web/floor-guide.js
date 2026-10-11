'use strict';
// Public rules load automatically; saved hidden contents require a fresh click.
const floorGuide={context:null,key:null,level:null,catalog:null,serial:0,signature:null,revealed:false,nodes:new Map()};
function floorGuideContext(){return JSON.stringify([snapshotViewOwner(),state?.revision,state?.settings_revision,state?.error,state?.stale,state?.data?.depth,state?.data?.branch,state?.data?.version,state?.data?.hero?.level]);}
function floorGuideKey(){return JSON.stringify([snapshotViewOwner(),state?.data?.depth,state?.data?.branch,state?.data?.version]);}
function hideFloorContents(message='隐藏门、陷阱和未见物品需主动揭示。'){
  floorGuide.revealed=false;$('#floor-hidden-content').replaceChildren();$('#floor-hidden-content').hidden=true;
  $('#floor-hidden-count').textContent='尚未揭示';$('#floor-hidden-status').textContent=message;$('#floor-hidden-open').textContent='揭示本层隐藏内容';
}
function refreshFloorGuide(force=false){
  const context=floorGuideContext();if(!force&&context===floorGuide.context)return;
  const key=floorGuideKey(),same=key===floorGuide.key;floorGuide.context=context;floorGuide.key=key;floorGuide.catalog=null;
  const level=state?.data?.hero?.level,levelChanged=level!==floorGuide.level;floorGuide.level=level;
  const serial=++floorGuide.serial;hideFloorContents('保存快照更新后，隐藏内容需重新主动揭示。');$('#floor-hidden-open').disabled=true;
  inlineError($('#floor-guide-error'),'');
  if(!same){floorGuide.signature=null;floorGuide.nodes.clear();$('#floor-monsters-list').replaceChildren();$('#floor-monsters-count').textContent='';}
  else if(levelChanged){
    floorGuide.signature=null;
    for(const row of floorGuide.nodes.values())if(row.content){
      if(row.content.contains(document.activeElement))row.summary.focus();
      row.content.replaceChildren();row.content.textContent='角色等级已变化，正在更新数值与掉落条件…';
    }
  }
  if(!state?.data||state.error||state.settings.mode!=='save'){
    floorGuide.signature=null;floorGuide.nodes.clear();$('#floor-monsters-list').replaceChildren();$('#floor-monsters-count').textContent='';
    $('#floor-guide-title').textContent='当前楼层';$('#floor-guide-source').textContent=state?.settings?.mode==='manual'?'手动局势不提供本层探查。':'游戏保存后，自动显示本层资料。';
    $('#floor-monsters-note').textContent='连接有效存档后显示本层生成规则。';return;
  }
  $('#floor-guide-title').textContent=`第 ${state.data.depth} 层${state.data.branch?' · 支线 '+state.data.branch:''}`;
  $('#floor-guide-source').textContent='正在读取本层资料…';
  void loadFloorGuide(serial,context,key);
}
async function loadFloorGuide(serial,context,key){
  try{
    const catalog=await post('/api/scouting',{action:'catalog'});
    if(serial!==floorGuide.serial||context!==floorGuideContext())return;
    if(catalog.source.depth!==state.data.depth||catalog.source.branch!==state.data.branch)throw new Error('角色正在换层，请等待保存完成后刷新。');
    floorGuide.catalog=catalog;
    $('#floor-guide-source').textContent=`槽位 ${catalog.source.slot} · ${fmtTime(catalog.source.modified)} 保存${state.stale?' · 旧快照':''}`;
    $('#floor-monsters-note').textContent=catalog.encounters.note;
    $('#floor-hidden-open').disabled=!catalog.supported||!catalog.floors.some(f=>f.current&&f.available);
    renderFloorMonsters(catalog,key);
  }catch(error){if(serial===floorGuide.serial){inlineError($('#floor-guide-error'),error.message);$('#floor-guide-source').textContent='本层资料尚未读取；可点击刷新重试。';}}
}
function renderFloorMonsters(catalog,key){
  const rows=catalog.encounters.rows,signature=JSON.stringify([key,catalog.source.hero_level,rows]);
  $('#floor-monsters-count').textContent=`${rows.length} 种`;
  if(signature===floorGuide.signature)return;
  const previous=new Map([...floorGuide.nodes].map(([id,row])=>[id,{open:row.node.open,focused:row.node.contains(document.activeElement)}]));
  floorGuide.signature=signature;floorGuide.nodes=new Map();const target=$('#floor-monsters-list');target.replaceChildren();
  let focus=null;const reopen=[];
  function remember(id,node,summary,content=null){const before=previous.get(id);node.open=Boolean(before?.open);floorGuide.nodes.set(id,{node,summary,content});if(before?.focused)focus=summary;}
  const groups=new Map();
  for(const row of rows){
    if(!row.fold_group||groups.has(row.fold_group))continue;
    const wrapper=document.createElement('details');wrapper.className='floor-monster-group';
    const heading=document.createElement('summary');heading.textContent=`${row.fold_group} · ${rows.filter(r=>r.fold_group===row.fold_group).length} 种`;
    const content=document.createElement('div');wrapper.append(heading,content);remember('group:'+row.fold_group,wrapper,heading);groups.set(row.fold_group,{wrapper,content,attached:false});
  }
  for(const row of rows){
    let container=target;
    if(row.fold_group){const group=groups.get(row.fold_group);if(!group.attached){target.append(group.wrapper);group.attached=true;}container=group.content;}
    const card=document.createElement('details');card.className='floor-monster';
    const summary=document.createElement('summary'),name=document.createElement('strong'),brief=document.createElement('span');
    name.textContent=row.name+(row.group==='普通轮换'?'':` · ${row.group}`);brief.textContent=`生命 ${row.hp} · 普攻 ${row.damage} · 减伤 ${row.dr}`;summary.append(name,brief);
    const condition=document.createElement('p');condition.className='muted';condition.textContent=row.group+' · '+row.condition;
    const content=document.createElement('div'),retry=document.createElement('button');retry.type='button';retry.className='text-button';retry.textContent='重新读取怪物资料';retry.hidden=true;
    card.append(summary,condition,content,retry);container.append(card);
    let loaded=false,busy=false;
    async function load(){
      if(loaded||busy||key!==floorGuide.key||signature!==floorGuide.signature)return;
      busy=true;retry.hidden=true;content.textContent='正在读取数值与掉落概率…';
      try{
        const hero=catalog.source.hero_level??1,referenceDepth=row.reference_depth??catalog.source.depth,query=new URLSearchParams({id:row.id,depth:referenceDepth,hero_level:hero,loot_count:0});
        const response=await fetch('/api/values?'+query);const detail=await response.json();if(!response.ok)throw new Error(detail.error||'怪物资料读取失败');
        if(key!==floorGuide.key||signature!==floorGuide.signature)return;
        const calculationParams=(detail.inputs||[]).filter(field=>!['depth','hero_level','loot_count','wealth_bonus'].includes(field.key));
        const parameterNote=calculationParams.length?`<p class="muted">本次参考参数：${escapeHTML(calculationParams.map(field=>`${field.label}：${field.value}`).join('；'))}。未读取敌人的当前状态，可在完整资料调整。</p>`:'';
        content.innerHTML=`<p class="muted">正常基础状态 · 角色等级 ${hero}${catalog.source.hero_level==null?'（示例）':''} · 累计成功掉落与财富有效加成都按0参考。完整资料可调整适用的次数和财富条件。</p>`+parameterNote+detail.blocks.map(exampleHTML).join('');
        const button=document.createElement('button');button.type='button';button.className='text-button';button.textContent='调整掉落次数等条件 / 查看来源';
        button.addEventListener('click',()=>{if(key!==floorGuide.key||signature!==floorGuide.signature)return;showReference({id:row.id,name:row.name,lookup_context:{capture_context:true,ignore_drafts:true,source:{mode:'example'},params:{depth:referenceDepth,hero_level:hero,loot_count:0},field_origins:row.reference_depth==null?{}:{depth:'召唤规则固定等效层数，非当前楼层'},conditions:row.condition+'；本层正常敌人参考；累计成功掉落示例0次，未读取本局计数或敌人临时状态。'}},'4.0.2');});
        content.append(button);loaded=true;
      }catch(error){if(key===floorGuide.key&&signature===floorGuide.signature){content.textContent=error.message;retry.hidden=false;}}
      finally{busy=false;}
    }
    card.addEventListener('toggle',()=>{if(card.open)void load();});retry.addEventListener('click',load);
    remember('monster:'+(row.reference_key||row.id),card,summary,content);if(card.open)reopen.push(load);
  }
  if(focus)focus.focus();for(const load of reopen)void load();
}
async function revealFloorContents(){
  if(floorGuide.revealed){hideFloorContents('隐藏内容已收起；游戏文件未改变。');return;}
  const catalog=floorGuide.catalog;if(!catalog||$('#floor-hidden-open').disabled)return;
  const serial=floorGuide.serial,context=floorGuide.context;$('#floor-hidden-open').disabled=true;inlineError($('#floor-guide-error'),'');
  $('#floor-hidden-status').textContent='正在只读解析本层保存内容…';
  try{
    const result=await post('/api/scouting',{action:'floor',depth:catalog.source.depth,branch:catalog.source.branch,expected:catalog.source.expected,reveal:true});
    if(serial!==floorGuide.serial||context!==floorGuideContext())return;
    renderFloorContents(result);floorGuide.revealed=true;$('#floor-hidden-open').textContent='收起本层隐藏内容';
  }catch(error){if(serial===floorGuide.serial){hideFloorContents('本次未揭示；请刷新后重试。');inlineError($('#floor-guide-error'),error.message);}}
  finally{if(serial===floorGuide.serial)$('#floor-hidden-open').disabled=false;}
}
function renderFloorContents(result){
  const target=$('#floor-hidden-content');target.replaceChildren();target.hidden=false;
  const hidden=result.features.filter(row=>row.hidden),unseen=result.traps.filter(row=>!row.visible);
  $('#floor-hidden-count').textContent=`${hidden.filter(r=>r.terrain===16).length} 门 · ${unseen.length} 未显陷阱`;
  $('#floor-hidden-status').textContent=`已主动揭示 · 楼层保存于 ${fmtTime(result.source.floor_modified)} · 非实时视野`;
  const lines=[...hidden.filter(r=>r.terrain===16).map(r=>`${scoutCoordinate(r)} ${r.name}`),...unseen.map(r=>`${scoutCoordinate(r)} ${r.name}${r.active?'':' · 已失效'}`)];
  const list=document.createElement('ul');for(const text of lines.length?lines:['没有保存隐藏门或未显示的陷阱。']){const li=document.createElement('li');li.textContent=text;list.append(li);}target.append(list);
  for(const heap of result.heaps){
    const card=document.createElement('details'),heading=document.createElement('summary');heading.textContent=`${heap.name} ${scoutCoordinate(heap)} · ${heap.items.length} 项${heap.seen?'':' · 未见'}${heap.hidden?' · 隐藏':''}`;card.append(heading);
    for(const item of heap.items){const button=document.createElement('button');button.type='button';button.className='text-button';button.textContent=`${item.name} ×${item.quantity}${item.cursed===true?' · 诅咒':''}`;button.addEventListener('click',()=>showScoutedItem(item,result));card.append(button);}target.append(card);
  }
  const saved=document.createElement('details'),heading=document.createElement('summary');heading.textContent=`本层保存的生物 · ${result.mobs.length} 个`;saved.append(heading);
  const container=document.createElement('div');container.id='floor-saved-mobs';saved.append(container);target.append(saved);
  scoutingCards('floor-saved-mobs',result.mobs,result,row=>`${row.hp==null?'生命未确认':'保存生命 '+row.hp}${row.ht==null?'':' / '+row.ht} · 所列物品为随身保存记录`,'没有保存生物。');
  const full=document.createElement('button');full.type='button';full.className='text-button';full.textContent='查看本层完整地图与资料';full.addEventListener('click',()=>{const captured=scoutingContext();navigate('scouting');if(captured!==scoutingContext())return;scoutSerial++;scoutBusy=false;renderScoutingCatalog(floorGuide.catalog);scoutContext=captured;inlineError($('#scout-error'),'');const select=$('#scout-floor');select.value=`${result.depth}:${result.branch}`;$('#scout-reveal').checked=true;scoutResult=result;renderScouting(result);scoutingControls();$('#scout-status').textContent=result.note;});target.append(full);
}
$('#floor-guide-refresh').addEventListener('click',()=>refreshFloorGuide(true));
$('#floor-hidden-open').addEventListener('click',revealFloorContents);
if(state)refreshFloorGuide();
