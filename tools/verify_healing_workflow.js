// Actual handbook code and Python values; isolated DOM, no browser or user saves.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),vm=require('node:vm'),{spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'..'),home=path.join(os.tmpdir(),'denghuo-healing-synthetic-'+process.pid);
const python=process.env.PYTHON||(process.platform==='win32'?'python':'python3');
function element(){return {value:'',textContent:'',className:'',innerHTML:'',dataset:{},open:true,isConnected:true,disabled:false,scrollTop:0,listeners:{},validity:{valid:true},classList:{toggle(){}},
  addEventListener(name,fn){this.listeners[name]=fn;},querySelector(){return null;},querySelectorAll(){return [];},contains(){return false;},setCustomValidity(message){this.validity.valid=!message;},reportValidity(){return this.validity.valid;},focus(){},remove(){},insertAdjacentHTML(){}};}
function calculate(params){
  const script='import json,sys\nfrom companion.engine import Catalog\nfrom companion.rules import NumericRules\nfrom companion.values import PlayerValues\np=json.load(sys.stdin)\nprint(json.dumps(PlayerValues(NumericRules(Catalog())).detail("actors.buffs.healing",p),ensure_ascii=False))';
  const result=spawnSync(python,['-B','-c',script],{cwd:root,input:JSON.stringify(params),encoding:'utf8',env:{...process.env,APPDATA:home,LOCALAPPDATA:home,PYTHONIOENCODING:'utf-8'}});
  assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout);
}
const elements=new Map(),get=selector=>{if(!elements.has(selector))elements.set(selector,element());return elements.get(selector);};
let inputs=[];
const state={started:10,modified:20,active_slot:1,revision:3,stale:false,settings:{mode:'save',save_root:'synthetic-root'},
  data:{hero:{hp:20,ht:100,level:5,strength:10},depth:2,buffs:[{kind:'Healing',left:80,percent:.1,flat:2,vial_level:-1,next_heal:10}]}};
const context=vm.createContext({URL,URLSearchParams,Map,Set,Number,String,Math,Promise,JSON,console,state,$:get,$$:()=>inputs,escapeHTML:String,fmtTime:String,
  document:{activeElement:null,body:{},createElement:element},fetch:async url=>{const query=new URLSearchParams(url.split('?')[1]);query.delete('id');const result=calculate(Object.fromEntries(query));return {ok:true,json:async()=>result};}});
Object.defineProperty(get('#detail-rules'),'innerHTML',{set(html){
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
  assert.equal(input('power').value,'80');assert.equal(input('healing_percent').value,'10');
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
  await run("loadNumericalDetail('actors.buffs.healing',{hp:20,max_hp:100},'example',{ignoreDrafts:true,capturedContext:true})");
  assert.equal(input('power').value,'');assert.equal(input('healing_percent').value,'');assert.equal(input('healing_flat').value,'');assert.equal(input('vial').value,'');
  assert.equal(run('numericalDetail.calculated'),null);assert(run('numericalDetail.dirty'));
  assert.equal(run('numericalDetail.origins.power'),'未确认 · 请填写');
  assert.equal(run('visibleCalculationContext("actors.buffs.poison").power'),undefined,'Healing fields cannot become a different buff strength');
  console.log('PASS: real Healing handbook values; exact saved inputs and origins; all six stamp changes; explicit manual override; latest import and undo; missing latest preserves manual conditions; presence-only fields stay blank and uncalculated.');
})().catch(error=>{console.error(error);process.exitCode=1;});
