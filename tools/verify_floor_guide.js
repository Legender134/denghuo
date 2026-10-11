'use strict';
// DOM/transport controllers only. No browser, native window or game execution.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/floor-guide.js'),'utf8');
const scoutingSource=fs.readFileSync(path.join(__dirname,'../web/scouting.js'),'utf8');
function harness(){
  const nodes=new Map(),writes=[],reads=[];
  function node(tag='div'){return {tagName:tag.toUpperCase(),children:[],listeners:{},open:false,hidden:false,disabled:false,textContent:'',innerHTML:'',
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;this.innerHTML='';this.textContent='';},addEventListener(name,handler){this.listeners[name]=handler;},getContext(){return {fillRect(){},strokeRect(){}};}};}
  const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
  const state={started:1,revision:1,settings_revision:'s1',active_slot:1,run_id:'run1',error:'',stale:false,
    settings:{mode:'save',save_root:'synthetic-only'},data:{depth:4,branch:0,version:922,hero:{level:5}}};
  const context=vm.createContext({console,JSON,String,Number,Object,Map,Set,URLSearchParams,state,$:get,view:'overview',
    document:{createElement:node},snapshotViewOwner:()=>JSON.stringify([state.started,state.settings.save_root,state.active_slot,state.run_id,state.settings.mode]),
    inlineError:(target,text)=>{target.textContent=text;target.hidden=!text;},fmtTime:String,
    post:(url,payload)=>new Promise((resolve,reject)=>writes.push({url,payload,resolve,reject})),
    fetch:url=>new Promise((resolve,reject)=>reads.push({url,resolve,reject})),exampleHTML:block=>`<section>${block.title}</section>`,
    scoutCoordinate:row=>`(${row.x}, ${row.y})`,scoutingCards:()=>{},showScoutedItem:()=>{},showReference:()=>{}});
  const run=code=>vm.runInContext(code,context);run(scoutingSource);
  context.navigate=view=>{context.view=view;run('loadScouting()');};
  run(source);return {context,state,get,writes,reads,run};
}
function catalog(){return {source:{slot:1,depth:4,branch:0,version:922,modified:100,expected:'a'.repeat(64),hero_level:5},supported:true,
  floors:[{depth:4,branch:0,current:true,available:true}],encounters:{note:'常规生成参考，不是本局实例',rows:[{id:'actors.mobs.crab',name:'螃蟹',hp:'15',damage:'1–7',dr:'0–4',condition:'每轮名额',group:'普通轮换'}]}};}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
async function load(h){h.writes.at(-1).resolve(catalog());await settle();}
const deadline=setTimeout(()=>{console.error('FAIL: floor guide verification did not complete');process.exitCode=1;},5000);
(async()=>{
  const h=harness();assert.equal(h.writes.length,1);assert.equal(h.writes[0].payload.action,'catalog');await load(h);
  assert.equal(h.writes.length,1,'automatic guide must never reveal a floor');assert.equal(h.reads.length,0,'collapsed cards must not fetch all numeric details');
  assert.equal(h.get('#floor-hidden-open').disabled,false);assert.equal(h.get('#floor-monsters-count').textContent,'1 种');
  const card=h.get('#floor-monsters-list').children[0];assert.equal(card.tagName,'DETAILS');assert.equal(card.open,false);assert.match(card.children[0].children[1].textContent,/生命 15.*伤害 1–7/);
  card.open=true;card.listeners.toggle();assert.equal(h.reads.length,1);const params=new URL(h.reads[0].url,'http://synthetic').searchParams;
  assert.equal(params.get('hero_level'),'5');assert.equal(params.get('loot_count'),'0');assert.equal(params.get('depth'),'4');
  h.reads[0].resolve({ok:true,json:async()=>({blocks:[{title:'掉落物、数量与概率'}]})});await settle();assert.match(card.children[2].innerHTML,/掉落物、数量与概率/);
  card.open=false;card.listeners.toggle();card.open=true;card.listeners.toggle();assert.equal(h.reads.length,1);
  const reveal=h.run('revealFloorContents()');assert.equal(h.writes.length,2);assert.equal(h.writes[1].payload.reveal,true);assert.equal(h.writes[1].payload.expected,'a'.repeat(64));
  h.writes[1].resolve({depth:4,branch:0,source:{slot:1,floor_modified:100},map:{width:1,height:1,tiles:[1],hero:null},item_count:0,note:'已保存事实',features:[{terrain:16,name:'隐藏门',x:2,y:1,hidden:true}],traps:[{name:'毒镖陷阱',x:2,y:2,visible:false,active:true}],heaps:[],mobs:[]});await reveal;
  assert.equal(h.get('#floor-hidden-content').hidden,false);assert.match(h.get('#floor-hidden-count').textContent,/1 门.*1 未显陷阱/);
  const mapButton=h.get('#floor-hidden-content').children.at(-1);mapButton.listeners.click();
  assert.equal(h.get('#scout-reveal').checked,true);assert.equal(h.get('#scout-result').hidden,false);
  assert.match(h.get('#scout-source').textContent,/槽位 1.*第 4 层/);assert.equal(h.get('#scout-open').disabled,false);
  h.writes.at(-1).resolve(catalog());await settle();assert.equal(h.get('#scout-result').hidden,false,'late catalog must not clear revealed handoff');
  h.context.view='overview';
  h.state.revision++;h.run('refreshFloorGuide()');assert.equal(h.get('#floor-hidden-content').hidden,true);await load(h);
  assert.equal(h.get('#floor-monsters-list').children[0],card,'same-floor save refresh preserves open public monster cards');
  const old=h.run('revealFloorContents()');const pending=h.writes.at(-1);h.state.active_slot=2;h.state.run_id='run2';h.run('refreshFloorGuide()');
  pending.resolve({source:{floor_modified:100},features:[],traps:[],heaps:[],mobs:[]});await old;assert.equal(h.get('#floor-hidden-content').hidden,true);
  const newer=h.writes.at(-1);h.state.error='存档不可读';h.run('refreshFloorGuide()');newer.resolve(catalog());await settle();
  assert.equal(h.get('#floor-monsters-list').children.length,0);assert.equal(h.get('#floor-hidden-open').disabled,true);
  const retry=harness();await load(retry);const retryCard=retry.get('#floor-monsters-list').children[0];retryCard.open=true;retryCard.listeners.toggle();retry.reads[0].reject(new Error('离线'));await settle();
  assert.equal(retryCard.children[3].hidden,false);const retrying=retryCard.children[3].listeners.click();assert.equal(retry.reads.length,2);
  retry.state.data.depth=5;retry.state.revision++;retry.run('refreshFloorGuide()');retry.reads[1].resolve({ok:true,json:async()=>({blocks:[{title:'过期响应'}]})});await retrying;
  assert(!retryCard.children[2].innerHTML.includes('过期响应'));
  console.log(JSON.stringify({public_only_automatic:true,collapsed_lazy_numeric_and_loot:true,same_floor_expansion_preserved:true,explicit_hidden_opt_in:true,save_slot_error_and_late_response_invalidation:true,retry:true}));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>clearTimeout(deadline));
