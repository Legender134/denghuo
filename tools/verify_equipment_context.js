'use strict';
// Production functions in a synthetic DOM/transport. No browser or game access.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.join(__dirname,'..'),source=fs.readFileSync(path.join(root,'web/compare.js'),'utf8');
function harness(){
  const nodes=new Map(),pending=[];
  const get=key=>{if(!nodes.has(key))nodes.set(key,{value:'0',checked:false,dataset:{},innerHTML:'',textContent:'',hidden:false,disabled:false,childElementCount:0,children:[],open:false,listeners:{},
    addEventListener(event,fn){this.listeners[event]=fn;},querySelectorAll(){return [];},querySelector(){return {disabled:false};},closest(){return {hidden:false};},replaceChildren(){this.children=[];this.innerHTML='';},focus(){},scrollIntoView(){}});return nodes.get(key);};
  const context=vm.createContext({URLSearchParams,JSON,console,$:get,$$:()=>[],state:{data:null},navigationSerial:0,compareCharacterReference:null,
    document:{addEventListener(){}},window:{addEventListener(){}},calculationStamp:()=>null,fmtTime:String,escapeHTML:String,
    inlineError:(node,text)=>{node.textContent=text;},characterClone:value=>value==null?null:JSON.parse(JSON.stringify(value)),
    originLabel:()=> '保存参考',cleanStoredOrigin:value=>value||{},planSource:()=>({mode:'manual'}),
    openPlanSave:(...args)=>{context.saveArgs=args;},fetch:()=>new Promise(resolve=>pending.push(resolve)),getJSON:async()=>({inputs:[]})});
  const run=code=>vm.runInContext(code,context);
  const character=fs.readFileSync(path.join(root,'web/character.js'),'utf8'),start=character.indexOf('function characterOptionalInteger('),end=character.indexOf('\n}',start);
  run(character.slice(start,end+2));run(source);
  context.catalog=[{id:'items.weapon.melee.sword',name:'单手剑'},{id:'items.weapon.melee.dagger',name:'匕首'}];
  run("compareCatalog=catalog;compareCatalogState='ready';compareCatalogPending=null;refreshComparisonOrigin=()=>{};");
  get('#compare-kind').value='weapon';get('#compare-investment-mode').value='all';
  return {context,run,get};
}
(async()=>{
  const h=harness();
  h.context.plan={id:'1'.repeat(32),kind:'equipment',name:'旧方案',note:'原备注',rules_version:'3.0.0',origin:{mode:'save',slot:2,fields:{level_a:'原等级来源'}},
    params:{strength:14,id_a:'items.weapon.melee.retiredsword',id_b:'items.weapon.melee.sword',level_a:3,level_b:2,tier_a:3,tier_b:3,mastery_a:'0',mastery_b:'0',augment_a:'SPEED',augment_b:'NONE'}};
  const original=JSON.stringify(h.context.plan);
  assert.equal(await h.run("openEquipmentPlan(plan,null,true,'原装备身份不支持')"),true);
  assert.match(h.get('#compare-original-plan').textContent,/旧方案.*3\.0\.0/);
  assert.match(h.get('#compare-original-plan').textContent,/原备注/);
  assert.match(h.get('#compare-original-plan').textContent,/原等级来源/);
  assert.equal(h.get('#compare-level-a').value,'3');assert.equal(h.get('#compare-augment-a').value,'SPEED');
  assert(h.run("compareItems[Number($('#compare-a').value)].unavailable"));
  assert.throws(()=>h.run('readComparisonArgs()'),/替换装备/);
  assert.equal(h.get('#compare-combat-enabled').checked,false); // Legacy plans stay on their original model.
  h.get('#compare-a').value=String(h.run("compareItems.findIndex(item=>item.key==='items.weapon.melee.dagger')"));
  h.get('#compare-a').listeners.change();h.get('#compare-level-a').value='4';
  assert.equal(h.run('readComparisonArgs().id_a'),'items.weapon.melee.dagger');
  h.run('compareResultArgs=canonicalComparisonParams(readComparisonArgs());compareDirty=false;compareError="";');
  h.get('#compare-save').listeners.click();assert.equal(h.context.saveArgs[1],null);assert.equal(h.context.saveArgs[2],'旧方案 · 修正版');
  assert.equal(h.context.saveArgs[0].note,'原备注');assert.equal(JSON.stringify(h.context.plan),original);
  h.get('#compare-combat-enabled').checked=true;h.get('#compare-target-enabled').checked=true;
  h.get('#compare-target-name').value='首领前';h.get('#compare-target-base_accuracy').value='17';h.get('#compare-target-evasion').value='';h.get('#compare-target-dr_min').value='2';h.get('#compare-target-dr_max').value='';
  const first=h.run('canonicalComparisonParams(readComparisonArgs())');assert.equal(first.combat_model,'ordinary-v1');
  assert.equal(first.target_context.evasion,null);assert.equal(first.target_context.dr_max,null);assert.equal(first.target_context.base_accuracy,17);
  h.get('#compare-target-name').value='另一目标';const second=h.run('canonicalComparisonParams(readComparisonArgs())');
  assert.equal(first.target_context.name,'首领前');assert.equal(second.target_context.name,'另一目标');
  // Raw import undo carries both target fields and the repair-only save guard.
  h.run('rememberComparisonImport();compareRepairOriginal=null;');
  h.get('#compare-undo-import').listeners.click();assert.equal(h.run('compareRepairOriginal.id'),h.context.plan.id);
  let release;h.context.waiting=new Promise(resolve=>{release=resolve;});h.run('initializeEquipmentComparison=()=>waiting');
  const opening=h.run("openEquipmentPlan(plan,null,true,'原装备身份不支持')");
  h.get('#compare-level-a').value='19';h.run('compareEditGeneration++');release(true);
  assert.equal(await opening,false);assert.equal(h.get('#compare-level-a').value,'19');
  console.log('equipment context: original placeholder, field/source retention, replacement, copy-only save, named/null target, undo and late-open guard passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
