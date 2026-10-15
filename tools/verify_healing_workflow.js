// Actual handbook code and Python values; isolated DOM, no browser or user saves.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),vm=require('node:vm'),{spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'..'),home=path.join(os.tmpdir(),'denghuo-healing-synthetic-'+process.pid);
const python=process.env.PYTHON||(process.platform==='win32'?'python':'python3');
function element(){return {value:'',textContent:'',className:'',innerHTML:'',dataset:{},open:true,isConnected:true,disabled:false,scrollTop:0,listeners:{},validity:{valid:true},classList:{toggle(){}},
  addEventListener(name,fn){this.listeners[name]=fn;},querySelector(){return null;},querySelectorAll(){return [];},contains(){return false;},setCustomValidity(message){this.validity.valid=!message;},reportValidity(){return this.validity.valid;},focus(){},remove(){},insertAdjacentHTML(position,html){if(html.includes('value-error'))throw new Error(html);}};}
function calculate(params,identity='actors.buffs.healing'){
  const script='import json,sys\nfrom companion.engine import Catalog\nfrom companion.rules import NumericRules\nfrom companion.values import PlayerValues\np=json.load(sys.stdin)\nprint(json.dumps(PlayerValues(NumericRules(Catalog())).detail(sys.argv[1],p),ensure_ascii=False))';
  const result=spawnSync(python,['-B','-c',script,identity],{cwd:root,input:JSON.stringify(params),encoding:'utf8',env:{...process.env,APPDATA:home,LOCALAPPDATA:home,PYTHONIOENCODING:'utf-8'}});
  assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout);
}
const elements=new Map(),get=selector=>{if(!elements.has(selector))elements.set(selector,element());return elements.get(selector);};
let inputs=[];
const state={started:10,modified:20,active_slot:1,revision:3,stale:false,settings:{mode:'save',save_root:'synthetic-root'},
  data:{hero:{hp:20,ht:100,level:5,strength:10},depth:2,buffs:[{kind:'Healing',left:80,percent:.1,flat:2,vial_level:-1,next_heal:10}]}};
const context=vm.createContext({URL,URLSearchParams,Map,Set,Number,String,Math,Promise,JSON,console,state,$:get,$$:()=>inputs,escapeHTML:String,fmtTime:String,
  document:{activeElement:null,body:{},createElement:element},fetch:async url=>{const query=new URLSearchParams(url.split('?')[1]),identity=query.get('id');query.delete('id');const result=calculate(Object.fromEntries(query),identity);return {ok:true,json:async()=>result};}});
let renderedHTML='';
Object.defineProperty(get('#detail-rules'),'innerHTML',{set(html){
  renderedHTML=html;
  inputs=[...html.matchAll(/<input data-value-key="([^"]+)"[^>]*value="([^"]*)"/g)].map(match=>{const input=element();input.dataset.valueKey=match[1];input.value=match[2];elements.set(`[data-value-key="${match[1]}"]`,input);return input;});
  get('#value-calculator').querySelectorAll=()=>inputs;
}});
const run=code=>vm.runInContext(code,context),tick=()=>new Promise(resolve=>setImmediate(resolve)),input=key=>get(`[data-value-key="${key}"]`);
vm.runInContext(fs.readFileSync(path.join(root,'web','rules.js'),'utf8'),context);
const lookup=fs.readFileSync(path.join(root,'web','workspace.js'),'utf8').match(/function lookupCalculationOptions\(context\)\{[\s\S]*?\n\}/)[0];
vm.runInContext(lookup,context);
const buffLabel=fs.readFileSync(path.join(root,'web','app.js'),'utf8').match(/function buffReferenceLabel\(buff,hero\)\{[\s\S]*?\n\}/)[0];
vm.runInContext(buffLabel,context);
(async()=>{
  context.publicBuff={name:'治疗',reference_id:'actors.buffs.healing',left:80,next_heal:10};
  assert(run('buffReferenceLabel(publicBuff,{hp:20,ht:100})').includes('下一次可回 10'));
  assert(run('buffReferenceLabel(publicBuff,{hp:95,ht:100})').includes('下一次可回 5'));
  assert(run('buffReferenceLabel(publicBuff,{hp:100,ht:100})').includes('下一次可回 0'));
  assert(!run("buffReferenceLabel({name:'治疗',reference_id:'actors.buffs.healing',left:80},{hp:20,ht:100})").includes('下一次'));
  assert(run("buffReferenceLabel({name:'治疗',reference_id:'actors.buffs.healing'},{hp:20,ht:100})").includes('条件不完整'));
  assert.equal(run("buffReferenceLabel({name:'中毒',reference_id:'actors.buffs.poison',left:80,next_heal:10},{hp:20,ht:100})"),'中毒');
  context.lookupContext={params:{hp:20,max_hp:100,power:80,healing_percent:10,healing_flat:2,vial:-1},stamp:[10,'synthetic-root','save',1,3,20],field_origins:{power:'剩余治疗池',healing_percent:'当前恢复百分比',healing_flat:'当前固定恢复',vial:'当前来源试管限速'}};
  await run("loadNumericalDetail('actors.buffs.healing',lookupContext.params,'example',{ignoreDrafts:true,capturedContext:true,...lookupCalculationOptions(lookupContext)})");
  assert.equal(input('power').value,'80',renderedHTML);assert.equal(input('healing_percent').value,'10');
  assert(run("numericalDetail.origins.healing_percent").includes('快照记录'));
  assert.equal(run("numericalDetail.result.blocks[0].values.find(row=>row.label==='首次恢复').value"),'10');
  input('healing_percent').value='40';input('healing_percent').listeners.input();
  get('#value-calculator').listeners.submit({preventDefault(){}});await tick();
  assert.equal(run('numericalDetail.context.healing_percent'),40);assert.equal(run('numericalDetail.origins.healing_percent'),'手填');
  for(const [field,value] of [['modified',21],['active_slot',2],['revision',4],['started',11]]){
    const old=state[field];state[field]=value;run('refreshNumericalOrigin()');assert(get('#values-freshness').textContent.includes('已经变化'),field);state[field]=old;
  }
  for(const [field,value] of [['mode','manual'],['save_root','another-synthetic-root']]){
    const old=state.settings[field];state.settings[field]=value;run('refreshNumericalOrigin()');assert(get('#values-freshness').textContent.includes('已经变化'),field);state.settings[field]=old;
  }
  state.revision=4;state.modified=21;state.data.buffs[0]={kind:'Healing',left:30,percent:.2,flat:1,vial_level:3};
  get('#values-use-latest').listeners.click();await tick();
  assert.equal(input('power').value,'30');assert.equal(input('healing_percent').value,'20');assert.equal(input('vial').value,'3');
  assert.equal(run('numericalDetail.source.revision'),4);
  get('#values-undo-import').listeners.click();await tick();
  assert.equal(input('power').value,'80');assert.equal(input('healing_percent').value,'40');
  assert.equal(run('numericalDetail.origins.healing_percent'),'手填');assert.equal(run('numericalDetail.source.revision'),3);
  state.data.buffs=[{kind:'Healing'}];
  get('#values-use-latest').listeners.click();await tick();
  assert.equal(input('power').value,'80');assert.equal(input('healing_percent').value,'40');assert.equal(input('vial').value,'-1');
  run('cancelNumericalDetail()');
  run('numericalFormDrafts.clear();numericalCalculated.clear();numericalDrafts.clear()'); // Begin a separate, untouched captured form.
  await run("loadNumericalDetail('actors.buffs.healing',{hp:20,max_hp:100},'example',{ignoreDrafts:true,capturedContext:true})");
  assert.equal(input('power').value,'');assert.equal(input('healing_percent').value,'');assert.equal(input('healing_flat').value,'');assert.equal(input('vial').value,'');
  assert.equal(run('numericalDetail.calculated'),null);assert(run('numericalDetail.dirty'));
  assert.equal(run('numericalDetail.origins.power'),'未确认 · 请填写');
  assert.equal(run('visibleCalculationContext("actors.buffs.poison").power'),undefined,'Healing fields cannot become a different buff strength');
  state.settings.mode='save';state.data.hero={hp:32,ht:90,level:8,strength:12,build:{state:'known'}};state.data.buffs=[];
  state.data.items=[{kind:'VialOfBlood',known:true,available:true,level_known:true,level:3}];
  const first=()=>run("numericalDetail.result.blocks.flatMap(block=>block.values||[]).find(row=>row.label==='首次恢复').value");
  for(const identity of ['items.potions.potionofhealing','items.potions.elixirs.elixirofhoneyedhealing']){
    run('cancelNumericalDetail()');await run(`loadNumericalDetail('${identity}')`);
    assert.equal(input('vial').value,'3');assert.equal(first(),'6');assert.match(renderedHTML,/凝血试管 \+3（快照/);
  }
  run('cancelNumericalDetail()');await run("loadNumericalDetail('items.potions.potionofhealing')");
  input('vial').value='2';input('vial').listeners.input();get('#value-calculator').listeners.submit({preventDefault(){}});await tick();
  state.data.items[0].level=0;run('refreshNumericalOrigin()');assert.equal(input('vial').value,'2');
  get('#values-use-latest').listeners.click();await tick();assert.equal(input('vial').value,'0');assert.equal(first(),'18');
  get('#values-undo-import').listeners.click();await tick();assert.equal(input('vial').value,'2');assert.equal(run('numericalDetail.origins.vial'),'手填');
  run('cancelNumericalDetail()');
  await run("loadNumericalDetail('items.potions.potionofhealing',{hp:32,max_hp:90,vial:1},'saved',{fixed:true,savedPlan:{id:'fixed-vial',origin:{fields:{vial:'手填固定条件'}}}})");
  state.data.items[0].level=3;run('refreshNumericalOrigin()');assert.equal(input('vial').value,'1');assert.match(renderedHTML,/手填固定条件/);
  run('cancelNumericalDetail()');
  run('numericalFormDrafts.clear();numericalCalculated.clear();numericalDrafts.clear()');
  await run("loadNumericalDetail('items.potions.potionofhealing',{hp:32,max_hp:90},'known',{capturedContext:true,sourceStamp:calculationStamp(),ignoreDrafts:true})");
  assert.equal(input('vial').value,'3','same captured snapshot supplements confirmed vial');
  run('cancelNumericalDetail()');
  await run("loadNumericalDetail('items.potions.potionofhealing',{hp:32,max_hp:90},'known',{capturedContext:true,sourceStamp:{...calculationStamp(),revision:-1},ignoreDrafts:true})");
  assert.equal(run('numericalDetail.context.vial'),undefined,'stale captured parameters do not mix with current vial');assert.match(renderedHTML,/凝血试管 无效果（−1）（示例/);
  state.data.items[0].level_known=false;run('cancelNumericalDetail()');
  await run("loadNumericalDetail('items.potions.potionofhealing',{},'example',{ignoreDrafts:true})");
  assert.equal(run('numericalDetail.context.vial'),undefined);assert.match(renderedHTML,/凝血试管 无效果（−1）（示例/);assert(!renderedHTML.includes('未佩戴'));
  get('#values-use-latest').listeners.click();await tick();assert.match(run('numericalDetail.origins.vial'),/^示例.*未确认/);
  state.settings.mode='manual';state.data.items=[];assert.equal(run("visibleCalculationContext('items.potions.potionofhealing').vial"),undefined);
  for(const [identity,metric,note] of [['actors.buffs.poison','完整毒伤总量','后续续毒'],['actors.buffs.bleeding','预计总流血伤害','平均估计']]){
    run('cancelNumericalDetail()');await run(`loadNumericalDetail('${identity}',{},'example',{ignoreDrafts:true})`);
    assert.match(renderedHTML,new RegExp('<section id="values-answer"[\\s\\S]*?'+metric));assert(renderedHTML.includes(note));
    assert.match(renderedHTML,/（示例 · 请核对）/);input('power').value='4';input('power').listeners.input();
    get('#value-calculator').listeners.submit({preventDefault(){}});await tick();assert.match(renderedHTML,/（手填）/);
  }
  // Leaving an incomplete form keeps its untouched conditions and source with raw edits.
  state.settings.mode='save';state.data.depth=4;state.data.buffs=[];state.revision=7;
  run('cancelNumericalDetail()');await run("loadNumericalDetail('actors.buffs.corrosion',{},'example',{ignoreDrafts:true})");
  assert.equal(input('depth').value,'4');assert.equal(run('numericalDetail.calculated'),null);
  input('power').value='1e';input('power').listeners.input();
  input('remaining_turns').value='4.5';input('remaining_turns').listeners.input();
  const incompleteSource=run('JSON.stringify(numericalDetail.source)');
  run('cancelNumericalDetail()');
  assert.equal(run("numericalCalculated.get('actors.buffs.corrosion').params.depth"),4);
  assert.equal(run("JSON.stringify(numericalCalculated.get('actors.buffs.corrosion').source)"),incompleteSource);
  assert.equal(run("numericalFormDrafts.get('actors.buffs.corrosion').power"),'1e');
  state.data.depth=8;state.revision=8;
  await run("loadNumericalDetail('actors.buffs.corrosion')");
  assert.equal(input('depth').value,'4');assert.equal(input('power').value,'1e');assert.equal(input('remaining_turns').value,'4.5');
  assert.equal(run('JSON.stringify(numericalDetail.source)'),incompleteSource);
  assert.equal(run('numericalDetail.calculated'),null,'remembering conditions must not create a computed answer');
  assert.match(get('#values-freshness').textContent,/条件待补全/);
  assert.match(get('#values-freshness').textContent,/快照已变化.*已带入条件保留/);
  run('cancelNumericalDetail()');await run("loadNumericalDetail('actors.buffs.healing',{},'example',{ignoreDrafts:true})");
  assert.equal(input('max_hp').value,'90');assert.equal(input('healing_percent').value,'');
  input('power').value='  -unfinished  ';input('power').listeners.input();
  const healingSource=run('JSON.stringify(numericalDetail.source)');
  run('cancelNumericalDetail()');state.error='synthetic unavailable snapshot';
  await run("loadNumericalDetail('actors.buffs.healing')");
  assert.equal(input('max_hp').value,'90');assert.equal(input('healing_percent').value,'');
  assert.equal(input('power').value,'  -unfinished  ');assert.equal(run('numericalDetail.calculated'),null);
  assert.equal(run('JSON.stringify(numericalDetail.source)'),healingSource);
  assert.match(get('#values-freshness').textContent,/条件待补全.*当前快照不可用/);
  // Exercise production recovery and collection, not just the first close/reopen render.
  const workspace=fs.readFileSync(path.join(root,'web/workspace.js'),'utf8');
  const extract=(source,name)=>{const start=source.search(new RegExp('(?:async )?function '+name+'\\('));assert(start>=0,name);return source.slice(start,source.indexOf('\n}',start)+2);};
  Object.assign(context,{getJSON:async url=>(await context.fetch(url)).json(),showDetail:title=>{context.restoredTitle=title;run('cancelNumericalDetail()');},
    showDetailContext:text=>{context.detailContext=text;},setDetailEntry:()=>{},showPlanNote:()=>{},toast:()=>{},
    webDirtySummary:()=>['数值试算'],planNoteDrafts:new Map(),planNameDrafts:new Map(),planMetaOriginals:new Map(),
    manualUnsaved:false,compareSessionUnsaved:false,settingsDrafts:new Set(),planDraft:null});
  for(const name of ['compactNumeric','collectWebDraft','restoreNumericSession','openDecisionReference'])run(extract(workspace,name));
  run('cancelNumericalDetail();numericalFormDrafts.clear();numericalCalculated.clear();numericalDrafts.clear()');
  state.error=null;state.data.buffs=[{kind:'Healing',left:41,percent:.25}];state.revision=10;
  await run("loadNumericalDetail('actors.buffs.healing')");
  input('power').value='39';input('power').listeners.input();run('cancelNumericalDetail()');
  const saved=JSON.parse(run('JSON.stringify(collectWebDraft().draft.numeric[0])'));
  assert.equal(saved.raw.healing_flat,'');assert.equal(saved.raw.vial,'');
  // Legacy checkpoints may omit untouched raw blanks; exact params still must not absorb new state.
  delete saved.raw.healing_flat;delete saved.raw.vial;
  state.data.buffs=[{kind:'Healing',left:70,percent:.8,flat:7,vial_level:3}];state.revision=11;
  context.recovered=saved;
  for(let cycle=0;cycle<2;cycle++){
    run('numericalFormDrafts.clear();numericalCalculated.clear();numericalDrafts.clear()');
    await run('restoreNumericSession(recovered)');
    assert.equal(context.restoredTitle,'治疗');
    assert.equal(input('healing_flat').value,'');assert.equal(input('vial').value,'');assert.equal(input('power').value,'39');
    assert.equal(run('numericalDetail.context.healing_flat'),undefined);assert.equal(run('numericalDetail.context.vial'),undefined);
    assert.equal(run('JSON.stringify(numericalDetail.source)'),JSON.stringify(saved.source));
    assert.equal(get('[data-origin-key="power"]').textContent,'手填 · 尚未重新计算');
    run('cancelNumericalDetail()');context.recovered=JSON.parse(run('JSON.stringify(collectWebDraft().draft.numeric[0])'));
    assert.equal(context.recovered.params.healing_flat,undefined);assert.equal(context.recovered.params.vial,undefined);
  }
  // The actual overview entry must preserve an existing same-entry draft and its source.
  run('numericalFormDrafts.clear();numericalCalculated.clear();numericalDrafts.clear()');
  context.ref={entry:'actors.buffs.healing',name:'治疗',params:{max_hp:100,hp:4},stamp:[10,'synthetic-root','save',1,12,20]};
  run('openDecisionReference(ref)');await tick();input('power').value='  1e  ';input('power').listeners.input();run('cancelNumericalDetail()');
  context.ref={...context.ref,params:{max_hp:140,hp:30,power:75,healing_percent:20,healing_flat:5,vial:3},stamp:[10,'synthetic-root','save',1,13,21]};
  run('openDecisionReference(ref)');await tick();
  assert.equal(input('power').value,'  1e  ');assert.equal(input('max_hp').value,'100');assert.match(context.detailContext,/未完成试算/);
  context.recovered=JSON.parse(run('JSON.stringify(collectWebDraft().draft.numeric[0])'));
  assert.equal(context.recovered.raw.power,'  1e  ');assert.equal(context.recovered.source.revision,12);
  run('cancelNumericalDetail();numericalFormDrafts.clear();numericalCalculated.clear();numericalDrafts.clear()');
  await run('restoreNumericSession(recovered)');assert.equal(input('power').value,'  1e  ');assert.equal(input('healing_flat').value,'');
  // Shared character provenance survives close/reopen and a saved session round trip.
  run('cancelNumericalDetail();numericalFormDrafts.clear();numericalCalculated.clear();numericalDrafts.clear()');
  context.characterResult={params:{base_strength:12},strength:{usable:true,effective:12}};
  context.sharedReference={params:context.characterResult.params,source:{mode:'manual'},stamp:saved.source,label:'共享角色条件',signature:JSON.stringify(context.characterResult.params)};
  Object.assign(context,{characterClone:value=>JSON.parse(JSON.stringify(value)),characterReference:()=>JSON.parse(JSON.stringify(context.sharedReference)),numericCharacterLabel:()=> '共享角色条件 · 固定参考'});
  run(extract(fs.readFileSync(path.join(root,'web/character.js'),'utf8'),'applyCharacterToNumeric'));
  await run("loadNumericalDetail('items.rings.ringofforce')");run('applyCharacterToNumeric();cancelNumericalDetail()');
  const shared=JSON.parse(run('JSON.stringify(collectWebDraft().draft.numeric[0])'));
  assert.deepEqual(shared.character_reference,context.sharedReference);
  await run("loadNumericalDetail('items.rings.ringofforce')");
  assert.equal(input('strength').value,'12');assert.equal(run('numericalDetail.origins.strength'),'共享角色条件 · 固定参考');
  run('cancelNumericalDetail();numericalFormDrafts.clear();numericalCalculated.clear();numericalDrafts.clear()');
  context.recovered=shared;await run('restoreNumericSession(recovered)');
  assert.deepEqual(JSON.parse(run('JSON.stringify(numericalDetail.characterReference)')),context.sharedReference);
  assert.equal(get('[data-origin-key="strength"]').textContent,'共享角色条件 · 固定参考');
  input('strength').value='13';input('strength').listeners.input();assert.equal(run('numericalDetail.characterReference'),null);
  console.log('PASS: real handbook values and source stamps; close/reopen and two recovery cycles preserve exact missing conditions; overview reentry retains raw work; shared character provenance survives recovery and only explicit edits replace it.');
})().catch(error=>{console.error(error);process.exitCode=1;});
