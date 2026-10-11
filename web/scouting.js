'use strict';
let scoutCatalog=null,scoutResult=null,scoutSerial=0,scoutContext=null,scoutBusy=false;
function scoutingContext(){return JSON.stringify([state?.started,state?.settings_revision,state?.active_slot,state?.run_id,state?.revision,state?.error,state?.settings?.mode]);}
function scoutingLocation(){const [depth,branch]=String($('#scout-floor').value).split(':').map(Number);return {depth,branch};}
function scoutingControls(){
  const location=scoutingLocation(),row=scoutCatalog?.floors.find(f=>f.depth===location.depth&&f.branch===location.branch);
  $('#scout-floor').disabled=scoutBusy||!scoutCatalog;
  $('#scout-reveal').disabled=!scoutCatalog?.supported||!row?.available;
  $('#scout-open').disabled=scoutBusy||$('#scout-reveal').disabled||!$('#scout-reveal').checked;
}
function clearScoutingResult(){scoutResult=null;$('#scout-result').hidden=true;for(const id of ['scout-features','scout-heaps','scout-traps','scout-mobs'])$('#'+id).replaceChildren();$('#scout-map-text').textContent='';}
function refreshScoutingContext(){
  if(typeof refreshForecastContext==='function')refreshForecastContext();
  const current=scoutingContext();if(current===scoutContext)return;
  scoutSerial++;scoutContext=current;scoutCatalog=null;scoutBusy=false;$('#scout-reveal').checked=false;clearScoutingResult();scoutingControls();
  $('#scout-source').textContent='存档连接或保存快照已变化，请重新读取楼层清单。';$('#scout-status').textContent='旧探查已收起；重新选择并主动揭示后查看。';
  if(view==='scouting'&&state?.data&&!state.error&&state.settings.mode==='save')void loadScouting();
}
async function loadScouting(){
  const serial=++scoutSerial,context=scoutingContext();scoutContext=context;scoutBusy=true;scoutCatalog=null;
  $('#scout-reveal').checked=false;clearScoutingResult();scoutingControls();inlineError($('#scout-error'),'');$('#scout-status').textContent='正在读取本局已生成楼层清单，隐藏内容尚未展开…';
  try{
    const result=await post('/api/scouting',{action:'catalog'});if(serial!==scoutSerial||context!==scoutingContext())return;
    scoutCatalog=result;const source=result.source,select=$('#scout-floor');select.replaceChildren();
    for(const floor of result.floors){const option=document.createElement('option');option.value=`${floor.depth}:${floor.branch}`;option.textContent=`第 ${floor.depth} 层 · ${floor.branch?`支线 ${floor.branch}`:'主地牢'}${floor.current?' · 当前':''}${floor.available?'':' · 文件尚不可读'}`;option.disabled=!floor.available;select.append(option);if(floor.current)select.value=option.value;}
    $('#scout-source').textContent=`槽位 ${source.slot} · 角色保存于第 ${source.depth} 层${source.branch?` / 支线 ${source.branch}`:''} · 游戏 ${source.version_name||`版本码 ${source.version}`} · ${fmtTime(source.modified)}`;
    $('#scout-status').textContent=result.supported?result.note+' 勾选后点击揭示；游戏文件只读。':'当前版本尚未支持；已核对官方4.0.1与4.0.2，隐藏内容未展开。';
  }catch(error){if(serial===scoutSerial){inlineError($('#scout-error'),error.message);$('#scout-status').textContent='楼层清单尚未读取；隐藏内容未展开。';}}
  finally{if(serial===scoutSerial){scoutBusy=false;scoutingControls();}}
}
async function revealScoutingFloor(){
  if(!scoutCatalog||$('#scout-open').disabled||!$('#scout-reveal').checked)return;
  const serial=++scoutSerial,context=scoutingContext(),location=scoutingLocation(),expected=scoutCatalog.source.expected;
  scoutBusy=true;clearScoutingResult();scoutingControls();inlineError($('#scout-error'),'');$('#scout-status').textContent='正在只读解析所选楼层…';
  try{
    const result=await post('/api/scouting',{action:'floor',...location,expected,reveal:true}),current=scoutingLocation();
    if(serial!==scoutSerial||context!==scoutingContext()||!$('#scout-reveal').checked||location.depth!==current.depth||location.branch!==current.branch)return;
    scoutResult=result;renderScouting(result);$('#scout-status').textContent=result.note;
  }catch(error){if(serial===scoutSerial){inlineError($('#scout-error'),error.message);$('#scout-status').textContent='本次未展开探查；需要时重新读取楼层清单。';}}
  finally{if(serial===scoutSerial){scoutBusy=false;scoutingControls();}}
}
const scoutCoordinate=row=>`(${row.x}, ${row.y})`;
function scoutingList(id,rows,describe,empty){const target=$('#'+id);target.replaceChildren();for(const row of rows){const li=document.createElement('li');li.textContent=describe(row);target.append(li);}if(!rows.length){const li=document.createElement('li');li.textContent=empty;target.append(li);}}
function showScoutedItem(item,result){
  const source=result.source,label=`槽位 ${source.slot} · 第 ${result.depth} 层${result.branch?` / 支线 ${result.branch}`:''} · ${fmtTime(source.floor_modified)}`;
  showDetail(item.name,item.description,item.location,`${label} · 已主动揭示；游戏鉴定状态未改变，未加入背包。${source.version===920?' 数值手册按4.0.2参考，请核对版本差异。':''}`);
  showItemNote(item.user_note);if(typeof setDetailEntry==='function')setDetailEntry(item.key);
  const params={...(item.level==null?{}:{level:item.level}),...(item.tier?{tier:item.tier}:{}),...(item.volume==null?{}:{dew_volume:item.volume})};
  loadNumericalDetail(item.key,params,item.level_applicable===false?'not_applicable':item.level==null?'unknown':'revealed',{
    capturedContext:true,ignoreDrafts:true,sourceStamp:null,fieldOrigins:Object.fromEntries(Object.keys(params).map(key=>[key,'已主动揭示的楼层物品 · '+label])),
    skillConditions:`${label}；楼层物品的存档参考，未合并当前角色、装备或临时状态。`,skillState:'unknown'});
}
function scoutingCards(id,rows,result,describe,empty){
  const target=$('#'+id);target.replaceChildren();if(!rows.length){const p=document.createElement('p');p.textContent=empty;target.append(p);return;}
  for(const row of rows){const card=document.createElement('section');card.className='scout-card';const heading=document.createElement('h3');heading.textContent=`${row.name} ${scoutCoordinate(row)}`;const note=document.createElement('p');note.className='muted';note.textContent=describe(row);card.append(heading,note);
    for(const item of row.items){const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=`${item.name} ×${item.quantity}${item.cursed===true?' · 诅咒':''}`;button.addEventListener('click',()=>showScoutedItem(item,result));card.append(button);}
    if(row.reference){const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='查正常数值与随机掉落';button.addEventListener('click',()=>showReference({...row.reference,lookup_context:{capture_context:true,ignore_drafts:true,source:{mode:'example'},params:{depth:result.depth},conditions:'正常基础状态的独立参考；角色等级默认1、累计成功掉落默认0。未将当前生物的状态或本局掉落计数代入。'}},'4.0.2'));card.append(button);}
    if(!row.items.length){const p=document.createElement('p');p.textContent='未保存随身物品；随机掉落另查怪物手册。';card.append(p);}target.append(card);
  }
}
function renderScouting(result){
  $('#scout-title').textContent=`第 ${result.depth} 层 · ${result.branch?`支线 ${result.branch}`:'主地牢'} · 存档探查`;
  $('#scout-snapshot').textContent=`槽位 ${result.source.slot} · 楼层保存于 ${fmtTime(result.source.floor_modified)} · ${result.item_count} 项仍保存的物品 · 非实时视野`;
  scoutingList('scout-features',result.features,row=>`${scoutCoordinate(row)} ${row.name}${row.hidden?' · 主动揭示':''}`,'没有保存所列门、楼梯或设施。');
  scoutingList('scout-traps',result.traps,row=>`${scoutCoordinate(row)} ${row.name} · ${row.active?'可触发':'已失效'} · ${row.visible?'游戏内已显示':'尚未显示，主动揭示'}`,'没有保存陷阱对象。');
  scoutingCards('scout-heaps',result.heaps,result,row=>`${row.seen?'游戏内已看见':'游戏内尚未看见'}${row.hidden?' · 隐藏':''}${row.haunted?' · 闹鬼':''} · 取得需符合容器或购买条件`,'没有仍保存的地面或容器物品。');
  scoutingCards('scout-mobs',result.mobs,result,row=>`${row.hp==null?'生命未确认':`保存生命 ${row.hp}${row.ht==null?'':' / '+row.ht}`} · 所列物品仅为生物随身保存记录`,'没有保存的生物。');
  const map=result.map,canvas=$('#scout-map');canvas.width=map.width*12;canvas.height=map.height*12;const ctx=canvas.getContext('2d');
  const colors={0:'#080e0b',4:'#687463',12:'#687463',5:'#a2875d',10:'#a87e50',16:'#f29ab2',17:'#cd6d65',18:'#cd6d65',19:'#786353',7:'#8bb39d',8:'#d5bd82',29:'#426874',15:'#527944',30:'#527944'};
  map.tiles.forEach((tile,index)=>{ctx.fillStyle=colors[tile]||'#344133';ctx.fillRect(index%map.width*12,Math.floor(index/map.width)*12,11,11);});
  for(const [rows,color] of [[result.heaps,'#f4d69c'],[result.mobs,'#96c8ef']])for(const row of rows){ctx.strokeStyle=color;ctx.strokeRect((row.x-1)*12+2,(row.y-1)*12+2,7,7);}
  if(map.hero!==null){ctx.fillStyle='#fff0c9';ctx.fillRect(map.hero%map.width*12+3,Math.floor(map.hero/map.width)*12+3,5,5);}
  const symbols={0:' ',4:'#',12:'#',5:'+',6:'/',10:'+',16:'?',17:'^',18:'^',19:'_',7:'<',8:'>',21:'>',22:'>',29:'~',37:'<'};
  const lines=[];for(let y=0;y<map.height;y++)lines.push(String(y+1).padStart(3,' ')+' '+map.tiles.slice(y*map.width,(y+1)*map.width).map((tile,x)=>y*map.width+x===map.hero?'@':symbols[tile]||'.').join(''));
  $('#scout-map-text').textContent=lines.join('\n');$('#scout-result').hidden=false;
}
$('#scout-refresh').addEventListener('click',loadScouting);
$('#scout-floor').addEventListener('change',()=>{scoutSerial++;scoutBusy=false;$('#scout-reveal').checked=false;clearScoutingResult();scoutingControls();$('#scout-status').textContent='已更换楼层；勾选并主动揭示后查看。';});
$('#scout-reveal').addEventListener('change',()=>{if(!$('#scout-reveal').checked){scoutSerial++;scoutBusy=false;clearScoutingResult();$('#scout-status').textContent='隐藏内容已收起；游戏文件未改变。';}scoutingControls();});
$('#scout-open').addEventListener('click',revealScoutingFloor);
if(view==='scouting'&&state)void loadScouting();
