// Execute the real workspace handlers on synthetic DOM controls; no browser or GUI.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/workspace.js'),'utf8');
function harness(){
  const nodes=new Map(),pending=[],messages=[],downloads=[],blobs=[];
  function element(tag='div'){
    const node={tagName:tag.toUpperCase(),id:'',value:'',textContent:'',innerHTML:'',hidden:false,checked:false,disabled:false,isConnected:true,
      dataset:{},children:[],listeners:{},queries:new Map(),open:false,
      addEventListener(event,callback){this.listeners[event]=callback;},setAttribute(key,value){this[key]=value;},
      append(...children){for(const child of children){child.parentNode=this;this.children.push(child);}},
      before(child){const parent=this.parentNode;assert(parent,'synthetic parent');child.parentNode=parent;parent.children.splice(parent.children.indexOf(this),0,child);},
      replaceChildren(...children){this.children=[];this.append(...children);},
      contains(child){return child===this||this.children.some(row=>row.contains(child));},
      remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(row=>row!==this);this.isConnected=false;},
      querySelector(selector){
        if(selector.startsWith('.'))return this.children.find(row=>(row.className||'').split(' ').includes(selector.slice(1)))||null;
        const child=this.children.find(row=>row.tagName===selector.toUpperCase());if(child)return child;
        if(selector==='button'&&this.innerHTML.includes('<button')){if(!this.queries.has(selector))this.queries.set(selector,element('button'));return this.queries.get(selector);}
        return null;
      },querySelectorAll(){return [];},showModal(){this.open=true;},
      close(){this.open=false;this.listeners.close?.();},focus(){this.focused=true;},
      click(){if(this.tagName==='A')downloads.push({href:this.href,download:this.download});return this.listeners.click?.();}};
    return node;
  }
  const get=selector=>{if(!nodes.has(selector)){const node=element();if(selector.startsWith('#'))node.id=selector.slice(1);nodes.set(selector,node);}return nodes.get(selector);};
  get('#workspace-confirm').append(get('#workspace-confirm-form'));
  const context=vm.createContext({URLSearchParams,Blob,URL:{createObjectURL(blob){blobs.push(blob);return 'blob:synthetic';},revokeObjectURL(){}},
    $:get,$$:()=>[],document:{activeElement:null,createElement:element,addEventListener(){},querySelector(){return null;}},
    window:{addEventListener(){},requestAnimationFrame:callback=>callback()},view:'settings',navigationSerial:0,token:'synthetic',panelClient:'synthetic-client',state:null,
    numericalFormDrafts:new Map(),numericalCalculated:new Map(),numericalDrafts:new Map(),fixedNumericalDrafts:new Map(),numericalDetail:null,
    compareSessionUnsaved:false,comparePending:false,settingsDrafts:new Set(),playDirty:false,manualFormGeneration:0,
    inlineError:(node,text)=>{node.textContent=text;},escapeHTML:String,fmtTime:String,toast:message=>messages.push(message),
    post:(url,payload)=>new Promise((resolve,reject)=>pending.push({url,payload,resolve,reject})),
    showReference(){throw new Error('Unavailable favorite must not open a reference');},loads:0});
  const run=code=>vm.runInContext(code,context);run(source);run('loadWorkspace=async()=>{loads++}');context.view='workspace';
  const details=()=>get('#workspace-confirm').querySelector('.workspace-recovery-preview');
  return {get,context,run,pending,messages,downloads,blobs,details};
}
const preview={expected:'a'.repeat(64),bytes:345,mode:'recover',healthy_count:3,can_export:true,
  message:'先完整保留原文件，再恢复 3 条结构健康记录',
  categories:{favorites:{healthy:1,invalid:0,ambiguous:0},recent:{healthy:1,invalid:0,ambiguous:0},plans:{healthy:1,invalid:1,ambiguous:2}},
  issues:[{category:'plans',index:2,identity:'bad-record',reason:'方案名称需要1–80个字'},
          {category:'plans',index:3,identity:'duplicate-record',reason:'身份重复冲突；所有同身份记录均不选择'}]};
const event={preventDefault(){}};
const submit=h=>h.get('#workspace-confirm-form').listeners.submit(event);
(async()=>{
  let checks=0;
  const copies=harness(),copyId='b'.repeat(64);copies.context.preview={...preview,source:'current',healthy_copies:[{id:copyId,available:true,time:123,counts:{plans:1,favorites:2,recent:0}}]};copies.run('showWorkspaceRecoveryPreview(preview)');
  const sourceSelect=copies.details().children.find(row=>row.tagName==='LABEL').children[0];sourceSelect.value=copyId;copies.get('#workspace-confirm-check').checked=true;
  const choosing=sourceSelect.listeners.change();assert(copies.get('#workspace-confirm-submit').disabled);assert(!copies.get('#workspace-confirm-check').checked);assert.equal(copies.pending[0].payload.source,copyId);
  copies.pending.shift().resolve({...copies.context.preview,source:copyId});await choosing;
  copies.get('#workspace-confirm-check').checked=true;const restoreCopy=submit(copies);assert.equal(copies.pending[0].payload.source,copyId);copies.pending.shift().resolve({mode:'recover',preserved_file:'bad.json',recovered_count:3});await restoreCopy;checks++;
  const failedSource=harness();failedSource.context.preview=copies.context.preview;failedSource.run('showWorkspaceRecoveryPreview(preview)');
  const failedSelect=failedSource.details().children.find(row=>row.tagName==='LABEL').children[0];failedSelect.value=copyId;const selecting=failedSelect.listeners.change();failedSource.pending.shift().reject(new Error('copy unavailable'));await selecting;
  assert.equal(failedSelect.value,'current');assert(!failedSource.get('#workspace-confirm-check').checked);assert.match(failedSource.get('#workspace-confirm-error').textContent,/copy unavailable/);checks++;
  const closedSource=harness();closedSource.context.preview=copies.context.preview;closedSource.run('showWorkspaceRecoveryPreview(preview)');
  const closedSelect=closedSource.details().children.find(row=>row.tagName==='LABEL').children[0];closedSelect.value=copyId;const oldChoice=closedSelect.listeners.change();closedSource.get('#workspace-confirm').close();closedSource.pending.shift().resolve({...copies.context.preview,source:copyId});await oldChoice;
  assert(!closedSource.get('#workspace-confirm').open);checks++;
  const missing=harness();missing.context.preview={...copies.context.preview,expected:'missing',bytes:0,primary_missing:true,can_repair:false,can_export:false,mode:'empty',message:'主文件缺失，请选择健康副本'};missing.run('showWorkspaceRecoveryPreview(preview)');
  assert.match(missing.get('#workspace-confirm-title').textContent,/选择健康副本/);assert(missing.get('#workspace-confirm-submit').disabled);
  assert.match(missing.get('#workspace-confirm-description').textContent,/没有主文件可保留/);assert(!/原件 0 字节/.test(missing.get('#workspace-confirm-description').textContent));
  missing.get('#workspace-confirm-check').checked=true;await submit(missing);assert.equal(missing.pending.length,0,'Missing primary cannot submit an implicit empty rebuild');
  const missingSelect=missing.details().children.find(row=>row.tagName==='LABEL').children[0];assert(missingSelect.children[0].disabled);missingSelect.value=copyId;
  const failedMissingChoice=missingSelect.listeners.change();missing.pending.shift().reject(new Error('source changed'));await failedMissingChoice;
  assert(missing.get('#workspace-confirm-submit').disabled);assert(!missing.get('#workspace-confirm-check').checked);checks++;
  missingSelect.value=copyId;const selectMissing=missingSelect.listeners.change();missing.pending.shift().resolve({...missing.context.preview,source:copyId,can_repair:true,can_export:true,mode:'recover'});await selectMissing;
  assert(!missing.get('#workspace-confirm-submit').disabled);assert(!missing.get('#workspace-confirm-check').checked);
  assert.match(missing.get('#workspace-confirm-title').textContent,/所选健康副本/);
  missing.get('#workspace-confirm-check').checked=true;const restoreMissing=submit(missing);await submit(missing);assert.equal(missing.pending.length,1,'Only one repair request while pending');
  missing.pending.shift().resolve({mode:'recover',primary_missing:true,preserved_file:null,recovered_count:3});await restoreMissing;
  assert(missing.messages.some(row=>/所选健康副本恢复 3/.test(row)));assert(!missing.messages.some(row=>/方案已删除|已完整保留原件/.test(row)));checks++;
  const normal=harness();normal.context.preview=preview;normal.run('showWorkspaceRecoveryPreview(preview)');
  assert.match(normal.get('#workspace-confirm-title').textContent,/恢复健康/);
  assert(normal.details().children.some(row=>/方案：健康 1，损坏 1，重复冲突 2/.test(row.textContent)));
  const reasons=normal.details().children.find(row=>row.tagName==='DETAILS');assert(reasons.children.some(row=>/bad-record.*方案名称/.test(row.textContent)));
  await submit(normal);assert.equal(normal.pending.length,0,'repair needs explicit checkbox');checks++;
  const exportButton=normal.details().children.find(row=>row.tagName==='BUTTON');
  const exporting=exportButton.click();assert(exportButton.disabled);assert.equal(normal.pending[0].payload.action,'repair-export');
  assert.equal(normal.pending[0].payload.expected,preview.expected);
  normal.pending.shift().resolve({content:'{"format":1}',filename:'denghuo-healthy-knowledge.json'});await exporting;
  assert.equal(await normal.blobs[0].text(),'{"format":1}');assert.equal(normal.downloads[0].download,'denghuo-healthy-knowledge.json');
  assert(normal.get('#workspace-confirm').open);assert(!normal.get('#workspace-confirm-check').checked);assert(!exportButton.disabled);checks++;
  normal.get('#workspace-confirm-check').checked=true;const repairing=submit(normal);
  assert(normal.get('#workspace-confirm-submit').disabled);assert.equal(normal.pending[0].payload.action,'repair');
  assert.equal(normal.pending[0].payload.expected,preview.expected);assert.equal(normal.pending[0].payload.confirmed,true);
  normal.pending.shift().resolve({preserved_file:'synthetic-preserved.json',mode:'recover',recovered_count:3});await repairing;
  assert(!normal.get('#workspace-confirm').open);assert(normal.messages.some(row=>/恢复 3 条健康/.test(row)));assert.equal(normal.context.loads,1);checks++;
  const failure=harness();failure.context.preview=preview;failure.run('showWorkspaceRecoveryPreview(preview)');
  failure.get('#workspace-confirm-check').checked=true;const failed=submit(failure);failure.pending.shift().reject(new Error('原资料库刚被修改，请重新预览'));await failed;
  assert(failure.get('#workspace-confirm').open);assert(!failure.get('#workspace-confirm-submit').disabled);
  assert.match(failure.get('#workspace-confirm-error').textContent,/重新预览/);assert.equal(failure.context.loads,0);checks++;
  const stale=harness();stale.context.preview=preview;stale.run('showWorkspaceRecoveryPreview(preview)');stale.get('#workspace-confirm-check').checked=true;
  const late=submit(stale);stale.get('#workspace-confirm').close();stale.run("openWorkspaceConfirmation({action:'remove',id:'new'},'新确认','新操作')");
  stale.pending.shift().resolve({preserved_file:'old-preserved.json',mode:'recover',recovered_count:3});await late;
  assert.equal(stale.get('#workspace-confirm-title').textContent,'新确认');assert(stale.get('#workspace-confirm').open);
  assert(!stale.get('#workspace-confirm-submit').disabled);assert.equal(stale.messages.length,0);assert.equal(stale.context.loads,0);checks++;
  const staleExport=harness();staleExport.context.preview=preview;staleExport.run('showWorkspaceRecoveryPreview(preview)');
  const oldExport=staleExport.details().children.find(row=>row.tagName==='BUTTON').click();staleExport.get('#workspace-confirm').close();
  staleExport.pending.shift().resolve({content:'{}',filename:'old.json'});await oldExport;assert.equal(staleExport.downloads.length,0);assert.equal(staleExport.messages.length,0);checks++;
  const left=harness(),latePreview=left.get('#workspace-repair').click();left.context.view='library';left.pending.shift().resolve(preview);await latePreview;
  assert(!left.get('#workspace-confirm').open);checks++;
  const oldError=harness(),oldRequest=oldError.get('#workspace-repair').click();oldError.run("openWorkspaceConfirmation({action:'remove'},'当前确认','保持')");
  oldError.pending.shift().reject(new Error('旧请求错误'));await oldRequest;assert.equal(oldError.get('#workspace-error').textContent,'');checks++;
  const empty=harness();empty.context.preview={...preview,mode:'empty',can_export:false,healthy_count:0,message:'未能证明有健康记录；先完整保留原文件，再建立空资料库'};
  empty.run('showWorkspaceRecoveryPreview(preview)');assert.match(empty.get('#workspace-confirm-title').textContent,/空资料库/);
  assert(!empty.details().children.some(row=>row.tagName==='BUTTON'));checks++;
  const unavailable=harness();unavailable.run("referenceList($('#favorites'),[{id:'items.retired',available:false}],'没有收藏')");
  const retained=unavailable.get('#favorites').children[0];assert.match(retained.innerHTML,/当前资料不可用/);assert.match(retained.innerHTML,/items.retired/);
  const cancel=retained.querySelector('button'),cancelling=cancel.click();assert(cancel.disabled);
  assert.equal(unavailable.pending[0].payload.entry,'items.retired');assert.equal(unavailable.pending[0].payload.enabled,false);
  unavailable.pending.shift().resolve({revision:1});await cancelling;assert(!cancel.disabled);assert.equal(unavailable.context.loads,1);checks++;
  const oldEquipment=harness();let equipmentArgs;
  oldEquipment.context.navigate=()=>{};oldEquipment.context.openEquipmentPlan=async(...args)=>{equipmentArgs=args;};
  oldEquipment.context.opened={plan:{id:'e'.repeat(32),kind:'equipment',params:{id_a:'items.retired'}},result:null,rules_changed:true,calculation_error:'请选择当前装备'};
  await oldEquipment.run('openPlan(opened.plan.id,opened,true)');assert.equal(equipmentArgs[0],oldEquipment.context.opened.plan);
  assert.equal(equipmentArgs[1],null);assert.equal(equipmentArgs[3],'请选择当前装备');checks++;
  for(const kind of ['manual','character']){
    const original=harness();let presented,copied;
    original.context.showDetail=(...args)=>{presented=args;};original.context.openPlanSave=(...args)=>{copied=args;};
    original.context.opened={plan:{id:'f'.repeat(32),kind,name:'旧条件',params:{retired_condition:1},origin:{mode:'example'},note:'原备注'},result:null,calculation_error:'当前规则不支持旧条件'};
    assert.equal(await original.run('openPlan(opened.plan.id,opened,true)'),true);
    assert.match(presented[1],/当前规则不支持旧条件/);assert.match(presented[1],/原备注/);
    const rules=original.get('#detail-rules'),label=rules.children.find(row=>row.tagName==='LABEL'),input=label.children[0],button=rules.children.find(row=>row.tagName==='BUTTON');
    input.value='{"hp":4}';button.click();assert.equal(copied[0].kind,kind);assert.equal(copied[0].params.hp,4);assert.equal(copied[0].note,'原备注');assert.equal(copied[1],null);checks++;
  }
  console.log(`Library recovery VM: ${checks} checks passed (explicit confirmation, healthy export, error/stale ownership, unavailable favorite and old equipment handoff).`);
})().catch(error=>{console.error(error);process.exitCode=1;});
