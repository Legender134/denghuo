// Actual extracted exit and poll functions; no browser, service, or mirrored implementation.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const workspace=fs.readFileSync(path.join(__dirname,'../web/workspace.js'),'utf8'),app=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
function extract(source,name){const found=new RegExp('^(?:async )?function '+name+'\\(','m').exec(source);assert(found,name);const start=found.index,lineEnd=source.indexOf('\n',start);if(source.slice(start,lineEnd).trimEnd().endsWith('}'))return source.slice(start,lineEnd).trimEnd();const end=source.indexOf('\n}',start);assert(end>start,name);return source.slice(start,end+2);}
const plain=value=>JSON.parse(JSON.stringify(value));
const backing={id:'own-request',phase:'backing-up',participants:[],error:''};
const success={...backing,phase:'finished',backup_result:{ok:true,state:'captured',captured:[{slot:1,id:'a'.repeat(64),saved:123}],error:''}};
const confirming={...backing,phase:'confirming',participants:[{surface_id:'synthetic',ack:null,dirty:false,revision:7}]};
function deferred(){let resolve,reject;return {promise:new Promise((yes,no)=>{resolve=yes;reject=no;}),resolve,reject};}
function setup(exit=null,latest=success,options={}){
  const controls=new Map(),messages=[],requests=[],timers=[];let clock=0;
  const get=id=>{if(!controls.has(id))controls.set(id,{textContent:'',className:'',hidden:false,disabled:false,open:false,dataset:{},children:[],close(){this.open=false;},showModal(){this.open=true;},replaceChildren(){this.children=[];}});return controls.get(id);};
  const captured={revision:7,dirty:!!options.dirty,labels:options.dirty?['局势表单']:[],draft:{manual:{hp:{value:'',checked:false}},numeric:[{raw:{level:'invalid'}}]}};
  const context=vm.createContext({Date:{now:()=>clock},Promise,setTimeout:(callback,delay)=>timers.push({callback,delay}),token:'synthetic',state:{exit:latest},webSurfaceId:'synthetic',
    $:get,freezeWebEditing:frozen=>requests.push({freeze:frozen}),toast:(message,error)=>messages.push({message,error}),inlineError:(node,text)=>node.textContent=text,currentWebDraft:()=>({...captured,revision:options.changed?8:7}),renderExitParticipants(){},
    getJSON:async url=>{requests.push({read:url});if(options.read)return options.read();if(options.readError)throw new Error('offline');return {exit:latest};},
    post:async(url,payload)=>{requests.push({url,payload:plain(payload)});if(options.postError&&payload.action==='save-draft')throw new Error('controlled save failure');if(payload.action==='report')return {exit:options.reported||confirming};if(payload.action==='save-draft'){if(options.changeOnSave)options.changed=true;return {saved:{id:'preserved-copy'}};}if(payload.action==='ack')return {exit:options.acknowledged||backing};throw new Error('forbidden terminal mutation');},
    fetch:async()=>{throw new Error('service stopped');},syncBackupContext(){},renderBackupHealth:()=>{get('#backup-health').textContent='自动备份状态尚未确认。';},render:()=>{get('#connection-banner').textContent='普通运行状态';},renderInventory(){},followPanelRequest:async()=>{},
    polling:false,settingsWriteGeneration:0,view:'overview',lastRender:'',slotsSignature:'',initialPanelPlanHandled:true,initialPanelPlan:null,restoreTarget:null,backupState:null,backupViewKeys:new Map()});
  vm.runInContext('let webExitState='+JSON.stringify(exit)+',webExitCompletionWatch=null,webExitHandling=false,webExitBusy=false,webEditingFrozen=false;',context);
  for(const name of ['updateWebRecoveryStatus','renderWebExitReceipt','watchWebExitCompletion','reportWebExitSurface','handleWebExitState','decideWebExit']){if(!workspace.includes('function '+name+'('))continue;vm.runInContext(extract(workspace,name),context);}
  vm.runInContext(extract(app,'poll'),context);const run=code=>vm.runInContext(code,context);
  async function advance(){assert(timers.length,'termination observer must be scheduled');const timer=timers.shift();clock+=timer.delay;timer.callback();await new Promise(setImmediate);}
  async function settle(){for(let n=0;timers.length&&n<60;n++)await advance();await run('webExitCompletionWatch');}
  return {context,get,messages,requests,timers,captured,run,advance,settle};
}
const cases=[],test=(name,work)=>cases.push({name,work});
test('dirty report exposes durable checkpoint failure in a persistent status',async()=>{
  const options={dirty:true,reported:{id:null,phase:'idle',participants:[{surface_id:'synthetic',dirty:true,recovery_error:'自动保留草稿尚未完成：disk full'}]}};
  const f=setup(null,success,options);await f.run('reportWebExitSurface()');
  assert.match(f.get('#draft-recovery-status').textContent,/自动保留草稿尚未完成/);assert.equal(f.get('#draft-recovery-status').hidden,false);
  options.reported={id:null,phase:'idle',participants:[{surface_id:'synthetic',dirty:true,recovery_saved:true,recovery_error:''}]};
  await f.run('reportWebExitSurface()');assert.equal(f.get('#draft-recovery-status').hidden,true);
});
test('lost dirty report does not claim raw input was persisted',async()=>{
  const f=setup(null,success,{dirty:true});f.context.post=async()=>{throw new Error('report response lost');};
  await f.run('reportWebExitSurface()');assert.match(f.get('#draft-recovery-status').textContent,/尚未确认自动保留/);
  assert.equal(f.get('#draft-recovery-status').hidden,false);assert.equal(f.captured.draft.numeric[0].raw.level,'invalid');
});
test('terminal report reads without posting',async()=>{const failed={...success,error:'最后备份未完成，原件保留'};const f=setup(backing,failed);await f.run('reportWebExitSurface()');assert.equal(f.run('webExitState.phase'),'finished');assert.match(f.messages[0].message,/最后备份未完成/);assert(!f.requests.some(r=>r.payload));});
test('direct backing-up starts read observer',async()=>{const f=setup();await f.run('handleWebExitState('+JSON.stringify(backing)+')');await f.settle();assert.equal(f.run('webExitState.phase'),'finished');assert.equal(f.requests.filter(r=>r.read).length,1);});
test('finished ignores stale backing-up state',async()=>{const f=setup(success,backing);await f.run('handleWebExitState('+JSON.stringify(backing)+')');assert.equal(f.run('webExitState.phase'),'finished');assert.equal(f.messages.length,0);});
test('response loss remains unknown and frozen',async()=>{const f=setup(null,success,{readError:true});await f.run('handleWebExitState('+JSON.stringify(backing)+')');await f.settle();assert.equal(f.run('webExitState.phase'),'backing-up');assert.match(f.messages[0].message,/结果暂未确认/);assert(!f.requests.some(r=>r.freeze===false));});
test('clean ack observes completion and retains receipt after disconnect',async()=>{
  const f=setup();await f.run('handleWebExitState('+JSON.stringify(confirming)+')');
  assert.deepEqual(f.requests.filter(r=>r.payload).map(r=>r.payload.action),['report','ack']);assert.equal(f.requests.find(r=>r.payload?.action==='ack').payload.decision,'clean');
  assert.equal(f.run('webExitHandling'),false);assert.equal(f.timers.length,1);await f.settle();assert.match(f.get('#backup-status').textContent,/最后备份已完成/);
  await f.run('poll()');await f.run('poll()');assert.match(f.get('#connection-banner').textContent,/本次辅助已结束/);assert.match(f.get('#backup-health').textContent,/最后备份已完成/);assert(!f.get('#backup-status').textContent.includes('尚未确认'));assert.equal(f.run('state'),null);
});
for(const transition of ['ack','report'])test('clean '+transition+' already finished',async()=>{
  const reported=transition==='report'?{...success,participants:[{surface_id:'synthetic',ack:'clean'}]}:confirming,f=setup(null,success,{reported,acknowledged:success});
  await f.run('handleWebExitState('+JSON.stringify(confirming)+')');assert.equal(f.run('webExitState.phase'),'finished');assert.match(f.get('#backup-status').textContent,/最后备份已完成/);assert.equal(f.timers.length,0);
});
test('clean report enters backing-up before ack',async()=>{const f=setup(null,success,{reported:{...backing,participants:[{surface_id:'synthetic',ack:'clean'}]}});await f.run('handleWebExitState('+JSON.stringify(confirming)+')');assert.equal(f.timers.length,1);await f.settle();assert.match(f.get('#backup-status').textContent,/最后备份已完成/);assert.equal(f.requests.filter(r=>r.payload?.action==='ack').length,0);});
test('actual poll finishes then disconnects',async()=>{const f=setup();f.context.fetch=async()=>({ok:true,json:async()=>({token:'synthetic',exit:success})});await f.run('poll()');f.context.fetch=async()=>{throw new Error('offline');};await f.run('poll()');assert.match(f.get('#connection-banner').textContent,/本次辅助已结束/);assert.match(f.get('#backup-status').textContent,/最后备份已完成/);});
test('late observer error cannot replace finished poll result',async()=>{
  const pending=deferred(),f=setup(null,success,{read:()=>pending.promise});await f.run('handleWebExitState('+JSON.stringify(backing)+')');await f.advance();
  f.context.fetch=async()=>({ok:true,json:async()=>({token:'synthetic',exit:success})});await f.run('poll()');pending.reject(new Error('late offline'));await new Promise(setImmediate);await f.run('webExitCompletionWatch');
  assert(!f.messages.some(row=>/结果暂未确认/.test(row.message)));assert.match(f.get('#backup-status').textContent,/最后备份已完成/);
});
for(const [name,result,error,expected] of [
  ['captured',success.backup_result,'',/最后备份已完成/],['no-save',{ok:true,state:'no-save',captured:[],error:''},'',/没有游戏存档需要备份/],
  ['paused',{ok:true,state:'paused',captured:[],error:''},'',/已暂停.*未执行/],['failed',{ok:false,state:'failed',captured:[],error:'磁盘写入失败'},'磁盘写入失败',/磁盘写入失败/],
  ['partial',{ok:false,state:'partial',captured:[{slot:1}],error:'槽位 2 未完成'},'',/槽位 2 未完成/],['timeout',{ok:false,state:'timeout',error:'检查超时'},'',/检查超时/],
  ['configuration-error',{ok:false,state:'configuration-error',error:'连接设置尚未修复'},'',/连接设置尚未修复/],['unavailable',{ok:false,state:'unavailable',error:'存档目录暂时不可用'},'',/存档目录暂时不可用/],
  ['missing-result',null,'',/结果尚未确认/],['future-state',{ok:true,state:'unchanged',captured:[],error:''},'',/结果尚未确认/],
  ['empty-capture',{ok:true,state:'captured',captured:[],error:''},'',/结果尚未确认/],['receipt-warning',{...success.backup_result,receipt_error:'退出检查记录无法写入'},'',/退出检查记录无法写入/]
])test('terminal '+name+' survives disconnect',async()=>{const f=setup(),finished={...success,backup_result:result,error};await f.run('handleWebExitState('+JSON.stringify(finished)+')');await f.run('poll()');assert.match(f.get('#backup-status').textContent,expected);assert.match(f.get('#connection-banner').textContent,/本次辅助已结束/);if(name!=='captured'&&name!=='receipt-warning')assert(!f.get('#backup-status').textContent.includes('最后备份已完成'));});
test('partial receipt retains completed slots without hiding failed slots after disconnect',async()=>{
  const completed=[{slot:1,id:'a'.repeat(64)},{slot:3,id:'b'.repeat(64)}],result={ok:false,state:'partial',captured:completed,error:'槽位 2 未完成；本次最后备份重试已结束'},f=setup();
  const finished={...success,backup_result:result,error:result.error};await f.run('handleWebExitState('+JSON.stringify(finished)+')');await f.run('poll()');
  for(const key of ['#connection-banner','#backup-health','#backup-status']){const text=f.get(key).textContent;assert.match(text,/槽位 2 未完成/);assert.match(text,/已完成.*槽位 1（aaaaaaaaaaaa）.*槽位 3（bbbbbbbbbbbb）/);assert.match(f.get(key).className||f.get('#connection-banner').className,/error/);}
});
test('unknown exit disconnect never claims completion',async()=>{const f=setup(null,success,{readError:true});await f.run('handleWebExitState('+JSON.stringify(backing)+')');await f.settle();await f.run('poll()');assert.match(f.get('#backup-status').textContent,/结果尚未确认/);assert(!f.get('#connection-banner').textContent.includes('本次辅助已结束'));});
test('ordinary disconnect keeps generic error',async()=>{const f=setup();await f.run('poll()');assert.match(f.get('#connection-banner').textContent,/服务已停止或连接中断/);assert.match(f.get('#backup-status').textContent,/自动备份状态尚未确认/);});
test('dirty raw draft waits for other windows',async()=>{const dirty={...confirming,participants:[{surface_id:'synthetic',ack:null,dirty:true},{surface_id:'other',ack:null,dirty:true}]},f=setup(null,success,{dirty:true,reported:dirty});await f.run('handleWebExitState('+JSON.stringify(dirty)+')');assert(!f.requests.some(r=>r.payload?.action==='ack'));assert(f.get('#session-exit-dialog').open);assert.equal(f.timers.length,0);assert.deepEqual(f.requests.find(r=>r.payload?.action==='report').payload.draft,f.captured.draft);});
test('explicit saved draft keeps invalid and empty inputs',async()=>{const f=setup(confirming,success,{dirty:true});await f.run("decideWebExit('saved')");assert.deepEqual(f.requests.find(r=>r.payload?.action==='save-draft').payload.draft,f.captured.draft);assert.equal(f.requests.find(r=>r.payload?.action==='ack').payload.decision,'saved');await f.settle();});
test('failed draft save never acknowledges',async()=>{const f=setup(confirming,success,{dirty:true,postError:true});await f.run("decideWebExit('saved')");assert(!f.requests.some(r=>r.payload?.action==='ack'));assert.equal(f.timers.length,0);assert.match(f.get('#session-exit-error').textContent,/controlled save failure/);assert(!f.get('#session-exit-cancel').disabled);});
test('draft edit during save cannot acknowledge older revision',async()=>{const f=setup(confirming,success,{dirty:true,changeOnSave:true});await f.run("decideWebExit('saved')");assert(!f.requests.some(r=>r.payload?.action==='ack'));assert.equal(f.timers.length,0);assert.match(f.get('#session-exit-error').textContent,/草稿已变化/);});
test('cancel keeps editing and does not finalize',async()=>{const f=setup(confirming,success,{acknowledged:{...confirming,phase:'cancelled'}});await f.run("decideWebExit('cancel')");assert.equal(f.run('webExitState.phase'),'cancelled');assert(f.requests.some(r=>r.freeze===false));assert.equal(f.timers.length,0);});
(async()=>{const results=[];for(const item of cases){try{await item.work();results.push({name:item.name,passed:true});}catch(error){results.push({name:item.name,passed:false,error:error.message});}}console.log(JSON.stringify({passed:results.every(row=>row.passed),cases:results.length,results,scope:'actual extracted functions and actual poll; deterministic transport/DOM, no GUI/service'}));if(results.some(row=>!row.passed))process.exitCode=1;})().catch(error=>{console.error(error);process.exitCode=1;});
