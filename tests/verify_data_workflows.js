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
  metadata.get('#manage-latest').children.find(node=>node.textContent==='已核对最新信息，重新确认上方名称和永久保留设置').listeners.click();
  assert.equal(confirmedVersion,'protected-version');assert.equal(metadata.get('#backup-label').value,'旧窗口未提交名称');checks++;
  pending=deferred();let singleReceipt;
  metadata.context.action=work=>work();metadata.context.backupFlowTicket=()=>({root:'/synthetic/a',context:'context-a',epoch:1});metadata.context.backupFlowCurrent=()=>true;
  metadata.context.recordBackupReceipt=(kind,ticket,result,submitted,changed)=>singleReceipt={kind,ticket,result,submitted,changed};metadata.context.refreshBackupReceiptScope=async()=>{};
  metadata.context.fetch=async()=>pending.promise;metadata.run("backupState={context:'context-a'}");
  const single=metadata.get('#import-backup'),oldFile={name:'single-old.zip',size:30};single.files=[oldFile];single.value='single-old.zip';
  const singleImport=single.listeners.change();single.files=[{name:'single-new.zip',size:40}];single.value='single-new.zip';
  pending.resolve({ok:true,json:async()=>({slot:1,id:'imported-original'})});await singleImport;
  assert.equal(single.value,'single-new.zip');assert.equal(singleReceipt.submitted.file_name,'single-old.zip');assert(singleReceipt.changed);checks++;
  console.log(JSON.stringify({passed:true,deferred_workflow_cases:checks,scope:'actual JS components with deferred requests; browser/native E2E remains separate'}));
})().catch(error=>{console.error(error);process.exitCode=1;});
