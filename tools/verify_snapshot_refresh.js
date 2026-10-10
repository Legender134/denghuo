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
