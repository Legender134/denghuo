'use strict';
let forecastInfo=null,forecastValue=null,forecastSource=null,forecastWorker=null,forecastTimer=null,forecastSerial=0,forecastBusy=false,forecastContext=null;
const forecastSources={heap:'地面物品',chest:'宝箱',locked_chest:'上锁宝箱',crystal_chest:'水晶宝箱',tomb:'墓碑',skeleton:'骸骨',sacrificial_fire:'献祭之火',mimic:'宝箱怪',golden_mimic:'金色宝箱怪',crystal_mimic:'水晶宝箱怪',statue:'石像',armored_statue:'装甲石像',shop:'商店（需要购买）',ghost_reward:'悲伤幽灵任务奖励',wandmaker_reward:'老杖匠任务奖励',blacksmith_reward:'巨魔铁匠任务奖励',imp_reward:'小恶魔金库最终奖励',vault_treasure:'小恶魔金库宝物'};
const forecastRooms={weak_floor:'坍塌地板房',crypt:'墓室',pool:'水池房',armory:'军械库',sentry:'哨卫房',statue:'石像房',crystal_vault:'水晶宝库',crystal_choice:'水晶选择房',sacrifice:'献祭房',runestone:'符石房',garden:'花园',library:'图书室',storage:'储藏室',treasury:'金库',magic_well:'魔法水井',toxic_gas:'毒气房',magical_fire:'魔法火焰房',traps:'陷阱房',crystal_path:'水晶通道',laboratory:'实验室',pit:'坠落坑房',shop:'商店',demon_spawner:'恶魔血巢房',secret_garden:'隐藏花园',secret_laboratory:'隐藏实验室',secret_library:'隐藏图书室',secret_larder:'隐藏食品库',secret_well:'隐藏水井',secret_runestone:'隐藏符石房',secret_artillery:'隐藏投掷武器库',secret_chest_chasm:'隐藏深渊宝箱房',secret_honeypot:'隐藏蜂蜜罐房',secret_hoard:'隐藏宝藏房',secret_maze:'隐藏迷宫',secret_summoning:'隐藏召唤房',secret_mine:'隐藏矿井',secret_rat_king:'鼠王隐藏房',quest_mass_grave:'老杖匠乱葬岗',quest_ritual_site:'老杖匠仪式场',quest_rot_garden:'老杖匠腐莓园',quest_blacksmith:'巨魔铁匠任务房',quest_ambitious_imp:'小恶魔任务房'};
const forecastFeelings={None:'普通',Chasm:'深渊',Water:'水域',Grass:'植被',Dark:'黑暗',Large:'宽阔',Traps:'陷阱密集',Secrets:'秘密密集'};
function parseForecastSeed(input){
  const text=String(input).trim().toUpperCase();
  if(/^(?:[A-Z]{9}|[A-Z]{3}-[A-Z]{3}-[A-Z]{3})$/.test(text))return [...text.replaceAll('-','')].reduce((value,letter)=>value*26n+BigInt(letter.charCodeAt(0)-65),0n).toString();
  if(/^\d{4}-\d{2}-\d{2}$/.test(text)&&Number(text.slice(0,4))>=1970){const date=new Date(text+'T00:00:00Z');if(Number.isFinite(date.getTime())&&date.toISOString().slice(0,10)===text)return (5429503678976n+BigInt(date.getTime())).toString();}
  throw Error('请输入九个英文字母的种子（可按三组分隔），或 1970–9999 年的有效 UTC 每日日期。');
}
function forecastControls(){
  let valid=false;try{parseForecastSeed($('#forecast-seed').value);valid=true;}catch{}
  $('#forecast-run').disabled=forecastBusy||!valid||!$('#forecast-confirm').checked;
  $('#forecast-read-seed').disabled=forecastBusy||!state?.data||!!state.error||state?.settings?.mode!=='save';
  $('#forecast-cancel').hidden=!forecastBusy;
}
function clearForecast(){forecastValue=null;$('#forecast-result').hidden=true;$('#forecast-floors').replaceChildren();$('#forecast-count').textContent='';}
function stopForecast(message,hide=true){forecastSerial++;forecastWorker?.terminate();forecastWorker=null;clearTimeout(forecastTimer);forecastTimer=null;forecastBusy=false;if(hide)clearForecast();if(message)$('#forecast-status').textContent=message;forecastControls();}
function refreshForecastContext(){
  const current=scoutingContext();if(current===forecastContext)return;forecastContext=current;
  if(forecastSource){forecastSource=null;$('#forecast-confirm').checked=false;$('#forecast-origin').textContent='原存档快照已变化；输入仍保留为手填参考种子，请重新确认情景或读取本局。';stopForecast('已收起旧存档关联的预测。');}
  forecastControls();
}
async function readForecastSeed(){
  stopForecast('',true);const serial=forecastSerial,context=scoutingContext();forecastBusy=true;forecastControls();inlineError($('#forecast-error'),'');$('#forecast-status').textContent='仅读取种子，不计算或揭示楼层…';
  try{
    const result=await post('/api/forecast',{action:'seed',reveal:true});if(serial!==forecastSerial||context!==scoutingContext())return;
    if(parseForecastSeed(result.seed_code)!==result.seed)throw Error('存档种子校验不一致，未代入预测。');
    forecastSource=result.source;forecastContext=context;$('#forecast-seed').value=result.seed_code;$('#forecast-confirm').checked=false;
    $('#forecast-from').value=String(Math.min(24,result.source.depth+1));
    $('#forecast-origin').textContent=`种子来自槽位 ${result.source.slot} · 游戏 ${result.source.version_name} · 第 ${result.source.depth} 层 · ${fmtTime(result.source.modified)}。${result.note}`;
    $('#forecast-status').textContent=result.source.depth>=24?'种子已读取；此引擎只到第24层，没有更深楼层预测。可查看独立情景中的早期楼层。':'种子已读取；确认参考条件后可生成。';
  }catch(error){if(serial===forecastSerial){forecastSource=null;inlineError($('#forecast-error'),error.message);$('#forecast-status').textContent='未读取种子；可重试或手填独立种子。';}}
  finally{if(serial===forecastSerial){forecastBusy=false;forecastControls();}}
}
function validateForecastResult(value,seed,depth){
  if(value?.schema!==1||value.seed!==seed||value.maximum_depth!==depth||value.game_version!=='4.0.2'||value.engine_commit!==forecastInfo.engine_commit||value.profile!==forecastInfo.profile||!Array.isArray(value.items)||value.items.length>5000||!Array.isArray(value.floors)||value.floors.length>24)throw Error('预测结果版本或范围校验失败。');
  const identities=new Set(forecastInfo.items.map(item=>item.id));
  for(const item of value.items){
    const access=item.access;
    if(!identities.has(item.id)||!Number.isInteger(item.depth)||item.depth<1||item.depth>depth||!Number.isInteger(item.level)||item.level<0||item.level>10||typeof item.cursed!=='boolean'||typeof item.secret!=='boolean'||!(item.source in forecastSources)||!access||!['independent','choice','scenarios'].includes(access.type))throw Error('预测物品数据不完整。');
    if(access.type!=='independent'&&(!Number.isInteger(access.group)||access.group<0||access.group>65535))throw Error('互斥奖励组无效。');
    if(access.type==='choice'&&(!Number.isInteger(access.option)||access.option<0||access.option>63))throw Error('互斥奖励选项无效。');
    if(access.type==='scenarios'&&(typeof access.mask!=='string'||!/^\d{1,20}$/.test(access.mask)||BigInt(access.mask)<1n||BigInt(access.mask)>0xffffffffffffffffn))throw Error('奖励取得路径无效。');
  }
  for(const floor of value.floors)if(!Number.isInteger(floor.depth)||floor.depth<1||floor.depth>depth||!Array.isArray(floor.rooms)||floor.rooms.length>128||floor.rooms.some(room=>typeof room!=='string')||!(floor.feeling in forecastFeelings))throw Error('预测楼层数据不完整。');
}
async function runForecast(){
  if($('#forecast-run').disabled||!$('#forecast-confirm').checked)return;
  stopForecast('',true);const serial=forecastSerial,seed=parseForecastSeed($('#forecast-seed').value),depth=Number($('#forecast-depth').value);
  forecastBusy=true;forecastControls();inlineError($('#forecast-error'),'');$('#forecast-status').textContent='正在离线生成参考情景；可以随时取消…';
  try{
    if(!forecastInfo)forecastInfo=await getJSON('/api/forecast');if(serial!==forecastSerial)return;
    if(forecastInfo.game_version!=='4.0.2'||forecastInfo.maximum_depth!==24||!Array.isArray(forecastInfo.items))throw Error('本地预测资料版本不匹配。');
    $('#forecast-profile').textContent=forecastInfo.note;
    if(typeof Worker!=='function'||typeof WebAssembly!=='object')throw Error('此浏览器组件暂不支持离线计算，请使用软件内支持 WebAssembly 的面板。');
    forecastWorker=new Worker('/forecast-worker.js');
    forecastTimer=setTimeout(()=>{if(serial===forecastSerial){stopForecast('计算已超时并取消；可重新尝试。');inlineError($('#forecast-error'),'离线计算未在15秒内返回，旧结果不会显示。');}},15000);
    forecastWorker.onmessage=event=>{
      if(serial!==forecastSerial||!$('#forecast-confirm').checked)return;
      try{
        if(!event.data?.ok)throw Error(event.data?.error||'离线计算失败。');validateForecastResult(event.data.result,seed,depth);
        forecastValue=event.data.result;forecastWorker.terminate();forecastWorker=null;clearTimeout(forecastTimer);forecastTimer=null;forecastBusy=false;
        $('#forecast-title').textContent=`${forecastValue.seed_code} · 官方4.0.2新局参考 · 第1–${depth}层`;
        renderForecast();$('#forecast-result').hidden=false;$('#forecast-status').textContent='参考情景已生成。数值可点击查询；这些装备未加入背包，实际冒险请以存档探查为准。';forecastControls();
      }catch(error){stopForecast('本次未展示预测结果。');inlineError($('#forecast-error'),error.message);}
    };
    forecastWorker.onerror=()=>{if(serial===forecastSerial){stopForecast('本次未展示预测结果。');inlineError($('#forecast-error'),'离线模块加载或运行失败，请完整解压软件后重试。');}};
    forecastWorker.postMessage({seed,depth});
  }catch(error){if(serial===forecastSerial){stopForecast('本次未展示预测结果。');inlineError($('#forecast-error'),error.message);}}
}
function forecastEffect(item){return item.effect?(forecastInfo.effects?.[item.kind]?.[item.effect.replaceAll('-','').replaceAll('_','').toLowerCase()]||item.effect):'';}
function forecastAccess(access,brief=false){
  if(access.type==='choice')return `互斥组 ${access.group} · 选项 ${access.option+1}（同组不同选项不能同时取得）`;
  if(access.type==='scenarios'){const paths=[],mask=BigInt(access.mask);for(let bit=0;bit<64;bit++)if(mask&(1n<<BigInt(bit)))paths.push(bit+1);return `取得路径组 ${access.group} · 可走路径 ${paths.join('、')}（同组物品共有至少一条路径才可兼得）`;}
  return brief?'未记录互斥':'无该引擎记录的互斥组；仍需符合来源条件';
}
function showForecastItem(item,definition){
  const label=`${forecastValue.seed_code} · 4.0.2新局参考 · 第 ${item.depth} 层 · ${forecastSources[item.source]}`;
  showDetail(definition.name,definition.description,'独立种子参考',`${label}；${forecastAccess(item.access)}。预测显示等级 +${item.level}${item.cursed?'，诅咒':''}；未持有、未在游戏中鉴定。`);
  if(typeof setReferencePortrait==='function'){setReferencePortrait(definition.key,definition.name);void hydrateReference({id:definition.key,name:definition.name,preserve_description:true},detailReferenceSerial);}if(typeof setDetailEntry==='function')setDetailEntry(definition.key);
  const level=definition.kind==='Artifact'?null:definition.kind==='Trinket'?0:item.level;
  const params={...(level===null?{}:{level}),...(definition.tier?{tier:definition.tier}:{})};
  loadNumericalDetail(definition.key,params,level===null?'unknown':'assumed',{capturedContext:true,ignoreDrafts:true,sourceStamp:null,
    fieldOrigins:Object.fromEntries(Object.keys(params).map(key=>[key,'独立新局参考 · '+label])),
    skillConditions:`${label}；基础数值，未计入诅咒、附魔/刻印或当前角色增益。${level===null?'神器显示等级未转换为内部等级，等级相关公式需另行确认。':''}`,skillState:'unknown'});
}
function renderForecast(){
  if(!forecastValue)return;const from=Number($('#forecast-from').value),kind=$('#forecast-kind').value,query=$('#forecast-query').value.trim().toLowerCase(),target=$('#forecast-floors');target.replaceChildren();
  const definitions=new Map(forecastInfo.items.map(item=>[item.id,item]));
  const items=forecastValue.items.filter(item=>item.depth>=from&&(!kind||item.kind===kind)&&(!query||[definitions.get(item.id).name,definitions.get(item.id).english_name,forecastSources[item.source],forecastEffect(item),item.effect].join(' ').toLowerCase().includes(query)));
  $('#forecast-count').textContent=`第 ${from}–${forecastValue.maximum_depth} 层显示 ${items.length} 项候选；筛选仅影响显示，不改变互斥条件。隐藏房间只列类型，不提供未生成楼层坐标。`;
  for(let depth=from;depth<=forecastValue.maximum_depth;depth++){
    const rows=items.filter(item=>item.depth===depth),floor=forecastValue.floors.find(row=>row.depth===depth);
    const section=document.createElement('section');section.className='scout-card';const heading=document.createElement('h3');heading.textContent=`第 ${depth} 层${floor?' · '+forecastFeelings[floor.feeling]:''}`;section.append(heading);
    if(floor){const rooms=floor.rooms.filter(room=>room in forecastRooms).map(room=>forecastRooms[room]);const note=document.createElement('p');note.className='muted';note.textContent=rooms.length?'特殊、任务与隐藏房间：'+rooms.join('、'):'未记录所列特殊、任务或隐藏房间类型。';section.append(note);}
    for(const item of rows){const definition=definitions.get(item.id),card=document.createElement('div');card.className='forecast-item';const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=`${definition.name}${item.kind==='Trinket'?' · 初始候选':` +${item.level}`}${item.cursed?' · 诅咒':''}${item.effect?' · '+forecastEffect(item):''}${item.secret?' · 隐藏房间':''}`;if(typeof referenceNameHTML==='function'){const label=button.textContent;button.innerHTML=referenceNameHTML(definition.key,definition.name)+escapeHTML(label.slice(definition.name.length));if(typeof bindReferencePreview==='function')bindReferencePreview(button,{id:definition.key,name:definition.name,condition:'4.0.2独立新局参考 · 未持有，非本局实物'},{params:{...(definition.kind==='Artifact'?{}:{level:definition.kind==='Trinket'?0:item.level}),...(definition.tier?{tier:definition.tier}:{}),depth:item.depth}});}button.addEventListener('click',()=>showForecastItem(item,definition));const note=document.createElement('p');note.className='muted';note.textContent=`${forecastSources[item.source]} · ${forecastAccess(item.access,true)}`;card.append(button,note);section.append(card);}
    if(!rows.length){const note=document.createElement('p');note.className='muted';note.textContent=kind||query?'没有符合此筛选的装备。':'此层未预测到所支持的静态装备；不代表没有消耗品、机关或其他内容。';section.append(note);}target.append(section);
  }
  if(from>forecastValue.maximum_depth){const note=document.createElement('p');note.textContent='查看起始楼层超过计算范围，请调整起始楼层或重新计算到更深处。';target.append(note);}
}
for(const id of ['forecast-depth','forecast-from']){const select=$('#'+id);for(let depth=1;depth<=24;depth++){const option=document.createElement('option');option.value=String(depth);option.textContent=`第 ${depth} 层`;select.append(option);}select.value=id==='forecast-depth'?'24':'1';}
$('#forecast-read-seed').addEventListener('click',readForecastSeed);$('#forecast-run').addEventListener('click',runForecast);
$('#forecast-cancel').addEventListener('click',()=>stopForecast('已取消计算，旧结果已收起。'));
$('#forecast-hide').addEventListener('click',()=>{$('#forecast-confirm').checked=false;stopForecast('预测已收起；种子输入保留。');$('#forecast-panel').open=false;});
for(const id of ['forecast-seed','forecast-depth'])$('#'+id).addEventListener('input',()=>{forecastSource=null;$('#forecast-confirm').checked=false;$('#forecast-origin').textContent='手填的独立参考情景；未读取或关联当前存档状态。';stopForecast('输入已变化，请重新确认情景后计算。');});
$('#forecast-confirm').addEventListener('change',()=>{if(!$('#forecast-confirm').checked)stopForecast('已取消确认，旧结果已收起。');forecastControls();});
for(const id of ['forecast-from','forecast-kind','forecast-query'])$('#'+id).addEventListener(id==='forecast-query'?'input':'change',renderForecast);
refreshForecastContext();
