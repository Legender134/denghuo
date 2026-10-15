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
  const revealed=harness();
  revealed.context.state={started:1,active_slot:1,data:{hero:{strength:10},items:[{key:'items.rings.ringofmight',name:'根骨之戒 +3',location:'背包',level:3,known:false,revealed:true,game_level_known:false,available:true,cursed:false}]}};
  revealed.context.catalog=[{id:'items.rings.ringofmight',name:'根骨之戒'}];
  revealed.run("compareCatalog=catalog;$('#compare-kind').value='ring';renderEquipmentComparison();");
  assert(revealed.run('compareItems[0].owned'));
  assert.equal(Number(revealed.get('#compare-level-a').value),3);
  assert.match(revealed.get('#compare-origin-a').textContent,/主动揭示/);
  assert.match(revealed.get('#compare-a').innerHTML,/主动揭示/);
  assert.equal(revealed.context.state.data.items[0].known,false);
  revealed.context.state.data.items[0].revealed=false;
  revealed.run("compareSignature='';renderEquipmentComparison();");
  assert.equal(revealed.run('compareItems.some(item=>item.owned)'),false);
  const app=fs.readFileSync(path.join(root,'web/app.js'),'utf8'),start=app.indexOf('function showItem(item,'),end=app.indexOf('\nfunction showReference(',start);
  const calls=[],metadata=[];
  const detail=vm.createContext({showDetail:(name,description,location,meta)=>metadata.push(meta),showItemNote:()=>{},visibleCalculationContext:()=>({}),setDetailEntry:()=>{},currentSkillContext:()=>null,loadNumericalDetail:(...args)=>calls.push(args),showRelatedReferences:()=>{},lookupCalculationOptions:()=>({}),comparisonFamily:()=>null});
  vm.runInContext(app.slice(start,end),detail);
  const item={...revealed.context.state.data.items[0],revealed:true,details:[],level_applicable:true};
  detail.showItem(item,{stamp:null});
  assert.equal(calls.length,1);assert.equal(calls[0][1].level,3);assert.equal(calls[0][2],'revealed');
  assert.match(metadata[0],/已主动揭示/);assert.doesNotMatch(metadata[0],/保留未知身份/);
  detail.showItem({...item,revealed:false},{stamp:null});
  assert.equal(calls.length,1);assert.match(metadata[1],/保留未知身份/);
  // Exercise the production unfinished-draft loader with mixed manual/reference cells.
  const recovered=harness(),controls=[];
  const cell=(id,value,manual='',edited='')=>{const input=recovered.get('#'+id);input.id=id;input.value=value;input.dataset={manual,edited};controls.push(input);return {value,checked:false,manual,edited};};
  const form={'compare-kind':cell('compare-kind','weapon'),'compare-strength':cell('compare-strength','14')};
  for(const side of ['a','b'])for(const [key,value] of Object.entries({level:side==='a'?'+':'2',mastery:'0',augment:side==='a'?'SPEED':'DAMAGE',tier:'3',resin:'0',infusion:'1',hardened:'1'})){
    const manual=side==='a'&&['level','augment'].includes(key)?'true':'';
    form['compare-'+key+'-'+side]=cell('compare-'+key+'-'+side,value,manual,manual);
  }
  recovered.context.$$=selector=>selector.startsWith('#equipment-comparison input')?controls:[];
  const references=Object.fromEntries(['a','b'].map(side=>[side,{id:'items.weapon.melee.sword',name:'保存的单手剑 +2',effect_id:null,user_note:null}]));
  recovered.context.draftResponse={draft:{draft_kind:'web-session',draft:{format:2,schema:'denghuo-web-session',comparison:{form,choices:{a:references.a.id,b:references.b.id},references}}}};
  Object.assign(recovered.context,{unfinishedDraftRequest:0,draftRecoveryEditGeneration:0,webEditingFrozen:false,webDirtySummary:()=>[],post:async()=>recovered.context.draftResponse,
    planNameDrafts:new Map(),planNoteDrafts:new Map(),planMetaOriginals:new Map(),verifySettingsRecovery:async()=>{},applySettingsRecovery:()=>{},toast:()=>{},navigate:()=>{recovered.context.navigationSerial++;}});
  const workspace=fs.readFileSync(path.join(root,'web/workspace.js'),'utf8'),loadStart=workspace.indexOf('async function loadUnfinishedDraft('),loadEnd=workspace.indexOf('\n}',loadStart)+2;
  assert(loadStart>=0&&loadEnd>loadStart);recovered.run(workspace.slice(loadStart,loadEnd));
  await recovered.run("loadUnfinishedDraft('a'.repeat(32),'b'.repeat(64))");
  assert.equal(recovered.get('#draft-error').textContent,'');
  for(const [id,expected] of Object.entries(form)){
    assert.equal(recovered.get('#'+id).value,expected.value,id+' raw value');
    assert.equal(recovered.get('#'+id).dataset.manual,expected.manual,id+' manual origin');
    assert.equal(recovered.get('#'+id).dataset.edited,'true',id+' restored input is deliberately held');
  }
  assert.match(recovered.get('#compare-origin-a').textContent,/手填/);
  assert.match(recovered.get('#compare-origin-b').textContent,/保存的装备参考/);
  assert.doesNotMatch(recovered.get('#compare-origin-b').textContent,/存档的已知/);
  assert.equal(recovered.run('compareDirty'),true);assert.equal(recovered.run('compareResultArgs'),null);
  // A newer inventory rebuilds select options; it must not take ownership of restored inputs.
  for(const side of ['a','b']){
    const augment=recovered.get('#compare-augment-'+side);
    Object.defineProperty(augment,'innerHTML',{set(){this.value='NONE';},get(){return '';},configurable:true});
  }
  const newer={started:2,active_slot:2,data:{hero:{strength:19},items:[{key:'items.weapon.melee.sword',name:'新长剑 +7',location:'主武器',level:7,known:true,available:true,cursed:false}]}};
  for(const snapshot of [newer,{...newer,data:null},newer]){
    recovered.context.state=snapshot;recovered.run('renderEquipmentComparison()');
    for(const [id,expected] of Object.entries(form)){
      assert.equal(String(recovered.get('#'+id).value),expected.value,id+' survives snapshot refresh');
      assert.equal(recovered.get('#'+id).dataset.manual,expected.manual,id+' retains provenance');
    }
    assert.equal(recovered.run("compareItems[Number($('#compare-b').value)].reference"),true);
  }
  // Explicitly choosing current equipment still replaces the held conditions.
  recovered.get('#compare-b').value=String(recovered.run('compareItems.findIndex(item=>item.owned)'));
  recovered.get('#compare-b').listeners.change();
  assert.equal(String(recovered.get('#compare-level-b').value),'7');
  assert.equal(recovered.get('#compare-augment-b').value,'NONE');
  assert.equal(recovered.get('#compare-strength').value,'14');
  assert.match(recovered.get('#compare-origin-b').textContent,/已带入已知/);
  recovered.run("compareFixed=true;compareSavedPlan={params:{level_a:2},origin:{fields:{level_a:'旧方案等级'}}};$('#compare-level-a').value='2';refreshCompareChoiceOrigin('a');");
  assert.match(recovered.get('#compare-origin-a').textContent,/手填/,'manual augmentation must not be hidden by an unchanged saved level');
  console.log('equipment context: original placeholder, field/source retention, replacement, copy-only save, named/null target, undo and late-open guard passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
