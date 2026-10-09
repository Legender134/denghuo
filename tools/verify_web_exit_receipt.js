// Exercise the actual source functions: terminal reads never report a forbidden mutation.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/workspace.js'),'utf8');
function extract(name){const start=source.indexOf('async function '+name+'(');assert(start>=0,name);const end=source.indexOf('\n}',start);assert(end>start);return source.slice(start,end+2);}
function setup(exit,latest,{readError=false}={}){
  const controls=new Map(),messages=[],requests=[];
  const context=vm.createContext({setTimeout,Date,Promise,token:'synthetic',state:{exit:latest},webSurfaceId:'synthetic',
    $:id=>{if(!controls.has(id))controls.set(id,{open:false,close(){this.open=false;}});return controls.get(id);},
    freezeWebEditing:frozen=>requests.push({freeze:frozen}),toast:(message,error)=>messages.push({message,error}),
    getJSON:async path=>{requests.push({read:path});if(readError)throw new Error('offline');return {exit:latest};},
    post:async()=>{throw new Error('forbidden terminal mutation');},inlineError(){},currentWebDraft(){throw new Error('terminal capture must not run');}});
  vm.runInContext('let webExitState='+JSON.stringify(exit)+',webExitCompletionWatch=null,webExitHandling=false,webExitBusy=false;',context);
  for(const name of ['watchWebExitCompletion','reportWebExitSurface','handleWebExitState'])vm.runInContext(extract(name),context);
  return {context,messages,requests};
}
(async()=>{
  const backing={id:'own-request',phase:'backing-up'},finished={id:'own-request',phase:'finished',error:'最后备份未完成，原件保留'};
  let fixture=setup(backing,finished);
  await vm.runInContext('reportWebExitSurface()',fixture.context);
  assert.equal(vm.runInContext('webExitState.phase',fixture.context),'finished');assert.equal(fixture.messages.length,1);
  assert.match(fixture.messages[0].message,/最后备份未完成/);
  fixture=setup(null,finished);
  await vm.runInContext('handleWebExitState('+JSON.stringify(backing)+')',fixture.context);
  await vm.runInContext('webExitCompletionWatch',fixture.context);
  assert.equal(vm.runInContext('webExitState.phase',fixture.context),'finished');assert.equal(fixture.requests.filter(r=>r.read).length,1);
  fixture=setup(finished,backing);
  await vm.runInContext('handleWebExitState('+JSON.stringify(backing)+')',fixture.context);
  assert.equal(vm.runInContext('webExitState.phase',fixture.context),'finished');assert.equal(fixture.messages.length,0);
  fixture=setup(null,finished,{readError:true});
  await vm.runInContext('handleWebExitState('+JSON.stringify(backing)+')',fixture.context);
  await vm.runInContext('webExitCompletionWatch',fixture.context);
  assert.equal(vm.runInContext('webExitState.phase',fixture.context),'backing-up');assert.match(fixture.messages[0].message,/结果暂未确认/);
  assert(!fixture.requests.some(r=>r.freeze===false));
  console.log(JSON.stringify({passed:true,cases:4,scope:'actual extracted terminal exit components; real UI acceptance separately recorded'}));
})().catch(error=>{console.error(error);process.exitCode=1;});
