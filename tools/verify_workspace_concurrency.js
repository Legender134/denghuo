// Source-derived components for original naming revisions and note search.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.join(__dirname,'..'),source=fs.readFileSync(path.join(root,'web/workspace.js'),'utf8');
function extract(name){const start=source.search(new RegExp('(?:async )?function '+name+'\\('));assert(start>=0,name);const end=source.indexOf('\n}',start);assert(end>start,name);return source.slice(start,end+2);}
function controls(){const map=new Map();return id=>{if(!map.has(id))map.set(id,{value:'',textContent:'',hidden:false});return map.get(id);};}
function recoveryHarness(){
  const elements=new Map(),events=new Map(),messages=[],pending=[];
  function element(id=''){return {id,value:'',checked:false,disabled:false,hidden:false,dataset:{},children:[],listeners:{},options:[],textContent:'',innerHTML:'',open:false,
    addEventListener(name,fn){this.listeners[name]=fn;},querySelectorAll(){return [];},querySelector(){return null;},append(...rows){this.children.push(...rows);this.options.push(...rows);},replaceChildren(...rows){this.children=rows;},focus(){},close(){this.open=false;},showModal(){this.open=true;},scrollIntoView(){}};}
  const get=selector=>{if(!elements.has(selector))elements.set(selector,element(selector.replace(/^#/,'')));return elements.get(selector);};
  const hp=element();hp.name='hp';hp.value='20';hp.closest=()=>get('#manual-form');get('#manual-form').querySelectorAll=()=>[hp];
  const context=vm.createContext({URLSearchParams,$:get,$$:()=>[],document:{activeElement:null,createElement:()=>element(),addEventListener(name,fn){if(!events.has(name))events.set(name,[]);events.get(name).push(fn);}},
    window:{addEventListener(){},requestAnimationFrame:fn=>fn()},view:'workspace',navigationSerial:0,token:'synthetic',panelClient:'synthetic-client',state:null,
    numericalFormDrafts:new Map(),numericalCalculated:new Map(),numericalDrafts:new Map(),fixedNumericalDrafts:new Map(),numericalDetail:null,
    compareSessionUnsaved:false,comparePending:false,settingsDrafts:new Set(),playDirty:false,manualFormGeneration:0,
    inlineError:(node,text)=>{node.textContent=text;},escapeHTML:String,fmtTime:String,toast:text=>messages.push(text),
    navigate:next=>{context.view=next;context.navigationSerial++;},post:()=>new Promise(resolve=>pending.push(resolve))});
  const run=code=>vm.runInContext(code,context);run(source);
  return {get,hp,context,run,messages,pending,input(value){hp.value=value;const event={target:hp};for(const fn of events.get('input')||[])fn(event);get('#manual-form').listeners.input(event);}};
}
function savedManualDraft(value='8'){return {draft:{draft_kind:'web-session',draft:{format:2,schema:'denghuo-web-session',manual:{hp:[{value,checked:false}]},numeric:[]}}};}
(async()=>{
  const context=vm.createContext({});vm.runInContext(extract('filterWorkspacePlans'),context);
  const rows=[{id:'a',name:'Alpha',kind:'numeric',updated:20,note:'蛇层备选\nTARGET Beta'},
    {id:'b',name:'Beta',kind:'alchemy',updated:30,note:'蛇层备选'},{id:'c',name:'Gamma',kind:'numeric',updated:10}];
  context.rows=rows;
  assert.deepEqual(Array.from(vm.runInContext("filterWorkspacePlans(rows,' 蛇层备选 ').map(r=>r.id)",context)),['b','a']);
  assert.deepEqual(Array.from(vm.runInContext("filterWorkspacePlans(rows,'target beta','numeric').map(r=>r.id)",context)),['a']);
  assert.deepEqual(Array.from(vm.runInContext("filterWorkspacePlans(rows,'蛇层备选','all','name').map(r=>r.id)",context)),['a','b']);
  assert.equal(rows[0].note,'蛇层备选\nTARGET Beta');
  let checked=0;
  for(const kind of ['numeric','equipment','manual','alchemy','character']){
    const get=controls();get('#plan-name').value='B 未完成';get('#plan-note').value='B 原始备注';
    const prior={id:'a'.repeat(32),record_revision:'1'.repeat(64),kind,name:'原名称',note:'原备注',origin:{mode:'example'}};
    const payload={kind,entry:kind==='numeric'?'items.potions.potionofhealing':null,params:{hp:10},source:prior.origin};
    const capture=vm.createContext({$:get,webDirtySummary:()=>[],fixedNumericalDrafts:new Map(),numericalFormDrafts:new Map(),
      numericalCalculated:new Map(),numericalDrafts:new Map(),numericalDetail:null,manualUnsaved:false,compareSessionUnsaved:false,
      settingsDrafts:new Map(),planNameDrafts:new Map(),planNoteDrafts:new Map(),planMetaOriginals:new Map(),planDraft:{payload,existing:prior}});
    vm.runInContext(extract('collectWebDraft'),capture);
    const raw=vm.runInContext('collectWebDraft().draft',capture);
    assert.equal(raw.open_plan.existing_revision,prior.record_revision,kind);
    const latest={...prior,record_revision:'2'.repeat(64),name:'A 新名称',note:'A 新备注',params:{hp:20}};
    for(const legacy of [false,true]){
      const draft=JSON.parse(JSON.stringify(raw));if(legacy)delete draft.open_plan.existing_revision;
      let opened,warning='';
      const load=vm.createContext({unfinishedDraftRequest:0,draftRecoveryEditGeneration:0,navigationSerial:0,webEditingFrozen:false,URLSearchParams,$:get,webDirtySummary:()=>[],post:async()=>({draft:{draft}}),getJSON:async()=>({plan:latest}),
        openPlanSave:(args,existing,name)=>{opened={args,existing,name};},toast(){},inlineError:(target,text)=>{if(target===get('#plan-error'))warning=text;},
        planNameDrafts:new Map(),planNoteDrafts:new Map(),planMetaOriginals:new Map()});
      vm.runInContext(extract('loadUnfinishedDraft'),load);await vm.runInContext('loadUnfinishedDraft("own-draft")',load);
      assert.equal(opened.existing.record_revision,legacy?'':prior.record_revision,kind);
      assert.notEqual(opened.existing.record_revision,latest.record_revision,kind);
      assert.equal(opened.args.params.hp,10);assert.equal(opened.existing.note,'原备注');
      assert.equal(get('#plan-name').value,'B 未完成');assert.equal(get('#plan-note').value,'B 原始备注');
      assert.match(warning,/关联方案已变化/);checked++;
    }
  }
  let recoveryCases=0;
  const changed=recoveryHarness(),original=savedManualDraft();
  const restoring=changed.run('loadUnfinishedDraft("original")');changed.input('17');changed.pending[0](original);await restoring;
  assert.equal(changed.hp.value,'17');assert(changed.run('manualUnsaved'));assert.match(changed.get('#draft-error').textContent,/新编辑|当前输入/);
  assert(!changed.messages.some(text=>text.startsWith('已找回原始草稿')));assert.equal(original.draft.draft.manual.hp[0].value,'8');recoveryCases++;
  const normal=recoveryHarness(),loading=normal.run('loadUnfinishedDraft("original")');normal.pending[0](savedManualDraft());await loading;
  assert.equal(normal.hp.value,'8');assert(normal.run('manualUnsaved'));assert(normal.messages.some(text=>text.startsWith('已找回原始草稿')));recoveryCases++;
  const dirty=recoveryHarness();dirty.input('17');await dirty.run('loadUnfinishedDraft("original")');
  assert.equal(dirty.pending.length,0);assert.equal(dirty.hp.value,'17');assert.match(dirty.get('#draft-error').textContent,/当前有未保存草稿/);recoveryCases++;
  const moved=recoveryHarness(),oldPage=moved.run('loadUnfinishedDraft("original")');moved.context.navigationSerial++;moved.pending[0](savedManualDraft());await oldPage;
  assert.equal(moved.hp.value,'20');assert(!moved.messages.some(text=>text.startsWith('已找回原始草稿')));recoveryCases++;
  const concurrent=recoveryHarness(),first=concurrent.run('loadUnfinishedDraft("first")'),second=concurrent.run('loadUnfinishedDraft("second")');
  concurrent.pending[1](savedManualDraft('9'));await second;concurrent.pending[0](savedManualDraft('8'));await first;assert.equal(concurrent.hp.value,'9');recoveryCases++;
  const withNaming=recoveryHarness();withNaming.context.getJSON=async()=>({plan:{id:'c'.repeat(32),kind:'manual',record_revision:'d'.repeat(64),name:'original',note:'',origin:{mode:'example'}}});
  withNaming.context.openPlanSave=()=>{};withNaming.context.namingDraft=savedManualDraft();
  withNaming.context.namingDraft.draft.draft.open_plan={payload:{kind:'manual'},existing_id:'c'.repeat(32),existing_revision:'d'.repeat(64),name:'unfinished name',note:'unfinished note'};
  const restoreWithNaming=withNaming.run('loadUnfinishedDraft("manual-and-name")');withNaming.pending[0](withNaming.context.namingDraft);await restoreWithNaming;
  assert.equal(withNaming.hp.value,'8');assert.equal(withNaming.context.view,'manual');assert.equal(withNaming.get('#plan-name').value,'unfinished name');
  assert.equal(withNaming.get('#draft-error').textContent,'');assert(withNaming.messages.some(text=>text.startsWith('已找回原始草稿')));recoveryCases++;
  const characterSource=fs.readFileSync(path.join(root,'web/character.js'),'utf8');
  function characterHarness(){
    const h=recoveryHarness();h.context.document.createElement=()=>h.get('option-'+Math.random());h.context.cleanStoredOrigin=value=>value||{mode:'example'};
    h.context.getJSON=()=>new Promise(resolve=>h.pending.push(resolve));h.run(characterSource);
    h.context.plan={id:'c'.repeat(32),name:'saved character',params:{format:1,base_strength:8,rings:[],strongman:0,adrenaline:0,magic_immune:false,spirit_form:false,spirit_ring:null,spirit_level:null,spirit_cursed:null},origin:{mode:'example'}};
    h.context.result={params:h.context.plan.params,strength:{usable:true,effective:8,components:{base:8,might_rings:0,strongman:0,adrenaline:0}},boundary:'synthetic'};return h;
  }
  const character=characterHarness(),opening=character.run('openCharacterPlan(plan,result,false)');
  character.get('#character-base').value='17';character.get('#character-form').listeners.input();character.pending[0]({entries:[]});assert.equal(await opening,false);
  assert.equal(character.get('#character-base').value,'17');assert(character.run('characterDirty&&characterUnsaved'));assert.match(character.get('#character-error').textContent,/新编辑/);recoveryCases++;
  const unchanged=characterHarness(),openingNormally=unchanged.run('openCharacterPlan(plan,result,false)');unchanged.pending[0]({entries:[]});assert.equal(await openingNormally,true);
  assert.equal(Number(unchanged.get('#character-base').value),8);assert(!unchanged.run('characterDirty||characterUnsaved'));recoveryCases++;
  const dependency=characterHarness();dependency.context.raw={format:1,form:{},saved:{id:'c'.repeat(32),record_revision:'d'.repeat(64)}};
  dependency.context.restoreNamedForm=()=>{throw new Error('New input must not be overwritten');};
  const restoreCharacter=dependency.run('restoreCharacterDraft(raw)');dependency.pending[0]({entries:[]});await new Promise(resolve=>setImmediate(resolve));
  dependency.get('#character-base').value='17';dependency.get('#character-form').listeners.input();dependency.pending[1]({plan:{kind:'character'}});
  await assert.rejects(restoreCharacter,/角色条件已修改/);assert.equal(dependency.get('#character-base').value,'17');assert(dependency.run('characterUnsaved'));recoveryCases++;
  console.log(JSON.stringify({passed:true,original_and_legacy_naming_cases:checked,note_search_cases:4,recovery_race_cases:recoveryCases,scope:'actual components with deferred IO; browser E2E recorded separately'}));
})().catch(error=>{console.error(error);process.exitCode=1;});
