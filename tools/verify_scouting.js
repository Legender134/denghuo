'use strict';
// Production DOM/transport handlers under Node; no browser or game access.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/scouting.js'),'utf8');
const application=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
function harness(){
  const nodes=new Map(),writes=[],details=[],calculations=[],fills=[];
  function node(tag='div'){return {tagName:tag.toUpperCase(),value:'',textContent:'',checked:false,disabled:false,hidden:false,children:[],listeners:{},
    append(...values){this.children.push(...values);},replaceChildren(){this.children=[];},addEventListener(event,fn){this.listeners[event]=fn;},
    getContext(){return {fillStyle:'',fillRect(){fills.push(this.fillStyle);},strokeRect(){}};}};}
  const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
  get('#scout-result').hidden=true;
  const context=vm.createContext({console,JSON,Number,String,Object,Map,Set,$:get,document:{createElement:node},
    state:{started:1,settings_revision:'r1',active_slot:1,run_id:'run1',revision:1,error:'',data:{},settings:{mode:'save'}},view:'overview',
    fmtTime:String,inlineError:(target,message)=>{target.textContent=message;target.hidden=!message;},
    post:(url,payload)=>new Promise((resolve,reject)=>writes.push({url,payload,resolve,reject})),
    showDetail:(...args)=>details.push(args),showItemNote:()=>{},setDetailEntry:()=>{},
    loadNumericalDetail:(...args)=>calculations.push(args),visibleCalculationContext:()=>{throw new Error('floor items must not import current hero conditions');}});
  const run=code=>vm.runInContext(code,context);
  run(application.slice(application.indexOf('function showItemState('),application.indexOf('function showDetail(')));
  run(source);
  return {context,run,get,writes,details,calculations,fills};
}
const catalog=()=>({source:{slot:1,depth:4,branch:0,version:922,version_name:'4.0.2',modified:100,expected:'a'.repeat(64)},supported:true,note:'只列已生成楼层',floors:[{depth:3,branch:0,available:true,current:false},{depth:4,branch:0,available:true,current:true},{depth:4,branch:1,available:false,current:false}]});
const item={key:'items.rings.ringofmight',name:'根骨之戒 +3 <保留原文本>',description:'具体说明',location:'上锁宝箱',quantity:1,level:3,level_applicable:true,revealed:true,known:false,game_level_known:false,cursed:true,tier:null,volume:null,available:false,details:['已知诅咒']};
const result=()=>({depth:4,branch:0,source:{...catalog().source,floor_modified:99},item_count:1,note:'存档事实，不是随机掉落',
  map:{width:2,height:2,tiles:[4,16,17,1],hero:3},features:[{x:2,y:1,name:'隐藏门',hidden:true}],
  heaps:[{name:'上锁宝箱',x:1,y:2,seen:false,hidden:true,haunted:false,items:[item]}],
  traps:[{name:'毒镖陷阱',x:1,y:2,active:true,visible:false}],mobs:[]});
async function load(h){const p=h.run('loadScouting()');h.writes.at(-1).resolve(catalog());await p;}
function enable(h){h.get('#scout-reveal').checked=true;h.get('#scout-reveal').listeners.change();}
(async()=>{
  const h=harness();assert.equal(h.writes.length,0);await load(h);
  assert.equal(h.writes.length,1);assert.equal(h.writes[0].payload.action,'catalog');assert.equal(h.get('#scout-reveal').checked,false);assert(h.get('#scout-open').disabled);assert(h.get('#scout-result').hidden);
  await h.run('revealScoutingFloor()');assert.equal(h.writes.length,1);
  enable(h);assert.equal(h.get('#scout-open').disabled,false);
  const opening=h.run('revealScoutingFloor()');const request=h.writes.at(-1);
  assert.equal(request.url,'/api/scouting');assert.equal(request.payload.reveal,true);assert.equal(request.payload.expected,'a'.repeat(64));assert.equal(request.payload.depth,4);assert.equal(h.get('#scout-reveal').disabled,false,'can cancel an in-flight reveal');
  request.resolve(result());await opening;
  assert.equal(h.get('#scout-result').hidden,false);assert.match(h.get('#scout-map-text').textContent,/\?/);assert.match(h.get('#scout-map-text').textContent,/@/);
  assert.match(h.get('#scout-features').children[0].textContent,/\(2, 1\).*隐藏门/);
  const card=h.get('#scout-heaps').children[0],button=card.children[2];assert.equal(button.textContent,item.name+' ×1 · 诅咒');
  button.listeners.click();assert.match(h.details[0][3],/游戏鉴定状态未改变，未加入背包/);
  assert.equal(h.get('#detail-item-state').textContent,'已知诅咒 · 已主动揭示 · 未加入背包');
  assert(!h.get('#detail-item-state').hidden);assert.match(h.details[0][3],/原物品记录：已知诅咒/);
  assert(!h.get('#detail-item-state').textContent.includes('当前记录不可用'),'floor availability means not held, not an unusable inventory record');
  h.context.sword={...item,key:'items.weapon.melee.sword',name:'单手剑 +4',level:4,tier:3,details:['已知诅咒','3 阶 · 力量 10','速度强化','已使用精通药剂']};h.context.floor=result();
  h.run('showScoutedItem(sword,floor)');
  assert.equal(h.get('#detail-item-state').textContent,'3 阶 · 已知诅咒 · 速度强化 · 已使用精通药剂 · 已主动揭示 · 未加入背包');
  assert.match(h.details[1][3],/原物品记录：.*力量 10/,'original captured strength remains available without competing with current trial results');
  const calculation=h.calculations[0];assert.equal(calculation[1].level,3);assert.equal(calculation[1].strength,undefined);assert.equal(calculation[2],'revealed');assert.equal(calculation[3].capturedContext,true);assert.equal(calculation[3].ignoreDrafts,true);assert.equal(calculation[3].sourceStamp,null);assert.match(calculation[3].fieldOrigins.level,/第 4 层/);
  h.get('#scout-reveal').checked=false;h.get('#scout-reveal').listeners.change();assert(h.get('#scout-result').hidden);assert.equal(h.get('#scout-heaps').children.length,0);
  enable(h);const late=h.run('revealScoutingFloor()');h.get('#scout-reveal').checked=false;h.get('#scout-reveal').listeners.change();h.writes.at(-1).resolve(result());await late;assert(h.get('#scout-result').hidden);
  enable(h);const oldFloor=h.run('revealScoutingFloor()');h.get('#scout-floor').value='3:0';h.get('#scout-floor').listeners.change();h.writes.at(-1).resolve(result());await oldFloor;assert(h.get('#scout-result').hidden);assert.equal(h.get('#scout-reveal').checked,false);
  enable(h);const oldConnection=h.run('revealScoutingFloor()');h.context.state.settings_revision='r2';h.run('refreshScoutingContext()');h.writes.at(-1).resolve(result());await oldConnection;assert(h.get('#scout-result').hidden);assert(h.get('#scout-open').disabled);
  const oldCatalog=h.run('loadScouting()'),oldRead=h.writes.at(-1);h.context.state.active_slot=2;h.run('refreshScoutingContext()');oldRead.resolve(catalog());await oldCatalog;assert.equal(h.run('scoutCatalog'),null);
  await load(h);enable(h);const failing=h.run('revealScoutingFloor()');h.writes.at(-1).reject(new Error('存档已变化'));await failing;assert(h.get('#scout-result').hidden);assert.match(h.get('#scout-error').textContent,/已变化/);
  const unsupported=h.run('loadScouting()');h.writes.at(-1).resolve({...catalog(),supported:false});await unsupported;assert(h.get('#scout-reveal').disabled);assert(h.get('#scout-open').disabled);assert.match(h.get('#scout-status').textContent,/版本尚未支持/);
  h.context.state=null;h.run('refreshScoutingContext()');assert(h.get('#scout-result').hidden);assert(h.get('#scout-open').disabled);
  const terrain=harness(),map=result();map.map={width:9,height:1,tiles:[1,13,25,27,35,39,4,29,255],hero:null};
  terrain.context.testResult=map;terrain.run('renderScouting(testResult)');
  assert.equal(terrain.get('#scout-map-text').textContent,'  1 .XXXXX#~U');
  assert(terrain.fills.slice(1,6).every(color=>color!==terrain.fills[0]));
  assert.notEqual(terrain.fills[8],terrain.fills[0]);
  // The public overview must distinguish obstacles too; it must not silently
  // paint unsupported terrain as ordinary floor or expose secret identities.
  const overview=harness(),app=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
  overview.run(app.slice(app.indexOf('function renderMapText('),app.indexOf('function itemSnapshotReference(')));
  overview.context.testMap={width:10,height:1,tiles:[1,13,25,27,35,39,4,29,255,-1],hero:null};
  overview.run('renderMap(testMap)');
  assert(overview.fills.slice(2,7).every(color=>color!==overview.fills[1]));
  assert.notEqual(overview.fills[9],overview.fills[1]);
  assert.equal(overview.get('#map-coordinate-list').children.length,9);
  assert.match(overview.get('#map-coordinate-list').children[8].textContent,/未知地形.*255.*通行情况未确认/);
  overview.context.testMap={width:4,height:1,tiles:[16,17,38,14],hero:3};
  overview.run('renderMap(testMap)');
  const labels=overview.get('#map-coordinate-list').children.map(row=>row.textContent).join('\n');
  assert.match(labels,/墙壁/);assert.match(labels,/锁住的门/);assert.doesNotMatch(labels,/隐藏门|陷阱/);
  map.mobs=[{name:'螃蟹',x:2,y:1,hp:15,ht:15,items:[],reference:{id:'actors.mobs.crab'}}];terrain.run('renderScouting(testResult)');
  const mob=terrain.get('#scout-mobs').children[0];assert.equal(mob.tagName,'DETAILS');assert.equal(mob.children[0].tagName,'SUMMARY');
  terrain.context.testCatalog=catalog();terrain.run('renderScoutingCatalog(testCatalog)');assert.match(terrain.get('#scout-source').textContent,/槽位 1.*第 4 层.*4.0.2/);
  console.log('PASS: saved-floor opt-in, exact request context, coordinates and text-only labels, captured item values, cancellation, floor/slot/revision races, failure, unsupported version and disconnect');
})().catch(error=>{console.error(error);process.exitCode=1;});
