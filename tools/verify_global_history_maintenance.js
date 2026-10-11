// Production handlers in a synthetic DOM/VM: no browser, GUI, game, or user files.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..'),html=fs.readFileSync(path.join(root,'web/index.html'),'utf8');
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
assert.equal(new Set(ids).size,ids.length,'HTML IDs must remain unique');
function node(id=''){
  const value={id,value:'',textContent:'',dataset:{},listeners:{},children:[],disabled:false,checked:false,open:false,hidden:false,
    addEventListener(type,fn){this.listeners[type]=fn;},showModal(){this.open=true;},close(){this.open=false;},
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;this._html='';},
    contains(child){return flatten(this).includes(child);},querySelectorAll(selector){return selector==='button'?flatten(this).filter(child=>child.tag==='button'):[];},
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;},click(){return this.listeners.click?.({target:this});}};
  Object.defineProperty(value,'innerHTML',{configurable:true,get(){return this._html||'';},set(text){
    this._html=text;this.children=[...text.matchAll(/<(input|button|option)\b([^>]*)>/g)].map(match=>{
      const child=node();child.tag=match[1];const attrs=match[2];
      for(const attr of attrs.matchAll(/\b([\w-]+)="([^"]*)"/g)){if(attr[1].startsWith('data-'))child.dataset[attr[1].slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase())]=attr[2];else child[attr[1]]=attr[2];}
      child.disabled=/\bdisabled(?:\s|$)/.test(attrs);return child;
    });
  }});return value;
}
const flatten=value=>[value,...value.children.flatMap(flatten)],plain=value=>JSON.parse(JSON.stringify(value));
function harness(){
  const nodes=new Map(ids.map(id=>[id,node(id)])),reads=[],writes=[],downloads=[],navigations=[];
  const document={activeElement:null,createElement:()=>{const created=node();created.click=function(){downloads.push(this.download);};return created;}};
  const attachFocus=value=>{value.focus=()=>{document.activeElement=value;};value.children.forEach(attachFocus);};
  for(const value of nodes.values()){
    const descriptor=Object.getOwnPropertyDescriptor(value,'innerHTML');
    Object.defineProperty(value,'innerHTML',{...descriptor,set(text){if(this.contains(document.activeElement))document.activeElement=null;descriptor.set.call(this,text);attachFocus(this);}});
    attachFocus(value);
  }
  for(const id of ['global-history-file-filter','global-history-health-filter'])nodes.get(id).value='all';
  const get=selector=>{const value=nodes.get(selector.replace(/^#/,''));assert(value,'production selector missing from HTML: '+selector);return value;};
  const query=selector=>[...new Set([...nodes.values()].flatMap(flatten))].filter(value=>selector.split(',').some(part=>{
    const match=part.trim().match(/^\[data-([\w-]+)\]$/);return match&&Object.hasOwn(value.dataset,match[1].replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase()));
  }));
  const context=vm.createContext({console,URLSearchParams,Map,Set,Number,String,Math,Promise,JSON,Date,
    state:{backup_context:'context-1'},token:'synthetic-token',view:'other',$:get,$$:query,
    escapeHTML:value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])),fmtTime:String,
    document,URL:{createObjectURL:()=> 'blob:synthetic',revokeObjectURL(){}},setTimeout:callback=>callback(),
    inlineError:(target,text)=>target.textContent=text,navigate:page=>navigations.push(page),poll:async()=>{},sourceURL:()=>null,names:{backups:'存档时光机'},
    getJSON:url=>new Promise((resolve,reject)=>reads.push({url,resolve,reject})),post:(url,payload)=>new Promise((resolve,reject)=>writes.push({url,payload:plain(payload),resolve,reject})),
    fetch:async(url,options)=>{writes.push({url,payload:JSON.parse(options.body)});return {ok:true,blob:async()=>({synthetic:true})};}});
  const run=source=>vm.runInContext(source,context),load=file=>run(fs.readFileSync(path.join(root,'web',file),'utf8'));
  return {context,get,query,reads,writes,downloads,navigations,run,load,click:id=>get('#'+id).click(),submit:id=>get('#'+id).listeners.submit({preventDefault(){}})};
}
const library='b'.repeat(24),archive='c'.repeat(32),id='a'.repeat(64);
const row={id,time:100,library,files:{'badges.dat':{valid:false,summary:null,error:'成就原始字节变化'},'rankings.dat':{valid:true,summary:{total:8,won:2,records:3,daily_history:1},error:''}}};
const saved={library,archive:null,context:'context-1',health:{state:'blocked',error:'历史需要核对'},history:[row],libraries:[{id:library,current:true}],
  archives:[{id:archive,state:'completed',count:512,damaged_count:1,bytes:67108864}],damaged_rows:[{id:'d'.repeat(64),bytes:42,sha256:'e'.repeat(64),error:'清单损坏'}],pending_maintenance:null,
  storage:{bytes:67108864,active_bytes:67108864,active_count:512,limit:67108864,pending_originals:0,total_local_bytes:134217728},snapshot_limit:512};
const maintenance={mode:'retain-local',expected:'maintenance-fresh',records:512,bytes:67108864,damaged_count:1,latest_usable:{id,time:100,files:['rankings.dat']},
  originals:[{path:'objects/synthetic.dat',bytes:123,sha256:'f'.repeat(64),damaged:true}],missing_originals:['objects/missing.dat'],active_after:{count:0,bytes:0},disk_bytes_released:0,message:'归档后重新捕获当前文件'};
async function read(h,value=saved){const loading=h.run('loadGlobalHistory(true)');h.reads.at(-1).resolve(structuredClone(value));await loading;}
async function preview(h,recovery=false,value=maintenance){const opening=h.run(`previewGlobalHistoryMaintenance(${recovery})`);h.writes.at(-1).resolve(structuredClone(value));await opening;}
function confirm(h,choice='retain-local'){h.get('#global-history-maintenance-choice').value=choice;h.get('#global-history-maintenance-choice').listeners.change();h.get('#global-history-maintenance-confirm').checked=true;h.run('renderGlobalHistoryControls()');}
async function verifyMaintenance(){
  const h=harness();h.load('global-history.js');await read(h);
  assert.equal(h.writes.length,0,'discovery must not mutate');assert.match(h.get('#global-history-damaged').innerHTML,/隔离的损坏历史/);
  assert.match(h.get('#global-history-list').innerHTML,/仅导出排行榜/);assert.match(h.get('#global-history-list').innerHTML,/其他健康文件可独立使用/);
  assert.match(h.get('#global-history-storage').textContent,/512 \/ 512/);
  await preview(h);assert.equal(h.writes.at(-1).payload.action,'maintenance-preview');
  assert(h.get('#global-history-maintenance-dialog').open);assert(h.get('#global-history-maintenance-submit').disabled);
  assert.match(h.get('#global-history-maintenance-summary').textContent,/512.*67,108,864/);assert.match(h.get('#global-history-maintenance-summary').textContent,/磁盘释放 0 字节/);
  assert.match(h.get('#global-history-maintenance-originals').innerHTML,/f{64}/);assert.match(h.get('#global-history-maintenance-originals').innerHTML,/损坏或结构不可用原件仍保留/);assert.match(h.get('#global-history-maintenance-latest').textContent,/排行榜/);
  assert.match(h.get('#global-history-maintenance-originals').innerHTML,/objects\/missing.dat · 关联原件已缺失/);assert.match(h.get('#global-history-maintenance-summary').textContent,/1 项已缺失/);
  h.get('#global-history-maintenance-confirm').checked=true;h.run('renderGlobalHistoryControls()');assert(h.get('#global-history-maintenance-submit').disabled,'confirmation without operation is insufficient');
  confirm(h);assert(!h.get('#global-history-maintenance-submit').disabled);
  const failed=h.submit('global-history-maintenance-form');assert.deepEqual(h.writes.at(-1).payload,{action:'maintenance',context:'context-1',library,expected:maintenance.expected,confirmed:true});
  assert(h.get('#global-history-maintenance-close').disabled);let prevented=false;h.get('#global-history-maintenance-dialog').listeners.cancel({preventDefault(){prevented=true;}});assert(prevented);
  h.writes.at(-1).reject(new Error('原件字节变化，重新预览'));await failed;
  assert.equal(h.get('#global-history-maintenance-choice').value,'retain-local');assert(!h.get('#global-history-maintenance-confirm').checked);confirm(h);assert(h.get('#global-history-maintenance-submit').disabled,'stale expected cannot be resubmitted');
  const fresh=h.run('previewGlobalHistoryMaintenance(false,true)');h.writes.at(-1).resolve({...maintenance,expected:'maintenance-new'});await fresh;
  assert.equal(h.get('#global-history-maintenance-choice').value,'retain-local');assert(!h.get('#global-history-maintenance-confirm').checked);confirm(h);
  const done=h.submit('global-history-maintenance-form');h.writes.at(-1).resolve({message:'归档完成',archive_id:archive,records:512,bytes:67108864,active_after:{count:1,bytes:512},health:{state:'protected',files:{'rankings.dat':{}}},disk_bytes_released:0});
  await new Promise(resolve=>setImmediate(resolve));h.reads.at(-1).resolve({...saved,health:{state:'protected'},storage:{...saved.storage,active_count:1,active_bytes:512,bytes:512}});await done;
  assert(!h.get('#global-history-maintenance-dialog').open);assert.match(h.get('#global-history-result').textContent,/活动库现有 1 份/);assert.match(h.get('#global-history-result').textContent,/当前保护结果：排行榜与每日记录最近文件已备份/);
  await preview(h,true,{pending:true,id:archive,state:'prepared',expected:'pending-new',can_continue:false,can_cancel:true,continue_reason:'当前源变化',message:'保留所有原件'});
  confirm(h,'continue');assert(h.get('#global-history-maintenance-submit').disabled);confirm(h,'cancel');assert(!h.get('#global-history-maintenance-submit').disabled);
  const cancellation=h.submit('global-history-maintenance-form');assert.equal(h.writes.at(-1).payload.action,'maintenance-cancel');h.writes.at(-1).reject(new Error('库身份变化'));await cancellation;
  assert.equal(h.get('#global-history-maintenance-choice').value,'cancel');assert.match(h.get('#global-history-maintenance-error').textContent,/库身份变化/);
  h.click('global-history-maintenance-close');const late=h.run('previewGlobalHistoryMaintenance(false)');h.click('global-history-maintenance-close');h.writes.at(-1).resolve(maintenance);await late;
  assert(!h.get('#global-history-maintenance-dialog').open);assert.equal(h.run('globalHistoryMaintenance'),null,'late preview cannot reopen a closed dialog');
  await preview(h);confirm(h);const oldReceipt=h.submit('global-history-maintenance-form');h.get('#global-history-result').textContent='new context result';h.context.state.backup_context='context-2';
  h.writes.at(-1).resolve({message:'old success',archive_id:archive,health:{state:'protected'}});await oldReceipt;
  assert.equal(h.get('#global-history-result').textContent,'new context result');assert(h.get('#global-history-maintenance-dialog').open);assert.equal(h.get('#global-history-maintenance-choice').value,'retain-local');
}
async function verifyIndependentArchiveFiles(){
  const h=harness();h.load('global-history.js');await read(h,{...saved,archive});
  assert.equal(h.get('#global-history-archive').value,archive);assert.match(h.get('#global-history-storage').textContent,/所选归档 512 份/);
  const opening=h.run(`previewGlobalHistory('${id}')`);assert.deepEqual(h.writes.at(-1).payload.selected,['rankings.dat']);assert.equal(h.writes.at(-1).payload.archive,archive);
  h.writes.at(-1).resolve({id,library,context:'context-1',expected:'restore-selected',target_root:'synthetic/saves',message:'只恢复健康文件',files:[{name:'rankings.dat',valid:true,source:row.files['rankings.dat'].summary,target_exists:true}]});await opening;
  h.query('[data-global-restore-name]')[0].checked=true;h.get('#global-history-version').checked=true;h.get('#global-history-confirm').checked=true;h.run('renderGlobalHistoryControls()');
  const restore=h.submit('global-history-restore-form');assert.deepEqual(h.writes.at(-1).payload.selected,['rankings.dat']);assert.deepEqual(h.writes.at(-1).payload.choices,{'rankings.dat':'replace'});assert.equal(h.writes.at(-1).payload.archive,archive);
  h.writes.at(-1).reject(new Error('source changed'));await restore;assert(h.query('[data-global-restore-name]')[0].checked);
  await h.run(`exportGlobalHistory('${id}',null,['rankings.dat'])`);assert.deepEqual(h.writes.at(-1).payload.selected,['rankings.dat']);assert.equal(h.writes.at(-1).payload.archive,archive);assert.equal(h.downloads.length,1);
  await h.run("exportGlobalHistory(null,null,null,'archive-export')");assert.equal(h.writes.at(-1).payload.action,'archive-export');assert.equal(h.writes.at(-1).payload.archive,archive);
  await h.run(`exportGlobalHistory('${'d'.repeat(64)}',null,null,'damaged-export')`);assert.equal(h.writes.at(-1).payload.action,'damaged-export');
  h.run(`openGlobalHistoryPortable('${id}')`);assert.equal(h.query('[data-global-portable-name]').find(input=>input.dataset.globalPortableName==='badges.dat').disabled,true);
  const healthy=h.query('[data-global-portable-name]').find(input=>input.dataset.globalPortableName==='rankings.dat');healthy.checked=true;h.get('#global-history-export-version').checked=true;
  h.run('renderGlobalHistoryControls()');assert(!h.get('#global-history-portable-export').disabled);
  let resolveDownload;h.context.fetch=()=>new Promise(resolve=>resolveDownload=resolve);const oldDownload=h.run(`exportGlobalHistory('${id}',null,['rankings.dat'])`);
  h.get('#global-history-archive').value='';resolveDownload({ok:true,blob:async()=>({})});await oldDownload;assert.equal(h.downloads.length,3,'old archive response cannot download in a new scope');assert(healthy.checked);
  h.run('renderGlobalHistoryControls()');assert(h.get('#global-history-portable-export').disabled);
  const stale=h.run('loadGlobalHistory(true)');h.get('#global-history-archive').value=archive;const current=h.run('loadGlobalHistory(true)');
  h.reads.at(-1).resolve({...saved,archive});await current;h.reads.at(-2).resolve({...saved,health:{state:'protected',error:'stale status'}});await stale;
  assert.equal(h.run('globalHistoryState.archive'),archive);assert(!h.get('#global-history-health').textContent.includes('stale status'));
  const candidates=harness();candidates.load('global-history.js');await read(candidates,{...saved,history:[{...row,files:{...row.files,'badges.dat':{valid:true,summary:{badges:3},error:''}}}]});
  const both=candidates.run(`previewGlobalHistory('${id}')`);assert.deepEqual(candidates.writes.at(-1).payload.selected,['badges.dat','rankings.dat']);
  candidates.writes.at(-1).resolve({id,library,context:'context-1',expected:'both-files',files:[{name:'badges.dat',valid:true,source:{badges:3}},{name:'rankings.dat',valid:true,source:row.files['rankings.dat'].summary}]});await both;
  candidates.query('[data-global-restore-name]').find(input=>input.dataset.globalRestoreName==='rankings.dat').checked=true;candidates.get('#global-history-version').checked=true;candidates.get('#global-history-confirm').checked=true;
  const onlyOne=candidates.submit('global-history-restore-form');assert.deepEqual(candidates.writes.at(-1).payload.selected,['badges.dat','rankings.dat']);assert.deepEqual(candidates.writes.at(-1).payload.choices,{'badges.dat':'keep','rankings.dat':'replace'});candidates.writes.at(-1).reject(new Error('preserve selections'));await onlyOne;
}
async function verifyRecoveryAndDamagedArchives(){
  const h=harness();h.load('global-history.js');await read(h);
  for(const result of [null,{pending:false}]){await preview(h,true,result);assert(!h.get('#global-history-maintenance-dialog').open);assert.match(h.get('#global-history-error').textContent,/没有未完成/);}
  await preview(h,true,{pending:true,id:archive,state:'continuing',expected:'resume-fresh',can_continue:true,can_cancel:true,message:'原件仍保留'});
  confirm(h,'continue');const continuing=h.submit('global-history-maintenance-form');assert.equal(h.writes.at(-1).payload.action,'maintenance-continue');h.writes.at(-1).reject(new Error('changed source'));await continuing;
  await preview(h,true,{pending:true,id:archive,state:'cancelling',expected:'cancel-fresh',can_continue:false,can_cancel:true,message:'可取消并恢复活动库'});
  confirm(h,'cancel');const cancelled=h.submit('global-history-maintenance-form');h.writes.at(-1).resolve({direction:'cancel',archive_id:archive,message:'维护已取消',records:512,bytes:67108864,active_after:{count:512,bytes:67108864},health:{state:'blocked'}});
  await new Promise(resolve=>setImmediate(resolve));h.reads.at(-1).resolve({...saved,archives:[]});await cancelled;
  assert.equal(h.get('#global-history-archive').value,'');assert.match(h.get('#global-history-result').textContent,/已取消的维护记录/);assert(!h.get('#global-history-result').textContent.includes('保留归档'));
  const damaged1={id:'1'.repeat(32),state:'damaged',error:'归档清单损坏'},damaged2={id:'2'.repeat(32),state:'unassociated',error:'未完成关联'};
  await read(h,{...saved,archives:[damaged1,...saved.archives,damaged2],storage:{...saved.storage,inventory_complete:false,unaccounted_containers:2}});
  const options=h.get('#global-history-archive').children;assert(options.find(option=>option.value===damaged1.id).disabled);assert(options.find(option=>option.value===damaged2.id).disabled);assert(!options.find(option=>option.value===archive).disabled);
  assert.match(h.get('#global-history-storage').textContent,/归档清单损坏/);assert.match(h.get('#global-history-storage').textContent,/未完成关联/);
  assert.match(h.get('#global-history-storage').textContent,/至少/);assert.match(h.get('#global-history-storage').textContent,/2 处保留原件未能核对/);assert.match(h.get('#global-history-storage').textContent,/数量\/字节未知（未完整核验）/);
  h.get('#global-history-archive').value=archive;await read(h,{...saved,archive,archives:[damaged1,...saved.archives,damaged2]});assert.equal(h.run('globalHistoryState.archive'),archive);
}
async function verifyHelp(){
  const h=harness();h.load('help.js');h.context.privateFixture={application_version:'1.0',reference_version:'4.0.2',platform:'Windows',
    backup:{state:'protected',has_problem:false,last_save_protected:true,global_history:{state:'blocked',has_problem:true,last_save_protected:false,error:'private-path token',directory:'private-path',note:'private-note',files:{data:'private-save'}}}};
  const diagnostic=JSON.parse(h.run('diagnosticText(privateFixture)'));
  assert.deepEqual(diagnostic.backup.global_history,{state:'blocked',has_problem:true,last_save_protected:false});
  for(const secret of ['private-path','private-note','private-save','token','directory','error'])assert(!JSON.stringify(diagnostic).includes(secret));
  h.context.privateFixture.backup.global_history={state:'C:/personal/token',has_problem:'private-note',last_save_protected:42};
  assert.deepEqual(JSON.parse(h.run('diagnosticText(privateFixture)')).backup.global_history,{state:'unknown',has_problem:null,last_save_protected:null});
  for(const state of ['warning','blocked','failed','timeout','unavailable']){
    const reading=h.run('loadHelp()');h.reads.at(-1).resolve({application_version:'1.0',reference_version:'4.0.2',reading_state:'saved',next_steps:[],diagnostic:{backup:{state:'protected',global_history:{state,has_problem:true,last_save_protected:false}}}});await reading;
    const next=h.get('#help-next');assert(!next.innerHTML.includes('当前没有发现'));assert.equal(next.children.length,1);await next.children[0].querySelector('button').click();assert.equal(h.navigations.at(-1),'backups');
  }
}
async function verifyHistorySelectionAndFocus(){
  const h=harness();h.load('global-history.js');
  const history=Array.from({length:512},(_,index)=>({...row,id:index.toString(16).padStart(64,'0'),time:1791288000+index*86400,files:{'rankings.dat':{valid:true,integrity:'verified',summary:{total:index,won:0,records:0,daily_history:0}}}}));
  history[511]={...history[511],files:{'badges.dat':{valid:false,integrity:'damaged',error:'目标原件损坏'},'rankings.dat':{valid:true,integrity:'verified',summary:{total:511,won:0,records:0,daily_history:0}}}};
  const raw={...row,id:'f'.repeat(64),files:{'badges.dat':{valid:false,integrity:'verified',summary:null}}};
  const value={...saved,history:[...history,raw]};await read(h,value);
  assert.equal(h.query('[data-global-history-export]').length,20);assert(!h.get('#global-history-more').hidden);
  h.get('#global-history-search').value=history[511].id;h.get('#global-history-search').listeners.input();
  assert.equal(h.query('[data-global-history-export]').length,1);assert.equal(h.query('[data-global-history-export]')[0].dataset.globalHistoryExport,history[511].id);
  assert(h.get('#global-history-more').hidden);assert.match(h.get('#global-history-count').textContent,/共 514 份，符合条件 1 份，已显示 1 份/);
  await read(h,value);assert.equal(h.get('#global-history-search').value,history[511].id,'poll preserves a whole-collection query');
  h.get('#global-history-file-filter').value='badges.dat';h.get('#global-history-health-filter').value='restorable';h.get('#global-history-health-filter').listeners.change();
  assert.equal(h.query('[data-global-history-export]').length,0,'a healthy ranking must not make damaged badges match');assert.match(h.get('#global-history-list').innerHTML,/没有符合条件/);
  h.get('#global-history-health-filter').value='damaged';h.get('#global-history-health-filter').listeners.change();assert.equal(h.query('[data-global-history-export]').length,1);
  h.click('global-history-filter-reset');h.get('#global-history-health-filter').value='raw-only';h.get('#global-history-health-filter').listeners.change();
  assert.equal(h.query('[data-global-history-export]').length,1);assert.equal(h.query('[data-global-history-export]')[0].dataset.globalHistoryExport,raw.id);
  h.click('global-history-filter-reset');h.get('#global-history-search').value=new Date(history[511].time*1000).toISOString().slice(0,10);h.get('#global-history-search').listeners.input();
  assert.equal(h.query('[data-global-history-export]').length,1,'ISO dates search beyond the first page');
  h.click('global-history-filter-reset');h.get('#global-history-search').value='目标 原件损坏';h.get('#global-history-search').listeners.input();assert.equal(h.query('[data-global-history-export]').length,1);
  h.click('global-history-filter-reset');h.get('#global-history-health-filter').value='damaged';h.get('#global-history-health-filter').listeners.change();
  assert.equal(h.query('[data-global-damaged-export]').length,1);h.get('#global-history-file-filter').value='badges.dat';h.get('#global-history-file-filter').listeners.change();
  assert.equal(h.query('[data-global-damaged-export]').length,0,'damaged manifests do not claim known files');
  h.click('global-history-filter-reset');await read(h,{...saved,history:[{...row,files:{...row.files,'badges.dat':{valid:true,summary:{badges:3}}}}]});
  for(const selector of ['[data-global-history-preview]','[data-global-history-export]','[data-global-history-file]','[data-global-history-portable]','[data-global-damaged-export]']){
    for(const identity of h.query(selector).map(button=>plain(button.dataset))){
      const original=h.query(selector).find(button=>JSON.stringify(button.dataset)===JSON.stringify(identity));original.focus();await read(h,{...saved,history:[{...row,files:{...row.files,'badges.dat':{valid:true,summary:{badges:3}}}}]});
      assert.notEqual(h.context.document.activeElement,original,'focus follows the replacement node');assert.deepEqual(plain(h.context.document.activeElement.dataset),identity);
    }
  }
  h.get('#global-history-search').focus();await read(h,saved);assert.equal(h.context.document.activeElement,h.get('#global-history-search'),'outside focus is not stolen');
  h.query('[data-global-history-preview]')[0].focus();await read(h,{...saved,history:[]});assert.equal(h.context.document.activeElement,h.get('#global-history-search'),'missing action returns to the search');
  await read(h,saved);h.query('[data-global-history-preview]')[0].focus();await read(h,{...saved,archive});assert.equal(h.context.document.activeElement,h.get('#global-history-search'),'identical IDs in another archive do not inherit action focus');
  h.query('[data-global-history-preview]')[0].focus();await read(h,{...saved,archive,history:[{...row,files:{'badges.dat':{valid:false,integrity:'damaged'}}}]});assert.equal(h.context.document.activeElement,h.get('#global-history-search'),'a disabled action is not refocused');
  assert.equal(h.writes.length,0,'querying and focus restoration do not write or restore files');
}
(async()=>{await verifyMaintenance();await verifyIndependentArchiveFiles();await verifyRecoveryAndDamagedArchives();await verifyHelp();await verifyHistorySelectionAndFocus();console.log('PASS: global history maintenance/recovery, independent archive files, full-collection search/file/health filters, poll focus, stale receipts, and private help diagnostics (production JS VM only)');})().catch(error=>{console.error(error);process.exitCode=1;});
