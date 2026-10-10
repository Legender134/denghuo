'use strict';
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const names = {overview:'冒险概览',inventory:'背包与装备',library:'地牢手册',alchemy:'炼金规划',workspace:'方案与收藏',backups:'存档时光机',migration:'搬机迁移',manual:'局势推演',settings:'连接设置',help:'帮助与关于','play-settings':'游玩显示与快捷键'};
const icons = {WARRIOR:'⚔',MAGE:'✦',ROGUE:'◐',HUNTRESS:'➶',DUELIST:'⚔',CLERIC:'✧'};
const initialPanelPlan=new URLSearchParams(location.search||'').get('plan');
let initialPanelPlanHandled=false;
let state, token, view='overview', lastRender='', slotsSignature='', libraryRequest=0, toastTimer;
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const fmtTime = seconds => new Date(seconds*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
const shortTime = seconds => new Date(seconds*1000).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
function toast(message,error=false){$('#toast').textContent=message;$('#toast').classList.toggle('error',error);$('#toast').hidden=false;clearTimeout(toastTimer);if(!error)toastTimer=setTimeout(()=>$('#toast').hidden=true,5000);}
function inlineError(target,message){target.textContent=message;target.hidden=!message;target.setAttribute('role','alert');}
async function post(path,payload={}){
  if(!token)throw new Error('助手还没连接，请稍后重试');
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Companion-Token':token},body:JSON.stringify(payload)});
  const result=await response.json();if(!response.ok){const error=new Error(result.error || '操作失败');error.status=response.status;throw error;}
  return result;
}
async function action(work,target=null){try{await work();if(target)inlineError(target,'');await poll();}catch(error){if(target)inlineError(target,error.message);else toast(error.message,true);}}
const viewPositions=new Map();
let navigationSerial=0;
if('scrollRestoration' in history)history.scrollRestoration='manual';
function navigate(next,historyMode='push'){
  if(!names[next])next='overview';
  const changed=view!==next;
  if(changed)navigationSerial++;
  if(changed)viewPositions.set(view,window.scrollY);
  view=next;
  for(const el of $$('.view'))el.hidden=el.id!==`view-${next}`;
  for(const el of $$('.nav')){el.classList.toggle('active',el.dataset.view===next);el.setAttribute('aria-current',el.dataset.view===next?'page':'false');}
  $('#page-name').textContent=names[next];
  const hash=`#${next}`;
  if(changed&&historyMode==='push')history.pushState(null,'',hash);
  else if(location.hash!==hash||historyMode==='replace')history.replaceState(null,'',hash);
  if(next==='library'&&!$('#library-search').value&&$('#library-category').value==='全部'&&typeof loadWorkspace==='function')loadWorkspace();
  else if(next==='library'&&!$('#library-results').childElementCount)searchLibrary();
  if(next==='inventory')renderInventory();if(next==='settings')loadSettings();if(next==='backups')loadBackups();
  if(next==='workspace'&&typeof loadWorkspace==='function')loadWorkspace();
  if(next==='migration'&&typeof loadMigration==='function')loadMigration();
  if(next==='alchemy'&&typeof loadAlchemy==='function')loadAlchemy();
  if(next==='help'&&typeof loadHelp==='function')loadHelp();
  if(next==='play-settings'){if(typeof loadPlaySettings==='function')loadPlaySettings();if(typeof loadBackupDestination==='function')loadBackupDestination();}
  if(changed)window.scrollTo({top:viewPositions.get(next)||0,behavior:'instant'});
}
$$('[data-view]').forEach(el=>el.addEventListener('click',()=>{navigate(el.dataset.view);if($('#main-nav').classList.contains('expanded')){setNavigationExpanded(false);$('#nav-toggle').focus();}}));
function setNavigationExpanded(expanded){$('#main-nav').classList.toggle('expanded',expanded);$('#nav-toggle').setAttribute('aria-expanded',String(expanded));$('#nav-toggle').textContent=expanded?'收起页面 ▴':`更多页面（共 ${Object.keys(names).length} 项） ▾`;}
$('#nav-toggle').addEventListener('click',()=>setNavigationExpanded($('#nav-toggle').getAttribute('aria-expanded')!=='true'));
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&$('#nav-toggle').getAttribute('aria-expanded')==='true'&&($('#main-nav').contains(event.target)||event.target===$('#nav-toggle'))){event.preventDefault();setNavigationExpanded(false);$('#nav-toggle').focus();}});
$$('[data-goto]').forEach(el=>el.addEventListener('click',()=>navigate(el.dataset.goto)));
$('.brand').addEventListener('click',event=>{event.preventDefault();navigate('overview');});
function restoreNavigation(){
  const next=location.hash.slice(1);
  if(names[next]&&view===next)return;
  navigate(next,'restore');
}
window.addEventListener('popstate',restoreNavigation);
window.addEventListener('hashchange',restoreNavigation);
window.addEventListener('DOMContentLoaded',()=>{if(view==='alchemy'&&typeof loadAlchemy==='function')loadAlchemy();if(view==='migration'&&typeof loadMigration==='function')loadMigration();});
function handlePageShortcut(event){
  const search=(event.ctrlKey&&!event.altKey&&event.key.toLowerCase()==='f')||(event.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName));
  if(event.key!=='F1'&&!search)return;
  event.preventDefault();
  const dialogs=$$('dialog[open]');
  if(dialogs.some(dialog=>dialog.id!=='detail-dialog'))return;
  dialogs.forEach(dialog=>dialog.close());
  if(event.key==='F1')navigate('help');
  else{navigate('library');$('#library-search').focus();$('#library-search').select();}
}
document.addEventListener('keydown',handlePageShortcut);
function renderStatus(){
  const banner=$('#connection-banner');const isManual=state.settings.mode==='manual';
  const waiting=state.waiting_for_save;
  $('#refresh').textContent=isManual?'↻ 更新提示':'↻ 刷新存档';
  const ago=state.age_seconds===null?'尚未读取':state.age_seconds<60?`${Math.floor(state.age_seconds)} 秒前`:state.age_seconds<3600?`${Math.floor(state.age_seconds/60)} 分钟前`:state.age_seconds<86400?`${Math.floor(state.age_seconds/3600)} 小时前`:`${Math.floor(state.age_seconds/86400)} 天前`;
  const origin=isManual?'手动输入':`槽位 ${state.active_slot ?? '—'} · 存档快照`;
  banner.className='connection-banner'+(state.error?' error':state.stale?'':' fresh');
  let text=state.error || (waiting?'已准备好 · 游戏保存后自动连接，无需先配置':`${origin} · ${fmtTime(state.modified)} 更新（${ago}）`);
  if(!state.error&&!waiting)text+=isManual?(state.stale?' · 手动信息已过期，请重新填写当前局势；此模式不会自动跟随游戏。':' · 此模式不会自动跟随游戏，请随局势重新填写。'):state.stale?' · 这是旧快照；请先在游戏中保存，勿当作当前状态。':' · 以游戏画面为准，存档更新后自动同步。';
  if(state.warning && !state.error)text+=' '+state.warning;
  if(state.configuration_notice)text+=' '+state.configuration_notice;
  if(state.settings.reveal)text+=' · 剧透模式已开启';
  banner.textContent=text;
  $('#advice-source').textContent=state.error?'快照不可用；请恢复连接后重新核对。':waiting?'等待游戏保存。':`${isManual?'你填写的局势':`最近保存的状态 · ${origin}`} · ${fmtTime(state.modified)} · ${ago}。${state.stale?'信息已过期，先核对游戏画面。':'行动前核对游戏画面。'}${isManual?'手填信息不会自动跟随游戏。':'不是逐回合实时状态。'}`;
  $('#sidebar-dot').className='dot '+(state.error?'error':state.stale?'stale':'live');
  $('#connection-short').textContent=state.error?'等待可读存档':waiting?'已就绪 · 等待游戏':isManual?'手动局势':state.stale?'旧快照 · 等待更新':'正在跟随存档';
  $('#catalog-version').textContent=state.catalog_version;$('#library-count').textContent=`${state.catalog_count} 条官方资料`;
  const stop=state.settings.stop_at;let countdown='';if(stop){const minutes=Math.max(0,Math.ceil((new Date(stop).getTime()-Date.now())/60000));countdown=`${Math.floor(minutes/60)} 时 ${minutes%60} 分后停止`;}$('#stop-countdown').textContent=countdown;
  const sig=JSON.stringify(state.slots.map(row=>[row.id,row.valid,row.hero_class,row.depth]))+state.settings.slot;
  if(sig!==slotsSignature){slotsSignature=sig;$('#slot').innerHTML='<option value="auto">自动跟随最新存档</option>'+Array.from({length:6},(_,i)=>{const row=state.slots.find(row=>row.id===i+1);return `<option value="${i+1}">槽位 ${i+1}${row?.valid?` · 第 ${escapeHTML(row.depth)} 层`:' · 暂无可读角色'}</option>`;}).join('');$('#slot').value=String(state.settings.slot);}
}
function render(){
  renderStatus();const key=JSON.stringify([state.revision,state.error,state.active_slot,state.settings.mode,state.waiting_for_save]);if(key===lastRender)return;lastRender=key;
  const data=state.data;$('#empty-state').hidden=!!data;$('#adventure').hidden=!data;
  $('#empty-title').textContent=state.error?'暂时读不到冒险状态':'已就绪，直接开始游戏';
  $('#empty-description').textContent=state.error || '打开游戏，开始或继续一局。游戏保存后，角色状态和建议会自动出现。也可以先查数值手册，其他功能之后再探索。';
  $('#empty-options').open=!!state.error;
  if(!data){renderInventory();return;}
  const hero=data.hero;$('#hero-icon').textContent=icons[hero.class_id] || '✦';$('#hero-title').textContent=`${hero.class} · 等级 ${hero.level}`;$('#hero-subtitle').textContent=`${data.region} / ${state.settings.mode==='manual'?'手动局势':`存档槽位 ${state.active_slot}`} / ${data.version?`存档版本码 ${data.version}`:'手动数据'}`;
  $('#hero-tags').innerHTML=[...data.buffs.map(b=>`<span class="tag warn">${escapeHTML(b.name)}</span>`),...data.challenges.map(c=>`<span class="tag">${escapeHTML(c)}</span>`)].join('');
  const ratio=Math.max(0,Math.min(1,hero.hp/hero.ht));$('#health').textContent=`${hero.hp} / ${hero.ht}`;$('#health-percent').textContent=`${Math.round(ratio*100)}%`;$('#health-bar').style.width=`${ratio*100}%`;$('#health-bar').classList.toggle('low',ratio<.5);$('#depth').textContent=`第 ${data.depth} 层`;$('#region').textContent=data.region;$('#strength').textContent=hero.strength;$('#hunger').textContent=hero.hunger_label;$('#resources').textContent=state.settings.mode==='manual'?'金币与炼金能量未填写':`金币 ${data.gold} · 炼金能量 ${data.energy}`;
  const urgentTips=data.tips.filter(tip=>tip.severity==='critical');$('#overview-urgent').hidden=!urgentTips.length;$('#overview-urgent-summary').textContent=urgentTips.map(tip=>tip.title).join('；');
  $('#advice-list').innerHTML=data.tips.length?data.tips.map(t=>`<article class="advice ${t.severity}"><div class="advice-head"><span class="severity">${{critical:'优先处理',warning:'留意',info:'提示'}[t.severity]}</span><h3>${escapeHTML(t.title)}</h3></div><p>${escapeHTML(t.body)}</p><details><summary>为什么这样建议</summary>${escapeHTML(t.basis)}</details></article>`).join(''):'<p class="muted">当前没有触发特殊风险规则。继续留意周围敌人和退路。</p>';
  const equippedReference=itemSnapshotReference(),equipped=data.items.filter(item=>!['背包','收纳袋'].includes(item.location));$('#equipped').innerHTML=equipped.length?equipped.map(item=>`<button class="equipment-row"><span class="equipment-icon">${item.location==='护甲'?'◈':item.location.includes('武器')?'⚔':'◇'}</span><span><strong>${escapeHTML(item.name)}</strong>${itemNoteLabel(item)}<small>${escapeHTML(item.details.join(' · ')) || '查看物品说明'}</small></span><span class="item-place">${escapeHTML(item.location)}</span></button>`).join(''):`<p class="muted">${state.settings.mode==='manual'?'手动模式未填写装备；请在游戏中核对。':'快照中暂无装备记录；新的游戏保存到达后会自动更新。'}</p>`;
  $$('#equipped button').forEach((button,i)=>button.addEventListener('click',()=>showItem(equipped[i],equippedReference)));
  $('#history').innerHTML=state.history.length?state.history.slice(0,5).map(row=>`<div class="history-row">${escapeHTML(row.text)}<time>${escapeHTML(fmtTime(row.time))}</time></div>`).join(''):state.settings.mode==='manual'?'<p class="muted">手动局势不会自动跟随游戏；恢复自动读取后，会在这里记录保存时的血量和楼层变化。</p>':'<p class="muted">新的存档快照到达后，会在这里记录血量和楼层变化。</p>';
  renderMap(data.map);renderInventory();
}
function renderMapText(map){
  const summary=$('#map-summary'),list=$('#map-coordinate-list');list.replaceChildren();$('#map-coordinates').hidden=!map;
  if(!map){summary.textContent='当前没有可用的地图快照；无位置或地形可读取。';return;}
  const labels={0:'深渊',1:'地面',2:'草地',3:'干涸水井',4:'墙壁',5:'门',6:'开启的门',7:'上行楼梯',8:'下行楼梯',9:'余烬',10:'锁住的门',11:'基座',12:'墙壁',13:'障碍物',14:'地面',15:'高草',18:'已发现陷阱',19:'失效陷阱',20:'地面',21:'锁住的楼梯',22:'解锁的楼梯',24:'水井',25:'雕像',26:'雕像',27:'书架',28:'炼金装置',29:'水地',30:'草地',31:'水晶门',35:'矿晶',36:'巨石',37:'上行楼梯',38:'锁住的门',39:'水地'};
  const coordinate=i=>`(${i%map.width+1}, ${Math.floor(i/map.width)+1})`;
  const hero=Number.isInteger(map.hero)&&map.hero>=0&&map.hero<map.tiles.length?map.hero:null,nearby=[];let count=0;
  map.tiles.forEach((tile,i)=>{if(tile<0)return;count++;const label=labels[tile]||'已公开地形';const li=document.createElement('li');li.textContent=`${coordinate(i)}：${label}${i===hero?' · 英雄位置':''}`;list.append(li);if(hero!==null&&[7,8,18,19,21,22,29,37,39].includes(tile)&&Math.max(Math.abs(i%map.width-hero%map.width),Math.abs(Math.floor(i/map.width)-Math.floor(hero/map.width)))<=3)nearby.push(`${label} ${coordinate(i)}`);});
  summary.textContent=`${hero===null?'英雄位置不可用':`英雄位置 ${coordinate(hero)}`}。已探索 ${count} 格。${nearby.length?'坐标附近：'+nearby.join('；'):'坐标附近没有已公开的水地、楼梯或陷阱记录'}。${map.caption||'最近保存的快照，非实时地图'}。`;
}
function renderMap(map){
  renderMapText(map);
  const canvas=$('#map');canvas.hidden=!map;$('#map-empty').hidden=!!map;$('#map-caption').textContent=map?.caption || state.warning || '手动模式不提供地图。';if(!map)return;
  const ctx=canvas.getContext('2d');const width=460,height=320;ctx.fillStyle='#121914';ctx.fillRect(0,0,width,height);
  const visible=map.tiles.map((t,i)=>t>=0?i:-1).filter(i=>i>=0);if(map.hero!==null)visible.push(map.hero);if(!visible.length)return;
  const xs=visible.map(i=>i%map.width),ys=visible.map(i=>Math.floor(i/map.width));const minX=Math.max(0,Math.min(...xs)-2),maxX=Math.min(map.width-1,Math.max(...xs)+2),minY=Math.max(0,Math.min(...ys)-2),maxY=Math.min(map.height-1,Math.max(...ys)+2);const size=Math.max(2,Math.min(14,Math.floor(Math.min((width-30)/(maxX-minX+1),(height-30)/(maxY-minY+1)))));const ox=Math.floor((width-(maxX-minX+1)*size)/2),oy=Math.floor((height-(maxY-minY+1)*size)/2);
  const colors={0:'#080e0b',1:'#344133',2:'#42563a',4:'#687463',5:'#a2875d',6:'#645d42',7:'#8bb39d',8:'#d5bd82',10:'#a87e50',12:'#687463',15:'#527944',16:'#687463',17:'#344133',18:'#b57464',19:'#6f6152',21:'#8bb39d',22:'#d5bd82',24:'#698c88',27:'#756c4b',28:'#6a8d81',29:'#426874',30:'#527944',37:'#8bb39d'};
  for(let y=minY;y<=maxY;y++)for(let x=minX;x<=maxX;x++){const tile=map.tiles[y*map.width+x];if(tile<0)continue;ctx.fillStyle=colors[tile] || '#485440';ctx.fillRect(ox+(x-minX)*size,oy+(y-minY)*size,size-1,size-1);}
  if(map.hero!==null){const x=ox+(map.hero%map.width-minX)*size,y=oy+(Math.floor(map.hero/map.width)-minY)*size;ctx.fillStyle='#f4d69c';ctx.fillRect(x,y,size-1,size-1);ctx.strokeStyle='#fff0c9';ctx.lineWidth=1;ctx.strokeRect(x-2,y-2,size+3,size+3);}
}
function itemSnapshotReference(){return {items:state?.data?.items,stamp:typeof calculationStamp==='function'?calculationStamp():null};}
function itemNoteLabel(item){return item.user_note?`<small class="user-note">${escapeHTML('用户记录：'+(item.user_note.title||'查看备注'))}</small>`:'';}
function showItemNote(note){
  const target=$('#detail-user-note');if(!target)return;target.replaceChildren();target.hidden=!note;if(!note)return;
  const heading=document.createElement('h3');heading.textContent='游戏中的用户记录';
  const scope=document.createElement('p');scope.className='muted';scope.textContent=(note.scope==='item_type'?'此种物品的备注':'此件物品的备注')+' · 由玩家填写，非游戏规则';
  const title=document.createElement('strong');title.textContent=note.title;
  const body=document.createElement('p');body.className='user-note';body.textContent=note.body;target.append(heading,scope,title,body);
}
function renderInventory(){
  const reference=itemSnapshotReference(),query=$('#inventory-search').value.toLowerCase();const items=(reference.items || []).filter(item=>(item.name+' '+item.kind+' '+item.location+' '+(item.user_note?.title||'')+' '+(item.user_note?.body||'')).toLowerCase().includes(query));$('#item-count').textContent=state?.settings.mode==='manual'?`已填写 ${items.length} 项物品`:`${items.length} 项物品`;
  $('#inventory-list').innerHTML=items.length?items.map(item=>`<button class="item-card"><span class="item-meta">${escapeHTML(item.location)} · ×${item.quantity}</span><h3>${escapeHTML(item.name)}</h3>${itemNoteLabel(item)}<p>${escapeHTML(item.details.join(' · ')) || (item.known?'已知种类':'效果未知')}</p></button>`).join(''):'<p class="no-results">没有匹配的背包物品。连接有效存档后可查看。</p>';
  $$('#inventory-list button').forEach((button,i)=>button.addEventListener('click',()=>showItem(items[i],reference)));
}
let detailEntry=null;
function showDetailContext(text){showItemNote(null);const target=$('#detail-context');if(target){target.textContent=text||'';target.hidden=!text;}}
function showDetail(title,text,category,meta){showDetailContext('');cancelNumericalDetail();detailEntry=null;$('#detail-rules').replaceChildren();$('#detail-tools')?.replaceChildren();$('#detail-related')?.replaceChildren();$('#detail-title').textContent=title;$('#detail-text').textContent=text || '此条目没有独立说明，请参考游戏中的检查界面。';$('#detail-category').textContent=category;$('#detail-meta').textContent=meta;if(!$('#detail-dialog').open)$('#detail-dialog').showModal();$('#detail-dialog').scrollTop=0;}
function showRelatedReferences(rows,context={}){const target=$('#detail-related');if(!target)return;target.replaceChildren();for(const row of rows||[]){const button=document.createElement('button');button.className='secondary';button.textContent='查看 '+row.name;button.addEventListener('click',()=>showReference({...row,lookup_context:row.lookup_context||{...context,ignore_drafts:true,capture_context:true,conditions:row.conditions}}));target.append(button);}}
function showItem(item,reference=itemSnapshotReference()){
  showDetail(item.name,item.description,item.location,item.details.join(' · ')+(item.known?'':' · 未鉴定物品保留未知身份')+(item.available===false?' · 当前记录中不可用；仅供阅读参考':''));showItemNote(item.user_note);
  if(item.known){const params={...(typeof visibleCalculationContext==='function'?visibleCalculationContext():{}),...(item.level==null?{}:{level:item.level}),...(item.tier?{tier:item.tier}:{}),...(Number.isInteger(item.volume)&&item.volume>=0&&item.volume<=20?{dew_volume:item.volume}:{})},origin=item.level_applicable===false?'not_applicable':item.level==null?'unknown':'known',stamp=reference.stamp;
    if(typeof setDetailEntry==='function')setDetailEntry(item.key);const context={params,level_origin:origin,stamp:stamp?[stamp.started,stamp.save_root,stamp.mode,stamp.slot,stamp.revision,stamp.modified]:undefined};loadNumericalDetail(item.key,params,origin,{capturedContext:true,...(typeof lookupCalculationOptions==='function'?lookupCalculationOptions(context):{})});showRelatedReferences(item.related,context);
    if(item.available===true&&typeof comparisonFamily==='function'&&comparisonFamily(item.key)){const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='比较这件装备与升级预算';button.addEventListener('click',()=>compareInventoryItem(item,reference));$('#detail-related')?.append(button);}
  }
}
function showReference(row,version){showDetail(row.name,row.description+(row.hint?'\n\n'+row.hint:''),row.category,`游戏版本 ${version||state?.catalog_version||'以条目为准'}`);if(typeof setDetailEntry==='function')setDetailEntry(row.id);const context=row.lookup_context||{};showDetailContext(Array.isArray(context.conditions)?context.conditions.join('；'):context.conditions);showRelatedReferences(row.related,context);showItemNote(row.user_note||context.user_note);loadNumericalDetail(row.id,context.params||{},context.level_origin||'manual',{...(typeof lookupCalculationOptions==='function'?lookupCalculationOptions(context):{}),ignoreDrafts:context.ignore_drafts===true,capturedContext:context.capture_context===true||Array.isArray(context.stamp)||!!context.source});}
// Async backup previews may replace their original trigger during a status poll.
const backupDialogTriggers=new Map();
document.addEventListener('click',event=>{
  const button=event.target.closest?.('button');if(!button)return;
  const key=['restore','undo','remove','manage','recovery'].find(key=>button.dataset[key]!==undefined);
  const dialog=key==='recovery'?'backup-recovery':key==='manage'?'manage':key?'restore':button.id==='repair-timeline'?'repair':null;
  if(dialog)backupDialogTriggers.set(dialog,{button,key,value:key?button.dataset[key]:null,context:state?.backup_context});
},true);
for(const kind of ['repair','restore','manage','backup-recovery'])$('#'+kind+'-dialog').addEventListener('close',()=>{
  const saved=backupDialogTriggers.get(kind);if(!saved)return;
  const restore=()=>{if($('#'+kind+'-dialog').open||document.querySelector('dialog[open]')||view!=='backups'||saved.context!==state?.backup_context)return;
    const trigger=(saved.button.isConnected?saved.button:saved.key?Array.from(document.querySelectorAll('[data-'+saved.key+']')).find(button=>button.dataset[saved.key]===saved.value):$('#repair-timeline'))||(kind==='backup-recovery'?$('#backup-slot'):null);
    if(trigger&&!trigger.hidden&&!trigger.disabled)trigger.focus({preventScroll:true});
    backupDialogTriggers.delete(kind);
  };
  window.requestAnimationFrame(restore);
});
$('#close-detail').addEventListener('click',()=>$('#detail-dialog').close());
$('#detail-dialog').addEventListener('click',event=>{if(event.target===$('#detail-dialog')){const rect=event.target.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)event.target.close();}});
$('#inventory-search').addEventListener('input',renderInventory);
let manualFormGeneration=0;
$('#manual-form').addEventListener('input',()=>manualFormGeneration++);
let searchTimer,libraryOffset=0;
$('#library-search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>searchLibrary(),180);});
$('#library-category').addEventListener('change',()=>searchLibrary());

$('#library-more').addEventListener('click',()=>searchLibrary(false));
$$('[data-query]').forEach(button=>button.addEventListener('click',()=>{$('#library-search').value=button.dataset.query;$('#library-category').value='全部';searchLibrary();}));
async function searchLibrary(reset=true){const seq=++libraryRequest;const query=$('#library-search').value,category=$('#library-category').value;const home=!query.trim()&&category==='全部'&&typeof loadWorkspace==='function';$('#library-home').hidden=!home;$('#library-results').hidden=home;$('#library-more').hidden=home;if(home){$('#library-results-label').textContent='从当前已知资料、常用决策或收藏开始';await loadWorkspace();return;}if(reset){libraryOffset=0;$('#library-results').replaceChildren();}const offset=libraryOffset;$('#library-more').disabled=true;try{const response=await fetch('/api/library?'+new URLSearchParams({q:query,category,offset}));if(!response.ok)throw new Error('手册暂时无法读取');const result=await response.json();if(seq!==libraryRequest)return;for(const row of result.entries){const button=document.createElement('button');button.className='library-card';button.innerHTML=`<span class="tiny-label">${escapeHTML(row.type_label||row.category)}</span><h3>${escapeHTML(row.name)}</h3><p>${escapeHTML(row.description)}</p>${row.match_reason?`<small class="match-reason">${escapeHTML(row.match_reason)}</small>`:''}<span class="reference-badge">${row.numeric_status==='legacy'?'已从当前版本移除':'查看具体数值 →'}</span>`;button.addEventListener('click',()=>showReference(row,result.version));$('#library-results').append(button);}libraryOffset=offset+result.entries.length;$('#library-results-label').textContent=`找到 ${result.total} 条 · 已显示 ${libraryOffset} 条${(result.explanation||result.query_interpretation)?' · 查询解释：'+(result.explanation||result.query_interpretation):''}`;$('#library-more').hidden=libraryOffset>=result.total;if(!result.total){$('#library-results').innerHTML='<div class="no-results"><p>没有找到匹配资料。试试官方名称、别称或需求，例如「回血」「力量不足」「怎么逃跑」。</p><div id="library-suggestions" class="quick-searches"></div></div>';for(const q of result.suggestions?.length?result.suggestions:['治疗','力量','隐形']){const b=document.createElement('button');b.textContent=typeof q==='string'?q:q.query||q.name;b.addEventListener('click',()=>{$('#library-search').value=typeof q==='string'?q:q.query||q.name;searchLibrary();});$('#library-suggestions').append(b);}}}catch(error){if(seq===libraryRequest){$('#library-results-label').textContent=error.message;$('#library-results-label').setAttribute('role','alert');}}finally{if(seq===libraryRequest)$('#library-more').disabled=false;}}
$('#library-search').addEventListener('keydown',event=>{if(event.key==='Enter'||event.key==='ArrowDown'){event.preventDefault();clearTimeout(searchTimer);const query=$('#library-search').value,category=$('#library-category').value,nav=navigationSerial;searchLibrary().then(()=>{if(query!==$('#library-search').value||category!==$('#library-category').value||nav!==navigationSerial)return;const container=$('#library-results').hidden?$('#library-home'):$('#library-results'),first=container.querySelector('button');if(event.key==='Enter')first?.click();else first?.focus();});}});
$('#library-results').addEventListener('keydown',event=>{if(!['ArrowDown','ArrowUp'].includes(event.key))return;const buttons=$$('#library-results button'),index=buttons.indexOf(document.activeElement);if(index<0)return;event.preventDefault();if(index===0&&event.key==='ArrowUp')$('#library-search').focus();else buttons[Math.max(0,Math.min(buttons.length-1,index+(event.key==='ArrowDown'?1:-1)))].focus();});
$('#refresh').addEventListener('click',()=>action(async()=>{await post('/api/refresh');toast(state?.settings.mode==='manual'?'手动局势需要重新填写；刷新不会更新输入内容或时间。':'已重新读取磁盘上的存档。若未更新，请先在游戏内保存。');}));
let settingsWriteGeneration=0;
async function postSettings(patch,expected=state?.settings_revision){const result=await post('/api/settings',{...patch,expected_revision:expected});settingsWriteGeneration++;return result;}
$('#slot').addEventListener('change',()=>action(()=>postSettings({slot:$('#slot').value==='auto'?'auto':Number($('#slot').value),mode:'save'})));
const settingsDrafts=new Set();
let settingsRevision=null,settingsConflict=false,settingsFormGeneration=0,settingsRequestSerial=0,settingsBaseline=null;
const settingsChecks=new Set(['always-top','reveal']);
function settingsFormValues(){return Object.fromEntries(['save-root','settings-slot','source-mode','startup-surface','always-top','reveal','stop-at'].map(id=>[id,$('#'+id)[settingsChecks.has(id)?'checked':'value']]));}
function settingsSavedValues(settings){return {'save-root':settings.save_root,'settings-slot':String(settings.slot),'source-mode':settings.mode,'startup-surface':settings.startup_surface||'panel','always-top':settings.always_on_top,reveal:settings.reveal,'stop-at':settings.stop_at.slice(0,16)};}
function captureSettingsDraft(){return {format:2,raw:settingsFormValues(),baseline:settingsBaseline?{...settingsBaseline}:null,changed:Array.from(settingsDrafts)};}
function settingsDraftNotice(){$('#settings-draft-status').textContent=settingsConflict?'已保存设置发生变化；尚未保存的草稿仍保留。请重新载入已保存设置，再应用需要的修改。':settingsDrafts.size?'有尚未保存的修改，切换页面后会保留。点击「保存设置」应用。':'已按当前设置显示，需要时再调整。';}
function loadSettings(force=false,saved=state){
  if(!saved)return;
  if(force)settingsDrafts.clear();
  if(!settingsDrafts.size){settingsRevision=saved.settings_revision;settingsConflict=false;settingsBaseline=settingsSavedValues(saved.settings);}
  else if(saved.settings_revision!==settingsRevision)settingsConflict=true;
  const values=settingsSavedValues(saved.settings);
  for(const [id,value] of Object.entries(values))if(!settingsDrafts.has(id))$('#'+id)[settingsChecks.has(id)?'checked':'value']=value;
  settingsDraftNotice();
}
$('#settings-form').addEventListener('input',event=>{settingsFormGeneration++;const key=event.target.id,raw=settingsFormValues();if(key in raw){if(settingsBaseline&&raw[key]===settingsBaseline[key])settingsDrafts.delete(key);else settingsDrafts.add(key);}settingsDraftNotice();});
$('#settings-reset').addEventListener('click',()=>action(async()=>{
  const serial=++settingsRequestSerial,generation=settingsFormGeneration;
  const response=await fetch('/api/status');if(!response.ok)throw new Error('暂时无法重新载入设置，草稿仍保留。');
  const saved=await response.json();if(serial!==settingsRequestSerial)return;
  if(generation!==settingsFormGeneration)throw new Error('读取期间产生了新修改，草稿仍保留；需要时再次点击重新载入。');
  loadSettings(true,saved);
},$('#settings-error')));
$('#settings-form').addEventListener('submit',event=>{
  event.preventDefault();const submitted=settingsFormValues(),expected=settingsRevision,serial=++settingsRequestSerial;
  return action(async()=>{
    let result;try{result=await postSettings({save_root:submitted['save-root'],slot:submitted['settings-slot']==='auto'?'auto':Number(submitted['settings-slot']),mode:submitted['source-mode'],startup_surface:submitted['startup-surface'],always_on_top:submitted['always-top'],reveal:submitted.reveal,stop_at:submitted['stop-at']?submitted['stop-at']+':00+08:00':''},expected);}
    catch(error){if(error.status===409){settingsConflict=true;settingsDraftNotice();await poll();}throw error;}
    if(serial!==settingsRequestSerial)return;
    settingsRevision=result.settings_revision;settingsConflict=false;
    const current=settingsFormValues(),saved=result.settings?settingsSavedValues(result.settings):submitted;settingsBaseline={...saved};
    for(const [id,value] of Object.entries(submitted)){if(current[id]===value){$('#'+id)[settingsChecks.has(id)?'checked':'value']=saved[id];settingsDrafts.delete(id);}else if(current[id]===saved[id])settingsDrafts.delete(id);else settingsDrafts.add(id);}
    settingsDraftNotice();toast(settingsDrafts.size?'设置已保存；新的修改尚未保存':'设置已保存');
  },$('#settings-error'));
});
$$('[data-return-save]').forEach(button=>button.addEventListener('click',()=>action(async()=>{await postSettings({mode:'save'});toast('已恢复存档读取，保留当前槽位选择');navigate('overview');})));
$('#manual-form').addEventListener('submit',event=>{event.preventDefault();const payload=manualPayload();const nav=navigationSerial,generation=manualFormGeneration;action(async()=>{await post('/api/manual',payload);if(generation===manualFormGeneration&&typeof manualUnsaved!=='undefined'){manualUnsaved=false;manualAppliedRaw=captureNamedForm('#manual-form');}toast(generation===manualFormGeneration?'已根据提交的手动局势生成建议':'已按刚才提交的局势生成建议；新的表单修改仍是草稿');if(nav===navigationSerial&&generation===manualFormGeneration)navigate('overview');},$('#manual-error'));});
$('#copy-current').addEventListener('click',()=>{if(!state?.data){toast('还没有可读局势',true);return;}manualFormGeneration++;if(typeof manualUnsaved!=='undefined')manualUnsaved=true;const data=state.data,form=$('#manual-form');const values={class:data.hero.class_id,hp:data.hero.hp,ht:data.hero.ht,level:data.hero.level,strength:data.hero.strength,depth:data.depth,branch:data.branch?1:0,hunger:data.hero.hunger===null?'unknown':data.hero.hunger>=450?450:data.hero.hunger>=300?300:0,healing:data.items.filter(i=>i.kind==='PotionOfHealing' && i.known && i.available).reduce((a,b)=>a+b.quantity,0)};for(const [key,value] of Object.entries(values))form.elements.namedItem(key).value=value;$$('#manual-form input[name="buff"]').forEach(input=>input.checked=data.buffs.some(b=>b.kind===input.value && (b.kind!=='Berserk' || b.active)));$$('#manual-form input[name="challenge"]').forEach(input=>input.checked=({1:'饥饿游戏',2:'信念护体',4:'药水恐惧',8:'荒芜之地',16:'集群智慧',32:'深入黑暗',64:'禁忌符文',128:'精英强敌',256:'绝命头目'}[input.value] && data.challenges.includes({1:'饥饿游戏',2:'信念护体',4:'药水恐惧',8:'荒芜之地',16:'集群智慧',32:'深入黑暗',64:'禁忌符文',128:'精英强敌',256:'绝命头目'}[input.value])));if(typeof setManualCharacterReference==='function')setManualCharacterReference(data.character_scene?{params:data.character_scene.params,source:planSource(),stamp:calculationStamp(),label:'当前公开角色条件'}:null);toast('已带入快照，请对照游戏修正后提交');});
function calculate(){const axe=$('#calc-kind').value==='greataxe';$('#calc-tier').disabled=axe;$('#calc-tier').closest('label').hidden=axe;const tier=axe?6:Number($('#calc-tier').value),input=$('#calc-level'),level=Number(input.value);if(input.value.trim()===''||!Number.isInteger(level)||level< -10||level>100){$('#calc-result').textContent='—';$('#calc-note').textContent='请填写 -10 至 100 的整数等级；未鉴定装备请以游戏中的参考说明为准。';return;}$('#calc-result').textContent=8+2*tier-Math.floor((Math.sqrt(8*Math.max(0,level)+1)-1)/2)-($('#calc-mastery').checked?2:0);$('#calc-note').textContent=(axe?'巨斧固定为五阶，力量需求比普通五阶武器高 2 点。':'按所选阶数和已知等级计算；升级并非每次都降低需求。')+($('#calc-mastery').checked?' 已计入精通药剂降低的 2 点需求。':'');}
['#calc-kind','#calc-tier','#calc-level','#calc-mastery'].forEach(id=>$(id).addEventListener('input',calculate));
$('#stop-service').addEventListener('click',()=>requestWebSessionExit());
let polling=false;
const panelClient=crypto.randomUUID();let panelAcknowledged=null,panelHandling=null;
async function followPanelRequest(){try{const result=await post('/api/panel',{action:'heartbeat',client:panelClient,ack:panelAcknowledged});if(result.command&&panelHandling!==result.command.serial){panelHandling=result.command.serial;try{navigate(result.command.page);if(result.command.plan_id&&typeof openPlan==='function')await openPlan(result.command.plan_id);panelAcknowledged=result.command.serial;window.focus();}finally{panelHandling=null;}}}catch(error){/* Main connection state is handled by poll. */}}
async function poll(){if(polling)return;polling=true;const writeGeneration=settingsWriteGeneration;try{const response=await fetch('/api/status');if(!response.ok)throw new Error('连接失败');const next=await response.json();if(writeGeneration!==settingsWriteGeneration)return;state=next;token=state.token;syncBackupContext(state.backup_context);render();renderBackupHealth();if(view==='settings')loadSettings();if(typeof refreshNumericalOrigin==='function')refreshNumericalOrigin();if(typeof renderEquipmentComparison==='function')renderEquipmentComparison();if(view==='backups')loadBackups();if(typeof refreshWorkspaceViews==='function')refreshWorkspaceViews();await followPanelRequest();if(typeof handleWebExitState==='function'&&['backing-up','finished'].includes(state.exit?.phase))await handleWebExitState(state.exit);else if(typeof reportWebExitSurface==='function')await reportWebExitSurface();if(!initialPanelPlanHandled&&initialPanelPlan&&typeof openPlan==='function'){initialPanelPlanHandled=true;navigate('workspace');await openPlan(initialPanelPlan);} }catch(error){state=null;token=null;syncBackupContext(null);renderBackupHealth();lastRender='';slotsSignature='';$('#connection-banner').className='connection-banner error';$('#connection-banner').textContent='助手服务已停止或连接中断。重新打开「灯火」，默认会打开完整面板；若正在使用桌面管理窗口，请点击「完整面板」。';$('#connection-short').textContent='服务未连接';$('#sidebar-dot').className='dot error';$('#stop-countdown').textContent='';$('#adventure').hidden=true;$('#empty-state').hidden=false;$('#empty-title').textContent='助手连接已中断';$('#empty-description').textContent='连接中断，上一局势已失效。恢复连接后重新读取。';renderInventory();if(typeof refreshNumericalOrigin==='function')refreshNumericalOrigin();if(typeof decisionRequest!=='undefined'){decisionRequest++;decisionSignature='';decisionState=null;$('#decision-options').replaceChildren();} $('#restore-dialog').close();restoreTarget=null;backupState=null;backupViewKeys.clear();$('#backup-history').replaceChildren();$('#backup-retained').replaceChildren();$('#backup-undo').replaceChildren();$('#backup-nodes').textContent='连接中断，请重新启动助手后查看备份。';$('#backup-status').textContent='自动备份状态尚未确认。';if(typeof renderWebExitReceipt==='function')renderWebExitReceipt();}finally{polling=false;}}
initializeBackups();calculate();navigate(location.hash.slice(1) || 'overview','replace');poll().then(()=>{if(view==='settings')loadSettings();});setInterval(poll,2000);
