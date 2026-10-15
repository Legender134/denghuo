// Production component logic in an isolated synthetic DOM; no browser or GUI.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const document={body:{},activeElement:null};document.activeElement=document.body;
function node(){return {dataset:{},children:[],open:false,isConnected:true,textContent:'',
  focus(){document.activeElement=this;},replaceChildren(...children){this.children=children;},append(child){this.children.push(child);}};}
document.createElement=()=>node();
function list(kind){
  const target=node();let html='';
  Object.defineProperty(target,'innerHTML',{get:()=>html,set:value=>{
    html=value;for(const old of target.children){old.isConnected=false;if(old.details){old.details.isConnected=false;old.summary.isConnected=false;}if(document.activeElement===old||document.activeElement===old.summary)document.activeElement=document.body;}
    target.children=[];
    if(kind==='items')for(const _ of value.matchAll(/<button\b/g))target.children.push(node());
    if(kind==='advice')for(const match of value.matchAll(/<article\b[^>]*data-tip-id="([^"]*)"/g)){
      const article=node();article.dataset.tipId=match[1];article.details=node();article.summary=node();article.querySelector=()=>article.details;article.details.querySelector=()=>article.summary;target.children.push(article);
    }
  }});
  target.querySelector=()=>null;
  target.querySelectorAll=selector=>selector===(kind==='items'?'button':'article')?target.children:[];
  return target;
}
const nodes={'#advice-list':list('advice'),'#map-coordinate-list':node(),'#map-summary':node(),'#map-coordinates':node()};
let opened=null;
const context=vm.createContext({document,$:id=>nodes[id],JSON,Map,Array,String,escapeHTML:String,
  state:{started:1,settings:{save_root:'/synthetic',mode:'save'},active_slot:1,run_id:'run-a'},
  showItem:(item,reference)=>{opened={item,reference};}});
vm.runInContext(source.slice(source.indexOf('function snapshotViewOwner('),source.indexOf('function render(){')),context);
vm.runInContext(source.slice(source.indexOf('function renderMapText('),source.indexOf('function renderMap(map){')),context);
const call=(name,...args)=>{context.args=args;return vm.runInContext(`${name}(...args)`,context);};
const water={entry:'items.waterskin',healing_timing:'instant',values:[
  {label:'首次恢复',value:'80',unit:'HP'},{label:'最终实际恢复',value:'80',unit:'HP'},
  {label:'实际新增屏障',value:'0',unit:'点'}]};
assert.equal(call('overviewResourceSummary',water),'本次使用 · 即时恢复 80 HP');
const gradual=structuredClone(water);gradual.healing_timing='gradual';gradual.values[0].value='19';
assert.equal(call('overviewResourceSummary',gradual),'本次使用 · 首次恢复 19 HP · 逐回合合计 80 HP');
assert.match(call('overviewResourceSummary',{...water,calculation_missing:'露珠量未知'}),/露珠量未知/);
assert(!call('overviewResourceSummary',{...water,restriction:'不能行动'}).includes('80'));
assert.match(call('overviewResourceAssumption',gradual),/不再受伤.*不含已有治疗.*不能直接相加/);
assert.equal(call('overviewResourceAssumption',water),'不含已有治疗。');
assert.equal(call('overviewResourceAssumption',{...water,calculation_missing:'量未知'}),'');
const costedWater={...water,values:[...water.values,{label:'本次消耗露珠',value:'13',unit:'滴'},{label:'饮用后剩余露珠',value:'1',unit:'滴'}]};
assert.match(call('overviewResourceSummary',costedWater),/消耗 13 滴，剩 1 滴/);
assert(!call('overviewResourceSummary',{...costedWater,calculation_missing:'露珠量未知'}).includes('消耗 13'));
const emptyWater={...water,values:[{label:'本次消耗露珠',value:'0'},{label:'饮用后剩余露珠',value:'0'}]};
assert.equal(call('overviewResourceSummary',emptyWater),'水袋已空');assert.equal(call('overviewResourceAssumption',emptyWater),'');
const repeatHealing={entry:'items.potions.potionofhealing',comparison:{},values:[
  {label:'等待当前治疗 · 首次实际恢复',value:'1',unit:'HP'},
  {label:'再次喝已知治疗药剂 · 首次实际恢复',value:'25',unit:'HP'},
  {label:'再次喝药的额外实际恢复',value:'0',unit:'HP'}]};
assert.equal(call('overviewResourceSummary',repeatHealing),'再喝一瓶 · 首次恢复 1 → 25 HP · 最终额外恢复 0 HP');
assert(!call('overviewResourceSummary',{...repeatHealing,restriction:'当前状态限制主动行动'}).includes('25'));
assert.match(call('overviewResourceAssumption',repeatHealing),/不再受伤/);
for(const [entry,effect,limit] of [
  ['items.potions.exotic.potionofshielding','逐渐衰减','不恢复生命'],
  ['items.potions.potionofinvisibility','暂时隐形','攻击和施法会解除隐形'],
  ['items.scrolls.scrollofteleportation','本层另一处','落点不能指定'],
  ['items.stones.stoneofblink','定向转移','距离与障碍'],
]){
  const option={entry,values:[],purpose:'核对资源'};
  assert(call('overviewResourceSummary',option).includes(effect));
  assert(call('overviewResourceAssumption',option).includes(limit));
  for(const blocked of [{restriction:'不能行动'},{calculation_missing:'条件未确认'}]){
    assert(!call('overviewResourceSummary',{...option,...blocked}).includes(effect));
    assert.equal(call('overviewResourceAssumption',{...option,...blocked}),'');
  }
}
const food={entry:'items.food.food',values:[{label:'恢复饱食',value:'300',unit:'点'},{label:'进食耗时',value:'3',unit:'回合'}]};
for(const [hunger,cursed,expected] of [[false,false,300],[true,false,100],[false,true,201],[true,true,67]]){
  const option=structuredClone(food);
  if(hunger)option.values.push({label:'饥饿游戏基础饱食恢复',value:100,unit:'点'});
  if(cursed)option.values.push({label:'已知诅咒丰饶之角下的参考恢复',value:expected,unit:'点'});
  assert.equal(call('overviewResourceSummary',option),`每份参考饱食 ${expected} 点 · 基础进食耗时 3 回合`);
  const conditions=call('overviewResourceAssumption',option);
  assert.equal(conditions.includes('饥饿游戏'),hunger);assert.equal(conditions.includes('已知诅咒丰饶之角'),cursed);
  assert(conditions.includes('非即时回血'));
}
assert(!call('overviewResourceSummary',{...food,calculation_missing:'诅咒状态未确认'}).includes('300'));
context.shortTime=()=> '12:34';
assert.match(call('overviewSourceWarning',{settings:{mode:'save'},stale:true,modified:100}),/旧快照.*12:34.*核对游戏/);
assert.equal(call('overviewSourceWarning',{settings:{mode:'save'},stale:false}),'');
assert.match(call('overviewSourceWarning',{settings:{mode:'manual'}}),/手填.*不会自动跟随/);
assert.match(call('overviewSourceWarning',{error:'文件不可读'}),/读取受阻.*文件不可读/);
assert.match(call('overviewSourceWarning',null),/连接已中断/);
const tip={id:'burning',severity:'warning',title:'燃烧',body:'核对安全路线',basis:'已保存状态'};
call('renderAdvice',[tip]);const advice=nodes['#advice-list'].children[0];advice.details.open=true;advice.summary.focus();
call('renderAdvice',[{...tip}]);assert.equal(nodes['#advice-list'].children[0],advice);assert(advice.details.open);assert.equal(document.activeElement,advice.summary);
call('renderAdvice',[{...tip,body:'新保存的状态仍有风险'}]);const changed=nodes['#advice-list'].children[0];assert.notEqual(changed,advice);assert(changed.details.open);assert.equal(document.activeElement,changed.summary);
context.state.run_id='run-b';call('renderAdvice',[tip]);assert(!nodes['#advice-list'].children[0].details.open);assert.equal(document.activeElement,document.body);

const items=list('items'),a={key:'sword',name:'剑',location:'背包',user_note:null},b={key:'dagger',name:'匕首',location:'背包',user_note:null};
const markup=rows=>rows.map(row=>`<button>${row.name}</button>`).join('');
call('renderItemButtons',items,[a,b],markup([a,b]),{revision:1});const button=items.children[1];button.focus();
const latest=[{...a},{...b}];call('renderItemButtons',items,latest,markup(latest),{revision:2});assert.equal(items.children[1],button);assert.equal(document.activeElement,button);
button.onclick();assert.equal(opened.item,latest[1]);assert.equal(opened.reference.revision,2,'unchanged nodes use the latest snapshot');
call('renderItemButtons',items,[b,a],markup([b,a]),{revision:3});assert.equal(document.activeElement,items.children[0]);assert(!button.isConnected);
call('renderItemButtons',items,[b,b],markup([b,b]),{revision:4});assert.equal(document.activeElement,document.body,'ambiguous identities must not select an arbitrary replacement');
items.children[0].focus();context.state.run_id='run-c';call('renderItemButtons',items,[b,b],markup([b,b]),{revision:5});assert.equal(document.activeElement,document.body,'focus is not transferred to a different run');

const map={width:5,height:1,tiles:[1,39,29,30,-1],hero:0,caption:'合成快照'};
call('renderMapText',map);assert.match(nodes['#map-coordinate-list'].children[1].textContent,/不可通行/);
assert.match(nodes['#map-coordinate-list'].children[2].textContent,/水地/);assert.match(nodes['#map-coordinate-list'].children[3].textContent,/犁草/);
assert.match(nodes['#map-summary'].textContent,/水地 \(3, 1\)/);assert(!nodes['#map-summary'].textContent.includes('(2, 1)'));
assert.equal(nodes['#map-coordinate-list'].children.length,4,'unknown map cells remain hidden');
const firstCell=nodes['#map-coordinate-list'].children[0];call('renderMapText',structuredClone(map));assert.equal(nodes['#map-coordinate-list'].children[0],firstCell);
call('renderMapText',null);assert.equal(nodes['#map-coordinate-list'].children.length,0);assert(nodes['#map-coordinates'].hidden);
console.log(JSON.stringify({reading_state:true,same_run_focus:true,new_run_and_ambiguous_focus:true,
  latest_item_reference:true,terrain_water_semantics:true,unchanged_map_nodes:true,scope:'synthetic DOM/VM only'}));
