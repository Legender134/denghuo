'use strict';
let scoutCatalog=null,scoutResult=null,scoutSerial=0,scoutContext=null,scoutBusy=false;
const scoutMapView={zoom:1,panX:0,panY:0,selected:-1,width:0,height:0,drag:null};
const scoutTextures=new Map();
function scoutTexture(encoded){
  if(!encoded||typeof Image!=='function')return null;
  if(!scoutTextures.has(encoded)){const image=new Image();scoutTextures.set(encoded,image);image.onload=()=>drawScoutMap();image.src='data:image/png;base64,'+encoded;}
  const image=scoutTextures.get(encoded);return image.complete&&image.naturalWidth?image:null;
}
function scoutingContext(){return JSON.stringify([state?.started,state?.settings_revision,state?.active_slot,state?.run_id,state?.revision,state?.error,state?.settings?.mode]);}
function scoutingLocation(){const [depth,branch]=String($('#scout-floor').value).split(':').map(Number);return {depth,branch};}
function scoutingControls(){
  const location=scoutingLocation(),row=scoutCatalog?.floors.find(f=>f.depth===location.depth&&f.branch===location.branch);
  $('#scout-floor').disabled=scoutBusy||!scoutCatalog;
  $('#scout-reveal').disabled=!scoutCatalog?.supported||!row?.available;
  $('#scout-open').disabled=scoutBusy||$('#scout-reveal').disabled||!$('#scout-reveal').checked;
}
function clearScoutingResult(){scoutResult=null;resetScoutMap(true);$('#scout-map-panel').open=false;$('#scout-result').hidden=true;for(const id of ['scout-features','scout-heaps','scout-traps','scout-mobs'])$('#'+id).replaceChildren();$('#scout-map-text').textContent='';}
function renderScoutingCatalog(result){
  scoutCatalog=result;const source=result.source,select=$('#scout-floor');select.replaceChildren();
  for(const floor of result.floors){const option=document.createElement('option');option.value=`${floor.depth}:${floor.branch}`;option.textContent=`第 ${floor.depth} 层 · ${floor.branch?`支线 ${floor.branch}`:'主地牢'}${floor.current?' · 当前':''}${floor.available?'':' · 文件尚不可读'}`;option.disabled=!floor.available;select.append(option);if(floor.current)select.value=option.value;}
  $('#scout-source').textContent=`槽位 ${source.slot} · 角色保存于第 ${source.depth} 层${source.branch?` / 支线 ${source.branch}`:''} · 游戏 ${source.version_name||`版本码 ${source.version}`} · ${fmtTime(source.modified)}`;
}
function refreshScoutingContext(){
  if(typeof refreshFloorGuide==='function')refreshFloorGuide();
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
    renderScoutingCatalog(result);
    $('#scout-status').textContent=result.supported?'尚未揭示':'当前版本尚未支持；已核对官方4.0.1与4.0.2，隐藏内容未展开。';
    $('#scout-note').textContent=result.note;
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
    scoutResult=result;renderScouting(result);$('#scout-status').textContent='已揭示 · 仅存档内容';$('#scout-note').textContent=result.note;
  }catch(error){if(serial===scoutSerial){inlineError($('#scout-error'),error.message);$('#scout-status').textContent='本次未展开探查；需要时重新读取楼层清单。';}}
  finally{if(serial===scoutSerial){scoutBusy=false;scoutingControls();}}
}
const scoutCoordinate=row=>`(${row.x}, ${row.y})`;
function scoutingList(id,rows,describe,empty){const target=$('#'+id);target.replaceChildren();for(const row of rows){const li=document.createElement('li');li.textContent=describe(row);target.append(li);}if(!rows.length){const li=document.createElement('li');li.textContent=empty;target.append(li);}}
function showScoutedItem(item,result){
  const source=result.source,label=`槽位 ${source.slot} · 第 ${result.depth} 层${result.branch?` / 支线 ${result.branch}`:''} · ${fmtTime(source.floor_modified)}`;
  showDetail(item.name,item.description,item.location,`${label} · 已主动揭示；游戏鉴定状态未改变，未加入背包。${source.version===920?' 数值图鉴按4.0.2参考，请核对版本差异。':''}${item.details?.length?' 原物品记录：'+item.details.join(' · '):''}`);
  showItemState({...item,revealed:true},['未加入背包']);
  showItemNote(item.user_note);if(typeof setReferencePortrait==='function'){setReferencePortrait(publicReferenceId({...item,revealed:true}),item.name);void hydrateReference({id:item.key,name:item.name,appearance_id:publicReferenceId({...item,revealed:true}),preserve_description:true},detailReferenceSerial);}if(typeof setDetailEntry==='function')setDetailEntry(item.key);
  const params={...(item.level==null?{}:{level:item.level}),...(item.tier?{tier:item.tier}:{}),...(item.volume==null?{}:{dew_volume:item.volume})};
  loadNumericalDetail(item.key,params,item.level_applicable===false?'not_applicable':item.level==null?'unknown':'revealed',{
    capturedContext:true,ignoreDrafts:true,sourceStamp:null,fieldOrigins:Object.fromEntries(Object.keys(params).map(key=>[key,'已主动揭示的楼层物品 · '+label])),
    skillConditions:`${label}；楼层物品的存档参考，未合并当前角色、装备或临时状态。`,skillState:'unknown'});
}
function scoutingCards(id,rows,result,describe,empty){
  const target=$('#'+id);target.replaceChildren();if(!rows.length){const p=document.createElement('p');p.textContent=empty;target.append(p);return;}
  for(const row of rows){const isMob=id.endsWith('mobs'),card=document.createElement(isMob?'details':'section');card.className='scout-card';const heading=document.createElement(isMob?'summary':'h3');heading.textContent=`${row.name} ${scoutCoordinate(row)}`;if(row.reference&&typeof referenceNameHTML==='function'){const name=document.createElement('button');name.type='button';name.className='reference-link';name.innerHTML=referenceNameHTML(row.reference.id,row.name);name.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();showReference({...row.reference,lookup_context:{capture_context:true,ignore_drafts:true,source:{mode:'example'},params:{depth:result.depth},conditions:'正常基础状态的独立参考，未带入当前生物临时状态。'}},'4.0.2');});bindReferencePreview(name,{...row.reference,name:row.name},{params:{depth:result.depth}});heading.replaceChildren(name,document.createTextNode(' '+scoutCoordinate(row)));}const note=document.createElement('p');note.className='muted';note.textContent=describe(row);card.append(heading,note);
    for(const item of row.items){const button=document.createElement('button');button.type='button';button.className='secondary';if(typeof referenceNameHTML==='function')button.innerHTML=referenceNameHTML(publicReferenceId({...item,revealed:true}),item.name)+` ×${item.quantity}${item.cursed===true?' · 诅咒':''}`;else button.textContent=`${item.name} ×${item.quantity}${item.cursed===true?' · 诅咒':''}`;button.addEventListener('click',()=>showScoutedItem(item,result));if(typeof bindReferencePreview==='function')bindReferencePreview(button,{id:item.key,name:item.name},{item:{...item,revealed:true},params:{...(item.level==null?{}:{level:item.level}),...(item.tier?{tier:item.tier}:{})}});card.append(button);}
    if(row.reference){const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='查正常数值与随机掉落';button.addEventListener('click',()=>showReference({...row.reference,lookup_context:{capture_context:true,ignore_drafts:true,source:{mode:'example'},params:{depth:result.depth},conditions:'正常基础状态的独立参考；角色等级默认1、累计成功掉落默认0。未将当前生物的状态或本局掉落计数代入。'}},'4.0.2'));card.append(button);}
    if(!row.items.length){const p=document.createElement('p');p.textContent='未保存随身物品；随机掉落另查怪物图鉴。';card.append(p);}target.append(card);
  }
}
function renderScouting(result){
  scoutResult=result;resetScoutMap();
  $('#scout-title').textContent=`第 ${result.depth} 层 · ${result.branch?`支线 ${result.branch}`:'主地牢'} · 存档探查`;
  $('#scout-snapshot').textContent=`槽位 ${result.source.slot} · 楼层保存于 ${fmtTime(result.source.floor_modified)} · ${result.item_count} 项仍保存的物品 · 非实时视野`;
  scoutingList('scout-features',result.features,row=>`${scoutCoordinate(row)} ${row.name}${row.hidden?' · 主动揭示':''}`,'没有保存所列门、楼梯或设施。');
  scoutingList('scout-traps',result.traps,row=>`${scoutCoordinate(row)} ${row.name} · ${row.active?'可触发':'已失效'} · ${row.visible?'游戏内已显示':'尚未显示，主动揭示'}`,'没有保存陷阱对象。');
  scoutingCards('scout-heaps',result.heaps,result,row=>`${row.seen?'游戏内已看见':'游戏内尚未看见'}${row.hidden?' · 隐藏':''}${row.haunted?' · 闹鬼':''} · 取得需符合容器或购买条件`,'没有仍保存的地面或容器物品。');
  scoutingCards('scout-mobs',result.mobs,result,row=>`${row.hp==null?'生命未确认':`保存生命 ${row.hp}${row.ht==null?'':' / '+row.ht}`} · 所列物品仅为生物随身保存记录`,'没有保存的生物。');
  const map=result.map;
  const ground=[1,2,3,9,11,14,20,32],walls=[4,12],obstacles=[13,23,25,26,27,28,33,34,35,36,39];
  const symbols={0:' ',5:'+',6:'/',10:'+',16:'?',17:'^',18:'^',19:'_',7:'<',8:'>',21:'+',22:'>',24:'O',29:'~',37:'<',15:'%',30:'%',31:'+',38:'+'};
  for(const tile of ground)symbols[tile]='.';for(const tile of walls)symbols[tile]='#';for(const tile of obstacles)symbols[tile]='X';
  const lines=[];for(let y=0;y<map.height;y++)lines.push(String(y+1).padStart(3,' ')+' '+map.tiles.slice(y*map.width,(y+1)*map.width).map((tile,x)=>y*map.width+x===map.hero?'@':symbols[tile]??'U').join(''));
  $('#scout-map-text').textContent=lines.join('\n');$('#scout-result').hidden=false;drawScoutMap();
}
function scoutMapGeometry(){
  if(!scoutResult)return null;
  const map=scoutResult.map,width=$('#scout-map-viewport').clientWidth||600,height=$('#scout-map-viewport').clientHeight||380;
  const base=Math.min(width/map.width,height/map.height),size=base*scoutMapView.zoom;
  return {width,height,base,size,left:(width-map.width*size)/2+scoutMapView.panX,top:(height-map.height*size)/2+scoutMapView.panY};
}
function clampScoutMap(){
  const g=scoutMapGeometry();if(!g)return;
  const map=scoutResult.map,x=Math.max(0,(map.width*g.size-g.width)/2),y=Math.max(0,(map.height*g.size-g.height)/2);
  scoutMapView.panX=Math.max(-x,Math.min(x,scoutMapView.panX));scoutMapView.panY=Math.max(-y,Math.min(y,scoutMapView.panY));
}
function cancelScoutMapDrag(){
  const drag=scoutMapView.drag;scoutMapView.drag=null;const canvas=$('#scout-map');
  if(drag&&canvas.hasPointerCapture?.(drag.id))canvas.releasePointerCapture(drag.id);
  canvas.classList.remove('dragging');
}
function resetScoutMap(clear=false){
  cancelScoutMapDrag();Object.assign(scoutMapView,{zoom:1,panX:0,panY:0,selected:-1,width:0,height:0});
  $('#scout-cell-info').replaceChildren();$('#scout-cell-info').textContent='点击格子查看';
  $('#scout-map').setAttribute('aria-label','楼层地图');$('#scout-map-scale').textContent='100%';
  if(clear){if($('#scout-map-dialog').open)$('#scout-map-dialog').close();$('#scout-map').width=1;$('#scout-map').height=1;}
  else drawScoutMap();
}
function drawScoutMap(){
  let g=scoutMapGeometry();if(!g)return;
  const previous=scoutMapView;if(previous.width&&previous.height&&(g.width!==previous.width||g.height!==previous.height)){
    const oldBase=Math.min(previous.width/scoutResult.map.width,previous.height/scoutResult.map.height),ratio=g.base/oldBase;
    previous.panX*=ratio;previous.panY*=ratio;
  }
  previous.width=g.width;previous.height=g.height;clampScoutMap();g=scoutMapGeometry();
  const canvas=$('#scout-map'),dpr=typeof devicePixelRatio==='number'?Math.min(2,devicePixelRatio):1;
  canvas.width=Math.round(g.width*dpr);canvas.height=Math.round(g.height*dpr);
  const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,g.width,g.height);
  const colors={0:'#080e0b',5:'#a2875d',6:'#8d977c',10:'#a87e50',16:'#f29ab2',17:'#cd6d65',18:'#cd6d65',19:'#786353',7:'#8bb39d',37:'#8bb39d',8:'#d5bd82',21:'#a87e50',22:'#d5bd82',24:'#7595ad',29:'#426874',15:'#527944',30:'#527944',31:'#a87e50',38:'#a87e50'};
  for(const tile of [1,2,3,9,11,14,20,32])colors[tile]='#344133';for(const tile of [4,12])colors[tile]='#687463';for(const tile of [13,23,25,26,27,28,33,34,35,36,39])colors[tile]='#9b806d';
  const map=scoutResult.map,x0=Math.max(0,Math.floor(-g.left/g.size)),y0=Math.max(0,Math.floor(-g.top/g.size)),x1=Math.min(map.width,Math.ceil((g.width-g.left)/g.size)),y1=Math.min(map.height,Math.ceil((g.height-g.top)/g.size));
  const atlas=scoutTexture(map.art?.atlas),water=scoutTexture(map.art?.water);ctx.imageSmoothingEnabled=false;
  for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){
    const index=y*map.width+x,tile=map.tiles[index],frame=map.art?.frames?.[index],px=g.left+x*g.size,py=g.top+y*g.size;
    if(frame===-2&&atlas)continue;
    if(tile>=0&&atlas&&Number.isInteger(frame)&&frame>=0&&frame<256){
      if((tile===29||tile===39)&&water)ctx.drawImage(water,px,py,g.size,g.size);
      ctx.drawImage(atlas,(frame%16)*16,Math.floor(frame/16)*16,16,16,px,py,g.size,g.size);
      if(tile===16){ctx.strokeStyle='#f4d69c';ctx.lineWidth=Math.max(1,g.size*.1);ctx.strokeRect(px+g.size*.18,py+g.size*.18,g.size*.6,g.size*.6);}
    }else{ctx.fillStyle=tile<0?'#10180f':colors[tile]||'#a879ae';ctx.fillRect(px,py,Math.max(.1,g.size-(g.size>=4?.6:0)),Math.max(.1,g.size-(g.size>=4?.6:0)));}
  }
  ctx.lineWidth=Math.max(1,g.size*.08);
  if(Array.isArray(map.markers)){
    const items=scoutTexture(map.art?.items);
    for(const marker of map.markers){
      const pos=marker.pos;if(!Number.isInteger(pos)||pos<0||pos>=map.tiles.length||map.tiles[pos]<0)continue;
      const px=g.left+(pos%map.width)*g.size,py=g.top+Math.floor(pos/map.width)*g.size,icon=scoutTexture(map.art?.icons?.[marker.icon]);
      if(icon){const ratio=g.size/Math.max(icon.naturalWidth,icon.naturalHeight),w=icon.naturalWidth*ratio,h=icon.naturalHeight*ratio;ctx.drawImage(icon,px+(g.size-w)/2,py+(g.size-h)/2,w,h);}
      else if(items&&Number.isInteger(marker.sprite_frame)){const frame=marker.sprite_frame;ctx.drawImage(items,(frame%16)*16,Math.floor(frame/16)*16,16,16,px,py,g.size,g.size);}
      else{ctx.strokeStyle=marker.kind==='mob'?'#96c8ef':marker.kind==='trap'?'#f49c87':'#f4d69c';ctx.lineWidth=Math.max(1,g.size*.08);ctx.strokeRect(px+g.size*.18,py+g.size*.18,g.size*.6,g.size*.6);}
    }
  }else for(const [rows,color] of [[scoutResult.heaps,'#f4d69c'],[scoutResult.mobs,'#96c8ef']])for(const row of rows){if(map.tiles[(row.y-1)*map.width+row.x-1]<0)continue;ctx.strokeStyle=color;ctx.strokeRect(g.left+(row.x-.82)*g.size,g.top+(row.y-.82)*g.size,g.size*.6,g.size*.6);}
  if(map.hero!==null&&map.hero>=0&&map.tiles[map.hero]>=0){ctx.fillStyle='#fff0c9';ctx.fillRect(g.left+(map.hero%map.width+.33)*g.size,g.top+(Math.floor(map.hero/map.width)+.33)*g.size,g.size*.3,g.size*.3);}
  if(previous.selected>=0){ctx.strokeStyle='#ffe2a0';ctx.lineWidth=2;ctx.strokeRect(g.left+previous.selected%map.width*g.size,g.top+Math.floor(previous.selected/map.width)*g.size,g.size,g.size);}
  $('#scout-map-scale').textContent=Math.round(previous.zoom*100)+'%';$('#scout-map-minus').disabled=previous.zoom<=1;$('#scout-map-plus').disabled=previous.zoom>=12;
}
function zoomScoutMap(factor,point){
  const g=scoutMapGeometry();if(!g)return;point=point||{x:g.width/2,y:g.height/2};
  const next=Math.max(1,Math.min(12,scoutMapView.zoom*factor)),ratio=next/scoutMapView.zoom;
  const x=(point.x-g.left)*ratio,y=(point.y-g.top)*ratio;scoutMapView.zoom=next;
  scoutMapView.panX=point.x-x-(g.width-scoutResult.map.width*g.size*ratio)/2;scoutMapView.panY=point.y-y-(g.height-scoutResult.map.height*g.size*ratio)/2;drawScoutMap();
}
function scoutMapPoint(event){const rect=$('#scout-map').getBoundingClientRect();return {x:event.clientX-rect.left,y:event.clientY-rect.top};}
function scoutMapCell(point){
  const g=scoutMapGeometry();if(!g)return -1;const x=Math.floor((point.x-g.left)/g.size),y=Math.floor((point.y-g.top)/g.size),map=scoutResult.map;
  return x>=0&&y>=0&&x<map.width&&y<map.height?y*map.width+x:-1;
}
function selectScoutMapCell(index){
  if(!scoutResult||index<0||index>=scoutResult.map.tiles.length)return;
  const result=scoutResult,map=result.map,x=index%map.width+1,y=Math.floor(index/map.width)+1,tile=map.tiles[index];scoutMapView.selected=index;
  const target=$('#scout-cell-info');target.replaceChildren();const heading=document.createElement('strong');heading.textContent=`(${x}, ${y}) · ${tile<0?'未探索':map.terrain_names?.[tile]||'未识别地形 '+tile}`;target.append(heading);$('#scout-map').setAttribute('aria-label','楼层地图 · '+heading.textContent);
  if(tile>=0){
    if(map.hero===index){const p=document.createElement('p');p.textContent='角色保存位置';target.append(p);}
    for(const [kind,rows] of [['heap',result.heaps],['trap',result.traps],['mob',result.mobs]])for(const row of rows){
      if(row.x!==x||row.y!==y)continue;const p=document.createElement('p');p.textContent=row.name+(row.haunted?' · 闹鬼':'')+(kind==='trap'?' · '+(row.active?'可触发':'已失效'):kind==='mob'&&row.hp!=null?' · 保存生命 '+row.hp+(row.ht==null?'':'/'+row.ht):'');target.append(p);
      for(const item of row.items||[]){const button=document.createElement('button');button.type='button';button.className='text-button';button.textContent=`${item.name} ×${item.quantity}`;button.addEventListener('click',()=>{if(scoutResult===result)showScoutedItem(item,result);});target.append(button);}
    }
  }
  drawScoutMap();
}
$('#scout-map-plus').addEventListener('click',()=>zoomScoutMap(1.25));$('#scout-map-minus').addEventListener('click',()=>zoomScoutMap(1/1.25));$('#scout-map-reset').addEventListener('click',()=>resetScoutMap());
$('#scout-map-expand').addEventListener('click',()=>{if(!scoutResult)return;cancelScoutMapDrag();$('#scout-map-dialog-body').append($('#scout-map-viewer'));$('#scout-map-expand').hidden=true;$('#scout-map-dialog').showModal();drawScoutMap();$('#scout-map').focus({preventScroll:true});});
$('#scout-map-close').addEventListener('click',()=>$('#scout-map-dialog').close());
$('#scout-map-dialog').addEventListener('close',()=>{$('#scout-map-home').append($('#scout-map-viewer'));$('#scout-map-expand').hidden=false;cancelScoutMapDrag();drawScoutMap();if(scoutResult)$('#scout-map-expand').focus();else $('#scout-floor').focus();});
$('#scout-map-panel').addEventListener('toggle',()=>{cancelScoutMapDrag();drawScoutMap();});
$('#scout-map').addEventListener('wheel',event=>{if(!scoutResult)return;event.preventDefault();zoomScoutMap(event.deltaY<0?1.25:1/1.25,scoutMapPoint(event));},{passive:false});
$('#scout-map').addEventListener('pointerdown',event=>{if(!scoutResult||event.button!==0)return;event.preventDefault();const p=scoutMapPoint(event);$('#scout-map').focus({preventScroll:true});scoutMapView.drag={id:event.pointerId,x:p.x,y:p.y,panX:scoutMapView.panX,panY:scoutMapView.panY,moved:false};$('#scout-map').setPointerCapture(event.pointerId);});
$('#scout-map').addEventListener('pointermove',event=>{const drag=scoutMapView.drag;if(!drag||drag.id!==event.pointerId||!scoutResult)return;const p=scoutMapPoint(event),dx=p.x-drag.x,dy=p.y-drag.y;if(Math.hypot(dx,dy)>4)drag.moved=true;if(drag.moved){scoutMapView.panX=drag.panX+dx;scoutMapView.panY=drag.panY+dy;$('#scout-map').classList.add('dragging');drawScoutMap();}});
$('#scout-map').addEventListener('pointerup',event=>{const drag=scoutMapView.drag;if(!drag||drag.id!==event.pointerId)return;const cell=scoutMapCell(scoutMapPoint(event));cancelScoutMapDrag();if(!drag.moved)selectScoutMapCell(cell);});
for(const type of ['pointercancel','lostpointercapture'])$('#scout-map').addEventListener(type,cancelScoutMapDrag);
$('#scout-map').addEventListener('keydown',event=>{
  const g=scoutMapGeometry();if(!g)return;const key=event.key,map=scoutResult.map;
  if(key==='Escape'&&scoutMapView.drag)cancelScoutMapDrag();else if(key==='+'||key==='=')zoomScoutMap(1.25);else if(key==='-')zoomScoutMap(1/1.25);else if(key==='Home')resetScoutMap();
  else if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Enter'].includes(key)){
    let pos=scoutMapView.selected>=0?scoutMapView.selected:scoutMapCell({x:g.width/2,y:g.height/2});if(pos<0)pos=0;let x=pos%map.width,y=Math.floor(pos/map.width);
    if(key==='ArrowLeft')x=Math.max(0,x-1);if(key==='ArrowRight')x=Math.min(map.width-1,x+1);if(key==='ArrowUp')y=Math.max(0,y-1);if(key==='ArrowDown')y=Math.min(map.height-1,y+1);selectScoutMapCell(y*map.width+x);
    const cx=g.left+(x+.5)*g.size,cy=g.top+(y+.5)*g.size;if(cx<0||cx>g.width)scoutMapView.panX+=g.width/2-cx;if(cy<0||cy>g.height)scoutMapView.panY+=g.height/2-cy;drawScoutMap();
  }else return;event.preventDefault();
});
if(typeof ResizeObserver==='function')new ResizeObserver(drawScoutMap).observe($('#scout-map-viewport'));
if(typeof window!=='undefined'){window.addEventListener('blur',cancelScoutMapDrag);window.addEventListener('resize',drawScoutMap);}
$('#scout-refresh').addEventListener('click',loadScouting);
$('#scout-floor').addEventListener('change',()=>{scoutSerial++;scoutBusy=false;$('#scout-reveal').checked=false;clearScoutingResult();scoutingControls();$('#scout-status').textContent='已更换楼层；勾选并主动揭示后查看。';});
$('#scout-reveal').addEventListener('change',()=>{if(!$('#scout-reveal').checked){scoutSerial++;scoutBusy=false;clearScoutingResult();$('#scout-status').textContent='隐藏内容已收起；游戏文件未改变。';}scoutingControls();});
$('#scout-open').addEventListener('click',revealScoutingFloor);
if(view==='scouting'&&state)void loadScouting();
