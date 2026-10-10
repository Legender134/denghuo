// Actual extracted exit and poll functions; no browser, service, or mirrored implementation.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const workspace=fs.readFileSync(path.join(__dirname,'../web/workspace.js'),'utf8'),app=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const backups=fs.readFileSync(path.join(__dirname,'../web/backups.js'),'utf8');
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
test('slow backup history cannot block status polling or the exit receipt',async()=>{
  const pending=deferred(),f=setup();let reads=0,reports=0;
  Object.assign(f.context,{view:'backups',backupLoading:false,healthName:()=> '最近保存已备份',renderBackups(){},reportWebExitSurface:async()=>{reports++;},
    fetch:async url=>{if(url.startsWith('/api/backups?'))return pending.promise;reads++;return {ok:true,json:async()=>({token:'synthetic',backup_context:'bound',exit:reads===1?{phase:'idle'}:success})};}});
  vm.runInContext(extract(backups,'loadBackups'),f.context);
  const first=f.run('poll()');await new Promise(setImmediate);
  assert.equal(f.run('polling'),false,'disk-bound backup history must not own the status poll');
  assert.equal(reports,1);await f.run('poll()');
  assert.equal(reads,2);assert.match(f.get('#backup-status').textContent,/最后备份已完成/);
  pending.resolve({ok:true,json:async()=>({context:'bound',save_root:'/save',enabled:true,health:'protected',error:'',notice:'',storage_bytes:0,storage_limit:1,history:[],slots:[]})});
  await new Promise(setImmediate);await first;
  assert.equal(f.run('backupLoading'),false);assert.match(f.get('#backup-status').textContent,/最后备份已完成/,'a late history read must not replace the final receipt');
});
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
function originalListHarness(rows){
  const elements=new Map(),posts=[],messages=[],prompts=[],links=[],downloads=[];let allow=false,fail=false;
  function node(){return {children:[],listeners:{},checked:false,disabled:false,textContent:'',innerHTML:'',className:'',append(...items){this.children.push(...items);},replaceChildren(){this.children=[];},addEventListener(name,fn){this.listeners[name]=fn;},click(){links.push({href:this.href,download:this.download});}};}
  const get=id=>{if(!elements.has(id))elements.set(id,node());return elements.get(id);};
  const context=vm.createContext({$:get,token:'synthetic-token',document:{createElement:()=>node()},window:{confirm:text=>{prompts.push(text);return allow;}},
    escapeHTML:String,fmtTime:String,inlineError:(target,text)=>{target.textContent=text;},toast:text=>messages.push(text),setTimeout:fn=>fn(),
    URL:{createObjectURL:blob=>{assert.equal(blob,'byte-exact-blob');return 'blob:synthetic';},revokeObjectURL(){}},
    post:async(url,payload)=>{posts.push(plain(payload));if(payload.action==='draft-list')return {drafts:rows,archived_count:rows.filter(row=>row.state==='archived').length};if(fail)throw new Error('synthetic preservation failure; original retained');return {};},
    fetch:async(url,options)=>{downloads.push({url,...options});return {ok:true,blob:async()=> 'byte-exact-blob'};},loadUnfinishedDraft:id=>messages.push('load:'+id)});
  vm.runInContext('let exitDraftListRequest=0;',context);
  for(const name of ['loadExitDrafts','downloadRecoveryOriginal'])vm.runInContext(extract(workspace,name),context);
  return {context,get,posts,messages,prompts,links,downloads,run:code=>vm.runInContext(code,context),confirm:value=>{allow=value;},fail:value=>{fail=value;}};
}
const damagedOriginal={id:'a'.repeat(32)+'.pending',label:'interrupted',state:'active',saved:0,error:'incompatible',raw_preservable:true,bytes:15,path:'synthetic/exit-recovery/a.json.pending',sha256:'b'.repeat(64),state_revision:'b'.repeat(64)};
const archivedOriginal={id:'raw-'+'c'.repeat(32),label:'preserved original',state:'archived',saved:1,raw_original:true,bytes:15,path:'synthetic/exit-recovery-preserved/c.raw',source_name:'a'.repeat(32)+'.json.pending',sha256:'b'.repeat(64),state_revision:'b'.repeat(64)};
test('damaged original has explicit byte-bound confirmation and never a form load',async()=>{
  const h=originalListHarness([damagedOriginal]);await h.run('loadExitDrafts()');
  const row=h.get('#session-drafts').children[0],buttons=row.children[0].children;
  assert.equal(buttons.length,1);assert.equal(buttons[0].textContent,'保留原始文件并归档');
  assert(row.innerHTML.includes(damagedOriginal.path));assert(row.innerHTML.includes(damagedOriginal.sha256));assert(row.innerHTML.includes('15 字节'));
  await buttons[0].listeners.click();assert.equal(h.posts.filter(row=>row.action==='draft-preserve-raw').length,0);
  h.confirm(true);await buttons[0].listeners.click();
  assert.deepEqual(h.posts.find(row=>row.action==='draft-preserve-raw'),{action:'draft-preserve-raw',id:damagedOriginal.id,expected_revision:damagedOriginal.state_revision,confirmed:true});
  assert(h.prompts.every(text=>text.includes(damagedOriginal.path)&&text.includes(damagedOriginal.sha256)&&text.includes('15 字节')));
  assert(!h.messages.some(text=>text.startsWith('load:')));assert(h.messages.some(text=>text.includes('独立保留并核验')));
});
test('unreadable original has no action and failed preservation retains truthful error',async()=>{
  const unreadable={...damagedOriginal,raw_preservable:false};delete unreadable.state_revision;
  const denied=originalListHarness([unreadable]);await denied.run('loadExitDrafts()');assert.equal(denied.get('#session-drafts').children[0].children.length,0);
  const h=originalListHarness([damagedOriginal]);h.confirm(true);h.fail(true);await h.run('loadExitDrafts()');
  await h.get('#session-drafts').children[0].children[0].children[0].listeners.click();
  assert.match(h.get('#draft-error').textContent,/synthetic preservation failure/);assert.equal(h.messages.length,0);
});
test('archived original only offers authenticated byte revision download',async()=>{
  const h=originalListHarness([archivedOriginal]);h.get('#draft-include-archived').checked=true;await h.run('loadExitDrafts()');
  const buttons=h.get('#session-drafts').children[0].children[0].children;assert.equal(buttons.length,1);assert.equal(buttons[0].textContent,'获取原始文件');
  await buttons[0].listeners.click();assert.equal(h.downloads.length,1);
  assert.equal(h.downloads[0].headers['X-Companion-Token'],'synthetic-token');
  assert.deepEqual(JSON.parse(h.downloads[0].body),{action:'draft-original-download',id:archivedOriginal.id,expected_revision:archivedOriginal.state_revision});
  assert.equal(h.links[0].download,archivedOriginal.source_name);assert(!h.posts.some(row=>row.action==='draft-state'||row.action==='draft-load'));
  h.context.fetch=async()=>({ok:false,json:async()=>({error:'stored bytes changed'})});await buttons[0].listeners.click();
  assert.match(h.get('#draft-error').textContent,/stored bytes changed/);assert.equal(h.links.length,1);
});
test('valid draft keeps existing load and archive actions',async()=>{
  const h=originalListHarness([{id:'d'.repeat(32),state:'active',saved:1,label:'valid',state_revision:'e'.repeat(64)}]);await h.run('loadExitDrafts()');
  const buttons=h.get('#session-drafts').children[0].children[0].children;assert.equal(buttons.length,2);
  await buttons[0].listeners.click();assert(h.messages.includes('load:'+'d'.repeat(32)));
  await buttons[1].listeners.click();assert(h.posts.some(row=>row.action==='draft-state'&&row.state==='archived'));
});
(async()=>{const results=[];for(const item of cases){try{await item.work();results.push({name:item.name,passed:true});}catch(error){results.push({name:item.name,passed:false,error:error.message});}}console.log(JSON.stringify({passed:results.every(row=>row.passed),cases:results.length,results,scope:'actual extracted functions and actual poll; deterministic transport/DOM, no GUI/service'}));if(results.some(row=>!row.passed))process.exitCode=1;})().catch(error=>{console.error(error);process.exitCode=1;});
