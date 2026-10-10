// Actual workflow components with deferred responses; no browser or personal data.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..');
function harness(script){
  const elements=new Map();
  function element(id=''){
    const node={value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,checked:false,open:false,
      dataset:{},children:[],listeners:{},classList:{toggle(){}},setAttribute(key,value){this[key]=value;},
      append(...items){this.children.push(...items);},prepend(...items){this.children.unshift(...items);},
      replaceChildren(...items){this.children=items;this.innerHTML='';this.textContent='';},
      addEventListener(name,handler){this.listeners[name]=handler;},querySelectorAll(){return [];},
      focus(){},showModal(){this.open=true;},close(){this.open=false;},remove(){},requestSubmit(){return this.listeners.submit?.({preventDefault(){}});}};
    Object.defineProperty(node,'id',{get(){return this._id||'';},set(value){this._id=value;elements.set('#'+value,this);}});if(id)node.id=id;return node;
  }
  const get=id=>elements.get(id)||element(id.replace(/^#/,''));
  const context=vm.createContext({console,URL,URLSearchParams,Map,Set,Promise,Date,JSON,Number,String,Math,
    $:get,$$:()=>[],document:{activeElement:null,createElement:()=>element(),createTextNode:text=>({textContent:text})},
    state:{backup_context:'context-a',settings:{save_root:'/synthetic/a'}},backupState:{context:'context-a',save_root:'/synthetic/a',history:[]},
    view:'overview',token:'synthetic-token',escapeHTML:String,fmtTime:String,inlineError:(node,text)=>node.textContent=text,
    toast(){},navigate(){},backupSummary:summary=>String(summary?.hp??'空槽位'),bindingLabels:{},names:{},setTimeout(){},fetch:async()=>({ok:true,json:async()=>({rows:[]})}),
    post:async()=>({}),loadBackups:async()=>{}});
  const run=source=>vm.runInContext(source,context);run(fs.readFileSync(path.join(root,'web',script),'utf8'));
  return {context,run,get};
}
function deferred(){let resolve;return {promise:new Promise(done=>resolve=done),resolve:value=>resolve(value)};}
const plain=value=>JSON.parse(JSON.stringify(value));
(async()=>{
  let checks=0;
  for(const context of ['context-b',null]){
    const changing=harness('backups.js');changing.get('#backup-status').textContent='原目录已恢复，可撤回';
    changing.run("backupContext='context-a';state.backup_context="+JSON.stringify(context)+";syncBackupContext("+JSON.stringify(context)+")");
    assert.equal(changing.get('#backup-status').textContent,context?'正在读取当前存档目录的备份状态…':'服务未连接，备份状态暂不可确认。');checks++;
  }
  const flow=harness('backup-workflows.js');
  flow.run("backupFlow.context='context-a';backupFlow.epoch=1;loadBackupFlowStorage=async()=>{}");
  let pending=deferred(),posted;
  flow.context.post=async(url,payload)=>{posted=payload;return pending.promise;};
  flow.run("backupFlow.retentionDraft={revision:0,policy:{keep_per_slot:1},expected:'old-preview',selected:[{slot:1,id:'old'}],candidates:[{slot:1,id:'old',label:'旧整理目标'}]}");
  flow.get('#backup-retention-confirm').checked=true;
  const retention=flow.run('archiveBackupRetention()');
  flow.run("backupFlow.policyRevision++;backupFlow.retentionDraft={revision:1,policy:{keep_per_slot:5},expected:'new-preview'}");
  pending.resolve({results:[{slot:1,id:'old',ok:true}],archived:1,deleted:0,message:'原件保持'});await retention;
  assert.equal(flow.run('backupFlow.receipts.length'),1);assert.equal(flow.run('backupFlow.receipts[0].result.results[0].label'),'旧整理目标');
  assert.equal(flow.run('backupFlow.retentionDraft.expected'),'new-preview');assert(flow.run('Object.isFrozen(backupFlow.receipts[0].result.results[0])'));checks++;

  pending=deferred();flow.run("backupFlow.importFile={name:'old.zip'};backupFlow.importDraft={revision:0,file:backupFlow.importFile,expected:'import-preview'};backupFlow.importSelection=new Set(['success.zip','failed.zip'])");
  flow.get('#backup-batch-import-confirm').checked=true;
  flow.context.backupFlowUpload=async()=>pending.promise;
  const importing=flow.run('importBackupBatch()');
  flow.run("backupFlow.importRevision++;backupFlow.importSelectionRevision++;backupFlow.importFile={name:'new.zip'};backupFlow.importDraft={revision:1,file:backupFlow.importFile,expected:'new-import'};backupFlow.importSelection=new Set(['new-choice'])");
  pending.resolve({results:[{file:'success.zip',ok:true},{file:'failed.zip',ok:false,error:'disk-full'}],success_count:1,failure_count:1});await importing;
  assert.equal(flow.run('backupFlow.importFile.name'),'new.zip');assert.deepEqual(Array.from(flow.run('backupFlow.importSelection')),['new-choice']);
  assert.equal(flow.run('backupFlow.receiptFiles.get(backupFlow.lastImportReceipt.id).name'),'old.zip');checks++;
  flow.run("backupFlow.context='context-b';state.backup_context='context-b';backupFlow.epoch++");
  let uploaded;
  flow.context.backupFlowUpload=async(endpoint,file,ticket,headers)=>{uploaded={endpoint,file,ticket,headers};return endpoint==='batch-preview'?{expected:'fresh',rows:[{file:'success.zip',valid:true},{file:'failed.zip',valid:true},{file:'unrelated.zip',valid:true}]}:{results:[{file:'failed.zip',ok:true}],success_count:1,failure_count:0};};
  await flow.run('retryBackupImportReceipt(backupFlow.lastImportReceipt)');
  const retry=flow.get('#backup-receipt-retry-2'),label=retry.children.find(node=>node.children?.some(child=>child.type==='checkbox')),confirm=label.children.find(child=>child.type==='checkbox'),button=retry.children.find(node=>node.textContent==='确认重试本次失败记录');
  flow.run('renderBackupReceipts()');assert.equal(flow.get('#backup-receipt-retry-2'),retry);assert(retry.children.includes(button));
  confirm.checked=true;await button.listeners.click();
  assert.deepEqual(JSON.parse(uploaded.headers['X-Companion-Transfer-Selection']),['failed.zip']);assert.equal(uploaded.file.name,'old.zip');
  assert.deepEqual(Array.from(flow.run('backupFlow.importSelection')),['new-choice']);assert.equal(flow.run('backupFlow.receipts.length'),3);checks++;

  flow.run('setupBackupReclaim()');pending=deferred();flow.context.post=async(url,payload)=>{posted=payload;return pending.promise;};
  flow.run("backupFlow.reclaimDraft={revision:0,verified:true,selected:[{kind:'retained',file:'old.zip'}],expected:'reclaim-old',external_path:'/external/originals.zip',archive_sha256:'hash',count:1,confirm_phrase:'回收 1 项原件',rows:[{kind:'retained',file:'old.zip',label:'确切旧原件'}]}");
  flow.get('#backup-reclaim-confirm').checked=true;flow.get('#backup-reclaim-phrase').value='回收 1 项原件';
  const reclaim=flow.get('#backup-reclaim-execute').listeners.click();
  flow.run("backupFlow.reclaimRevision++;backupFlow.reclaimDraft={revision:1,expected:'new-reclaim'};backupFlow.reclaimSelection.set('retained:new.zip',{kind:'retained',file:'new.zip'})");
  flow.get('#backup-reclaim-path').value='/external/new.zip';
  pending.resolve({results:[{kind:'retained',file:'old.zip',ok:true,released_bytes:5,deleted_files:['old.zip']}],success_count:1,failure_count:0,released_bytes:5,external_path:'/external/originals.zip',message:'已完成'});await reclaim;
  assert.equal(flow.run('backupFlow.reclaimDraft.expected'),'new-reclaim');assert.equal(flow.get('#backup-reclaim-path').value,'/external/new.zip');
  assert.equal(flow.run('backupFlow.receipts[3].result.results[0].label'),'确切旧原件');checks++;
  const immutable=plain(flow.run('backupFlow.receipts'));
  const normalGet=flow.context.$;let initialized=false;flow.context.ensureBackupWorkflows=()=>{initialized=true;};flow.context.$=id=>{if(id==='#backup-stage-review')assert(initialized,'create dynamic controls before resetting them');return normalGet(id);};
  flow.run("resetBackupWorkflows('new-connection')");assert.deepEqual(plain(flow.run('backupFlow.receipts')),immutable);checks++;
  flow.context.$=normalGet;

  flow.run("backupFlow.context='context-c';state.backup_context='context-c';backupFlow.epoch++;backupFlow.stageDraft=null");
  flow.context.post=async(url,payload)=>payload.action==='stage-preview'?{context:'context-c',file:'.denghuo-stage-1-123-12345678',path:'/synthetic/a/.denghuo-stage-1-123-12345678',bytes:20,verification:'完整核验',expected:'stage-digest',confirm_phrase:'重新尝试确切暂存',source:{slot:1,id:'original'},current:{hp:22},target:{hp:5}}:{ok:true,file:payload.file,original_stage_preserved:true,restored:true,message:'原暂存保持'};
  await flow.run("inspectBackupStage('.denghuo-stage-1-123-12345678',true)");
  const stage=flow.get('#backup-stage-content'),stagePhrase=stage.children.find(node=>node.children?.some(child=>child.type==='text')).children.find(child=>child.type==='text'),stageConfirm=stage.children.find(node=>node.children?.some(child=>child.type==='checkbox')).children.find(child=>child.type==='checkbox'),stageButton=stage.children.find(node=>node.textContent==='确认重新尝试回档');
  assert(stageButton.disabled);stagePhrase.value='重新尝试确切暂存';stageConfirm.checked=true;stageConfirm.listeners.change();assert(!stageButton.disabled);await stageButton.listeners.click();
  assert.equal(flow.run('backupFlow.receipts.at(-1).kind'),'stage');assert(flow.run('backupFlow.receipts.at(-1).result.original_stage_preserved'));checks++;

  const migration=harness('migration.js');pending=deferred();
  migration.run("migrationExportSelection=new Set(['backup:unavailable','preference:font_scale']);migrationState={rows:[{key:'backup:unavailable',group:'backup',label:'原选中进度',valid:false,error:'ZIP缺失'},{key:'preference:font_scale',group:'preference',label:'字号',valid:true}]};migrationRows($('#migration-export-list'),migrationState.rows,migrationExportSelection,'export')");
  const unavailable=migration.get('#migration-export-list').children[0].children[1].children[0].children[0];
  assert(unavailable.checked);assert(!unavailable.disabled,'previously selected unavailable row must remain deselectable');
  unavailable.checked=false;migration.get('#view-migration').listeners.change({target:unavailable});
  assert(unavailable.disabled);assert.deepEqual(Array.from(migration.run('migrationExportSelection')),['preference:font_scale']);checks++;
  migration.run("migrationFile={name:'submitted.zip'};migrationImportPreview={expected:'old',save_root:'/synthetic/a',rows:[{key:'draft:old',label:'已提交原始草稿'}]};migrationImportSelection=new Set(['draft:old']);migrationUpload=async()=>pendingResult;loadMigration=async()=>{}");
  migration.context.pendingResult=pending.promise;migration.get('#migration-confirm').checked=true;
  const applying=migration.get('#migration-import').listeners.click();
  migration.run("migrationEdited('import');migrationFile={name:'new.zip'};migrationImportSelection=new Set(['draft:new']);migrationImportPreview={expected:'new',save_root:'/synthetic/a',rows:[{key:'draft:new',label:'新选择'}]}");
  migration.get('#migration-import-panel').hidden=false;migration.get('#migration-import-info').textContent='新包等待预览';
  pending.resolve({results:[{key:'draft:old',ok:false,error:'controlled disk failure'}],success_count:0,failure_count:1,note:'原件保持'});await applying;
  assert.equal(migration.run('migrationImportPreview.expected'),'new');assert.equal(migration.run('migrationFile.name'),'new.zip');assert.equal(migration.get('#migration-import-panel').hidden,false);
  assert.equal(migration.run('migrationReceipts[0].result.results[0].label'),'已提交原始草稿');assert(migration.run('Object.isFrozen(migrationReceipts[0].result.results[0])'));checks++;
  migration.run("recordMigrationReceipt({results:[{key:'draft:new',ok:true,message:'保存'}],success_count:1,failure_count:0},{file_name:'new.zip',root:'/synthetic/a',rows:[{key:'draft:new',label:'新草稿'}]},migrationFile)");
  assert.equal(migration.run('migrationReceipts.length'),2);assert.equal(migration.run('migrationReceipts[0].result.results[0].label'),'已提交原始草稿');checks++;
  let migrationSubmitted;
  migration.context.migrationUpload=async(action,file,payload)=>{migrationSubmitted={action,file,payload};return action==='preview'?{expected:'retry-preview',save_root:'/synthetic/a',rows:[{key:'draft:old',label:'原失败项',valid:true},{key:'draft:new',label:'无关当前项',valid:true}]}:{results:[{key:'draft:old',ok:true,message:'已存原始输入'}],success_count:1,failure_count:0};};
  await migration.run('retryMigrationReceipt(migrationReceipts[0])');
  const migrationRetry=migration.get('#migration-retry-1'),migrationLabel=migrationRetry.children.find(node=>node.children?.some(child=>child.type==='checkbox')),migrationConfirm=migrationLabel.children.find(child=>child.type==='checkbox'),migrationButton=migrationRetry.children.find(node=>node.textContent==='确认重试这次失败项目');
  migration.run('renderMigrationResults()');assert.equal(migration.get('#migration-retry-1'),migrationRetry);assert(migrationRetry.children.includes(migrationButton));
  migrationConfirm.checked=true;await migrationButton.listeners.click();assert.deepEqual(Array.from(migrationSubmitted.payload.selected),['draft:old']);assert.equal(migrationSubmitted.file.name,'submitted.zip');
  assert.equal(migration.run('migrationFile.name'),'new.zip');assert.equal(migration.run('migrationImportPreview.expected'),'new');checks++;

  const metadata=harness('backups.js');metadata.run("initializeBackups();openManage({slot:1,id:'backup',label:'原名称',locked:false,metadata_revision:'original-version'},'context-a')");
  metadata.get('#backup-label').value='旧窗口未提交名称';metadata.get('#backup-locked').checked=false;
  metadata.context.fetch=async()=>({ok:true,json:async()=>({context:'context-a',history:[{slot:1,id:'backup',label:'另一窗口的新保护',locked:true,metadata_revision:'protected-version'}]})});
  await metadata.run('showLatestBackupMetadata(manageTarget)');
  assert.equal(metadata.run('manageTarget.expected_metadata_revision'),'original-version');assert.equal(metadata.get('#backup-label').value,'旧窗口未提交名称');assert.equal(metadata.get('#backup-locked').checked,false);
  assert(metadata.get('#manage-latest').children[0].textContent.includes('永久保留：已开启'));
  let confirmedVersion;metadata.get('#manage-form').requestSubmit=()=>confirmedVersion=metadata.run('manageTarget.expected_metadata_revision');
  metadata.get('#manage-latest').children.find(node=>node.textContent==='已核对最新信息，保留上方编辑并重新确认').listeners.click();
  assert.equal(confirmedVersion,undefined,'reviewing latest metadata must require a separate save');assert.equal(metadata.run('manageTarget.expected_metadata_revision'),'protected-version');assert.equal(metadata.get('#backup-label').value,'旧窗口未提交名称');checks++;
  pending=deferred();let singleReceipt;
  metadata.context.action=work=>work();metadata.context.backupFlowTicket=()=>({root:'/synthetic/a',context:'context-a',epoch:1});metadata.context.backupFlowCurrent=()=>true;
  metadata.context.recordBackupReceipt=(kind,ticket,result,submitted,changed)=>singleReceipt={kind,ticket,result,submitted,changed};metadata.context.refreshBackupReceiptScope=async()=>{};
  metadata.context.fetch=async()=>pending.promise;metadata.run("backupState={context:'context-a'}");
  const single=metadata.get('#import-backup'),oldFile={name:'single-old.zip',size:30};single.files=[oldFile];single.value='single-old.zip';
  const singleImport=single.listeners.change();single.files=[{name:'single-new.zip',size:40}];single.value='single-new.zip';
  pending.resolve({ok:true,json:async()=>({slot:1,id:'imported-original'})});await singleImport;
  assert.equal(single.value,'single-new.zip');assert.equal(singleReceipt.submitted.file_name,'single-old.zip');assert(singleReceipt.changed);checks++;
  const libraries=harness('backup-libraries.js');
  Object.assign(libraries.context,{flowSize:String,flowKey:row=>`${row.slot}:${row.id}`,flowTable:()=>'',classNames:{MAGE:'法师'},freezeBackupReceipt:value=>{
    const freeze=object=>{if(object&&typeof object==='object'){Object.values(object).forEach(freeze);Object.freeze(object);}return object;};return freeze(value);
  }});
  const libraryRows=['a','b'].map(id=>({id,current:false,record_count:1,errors:[],groups:Object.fromEntries(['active','retained','quarantine'].map(kind=>[kind,{bytes:100,directory:'/assistant/'+kind+'/'+id}]))}));
  libraries.context.libraryRows=libraryRows;libraries.run("backupLibraries.context='context-a';backupLibraries.catalog={libraries:libraryRows};backupLibraries.selected='a'");
  let oldDetails=deferred(),newDetails=deferred();
  libraries.context.fetch=async url=>({ok:true,json:async()=>url.includes('id=a')?oldDetails.promise:newDetails.promise});
  const readingOld=libraries.run('loadBackupLibrary("a")'),readingNew=libraries.run('loadBackupLibrary("b")');
  newDetails.resolve({library_id:'b',context:'context-a',groups:[{kind:'active',rows:[]},{kind:'retained',rows:[]}]});await readingNew;
  oldDetails.resolve({library_id:'a',context:'context-a',groups:[{kind:'active',rows:[{slot:1,id:'old'}]},{kind:'retained',rows:[]}]});await readingOld;
  assert.equal(libraries.run('backupLibraries.data.library_id'),'b');assert.equal(libraries.run('backupLibraries.selected'),'b');checks++;
  pending=deferred();libraries.context.fetch=async()=>({ok:true,json:async()=>pending.promise});
  const oldPreview=libraries.run('previewLibraryOperation("retention-preview",{policy:{keep_per_slot:1}})');
  libraries.run('invalidateLibraryPreview()');pending.resolve({library_id:'b',context:'context-a',expected:'stale-preview',candidates:[],kept:[]});await oldPreview;
  assert.equal(libraries.run('backupLibraries.preview'),null);assert(libraries.get('#library-backup-review').hidden);checks++;
  libraries.run("backupLibraries.selected='a';backupLibraries.preview={action:'retention-preview',payload:{policy:{keep_per_slot:1}},result:{expected:'old-exact-preview',candidates:[{slot:1,id:'old',label:'旧库实际名称'}]},ticket:libraryTicket()}");
  libraries.get('#library-backup-confirm').checked=true;pending=deferred();libraries.context.fetch=async()=>({ok:true,json:async()=>pending.promise});
  const oldExecution=libraries.run('executeLibraryOperation()');
  libraries.run("backupLibraries.selected='b';backupLibraries.epoch++;backupLibraries.preview={result:{expected:'new-library-preview'}}");
  pending.resolve({library_id:'a',context:'context-a',results:[{slot:1,id:'old',ok:true}],archived:1,deleted:0,message:'旧库原件完整保留'});await oldExecution;
  assert.equal(libraries.run('backupLibraries.preview.result.expected'),'new-library-preview');
  assert.equal(libraries.run('backupLibraries.receipts.length'),1);assert.equal(libraries.run('backupLibraries.receipts[0].library_id'),'a');
  assert(libraries.run('backupLibraries.receipts[0].changed'));assert.equal(libraries.run('backupLibraries.receipts[0].result.results[0].label'),'旧库实际名称');
  assert(libraries.run('Object.isFrozen(backupLibraries.receipts[0].result.results[0])'));checks++;
  libraries.run("backupLibraries.selection.set('1:x',{slot:1,id:'x'});resetBackupLibraries('context-b')");
  assert.equal(libraries.run('backupLibraries.selection.size'),0);assert.equal(libraries.run('backupLibraries.preview'),null);
  assert.equal(libraries.run('backupLibraries.receipts.length'),1);assert.equal(libraries.run('backupLibraries.context'),'context-b');checks++;
  let receiptChecks=0;
  async function restoreReceiptCase(operation,outcome,interrupt){
    const restore=harness('backups.js');
    restore.run(fs.readFileSync(path.join(root,'web','backup-workflows.js'),'utf8'));
    restore.run("initializeBackups();backupContext='context-a';backupFlow.context='context-a';backupFlow.epoch=1;backupState={context:'context-a',save_root:'/synthetic/a',history:[]};loadBackups=async()=>{};loadBackupFlowStorage=async()=>{}");
    restore.context.completed=[];
    restore.run("loadBackups=async()=>{completed.push(state.backup_context)}");
    restore.run(`openConfirm({slot:1,id:'original-id',label:'原始目标',expected_current:'original-digest',class:'WARRIOR',level:3,depth:4,hp:8,ht:30,saved:1000,before:{class:'MAGE',level:2,depth:3,hp:5,ht:25,saved:900}},'${operation}','context-a')`);
    restore.get('#restore-confirm').checked=true;
    const deferredResult=deferred();let submitted,nextPreview,previewing;
    restore.context.post=async(url,payload)=>{submitted=plain(payload);return deferredResult.promise;};
    const completing=restore.get('#restore-form').listeners.submit({preventDefault(){}});
    assert.equal(submitted.action,operation);assert.equal(submitted.context,'context-a');
    assert.equal(submitted.expected_current,'original-digest');assert.equal(submitted.id,'original-id');
    if(interrupt==='close')restore.get('#close-restore').listeners.click();
    else if(interrupt==='escape'){
      restore.get('#restore-dialog').listeners.cancel();restore.get('#restore-dialog').close();
    }else if(interrupt==='connection'){
      restore.run("state.backup_context='context-b';state.settings.save_root='/synthetic/b';syncBackupContext('context-b');backupState={context:'context-b',save_root:'/synthetic/b',history:[]}");
    }else if(interrupt==='new-target'){
      restore.run("openConfirm({slot:2,id:'new-id',expected_current:'new-digest'},'undo','context-a')");
      restore.get('#restore-confirm').checked=true;restore.get('#restore-submit').disabled=true;
      restore.get('#restore-error').textContent='new-preview-error';
    }else if(interrupt==='pending-preview'){
      nextPreview=deferred();restore.context.fetch=async()=>({ok:true,json:async()=>nextPreview.promise});
      previewing=restore.run("openRestore({slot:2,id:'pending-id'},'context-a','undo')");
      restore.get('#restore-confirm').checked=true;
      restore.get('#restore-error').textContent='pending-preview-error';
    }
    if(outcome==='success')deferredResult.resolve({ok:true,action:operation,root:'/synthetic/a',context:'context-a',
      scope:{root:'/synthetic/a',context:'context-a'},results:[{action:operation,slot:1,id:'original-id',ok:true}],message:'原目录实际完成'});
    else {
      const error=new Error(outcome==='failure'?'真实业务失败':'network-response-lost');
      if(outcome==='failure')error.status=400;
      deferredResult.resolve(Promise.reject(error));
    }
    await completing;await new Promise(done=>setImmediate(done));
    assert.equal(restore.run('backupFlow.receipts.length'),1,`${operation}/${outcome}/${interrupt}: completion must survive`);
    const receipt=plain(restore.run('backupFlow.receipts[0]'));
    assert.equal(receipt.kind,operation);assert.equal(receipt.root,'/synthetic/a');assert.equal(receipt.context,'context-a');
    assert.equal(receipt.submitted.action,operation);assert.equal(receipt.submitted.id,'original-id');
    assert.equal(receipt.submitted.slot,1);assert.equal(receipt.submitted.root,'/synthetic/a');
    assert.deepEqual(receipt.submitted.scope,{root:'/synthetic/a',context:'context-a'});
    assert.equal(receipt.submitted.expected_current,'original-digest');
    assert.equal(receipt.result.results[0].ok,outcome==='success');
    assert.equal(receipt.result.results[0].id,'original-id');assert.equal(receipt.result.results[0].label,'原始目标');
    const progress=receipt.result.results[0].summary;
    assert(progress,`${operation}/${outcome}/${interrupt}: preserve preview progress in the immutable receipt`);
    assert.equal(progress.class,operation==='undo'?'MAGE':'WARRIOR');
    assert.equal(progress.hp,operation==='undo'?5:8);assert.equal(progress.ht,operation==='undo'?25:30);
    assert.equal(progress.saved,operation==='undo'?900:1000);
    const receiptTable=restore.run('flowTable(backupFlow.receipts[0].result.results,{result:true})');
    assert(receiptTable.includes(operation==='undo'?'生命 5/25':'生命 8/30'));
    assert(!receiptTable.includes('摘要不可验证'));assert(!receiptTable.includes('源保存时间未提供'));
    assert(restore.run('Object.isFrozen(backupFlow.receipts[0].submitted.scope)'));
    assert(restore.run('Object.isFrozen(backupFlow.receipts[0].result.results[0])'));
    const rendered=restore.get('#backup-operation-receipts').children;
    assert(rendered.some(node=>node.children?.some(child=>String(child.textContent).includes('/synthetic/a'))),'receipt must be visible with original root');
    assert.equal(receipt.changed,interrupt!=='none');
    if(outcome==='failure')assert.equal(receipt.result.outcome,'failed');
    if(outcome==='unknown'){
      assert.equal(receipt.result.outcome,'unknown');assert.match(receipt.result.message,/结果尚未确认/);
    }
    if(interrupt==='new-target'){
      assert.equal(restore.run('restoreTarget.id'),'new-id');assert.equal(restore.run('restoreTarget.expected_current'),'new-digest');
      assert(restore.get('#restore-dialog').open);assert(restore.get('#restore-submit').disabled);
      assert(restore.get('#restore-confirm').checked);assert.equal(restore.get('#restore-error').textContent,'new-preview-error');
    }else if(interrupt==='pending-preview'){
      assert(restore.get('#restore-dialog').open);assert(restore.get('#restore-submit').disabled);
      assert(restore.get('#restore-confirm').checked);assert.equal(restore.get('#restore-error').textContent,'pending-preview-error');
      nextPreview.resolve({context:'context-a',expected_current:'pending-digest',current:{empty:true},target:{empty:true}});
      await previewing;
      assert.equal(restore.run('restoreTarget.id'),'pending-id');assert.equal(restore.run('restoreTarget.expected_current'),'pending-digest');
      assert(restore.get('#restore-dialog').open);assert(!restore.get('#restore-confirm').checked);
    }else if(interrupt==='connection'){
      assert.equal(restore.run('state.settings.save_root'),'/synthetic/b');assert.equal(restore.run('restoreTarget'),null);
      assert.equal(restore.context.completed.length,0,'old completion cannot refresh B');
      restore.run("state.backup_context='context-a-returned';state.settings.save_root='/synthetic/a';syncBackupContext('context-a-returned')");
      assert.equal(restore.run('backupFlow.receipts.length'),1,'A→B→A retains the submitted result');
      assert.equal(plain(restore.run('backupFlow.receipts[0]')).context,'context-a');
    }else if(interrupt==='none'){
      if(outcome==='success')assert(!restore.get('#restore-dialog').open);
      else {assert(restore.get('#restore-dialog').open);assert(!restore.get('#restore-submit').disabled);assert(!restore.get('#restore-confirm').checked);assert(!restore.get('#restore-error').hidden);}
    }
    receiptChecks++;
  }
  for(const operation of ['restore','undo','remove']){
    for(const outcome of ['success','failure'])for(const interrupt of ['none','close','escape','connection','new-target','pending-preview'])await restoreReceiptCase(operation,outcome,interrupt);
    await restoreReceiptCase(operation,'unknown','connection');
  }
  // The verified preview supersedes stale card metadata, including an originally empty slot.
  for(const [operation,empty] of [['restore',false],['undo',false],['undo',true]]){
    const preview=harness('backups.js');preview.run(fs.readFileSync(path.join(root,'web','backup-workflows.js'),'utf8'));
    preview.run("initializeBackups();backupFlow.context='context-a';backupFlow.epoch=1;backupState={save_root:'/synthetic/a'};loadBackups=async()=>{};loadBackupFlowStorage=async()=>{}");
    const target=empty?{empty:true}:{class:'CLERIC',level:9,depth:8,hp:17,ht:40,saved:2000};
    preview.context.fetch=async()=>({ok:true,json:async()=>({context:'context-a',expected_current:'preview-digest',original_existed:!empty,current:{empty:true},target})});
    await preview.run(`openRestore({slot:1,id:'preview-id',class:'WARRIOR',hp:99,ht:100,saved:1},'context-a','${operation}')`);
    preview.get('#restore-confirm').checked=true;
    const result=deferred();preview.context.post=async()=>result.promise;
    const completing=preview.get('#restore-form').listeners.submit({preventDefault(){}});
    target.hp=999;target.saved=9999;
    preview.run("state.backup_context='context-b';state.settings.save_root='/synthetic/b';syncBackupContext('context-b')");
    result.resolve({ok:true});await completing;
    const receipt=plain(preview.run('backupFlow.receipts[0]'));
    const table=preview.run('flowTable(backupFlow.receipts[0].result.results,{result:true})');
    if(empty){assert.equal(receipt.submitted.summary.empty,true);assert(table.includes('空槽位'));assert(!table.includes('摘要不可验证'));}
    else {assert.equal(receipt.submitted.summary.hp,17);assert.equal(receipt.submitted.summary.saved,2000);assert(table.includes('生命 17/40'));assert(table.includes('游戏保存 2000'));}
    assert.equal(receipt.root,'/synthetic/a');receiptChecks++;
  }
  assert(flow.run("flowTable([{ok:true,id:'metadata-absent'}],{result:true})").includes('未提供进度摘要'));
  assert(flow.run("flowTable([{valid:false,error:'ZIP校验失败'}],{result:true})").includes('摘要不可验证'));
  console.log(JSON.stringify({passed:true,deferred_workflow_cases:checks,restore_receipt_cases:receiptChecks,scope:'actual JS components with deferred requests; browser/native E2E remains separate'}));
})().catch(error=>{console.error(error);process.exitCode=1;});
