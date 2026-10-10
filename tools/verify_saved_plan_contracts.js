'use strict';
// Synthetic DOM/transport: execute production payload and late-response paths.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'..'),compare=fs.readFileSync(path.join(root,'web/compare.js'),'utf8'),workspace=fs.readFileSync(path.join(root,'web/workspace.js'),'utf8');
function extract(source,name){const start=source.search(new RegExp('(?:async )?function '+name+'\\('));assert(start>=0,name);const line=source.indexOf('\n',start),end=source.indexOf('\n}',start);return source.slice(start,source.slice(start,line).endsWith('}')?line:end+2);}
function harness(kind,id,items){
  const nodes=new Map(),pending=[],payloads=[];
  const get=key=>{if(!nodes.has(key))nodes.set(key,{value:'0',checked:false,dataset:{},innerHTML:'',textContent:'',hidden:false,disabled:false,childElementCount:0,children:[],open:false,listeners:{},setAttribute(key,value){this[key]=value;},addEventListener(event,fn){this.listeners[event]=fn;},querySelectorAll(){return [];},querySelector(){return {disabled:false};},closest(){return {hidden:false};},replaceChildren(){},append(...nodes){this.children.push(...nodes);},focus(){},scrollIntoView(){},reportValidity(){return true;},showModal(){this.open=true;},close(){this.open=false;}});return nodes.get(key);};
  const c=vm.createContext({console,URLSearchParams,JSON,$:get,$$:()=>[],state:{data:{},started:1},navigationSerial:0,
    document:{addEventListener(){},createElement(){return get('new'+nodes.size);}},window:{addEventListener(){}},
    calculationStamp:()=>({mode:'save',slot:1,modified:100}),compareCharacterReference:null,
    currentCharacterStrengthLabel:()=> '公开力量',fetch:()=>new Promise(resolve=>pending.push(resolve)),
    inlineError(node,text){node.textContent=text;},escapeHTML:String,fmtTime:String,toast(){},
    exampleHTML:()=>'',cellsText:()=>'',displayNumber:String,characterSummary:()=>'',characterClone:value=>JSON.parse(JSON.stringify(value)),
    numericalDetail:null,numericalDrafts:new Map(),numericalCalculated:new Map(),numericalFormDrafts:new Map(),fixedNumericalDrafts:new Map(),settingsDrafts:new Set(),manualUnsaved:false,
    post:async(url,payload)=>{payloads.push(JSON.parse(JSON.stringify(payload)));return {plan:{id:'a'.repeat(32),record_revision:'b'.repeat(64),...payload}};},loadWorkspace:async()=>{}});
  vm.runInContext(compare,c); // Initial catalog request deliberately stays pending.
  for(const name of ['planDraftKey','planSource','originLabel','cleanStoredOrigin','openPlanSave','savePlan'])vm.runInContext(extract(workspace,name),c);
  vm.runInContext("let planDialogSerial=0,planDraft=null;const planNameDrafts=new Map(),planNoteDrafts=new Map(),planMetaOriginals=new Map(),planLabels={equipment:'装备'};",c);
  c.items=items||['a','b'].map(side=>({key:id,name:side+'目录示例',owned:true,level:2}));
  vm.runInContext("compareItems=items;compareCatalogState='ready';compareCatalogPending=null;compareSignature='original';refreshComparisonOrigin=()=>{};",c);
  get('#compare-kind').value=kind;get('#compare-strength').value='14';
  for(const [index,side] of ['a','b'].entries()){
    get('#compare-'+side).value=String(index);get('#compare-context-'+side).dataset.identity=id;
    for(const [key,value] of Object.entries({level:'2',tier:'3',augment:'NONE',resin:'0',infusion:'0',hardened:'0',curse:'0','pair-level':'0','pair-curse':'0'}))get('#compare-'+key+'-'+side).value=value;
    get('#compare-level-known-'+side).checked=true;
  }
  return {c,get,pending,payloads,run:code=>vm.runInContext(code,c)};
}
async function generate(input){
  const h=harness(input.kind,input.id,input.items);
  if(input.planning){h.get('#compare-planning-enabled').checked=true;h.get('#compare-upgrade-budget').value='2';h.get('#compare-strength-budget').value='1';h.get('#compare-investment-mode').value=['wand','ring'].includes(input.kind)?'all':'min_strength';}
  if(input.character)h.c.compareCharacterReference={params:input.character,label:'固定角色条件'};
  const args=h.run('readComparisonArgs()');
  if(input.ack)h.c.post=async(url,payload)=>{h.payloads.push(JSON.parse(JSON.stringify(payload)));return {plan:input.ack};};
  const fields=h.run('comparisonFields()'),references=h.run('comparisonReferences()');
  assert(Object.keys(fields).every(key=>key in args));
  h.c.args=args;h.c.fields=fields;h.c.references=references;
  h.run("compareResultArgs=canonicalComparisonParams(args);compareResultFields=fields;compareResultReferences=references;compareDirty=false;compareError='';");
  h.get('#compare-save').listeners.click();h.get('#plan-name').value='五家族 '+input.kind;h.get('#plan-note').value='固定备注';await h.run('savePlan(false)');
  h.run("openPlanSave({kind:'equipment',entry:null,params:compareResultArgs,source:{mode:'save',slot:1,snapshot_at:100,fields:compareResultFields,references:compareResultReferences}},compareSavedPlan)");
  h.get('#plan-name').value='更新 '+input.kind;h.get('#plan-note').value='更新备注';await h.run('savePlan(true)');
  return {args,fields,references,payloads:h.payloads};
}
async function selfTest(){
  const id='items.weapon.melee.sword',items=['火剑','冰剑'].map((name,index)=>({key:id,name,owned:true,level:2,equipment_state:{effect_id:'items.weapon.enchantments.'+(index?'chilling':'blazing')},user_note:{title:index?'备用冰剑':'主手火剑',body:'合成用户正文',scope:'specific_item'}}));
  const h=harness('weapon',id,items),submit=h.get('#equipment-comparison').listeners.submit({preventDefault(){}});
  h.run("compareItems=[{key:'items.weapon.melee.axe',name:'后来选择'}];compareEditGeneration++;renderComparisonResult=(r,refs)=>{globalThis.renderedReferences=refs;};");
  const pending=h.pending[h.pending.length-1];pending({ok:true,json:async()=>({params:{strength:14},choices:[]})});await submit;
  assert.equal(h.c.renderedReferences.a.name,'火剑');assert(h.run('compareDirty'));assert.equal(h.run('compareResultReferences.b.user_note.title'),'备用冰剑');
  h.c.refs=h.c.renderedReferences;assert.match(h.run('comparisonReferencesText(refs)'),/未计其额外附魔 \/ 诅咒收益/);
  assert.match(h.run('comparisonReferencesText(refs)'),/主手火剑/);
  h.run("compareItems=items;rememberComparisonImport();compareResultReferences=null;");h.get('#compare-undo-import').listeners.click();assert.equal(h.run('compareResultReferences.a.name'),'火剑');
  // Source cleaners must deep-copy identity and user notes.
  h.c.origin={mode:'save',references:h.c.refs};const cleaned=h.run('cleanStoredOrigin(origin)');cleaned.references.a.name='changed';assert.equal(h.c.refs.a.name,'火剑');
  const saving=harness('weapon',id,items);saving.run("compareResultArgs=canonicalComparisonParams(readComparisonArgs());compareResultFields=comparisonFields();compareResultReferences=comparisonReferences();compareDirty=false;");
  saving.get('#compare-save').listeners.click();saving.get('#plan-name').value='提交时名称';
  let accept;saving.c.post=(url,payload)=>new Promise(resolve=>{accept=()=>resolve({plan:{id:'b'.repeat(32),...payload}});});
  const savingRequest=saving.run('savePlan(false)');saving.run('compareEditGeneration++;compareSessionUnsaved=true;compareDirty=true;');accept();await savingRequest;
  assert(saving.run('compareSessionUnsaved'));assert.equal(saving.run('compareSavedPlan'),null);
  const unfinished=harness('weapon',id,items);unfinished.c.webDirtySummary=()=>[];
  unfinished.run(extract(workspace,'collectWebDraft'));unfinished.run('compareSessionUnsaved=true');
  const draft=unfinished.run('collectWebDraft().draft');assert.equal(draft.comparison.references.b.user_note.title,'备用冰剑');
  const unavailable=harness('weapon',id,items);unavailable.c.showDetail=(name,text)=>{unavailable.c.originalText=text;};
  unavailable.c.view='library';unavailable.c.legacy={plan:{id:'1'.repeat(32),kind:'numeric',entry:'items.weapon.missiles.boomerang',name:'原名称',params:{level:3},rules_version:'2.0.0',note:'原备注',origin:{mode:'save',slot:2,snapshot_at:100}},result:null,calculation_error:'此条目不支持计算'};
  unavailable.run('let planRequest=0;');unavailable.run(extract(workspace,'openUnavailableNumericPlan'));unavailable.run(extract(workspace,'openPlan'));
  assert.equal(await unavailable.run('openPlan(legacy.plan.id,legacy)'),true);assert.match(unavailable.c.originalText,/"level": 3/);assert.match(unavailable.c.originalText,/2.0.0/);
  const [label,edit,status]=unavailable.get('#detail-rules').children,input=label.children[0];input.value='invalid';edit.listeners.click();assert.match(status.textContent,/输入仍保留/);
  input.value='{"level":4}';edit.listeners.click();assert.equal(unavailable.run('planDraft.payload.params.level'),4);assert.equal(unavailable.c.legacy.plan.params.level,3);
  console.log('saved plan frontend contracts: payload, late/edit, copy, undo and source snapshot passed');
}
async function reopen(input){
  const h=harness('weapon',input.plan.params.id_a);h.c.plan=input.plan;h.c.result=input.result;
  h.run("compareCatalog=[{id:plan.params.id_a,name:'单手剑'}];navigate=()=>{};");
  assert.equal(await h.run('openEquipmentPlan(plan,result,false)'),true);
  assert.match(h.get('#compare-result').innerHTML,/烈焰/);assert.match(h.get('#compare-copy-text').textContent,/备用冰剑/);
  assert.equal(h.run("comparisonReferences().a.user_note.title"),'主手火剑');
  return {copy:h.get('#compare-copy-text').textContent,references:h.run('comparisonReferences()')};
}
(async()=>{if(process.argv.includes('--wire')){const input=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(await generate(input)));}else if(process.argv.includes('--reopen'))process.stdout.write(JSON.stringify(await reopen(JSON.parse(fs.readFileSync(0,'utf8')))));else await selfTest();})().catch(error=>{console.error(error);process.exitCode=1;});
