// Execute the real backup recovery component with isolated DOM/network fixtures.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'web/backups.js'),'utf8');
const html=fs.readFileSync(path.join(root,'web/index.html'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function element(id=''){
  const value={id,value:'',textContent:'',hidden:false,disabled:false,checked:false,open:false,dataset:{},listeners:{},children:[],
    addEventListener(type,fn){this.listeners[type]=fn;},close(){this.open=false;},showModal(){this.open=true;},contains(){return false;},
    replaceChildren(...items){this.children=items;this.innerHTML='';},querySelectorAll(selector){return selector==='[data-recovery]'?this.children:[];}};
  let markup='';Object.defineProperty(value,'innerHTML',{get:()=>markup,set:text=>{markup=text;value.children=[...text.matchAll(/data-recovery="([^"]+)"/g)].map(match=>{const button=element();button.dataset.recovery=match[1];return button;});}});return value;
}
function harness(){
  const controls=new Map(),get=id=>{if(!controls.has(id))controls.set(id,element(id));return controls.get(id);};
  const requests=[],receipts=[],messages=[],refresh=[];
  const context=vm.createContext({Map,Set,URL,URLSearchParams,console,JSON,Date,Math,Number,String,Promise,
    $:get,$$:()=>[],document:{activeElement:null},escapeHTML:value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),fmtTime:String,
    state:{backup_context:'c1',settings_revision:'r1',settings:{save_root:'/save/one'}},
    post:(url,payload)=>new Promise((resolve,reject)=>requests.push({url,payload,resolve,reject})),
    freezeBackupReceipt:value=>Object.freeze(structuredClone(value)),backupFlowTicket:()=>({context:'c1',root:'/save/one',epoch:1}),
    recordBackupReceipt:(...args)=>receipts.push(structuredClone(args)),refreshBackupReceiptScope:async ticket=>refresh.push(ticket),toast:(...args)=>messages.push(args)});
  const run=code=>vm.runInContext(code,context);run(source);run('initializeBackupRecovery()');
  context.row={id:'a'.repeat(32),slot:1,kind:'restore',time:100};
  run("backupState={context:'c1',save_root:'/save/one',recovery:{available:true,pending:[row],blocked_slots:[1],error:''}};backupContext='c1'");
  return {context,get,requests,receipts,messages,refresh,run,open:()=>run('openBackupRecovery(row)'),
    input:(choice,phrase,checked=true)=>{get('#backup-recovery-choice').value=choice;get('#backup-recovery-choice').listeners.change();get('#backup-recovery-text').value=phrase;get('#backup-recovery-text').listeners.input();get('#backup-recovery-confirm').checked=checked;get('#backup-recovery-confirm').listeners.change();},
    submit:()=>get('#backup-recovery-form').listeners.submit({preventDefault(){}})};
}
function preview(choice='continue',expected='1'.repeat(64)){
  const labels={continue:'继续完成回档',cancel:'恢复操作开始前的进度',finish:'只结束已提交的恢复记录'};
  return {context:'c1',save_root:'/save/one',settings_revision:'r1',preview:{id:'a'.repeat(32),slot:1,kind:'restore',before:{empty:true},target:{empty:true},current:{empty:true},
    layout:choice==='finish'?'committed':'gap',journal_state:choice==='finish'?'after':'before',current_changed:choice==='finish',
    copies:[{role:'incoming',file:'.denghuo-stage-1-example',exists:choice!=='finish'},{role:'preserved',file:'.denghuo-before-1-example',exists:true}],
    choices:(choice==='finish'?['finish']:['continue','cancel']).map(key=>({choice:key,label:labels[key],confirm_phrase:`${labels[key]} 槽位 1`})),expected,originals_retained:true,message:'全部副本保留。'}};
}
function completed(choice='continue'){
  return {context:'c1',save_root:'/save/one',settings_revision:'r1',message:'已完成；原件保留。',recovery:{ok:true,id:'a'.repeat(32),slot:1,kind:'restore',choice,originals_retained:true}};
}
async function ready(h,choice='continue'){const opening=h.open();h.requests.at(-1).resolve(preview(choice));await opening;}
(async()=>{
  for(const id of ['backup-recovery','backup-recovery-dialog','backup-recovery-form','backup-recovery-choice','backup-recovery-text','backup-recovery-confirm','backup-recovery-error','backup-recovery-repreview','backup-recovery-submit'])assert(html.includes(`id="${id}"`),id);
  let checks=0;
  const visible=harness();visible.run('renderBackupRecovery()');assert.match(visible.get('#backup-recovery').innerHTML,/未完成/);assert.equal(visible.get('#backup-recovery').children.length,1);
  visible.get('#backup-recovery').children[0].listeners.click();visible.requests[0].resolve(preview('finish'));await tick();
  assert(visible.get('#backup-recovery-dialog').open);assert.match(visible.get('#backup-recovery-description').innerHTML,/当前进度后来发生变化/);assert.match(visible.get('#backup-recovery-description').innerHTML,/不会移动目录或覆盖当前保存/);assert.match(visible.get('#backup-recovery-description').innerHTML,/该路径当前无目录/);checks++;
  visible.run("backupState.recovery={available:false,pending:[],blocked_slots:[1,2,3,4,5,6],error:'索引损坏'};renderBackupRecovery()");assert.match(visible.get('#backup-recovery').innerHTML,/索引损坏/);assert.match(visible.get('#backup-recovery').innerHTML,/原件保留/);assert(visible.get('#backup-recovery-submit').disabled);
  visible.run("backupState.recovery={available:true,pending:[row],blocked_slots:[1]};renderBackupRecovery()");assert.equal(visible.get('#backup-recovery').children.length,1);checks++;
  const normal=harness();await ready(normal);assert(normal.get('#backup-recovery-submit').disabled);normal.input('continue','wrong');assert(normal.get('#backup-recovery-submit').disabled);
  normal.input('continue','继续完成回档 槽位 1');assert(!normal.get('#backup-recovery-submit').disabled);const saving=normal.submit();const request=normal.requests.at(-1);
  assert.equal(request.payload.action,'recovery_execute');assert.equal(request.payload.expected,'1'.repeat(64));assert.equal(request.payload.expected_settings_revision,'r1');assert.equal(request.payload.confirm,'继续完成回档 槽位 1');assert.equal(request.payload.confirmed,true);assert(!('root' in request.payload));
  request.resolve(completed());await saving;assert(!normal.get('#backup-recovery-dialog').open);assert.equal(normal.receipts.length,1);assert.equal(normal.receipts[0][2].results[0].expected,'1'.repeat(64));checks++;
  const conflict=harness();await ready(conflict);conflict.input('cancel','恢复操作开始前的进度 槽位 1');const failing=conflict.submit();conflict.requests.at(-1).reject(Object.assign(new Error('外部副本变化'),{status:409}));await failing;
  assert.equal(conflict.get('#backup-recovery-choice').value,'cancel');assert.equal(conflict.get('#backup-recovery-text').value,'恢复操作开始前的进度 槽位 1');assert(conflict.get('#backup-recovery-confirm').checked);assert(conflict.get('#backup-recovery-submit').disabled);assert.match(conflict.get('#backup-recovery-error').textContent,/草稿保持/);
  const reread=conflict.run('previewBackupRecovery()');conflict.requests.at(-1).resolve(preview('continue','2'.repeat(64)));await reread;assert.equal(conflict.get('#backup-recovery-choice').value,'cancel');assert.equal(conflict.get('#backup-recovery-text').value,'恢复操作开始前的进度 槽位 1');assert(conflict.get('#backup-recovery-confirm').checked);assert(conflict.get('#backup-recovery-submit').disabled);assert.match(conflict.get('#backup-recovery-phrase').textContent,/重新勾选/);
  conflict.get('#backup-recovery-confirm').checked=false;conflict.get('#backup-recovery-confirm').listeners.change();conflict.get('#backup-recovery-confirm').checked=true;conflict.get('#backup-recovery-confirm').listeners.change();assert(!conflict.get('#backup-recovery-submit').disabled);
  const sameRead=conflict.run('previewBackupRecovery()');conflict.requests.at(-1).resolve(preview('continue','2'.repeat(64)));await sameRead;assert(!conflict.get('#backup-recovery-submit').disabled);checks++;
  const committedRead=conflict.run('previewBackupRecovery()');conflict.requests.at(-1).resolve(preview('finish'));await committedRead;assert.equal(conflict.get('#backup-recovery-choice').value,'cancel');assert.equal(conflict.get('#backup-recovery-text').value,'恢复操作开始前的进度 槽位 1');assert.match(conflict.get('#backup-recovery-choice').innerHTML,/原选择现已不可执行/);assert(conflict.get('#backup-recovery-submit').disabled);checks++;
  const edited=harness();await ready(edited);edited.input('continue','继续完成回档 槽位 1');const reading=edited.run('previewBackupRecovery()');edited.input('cancel','new local text');edited.requests.at(-1).resolve(preview());await reading;
  assert.equal(edited.get('#backup-recovery-text').value,'new local text');assert.equal(edited.get('#backup-recovery-choice').value,'cancel');assert(edited.get('#backup-recovery-submit').disabled);assert.match(edited.get('#backup-recovery-error').textContent,/新输入/);checks++;
  const moved=harness();await ready(moved);moved.input('continue','继续完成回档 槽位 1');moved.run("state.settings_revision='r2';renderBackupRecovery()");assert(moved.get('#backup-recovery-submit').disabled);assert.equal(moved.get('#backup-recovery-text').value,'继续完成回档 槽位 1');
  const newRevision=moved.run('previewBackupRecovery()');assert.equal(moved.requests.at(-1).payload.expected_settings_revision,'r2');const revisionPreview=preview();revisionPreview.settings_revision='r2';moved.requests.at(-1).resolve(revisionPreview);await newRevision;assert.equal(moved.get('#backup-recovery-text').value,'继续完成回档 槽位 1');assert(moved.get('#backup-recovery-confirm').checked);assert(moved.get('#backup-recovery-submit').disabled);assert.match(moved.get('#backup-recovery-phrase').textContent,/重新勾选/);
  moved.get('#backup-recovery-confirm').checked=false;moved.get('#backup-recovery-confirm').listeners.change();moved.get('#backup-recovery-confirm').checked=true;moved.get('#backup-recovery-confirm').listeners.change();assert(!moved.get('#backup-recovery-submit').disabled);checks++;
  const late=harness();await ready(late);late.input('continue','继续完成回档 槽位 1');const oldSubmit=late.submit(),oldRequest=late.requests.at(-1);late.get('#close-backup-recovery').listeners.click();await ready(late,'finish');late.input('finish','只结束已提交的恢复记录 槽位 1');oldRequest.resolve(completed());await oldSubmit;
  assert(late.get('#backup-recovery-dialog').open);assert.equal(late.get('#backup-recovery-choice').value,'finish');assert.equal(late.get('#backup-recovery-text').value,'只结束已提交的恢复记录 槽位 1');assert.equal(late.receipts[0][4],true);checks++;
  const finish=harness();await ready(finish,'finish');finish.input('finish','只结束已提交的恢复记录 槽位 1');const finishing=finish.submit();assert.equal(finish.requests.at(-1).payload.choice,'finish');finish.requests.at(-1).resolve(completed('finish'));await finishing;assert.equal(finish.receipts[0][2].results[0].choice,'finish');checks++;
  const flat=harness();const flatOpen=flat.open();flat.requests[0].resolve(preview().preview);await flatOpen;assert.equal(flat.run('backupRecoveryTarget.preview'),null);assert.match(flat.get('#backup-recovery-error').textContent,/无法核对/);checks++;
  const disconnected=harness();const pendingOpen=disconnected.open();disconnected.run("state.backup_context='c2';invalidateBackupRecovery('连接变化，草稿保留')");disconnected.requests[0].resolve(preview());await pendingOpen;assert.equal(disconnected.run('backupRecoveryTarget.preview'),null);assert(disconnected.get('#backup-recovery-submit').disabled);checks++;
  console.log(`backup recovery component: ${checks} focused checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
