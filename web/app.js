'use strict';
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const names = {overview:'冒险概览',inventory:'背包与装备',library:'地牢手册',backups:'存档时光机',manual:'局势推演',settings:'连接设置'};
const icons = {WARRIOR:'⚔',MAGE:'✦',ROGUE:'◐',HUNTRESS:'➶',DUELIST:'⚔',CLERIC:'✧'};
let state, token, view='overview', lastRender='', slotsSignature='', libraryRequest=0, toastTimer;
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const fmtTime = seconds => new Date(seconds*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
const shortTime = seconds => new Date(seconds*1000).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
function toast(message,error=false){$('#toast').textContent=message;$('#toast').classList.toggle('error',error);$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,5000);}
async function post(path,payload={}){
  if(!token)throw new Error('助手还没连接，请稍后重试');
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Companion-Token':token},body:JSON.stringify(payload)});
  const result=await response.json();if(!response.ok)throw new Error(result.error || '操作失败');
  return result;
}
async function action(work){try{await work();await poll();}catch(error){toast(error.message,true);}}
const viewPositions=new Map();
function navigate(next){
  if(!names[next])next='overview';
  const changed=view!==next;
  if(changed)viewPositions.set(view,window.scrollY);
  view=next;
  for(const el of $$('.view'))el.hidden=el.id!==`view-${next}`;
  for(const el of $$('.nav')){el.classList.toggle('active',el.dataset.view===next);el.setAttribute('aria-current',el.dataset.view===next?'page':'false');}
  $('#page-name').textContent=names[next];history.replaceState(null,'',`#${next}`);
  if(next==='library'&&!$('#library-results').childElementCount)searchLibrary();
  if(next==='inventory')renderInventory();if(next==='settings')loadSettings();if(next==='backups')loadBackups();
  if(changed)window.scrollTo({top:viewPositions.get(next)||0,behavior:'instant'});
}
$$('[data-view]').forEach(el=>el.addEventListener('click',()=>navigate(el.dataset.view)));
$$('[data-goto]').forEach(el=>el.addEventListener('click',()=>navigate(el.dataset.goto)));
$('.brand').addEventListener('click',event=>{event.preventDefault();navigate('overview');});
window.addEventListener('hashchange',()=>navigate(location.hash.slice(1)));
document.addEventListener('keydown',event=>{if(event.key==='/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){event.preventDefault();navigate('library');$('#library-search').focus();}});
function renderStatus(){
  const banner=$('#connection-banner');const isManual=state.settings.mode==='manual';
  $('#refresh').textContent=isManual?'↻ 更新提示':'↻ 刷新存档';
  const ago=state.age_seconds===null?'尚未读取':state.age_seconds<60?`${Math.floor(state.age_seconds)} 秒前`:state.age_seconds<3600?`${Math.floor(state.age_seconds/60)} 分钟前`:state.age_seconds<86400?`${Math.floor(state.age_seconds/3600)} 小时前`:`${Math.floor(state.age_seconds/86400)} 天前`;
  const origin=isManual?'手动输入':`槽位 ${state.active_slot ?? '—'} · 存档快照`;
  banner.className='connection-banner'+(state.error?' error':state.stale?'':' fresh');
  let text=state.error || `${origin} · ${fmtTime(state.modified)} 更新（${ago}）`;
  if(!state.error)text+=isManual?(state.stale?' · 手动信息已过期，请重新填写当前局势；此模式不会自动跟随游戏。':' · 此模式不会自动跟随游戏，请随局势重新填写。'):state.stale?' · 这是旧快照；请先在游戏中保存，勿当作当前状态。':' · 以游戏画面为准，存档更新后自动同步。';
  if(state.warning && !state.error)text+=' '+state.warning;
  if(state.configuration_notice)text+=' '+state.configuration_notice;
  if(state.settings.reveal)text+=' · 剧透模式已开启';
  banner.textContent=text;
  $('#sidebar-dot').className='dot '+(state.error?'error':state.stale?'stale':'live');
  $('#connection-short').textContent=state.error?'等待可读存档':isManual?'手动局势':state.stale?'旧快照 · 等待更新':'正在跟随存档';
  $('#catalog-version').textContent=state.catalog_version;$('#library-count').textContent=`${state.catalog_count} 条官方资料`;
  const stop=state.settings.stop_at;let countdown='';if(stop){const minutes=Math.max(0,Math.ceil((new Date(stop).getTime()-Date.now())/60000));countdown=`${Math.floor(minutes/60)} 时 ${minutes%60} 分后停止`;}$('#stop-countdown').textContent=countdown;
  const sig=JSON.stringify(state.slots.map(row=>[row.id,row.valid,row.hero_class,row.depth]))+state.settings.slot;
  if(sig!==slotsSignature){slotsSignature=sig;$('#slot').innerHTML='<option value="auto">自动跟随最新存档</option>'+Array.from({length:6},(_,i)=>{const row=state.slots.find(row=>row.id===i+1);return `<option value="${i+1}">槽位 ${i+1}${row?.valid?` · 第 ${escapeHTML(row.depth)} 层`:' · 暂无可读角色'}</option>`;}).join('');$('#slot').value=String(state.settings.slot);}
}
function render(){
  renderStatus();const key=JSON.stringify([state.revision,state.error,state.active_slot,state.settings.mode]);if(key===lastRender)return;lastRender=key;
  const data=state.data;$('#empty-state').hidden=!!data;$('#adventure').hidden=!data;$('#empty-description').textContent=state.error || '开始一局并保存后，角色状态会出现在这里。';
  if(!data){renderInventory();return;}
  const hero=data.hero;$('#hero-icon').textContent=icons[hero.class_id] || '✦';$('#hero-title').textContent=`${hero.class} · 等级 ${hero.level}`;$('#hero-subtitle').textContent=`${data.region} / ${state.settings.mode==='manual'?'手动局势':`存档槽位 ${state.active_slot}`} / ${data.version?`存档版本码 ${data.version}`:'手动数据'}`;
  $('#hero-tags').innerHTML=[...data.buffs.map(b=>`<span class="tag warn">${escapeHTML(b.name)}</span>`),...data.challenges.map(c=>`<span class="tag">${escapeHTML(c)}</span>`)].join('');
  const ratio=Math.max(0,Math.min(1,hero.hp/hero.ht));$('#health').textContent=`${hero.hp} / ${hero.ht}`;$('#health-percent').textContent=`${Math.round(ratio*100)}%`;$('#health-bar').style.width=`${ratio*100}%`;$('#health-bar').classList.toggle('low',ratio<.5);$('#depth').textContent=`第 ${data.depth} 层`;$('#region').textContent=data.region;$('#strength').textContent=hero.strength;$('#hunger').textContent=hero.hunger_label;$('#resources').textContent=state.settings.mode==='manual'?'金币与炼金能量未填写':`金币 ${data.gold} · 炼金能量 ${data.energy}`;
  $('#advice-list').innerHTML=data.tips.length?data.tips.map(t=>`<article class="advice ${t.severity}"><div class="advice-head"><span class="severity">${{critical:'优先处理',warning:'留意',info:'提示'}[t.severity]}</span><h3>${escapeHTML(t.title)}</h3></div><p>${escapeHTML(t.body)}</p><details><summary>为什么这样建议</summary>${escapeHTML(t.basis)}</details></article>`).join(''):'<p class="muted">当前没有触发特殊风险规则。继续留意周围敌人和退路。</p>';
  const equipped=data.items.filter(item=>!['背包','收纳袋'].includes(item.location));$('#equipped').innerHTML=equipped.length?equipped.map(item=>`<button class="equipment-row"><span class="equipment-icon">${item.location==='护甲'?'◈':item.location.includes('武器')?'⚔':'◇'}</span><span><strong>${escapeHTML(item.name)}</strong><small>${escapeHTML(item.details.join(' · ')) || '查看物品说明'}</small></span><span class="item-place">${escapeHTML(item.location)}</span></button>`).join(''):'<p class="muted">手动模式未填写装备；请在游戏中核对。</p>';
  $$('#equipped button').forEach((button,i)=>button.addEventListener('click',()=>showItem(equipped[i])));
  $('#history').innerHTML=state.history.length?state.history.slice(0,5).map(row=>`<div class="history-row">${escapeHTML(row.text)}<time>${escapeHTML(fmtTime(row.time))}</time></div>`).join(''):'<p class="muted">新的存档快照到达后，会在这里记录血量和楼层变化。</p>';
  renderMap(data.map);renderInventory();
}
function renderMap(map){
  const canvas=$('#map');canvas.hidden=!map;$('#map-empty').hidden=!!map;$('#map-caption').textContent=map?.caption || state.warning || '手动模式不提供地图。';if(!map)return;
  const ctx=canvas.getContext('2d');const width=460,height=320;ctx.fillStyle='#121914';ctx.fillRect(0,0,width,height);
  const visible=map.tiles.map((t,i)=>t>=0?i:-1).filter(i=>i>=0);if(map.hero!==null)visible.push(map.hero);if(!visible.length)return;
  const xs=visible.map(i=>i%map.width),ys=visible.map(i=>Math.floor(i/map.width));const minX=Math.max(0,Math.min(...xs)-2),maxX=Math.min(map.width-1,Math.max(...xs)+2),minY=Math.max(0,Math.min(...ys)-2),maxY=Math.min(map.height-1,Math.max(...ys)+2);const size=Math.max(2,Math.min(14,Math.floor(Math.min((width-30)/(maxX-minX+1),(height-30)/(maxY-minY+1)))));const ox=Math.floor((width-(maxX-minX+1)*size)/2),oy=Math.floor((height-(maxY-minY+1)*size)/2);
  const colors={0:'#080e0b',1:'#344133',2:'#42563a',4:'#687463',5:'#a2875d',6:'#645d42',7:'#8bb39d',8:'#d5bd82',10:'#a87e50',12:'#687463',15:'#527944',16:'#687463',17:'#344133',18:'#b57464',19:'#6f6152',21:'#8bb39d',22:'#d5bd82',24:'#698c88',27:'#756c4b',28:'#6a8d81',29:'#426874',30:'#527944',37:'#8bb39d'};
  for(let y=minY;y<=maxY;y++)for(let x=minX;x<=maxX;x++){const tile=map.tiles[y*map.width+x];if(tile<0)continue;ctx.fillStyle=colors[tile] || '#485440';ctx.fillRect(ox+(x-minX)*size,oy+(y-minY)*size,size-1,size-1);}
  if(map.hero!==null){const x=ox+(map.hero%map.width-minX)*size,y=oy+(Math.floor(map.hero/map.width)-minY)*size;ctx.fillStyle='#f4d69c';ctx.fillRect(x,y,size-1,size-1);ctx.strokeStyle='#fff0c9';ctx.lineWidth=1;ctx.strokeRect(x-2,y-2,size+3,size+3);}
}
function renderInventory(){
  const query=$('#inventory-search').value.toLowerCase();const items=(state?.data?.items || []).filter(item=>(item.name+' '+item.kind+' '+item.location).toLowerCase().includes(query));$('#item-count').textContent=state?.settings.mode==='manual'?`已填写 ${items.length} 项物品`:`${items.length} 项物品`;
  $('#inventory-list').innerHTML=items.length?items.map(item=>`<button class="item-card"><span class="item-meta">${escapeHTML(item.location)} · ×${item.quantity}</span><h3>${escapeHTML(item.name)}</h3><p>${escapeHTML(item.details.join(' · ')) || (item.known?'已知种类':'效果未知')}</p></button>`).join(''):'<p class="no-results">没有匹配的背包物品。连接有效存档后可查看。</p>';
  $$('#inventory-list button').forEach((button,i)=>button.addEventListener('click',()=>showItem(items[i])));
}
function showDetail(title,text,category,meta){cancelNumericalDetail();$('#detail-rules').replaceChildren();$('#detail-title').textContent=title;$('#detail-text').textContent=text || '此条目没有独立说明，请参考游戏中的检查界面。';$('#detail-category').textContent=category;$('#detail-meta').textContent=meta;$('#detail-dialog').showModal();$('#detail-dialog').scrollTop=0;}
function showItem(item){showDetail(item.name,item.description,item.location,item.details.join(' · ')+(item.known?'':' · 未鉴定物品保留未知身份'));if(item.known)loadNumericalDetail(item.key,{...(item.level===null?{}:{level:item.level}),...(item.tier?{tier:item.tier}:{})},item.level===null?'unknown':'known');}
function showReference(row,version){showDetail(row.name,row.description+(row.hint?'\n\n'+row.hint:''),row.category,`游戏版本 ${version}`);loadNumericalDetail(row.id);}
$('#close-detail').addEventListener('click',()=>$('#detail-dialog').close());
$('#detail-dialog').addEventListener('click',event=>{if(event.target===$('#detail-dialog')){const rect=event.target.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)event.target.close();}});
$('#inventory-search').addEventListener('input',renderInventory);
let searchTimer,libraryOffset=0;
$('#library-search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>searchLibrary(),180);});
$('#library-category').addEventListener('change',()=>searchLibrary());

$('#library-more').addEventListener('click',()=>searchLibrary(false));
$$('[data-query]').forEach(button=>button.addEventListener('click',()=>{$('#library-search').value=button.dataset.query;$('#library-category').value='全部';searchLibrary();}));
async function searchLibrary(reset=true){const seq=++libraryRequest;if(reset){libraryOffset=0;$('#library-results').replaceChildren();}const offset=libraryOffset;$('#library-more').disabled=true;try{const query=$('#library-search').value,category=$('#library-category').value;const response=await fetch('/api/library?'+new URLSearchParams({q:query,category,offset}));if(!response.ok)throw new Error('手册暂时无法读取');const result=await response.json();if(seq!==libraryRequest)return;for(const row of result.entries){const button=document.createElement('button');button.className='library-card';button.innerHTML=`<span class="tiny-label">${escapeHTML(row.type_label||row.category)}</span><h3>${escapeHTML(row.name)}</h3><p>${escapeHTML(row.description)}</p><span class="reference-badge">${row.numeric_status==='legacy'?'已从当前版本移除':'查看具体数值 →'}</span>`;button.addEventListener('click',()=>showReference(row,result.version));$('#library-results').append(button);}libraryOffset=offset+result.entries.length;$('#library-results-label').textContent=`找到 ${result.total} 条 · 已显示 ${libraryOffset} 条`;$('#library-more').hidden=libraryOffset>=result.total;if(!result.total)$('#library-results').innerHTML='<p class="no-results">没找到匹配条目，试试更短的中文名称。</p>';}catch(error){if(seq===libraryRequest)$('#library-results-label').textContent=error.message;}finally{if(seq===libraryRequest)$('#library-more').disabled=false;}}
$('#refresh').addEventListener('click',()=>action(async()=>{await post('/api/refresh');toast(state?.settings.mode==='manual'?'手动局势需要重新填写；刷新不会更新输入内容或时间。':'已重新读取磁盘上的存档。若未更新，请先在游戏内保存。');}));
$('#slot').addEventListener('change',()=>action(()=>post('/api/settings',{slot:$('#slot').value==='auto'?'auto':Number($('#slot').value),mode:'save'})));
function loadSettings(){if(!state)return;$('#save-root').value=state.settings.save_root;$('#settings-slot').value=String(state.settings.slot);$('#source-mode').value=state.settings.mode;$('#always-top').checked=state.settings.always_on_top;$('#reveal').checked=state.settings.reveal;$('#stop-at').value=state.settings.stop_at.slice(0,16);}
$('#settings-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{await post('/api/settings',{save_root:$('#save-root').value,slot:$('#settings-slot').value==='auto'?'auto':Number($('#settings-slot').value),mode:$('#source-mode').value,always_on_top:$('#always-top').checked,reveal:$('#reveal').checked,stop_at:$('#stop-at').value?$('#stop-at').value+':00+08:00':''});toast('设置已保存');});});
$$('[data-return-save]').forEach(button=>button.addEventListener('click',()=>action(async()=>{await post('/api/settings',{mode:'save'});toast('已恢复存档读取，保留当前槽位选择');navigate('overview');}))); 
$('#manual-form').addEventListener('submit',event=>{event.preventDefault();const form=new FormData(event.target);const payload={class:form.get('class'),buffs:form.getAll('buff'),challenges:form.getAll('challenge').reduce((a,b)=>a|Number(b),0)};for(const key of ['hp','ht','depth','branch','level','strength','healing'])payload[key]=Number(form.get(key));payload.hunger=form.get('hunger')==='unknown'?null:Number(form.get('hunger'));action(async()=>{await post('/api/manual',payload);toast('已根据手动局势生成建议');navigate('overview');});});
$('#copy-current').addEventListener('click',()=>{if(!state?.data){toast('还没有可读局势',true);return;}const data=state.data,form=$('#manual-form');const values={class:data.hero.class_id,hp:data.hero.hp,ht:data.hero.ht,level:data.hero.level,strength:data.hero.strength,depth:data.depth,branch:data.branch?1:0,hunger:data.hero.hunger===null?'unknown':data.hero.hunger>=450?450:data.hero.hunger>=300?300:0,healing:data.items.filter(i=>i.kind==='PotionOfHealing' && i.known && i.available).reduce((a,b)=>a+b.quantity,0)};for(const [key,value] of Object.entries(values))form.elements.namedItem(key).value=value;$$('#manual-form input[name="buff"]').forEach(input=>input.checked=data.buffs.some(b=>b.kind===input.value && (b.kind!=='Berserk' || b.active)));$$('#manual-form input[name="challenge"]').forEach(input=>input.checked=({1:'饥饿游戏',2:'信念护体',4:'药水恐惧',8:'荒芜之地',16:'集群智慧',32:'深入黑暗',64:'禁忌符文',128:'精英强敌',256:'绝命头目'}[input.value] && data.challenges.includes({1:'饥饿游戏',2:'信念护体',4:'药水恐惧',8:'荒芜之地',16:'集群智慧',32:'深入黑暗',64:'禁忌符文',128:'精英强敌',256:'绝命头目'}[input.value])));toast('已带入快照，请对照游戏修正后提交');});
function calculate(){const axe=$('#calc-kind').value==='greataxe';$('#calc-tier').disabled=axe;$('#calc-tier').closest('label').hidden=axe;const tier=axe?6:Number($('#calc-tier').value),input=$('#calc-level'),level=Number(input.value);if(input.value.trim()===''||!Number.isInteger(level)||level< -10||level>100){$('#calc-result').textContent='—';$('#calc-note').textContent='请填写 -10 至 100 的整数等级；未鉴定装备请以游戏中的参考说明为准。';return;}$('#calc-result').textContent=8+2*tier-Math.floor((Math.sqrt(8*Math.max(0,level)+1)-1)/2)-($('#calc-mastery').checked?2:0);$('#calc-note').textContent=(axe?'巨斧固定为五阶，力量需求比普通五阶武器高 2 点。':'按所选阶数和已知等级计算；升级并非每次都降低需求。')+($('#calc-mastery').checked?' 已计入精通药剂降低的 2 点需求。':'');}
['#calc-kind','#calc-tier','#calc-level','#calc-mastery'].forEach(id=>$(id).addEventListener('input',calculate));
$('#stop-service').addEventListener('click',()=>action(async()=>{await post('/api/shutdown');toast('本次辅助已结束。再次使用时双击启动助手。');}));
let polling=false;
const panelClient=crypto.randomUUID();let panelAcknowledged=null;
async function followPanelRequest(){try{const result=await post('/api/panel',{action:'heartbeat',client:panelClient,ack:panelAcknowledged});if(result.command){panelAcknowledged=result.command.serial;navigate(result.command.page);window.focus();}}catch(error){/* Main connection state is handled by poll. */}}
async function poll(){if(polling)return;polling=true;try{const response=await fetch('/api/status');if(!response.ok)throw new Error('连接失败');state=await response.json();token=state.token;render();renderBackupHealth();if(typeof refreshNumericalOrigin==='function')refreshNumericalOrigin();if(typeof renderEquipmentComparison==='function')renderEquipmentComparison();if(view==='backups')await loadBackups();await followPanelRequest();}catch(error){state=null;token=null;lastRender='';slotsSignature='';$('#connection-banner').className='connection-banner error';$('#connection-banner').textContent='助手服务已停止或连接中断。双击「启动灯火助手.cmd」后使用新打开的页面。';$('#connection-short').textContent='服务未连接';$('#sidebar-dot').className='dot error';$('#stop-countdown').textContent='';$('#adventure').hidden=true;$('#empty-state').hidden=false;$('#empty-description').textContent='连接中断，上一局势已失效。恢复连接后重新读取。';renderInventory();$('#detail-dialog').close();$('#restore-dialog').close();restoreTarget=null;$('#backup-nodes').textContent='连接中断，请重新启动助手后查看备份。';$('#backup-status').textContent='自动备份状态尚未确认。';}finally{polling=false;}}
initializeBackups();calculate();navigate(location.hash.slice(1) || 'overview');poll().then(()=>{if(view==='settings')loadSettings();});setInterval(poll,2000);
