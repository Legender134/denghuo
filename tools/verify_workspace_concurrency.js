// Source-derived components for original naming revisions and note search.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.join(__dirname,'..'),source=fs.readFileSync(path.join(root,'web/workspace.js'),'utf8');
function extract(name){const start=source.search(new RegExp('(?:async )?function '+name+'\\('));assert(start>=0,name);const end=source.indexOf('\n}',start);assert(end>start,name);return source.slice(start,end+2);}
function controls(){const map=new Map();return id=>{if(!map.has(id))map.set(id,{value:'',textContent:'',hidden:false});return map.get(id);};}
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
      const load=vm.createContext({URLSearchParams,$:get,webDirtySummary:()=>[],post:async()=>({draft:{draft}}),getJSON:async()=>({plan:latest}),
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
  console.log(JSON.stringify({passed:true,original_and_legacy_naming_cases:checked,note_search_cases:4,scope:'actual extracted components; browser E2E pending'}));
})().catch(error=>{console.error(error);process.exitCode=1;});
