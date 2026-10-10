// Isolated component tests: no browser, user settings, or game manipulation.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'..');
function element(id=''){
  return {id,value:'',textContent:'',className:'',innerHTML:'',childElementCount:0,hidden:false,disabled:false,
    checked:false,dataset:{},open:true,isConnected:true,listeners:{},children:[],
    classList:{toggle(){},contains(){return false;}},closest(){return this;},replaceChildren(...items){this.innerHTML='';this.children=[...items];this.childElementCount=items.length;},append(...items){this.children.push(...items);this.childElementCount=this.children.length;},
    close(){this.open=false;},showModal(){this.open=true;},setAttribute(name,value){this[name]=value;},getAttribute(name){return this[name]??null;},
    validity:{valid:true},reportValidity(){return this.validity.valid;},focus(){this.focused=true;},
    addEventListener(name,fn){this.listeners[name]=fn;},querySelectorAll(){return [];},contains(){return false;},
    querySelector(selector){return selector.startsWith('option[')?element():null;},remove(){},insertAdjacentHTML(){}};
}
function harness(){
  const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,element(id.replace(/^#/,'')));return elements.get(id);};
  const context=vm.createContext({URL,URLSearchParams,Map,Set,Number,String,Math,Promise,JSON,console,
    compareCharacterReference:null,manualCharacterReference:null,
    characterClone:value=>value==null?null:structuredClone(value),
    $:get,$$:()=>[],document:{activeElement:null,createElement:()=>element(),createTextNode:text=>({textContent:text})},escapeHTML:String,fmtTime:String,state:null,fetch:async()=>({ok:true,json:async()=>({entries:[]})})});
  return {elements,get,context,run:code=>vm.runInContext(code,context),load:name=>vm.runInContext(fs.readFileSync(path.join(root,'web',name),'utf8'),context)};
}
function stamp(){return {modified:100,active_slot:1,settings:{mode:'save'},revision:1,started:90,stale:false,
  data:{hero:{level:1,ht:20,hp:10,strength:10},depth:1,items:[]}};}
async function verifyComparisonPlanOpenings(){
const entries=[['items.weapon.melee.shortsword','shortsword'],['items.weapon.melee.battleaxe','battleaxe'],['items.wands.wandoffireblast','fireblast'],['items.wands.wandofprismaticlight','prismatic']].map(([id,name])=>({id,name}));
const result={family:'weapon',choices:[{name:'shortsword',level:0,upgrade_risk:0,current_metrics:[],upgraded_metrics:[]},{name:'battleaxe',level:5,upgrade_risk:0,current_metrics:[],upgraded_metrics:[]}],rows:[],notice:'',version:'4.0.2'};
const schema={inputs:[{key:'hp',label:'生命',value:10,min:0,max:100},{key:'max_hp',label:'最大生命',value:100,min:1,max:1000}]};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function plan(id='saved-11',strength=11,wand=false){return {id,kind:'equipment',name:id,origin:{mode:'example'},params:{strength,id_a:entries[wand?2:0].id,id_b:entries[wand?3:1].id,level_a:0,level_b:5,tier_a:3,tier_b:3,mastery_a:'0',mastery_b:'0',augment_a:'NONE',augment_b:'NONE',level_known_a:'1',level_known_b:'1',hp_a:7,hp_b:8,max_hp_a:100,max_hp_b:100}};}
function setup(options={}){
  const h=harness(),catalog=[],schemas=[],comparisons=[];
  const controls=[h.get('#compare-strength'),h.get('#compare-level-a'),h.get('#compare-level-b')];
  h.get('#equipment-comparison').querySelectorAll=()=>controls;
  Object.assign(h.context,{navigationSerial:0,webEditingFrozen:false,displayNumber:String,originLabel:()=> 'saved reference',calculationStamp:()=>null,exampleHTML:()=>'',inlineError:(target,message)=>{target.textContent=message;}});
  h.get('.comparison-panel').scrollIntoView=()=>{};h.get('#compare-kind').value='weapon';h.get('#compare-strength').value='10';
  h.context.fetch=url=>{
    if(url.startsWith('/api/compare?'))return new Promise(resolve=>comparisons.push(resolve));
    const response={ok:true,json:async()=>({entries:entries.filter(item=>url.includes(item.id.startsWith('items.wands.')?'items.wands.':'items.weapon.melee.'))})};
    return options.catalogDeferred?new Promise(resolve=>catalog.push(()=>resolve(response))):Promise.resolve(response);
  };
  h.context.getJSON=url=>options.schemasDeferred?new Promise((resolve,reject)=>schemas.push({url,resolve,reject})):Promise.resolve(structuredClone(schema));
  h.load('compare.js');
  h.context.plan=plan();h.context.result=structuredClone(result);
  const input=(value='17')=>{h.get('#compare-strength').value=value;h.get('#equipment-comparison').listeners.input({target:h.get('#compare-strength')});};
  return {h,catalog,schemas,comparisons,input,controls,open:p=>{h.context.plan=p||plan();return h.run('openEquipmentPlan(plan,result,false)');},ready:()=>h.run('comparisonReady')};
}
  const checks=[];
  async function test(name,fn){await fn();checks.push(name);}
  await test('new input during catalog read remains dirty and unsaved',async()=>{
    const t=setup({catalogDeferred:true}),opening=t.open();t.input();t.catalog.forEach(done=>done());assert.equal(await opening,false);assert.equal(t.h.get('#compare-strength').value,'17');assert(t.h.run('compareDirty&&compareSessionUnsaved'));assert.equal(t.h.run('compareSavedPlan'),null);
  });
  await test('navigation during catalog read cancels saved-plan application',async()=>{
    const t=setup({catalogDeferred:true}),opening=t.open();t.h.run('navigationSerial++');t.catalog.forEach(done=>done());assert.equal(await opening,false);assert.equal(t.h.run('compareSavedPlan'),null);
  });
  await test('schema wait applies no saved fields and preserves new input',async()=>{
    const t=setup({schemasDeferred:true});await t.ready();t.h.get('#compare-level-a').value='23';const opening=t.open(plan('wand',11,true));await tick();assert.equal(t.schemas.length,2);assert.equal(t.h.get('#compare-kind').value,'weapon');assert.equal(t.h.get('#compare-level-a').value,'23');t.input();t.schemas.forEach(request=>request.resolve(structuredClone(schema)));assert.equal(await opening,false);assert.equal(t.h.get('#compare-strength').value,'17');assert.equal(t.h.get('#compare-level-a').value,'23');assert(t.h.run('compareDirty&&compareSessionUnsaved'));
  });
  await test('navigation during schema read leaves original form',async()=>{
    const t=setup({schemasDeferred:true});await t.ready();const opening=t.open(plan('wand',11,true));await tick();t.h.run('navigationSerial++');t.schemas.forEach(request=>request.resolve(structuredClone(schema)));assert.equal(await opening,false);assert.equal(t.h.get('#compare-kind').value,'weapon');assert.equal(t.h.run('compareSavedPlan'),null);
  });
  await test('newer plan wins when previous schemas arrive last',async()=>{
    const t=setup({schemasDeferred:true});await t.ready();const first=t.open(plan('old-wand',11,true));await tick();assert.equal(t.schemas.length,2);assert.equal(await t.open(plan('new-weapon',19)),true);t.schemas.forEach(request=>request.resolve(structuredClone(schema)));assert.equal(await first,false);assert.equal(t.h.get('#compare-strength').value,'19');assert.equal(t.h.run('compareSavedPlan.id'),'new-weapon');assert.equal(t.h.get('#compare-kind').value,'weapon');
  });
  await test('normal saved weapon open returns true and marks matching fields saved',async()=>{
    const t=setup();await t.ready();assert.equal(await t.open(),true);assert.equal(t.h.get('#compare-strength').value,'11');assert.equal(t.h.run('compareSavedPlan.id'),'saved-11');assert(!t.h.run('compareDirty||compareSessionUnsaved'));
  });
  await test('normal saved wand open installs both schemas with correct side keys',async()=>{
    const t=setup();await t.ready();assert.equal(await t.open(plan('wand',11,true)),true);assert.equal(t.h.get('#compare-kind').value,'wand');assert(t.h.get('#compare-context-a').innerHTML.includes('data-compare-key="hp_a"'));assert(t.h.get('#compare-context-b').innerHTML.includes('data-compare-key="hp_b"'));assert(t.h.get('#compare-context-a').innerHTML.includes('data-compare-key="charges_a"'));assert.equal(t.h.get('#compare-context-a').dataset.identity,entries[2].id);
  });
  await test('failed schema load reports failure and keeps original inputs',async()=>{
    const t=setup({schemasDeferred:true});await t.ready();t.h.get('#compare-strength').value='13';const opening=t.open(plan('wand',11,true));await tick();t.schemas[0].reject(new Error('资料读取失败'));t.schemas[1].resolve(structuredClone(schema));assert.equal(await opening,false);assert.equal(t.h.get('#compare-kind').value,'weapon');assert.equal(t.h.get('#compare-strength').value,'13');assert.equal(t.h.run('compareError'),'资料读取失败');assert.equal(t.h.run('compareSavedPlan'),null);
  });
  await test('saved plan supersedes calculation and releases all pending controls',async()=>{
    const t=setup();await t.ready();const submitting=t.h.get('#equipment-comparison').listeners.submit({preventDefault(){}});assert(t.h.run('comparePending'));assert(t.controls.every(control=>control.disabled));assert.equal(await t.open(),true);assert(!t.h.run('comparePending'));assert(!t.h.get('#compare-submit').disabled);assert(t.controls.every(control=>!control.disabled));t.comparisons[0]({ok:false,json:async()=>({error:'old request failed'})});await submitting;assert(!t.h.run('comparePending'));assert.equal(t.h.run('compareError'),'');assert.equal(t.h.run('compareSavedPlan.id'),'saved-11');
  });
  await test('exit editing freeze cancels a pending plan application',async()=>{
    const t=setup({catalogDeferred:true}),opening=t.open();t.h.run('webEditingFrozen=true');t.catalog.forEach(done=>done());assert.equal(await opening,false);assert.equal(t.h.run('compareSavedPlan'),null);
  });
  await test('change event invalidates a pending plan without a text input event',async()=>{
    const t=setup({catalogDeferred:true}),opening=t.open();t.h.get('#equipment-comparison').listeners.change({target:t.h.get('#compare-kind')});t.catalog.forEach(done=>done());assert.equal(await opening,false);assert.equal(t.h.run('compareSavedPlan'),null);
  });
  await test('explicit resource import cancels a pending saved plan',async()=>{
    const t=setup({catalogDeferred:true}),opening=t.open();t.h.context.state={data:{items:[]}};t.h.get('#compare-use-resources').listeners.click();t.catalog.forEach(done=>done());assert.equal(await opening,false);assert(t.h.run('compareSessionUnsaved'));assert.equal(t.h.run('compareSavedPlan'),null);
  });
  await test('character import outside comparison form cancels an older open',async()=>{
    const t=setup({catalogDeferred:true}),opening=t.open();
    Object.assign(t.h.context,{characterReference:()=>({params:{base_strength:19},source:{mode:'manual'}}),characterResult:{strength:{effective:19}},navigate(){},renderComparisonCharacterReference(){}});
    const code=fs.readFileSync(path.join(root,'web/character.js'),'utf8');
    const start=code.indexOf("$('#character-to-comparison').addEventListener");
    const end=code.indexOf('\n',code.indexOf("$('#compare-character-clear').addEventListener",start));
    t.h.run(code.slice(start,end));t.h.get('#character-to-comparison').listeners.click();t.catalog.forEach(done=>done());
    assert.equal(await opening,false);assert.equal(t.h.get('#compare-strength').value,'19');assert.equal(t.h.context.compareCharacterReference.params.base_strength,19);assert(t.h.run('compareSessionUnsaved'));assert.equal(t.h.run('compareSavedPlan'),null);
  });
  await test('clearing a character reference outside comparison form cancels an older open',async()=>{
    const t=setup({catalogDeferred:true}),opening=t.open();
    t.h.context.compareCharacterReference={params:{base_strength:19}};t.h.context.renderComparisonCharacterReference=()=>{};
    const code=fs.readFileSync(path.join(root,'web/character.js'),'utf8');
    const start=code.indexOf("$('#compare-character-clear').addEventListener");const end=code.indexOf('\n',start);
    t.h.run(code.slice(start,end));t.h.get('#compare-character-clear').listeners.click();t.catalog.forEach(done=>done());
    assert.equal(await opening,false);assert.equal(t.h.context.compareCharacterReference,null);assert(t.h.run('compareSessionUnsaved'));assert.equal(t.h.run('compareSavedPlan'),null);
  });
  await test('workspace reports a failed equipment, alchemy or character application explicitly',async()=>{
    for(const kind of ['equipment','alchemy','character']){
    const t=setup();t.h.context.view='inventory';Object.assign(t.h.context,{rememberWorkspaceDetailFocus(){},getJSON:async()=>({plan:{...plan(),kind},result}),navigate(){},openEquipmentPlan:async()=>false,openAlchemyPlan:async()=>false,openCharacterPlan:async()=>false});t.h.run('let planRequest=0;');
    const code=fs.readFileSync(path.join(root,'web/workspace.js'),'utf8');t.h.run(code.slice(code.indexOf('async function openPlan('),code.indexOf('function manualPayload(')));t.h.get('#detail-dialog').open=false;t.h.get('#plan-dialog').open=false;assert.equal(await t.h.run("openPlan('saved-11',null,true)"),false);
    }
  });
  console.log(JSON.stringify({comparison_saved_plan_race_cases:checks.length}));
}
function verifyNavigationHistory(){
  function setup(initial='#overview'){
    const h=harness(),events=new Map(),stack=[initial],loads=[];let index=0;
    h.context.location={hash:initial,search:''};
    h.context.history={scrollRestoration:'auto',replaceState(_state,_title,url){stack[index]=url;h.context.location.hash=url;},pushState(_state,_title,url){stack.splice(index+1);stack.push(url);index++;h.context.location.hash=url;}};
    h.context.document={querySelector:h.get,querySelectorAll:()=>[],addEventListener(){}};
    h.context.window={scrollY:0,scrollTo({top}){this.scrollY=top;},addEventListener(name,fn){if(!events.has(name))events.set(name,[]);events.get(name).push(fn);}};
    for(const name of ['loadWorkspace','searchLibrary','renderInventory','loadSettings','loadBackups','loadMigration','loadAlchemy','loadHelp','loadPlaySettings'])h.context[name]=()=>loads.push(name);
    const source=fs.readFileSync(path.join(root,'web/app.js'),'utf8');h.run(source.slice(0,source.indexOf('function handlePageShortcut(')));
    h.run("navigate(location.hash.slice(1),'replace')");
    return {h,stack,loads,move(delta){index+=delta;h.context.location.hash=stack[index];for(const name of ['popstate','hashchange'])for(const fn of events.get(name)||[])fn();},hash(value){h.context.history.pushState(null,'',value);for(const fn of events.get('hashchange')||[])fn();}};
  }
  const t=setup(),h=t.h;h.get('#manual-hp').value='17';assert.equal(h.context.history.scrollRestoration,'manual');
  h.context.window.scrollY=120;h.run("navigate('library')");h.context.window.scrollY=240;h.run("navigate('workspace')");h.context.window.scrollY=360;h.run("navigate('alchemy');navigate('alchemy')");
  assert.deepEqual(t.stack,['#overview','#library','#workspace','#alchemy']);
  const serial=h.run('navigationSerial'),loads=t.loads.length;t.move(-1);assert.equal(h.run('view'),'workspace');assert.equal(h.context.window.scrollY,360);assert.equal(h.run('navigationSerial'),serial+1);assert.equal(t.loads.length,loads+1,'popstate plus hashchange renders once');
  t.move(-1);assert.equal(h.run('view'),'library');assert.equal(h.context.window.scrollY,240);t.move(1);t.move(1);assert.equal(h.run('view'),'alchemy');assert.equal(h.get('#manual-hp').value,'17');
  t.hash('#invalid-tool');assert.equal(h.run('view'),'overview');assert.equal(t.stack.at(-1),'#overview');assert.equal(t.stack.length,5,'normalize an existing unknown hash rather than push a second entry');
  const deep=setup('#alchemy');assert.equal(deep.h.run('view'),'alchemy');assert.equal(deep.stack.length,1,'opening a deep link does not add a phantom overview visit');
  console.log(JSON.stringify({internal_navigation_history:true}));
}
async function verifyComparisonRecovery(){
  const markup=fs.readFileSync(path.join(root,'web/index.html'),'utf8').split('<form id="equipment-comparison">')[1].split('</form>')[0];
  const entries=['items.weapon.melee.shortsword','items.weapon.melee.battleaxe','items.wands.wandoffireblast','items.wands.wandofprismaticlight','items.weapon.missiles.shuriken','items.weapon.missiles.trident','items.weapon.missiles.boomerang','items.weapon.missiles.darts.dart','items.weapon.missiles.shuriken$shurikeninstanttracker'].map(id=>({id,name:id}));
  function setup(){
    const h=harness(),dynamic={a:[],b:[]};let catalogCalls=0,schemaCalls=0,failCatalog=true,failSchema=true;
    const controls=[...markup.matchAll(/<(input|select)\b[^>]*\bid="([^"]+)"[^>]*>/g)].map(match=>{const input=h.get('#'+match[2]);input.value=match[0].match(/\bvalue="([^"]*)"/)?.[1]||'';return input;});
    for(const side of ['a','b'])Object.defineProperty(h.get('#compare-context-'+side),'innerHTML',{get(){return this.html||'';},set(html){this.html=html;dynamic[side]=[...html.matchAll(/<input[^>]*data-compare-key="([^"]+)"[^>]*value="([^"]*)"/g)].map(match=>{const input=element();input.dataset.compareKey=match[1];input.value=match[2];return input;});}});
    h.context.$$=selector=>selector.startsWith('#compare-context-a')?dynamic.a:selector.startsWith('#compare-context-b')?dynamic.b:[...controls,...dynamic.a,...dynamic.b];
    h.get('#equipment-comparison').querySelectorAll=()=>[...controls,...dynamic.a,...dynamic.b];
    Object.assign(h.context,{navigationSerial:0,calculationStamp:()=>null,displayNumber:String,exampleHTML:()=>'',inlineError:(target,text)=>target.textContent=text,
      fetch:async url=>{if(url.startsWith('/api/compare?'))return {ok:false,json:async()=>({error:'controlled calculation failure'})};catalogCalls++;const q=new URLSearchParams(url.split('?')[1]).get('q');if(q==='items.wands.'&&failCatalog){failCatalog=false;return {ok:false};}return {ok:true,json:async()=>({entries:entries.filter(row=>row.id.startsWith(q))})};},
      getJSON:async url=>{schemaCalls++;if(url.includes('wandoffireblast')&&failSchema){failSchema=false;throw Error('controlled schema failure');}return {inputs:[{key:'hp',label:'生命',value:10,min:0,max:100}]};}});
    h.context.navigate=()=>{h.context.navigationSerial++;};h.get('.comparison-panel').scrollIntoView=()=>{};
    h.get('#compare-kind').value='weapon';h.get('#compare-strength').value='10';h.load('compare.js');
    return {h,dynamic,catalogCalls:()=>catalogCalls,schemaCalls:()=>schemaCalls};
  }
  const tick=()=>new Promise(resolve=>setImmediate(resolve)),t=setup(),h=t.h;
  assert.equal(await h.run('comparisonReady'),false);assert(!h.get('#compare-retry').hidden);
  for(const [id,value] of [['compare-level-a','23'],['compare-strength','17'],['compare-augment-a','SPEED']]){h.get('#'+id).value=value;h.get('#equipment-comparison').listeners.input({target:h.get('#'+id)});}
  await Promise.all([h.get('#compare-retry').listeners.click(),h.get('#compare-retry').listeners.click()]);
  assert.equal(t.catalogCalls(),10,'concurrent retries share one five-category load');
  assert.equal(h.get('#compare-level-a').value,'23');assert.equal(h.get('#compare-strength').value,'17');assert.equal(h.get('#compare-augment-a').value,'SPEED');
  h.run('renderEquipmentComparison();renderEquipmentComparison();renderEquipmentComparison()');assert.equal(t.catalogCalls(),10,'rendering must not retry settled catalog requests');
  h.get('#compare-kind').value='missile';h.get('#compare-kind').listeners.change();assert.equal(h.run('compareItems.length'),2,'exclude darts, obsolete and nested types');assert(!h.get('#compare-mastery-a').disabled);
  h.context.state={data:{items:[{key:'items.wands.wandoffireblast',name:'A',known:true,available:true,location:'背包',level:0},{key:'items.wands.wandofprismaticlight',name:'B',known:true,available:true,location:'背包',level:0}]}};
  h.get('#compare-kind').value='wand';h.get('#compare-kind').listeners.change();await tick();
  assert.equal(t.schemaCalls(),2);assert.match(h.get('#compare-status').textContent,/A 的条件资料读取失败/);assert.throws(()=>h.run('readComparisonArgs()'),/读取失败/);
  const kept=t.dynamic.b[0];kept.value='27';await h.get('#compare-retry').listeners.click();assert.equal(t.schemaCalls(),3,'retry only failed A');assert.equal(t.dynamic.b[0],kept);assert.equal(kept.value,'27');assert(h.get('#compare-retry').hidden);
  const charge=t.dynamic.a.find(input=>input.dataset.compareKey==='charges_a');charge.value='';
  h.get('#compare-kind').value='weapon';h.get('#compare-kind').listeners.change();assert(charge.disabled,'hidden wand fields do not validate a melee comparison');assert(h.get('#compare-tier-a').disabled);
  await h.get('#equipment-comparison').listeners.submit({preventDefault(){}});assert(charge.disabled,'request finally reapplies applicability');
  h.get('#compare-kind').value='wand';h.get('#compare-kind').listeners.change();assert.equal(charge.value,'');assert(!charge.disabled,'switching back retains and validates raw wand input');
  const saved=setup();await saved.h.run('comparisonReady');saved.h.context.params={id_a:entries[0].id,id_b:entries[1].id,strength:19,level_a:2,level_b:3,tier_a:3,tier_b:3,mastery_a:'0',mastery_b:'0',augment_a:'NONE',augment_b:'NONE'};
  assert.equal(await saved.h.run('fillComparisonParams(params)'),true,'explicit plan opening retries a failed startup catalog');assert.equal(saved.h.get('#compare-strength').value,'19');assert.equal(saved.catalogCalls(),10);
  const firstMissile={key:entries[4].id,name:'手里剑 +2',known:true,available:true,location:'背包',level:2,mastery:false,augmentation:'NONE'};
  h.context.state={data:{items:[firstMissile,{...firstMissile,name:'手里剑 +7',level:7,mastery:true,augmentation:'SPEED'},{...firstMissile,key:entries[5].id,name:'三叉戟 · 等级未知',level:null}]}};
  h.context.selectedItem=h.context.state.data.items[1];assert.equal(await h.run('compareInventoryItem(selectedItem)'),true);
  assert.equal(h.get('#compare-kind').value,'missile');assert.equal(Number(h.run('readComparisonArgs().level_a')),7);assert.equal(h.run('readComparisonArgs().level_known_a'),'1');assert(h.get('#compare-mastery-a').checked);assert.equal(h.get('#compare-augment-a').value,'SPEED');assert(h.run('compareImportUndo!==null&&compareSessionUnsaved'));
  h.get('#compare-level-a').value='9';h.get('#equipment-comparison').listeners.input({target:h.get('#compare-level-a')});assert.equal(h.run('readComparisonArgs().level_known_a'),'0','manual missile grade remains an assumption');
  h.context.params={id_a:entries[4].id,id_b:entries[5].id,strength:19,level_a:7,level_b:0,tier_a:3,tier_b:3,mastery_a:'1',mastery_b:'0',augment_a:'SPEED',augment_b:'NONE',level_known_a:'1',level_known_b:'0',planning:'1',upgrade_budget:3,strength_budget:1,investment_mode:'all'};
  assert.equal(await h.run('fillComparisonParams(params)'),true);assert.equal(h.run('readComparisonArgs().level_known_a'),'1');assert.equal(h.run('readComparisonArgs().level_known_b'),'0');assert.equal(h.run('canonicalComparisonParams(readComparisonArgs()).level_known_a'),'1');assert.equal(h.get('#compare-investment-mode').value,'all');
  h.context.calculationStamp=()=>({revision:h.context.state.revision||1});h.context.snapshot={items:h.context.state.data.items,stamp:{revision:1}};h.context.selectedItem=h.context.snapshot.items[1];h.context.state.data.items=structuredClone(h.context.state.data.items);
  assert.equal(await h.run('compareInventoryItem(selectedItem,snapshot)'),true,'unchanged polling must preserve the explicit same-instance entry');assert.equal(Number(h.run('readComparisonArgs().level_a')),7);
  h.context.state.revision=2;assert.equal(await h.run('compareInventoryItem(selectedItem,snapshot)'),false,'a newer save cannot rematch an indistinguishable item');assert.match(h.get('#detail-workspace-error').textContent,/背包快照已变化/);
  const changing=setup();await changing.h.run('comparisonReady');changing.h.context.state={data:{items:[firstMissile,{...firstMissile,level:7}]}};changing.h.context.selectedItem=changing.h.context.state.data.items[1];
  const pending=[];changing.h.context.fetch=url=>new Promise(resolve=>pending.push(()=>resolve({ok:true,json:async()=>({entries:entries.filter(row=>row.id.startsWith(new URLSearchParams(url.split('?')[1]).get('q')))})})));
  const choosing=changing.h.run('compareInventoryItem(selectedItem)');changing.h.context.state.data.items=[{...firstMissile,level:3}];pending.forEach(done=>done());assert.equal(await choosing,false);assert.match(changing.h.run('compareError'),/背包快照已变化/);
  const draft=setup(),messages=[];await draft.h.run('comparisonReady');
  Object.assign(draft.h.context,{unfinishedDraftRequest:0,draftRecoveryEditGeneration:0,webEditingFrozen:false,webDirtySummary:()=>[],
    post:async()=>({draft:{draft:{schema:'denghuo-web-session',format:2,comparison:{form:{'compare-kind':{value:'missile'},'compare-level-a':{value:'7',checked:false},'compare-level-known-a':{value:'',checked:true}},choices:{a:entries[4].id,b:entries[5].id}}}}}),
    verifySettingsRecovery:async()=>{},applySettingsRecovery(){},toast:text=>messages.push(text)});
  const workspace=fs.readFileSync(path.join(root,'web/workspace.js'),'utf8');draft.h.run(workspace.slice(workspace.indexOf('async function loadUnfinishedDraft('),workspace.indexOf("$('#draft-refresh').addEventListener")));
  await draft.h.run('loadUnfinishedDraft("original")');assert.equal(draft.catalogCalls(),10,'comparison draft recovery retries startup catalog failure');assert.equal(draft.h.get('#draft-error').textContent,'');assert(messages.some(text=>text.startsWith('已找回原始草稿')));assert.equal(draft.h.get('#compare-level-a').value,'7');assert.equal(draft.h.run('readComparisonArgs().level_known_a'),'1');assert(draft.h.run('compareDirty&&compareSessionUnsaved'));assert.equal(draft.h.run('compareResultArgs'),null);
  console.log(JSON.stringify({comparison_recovery_and_applicability:true}));
}
(async()=>{
  verifyNavigationHistory();
  await verifyComparisonPlanOpenings();
  await verifyComparisonRecovery();
  const markup=fs.readFileSync(path.join(root,'web','index.html'),'utf8'),ids=[...markup.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
  assert.equal(new Set(ids).size,ids.length,'form and error targets require unique document IDs');
  for(const page of ['workspace','help','play-settings'])assert(markup.includes(`id="view-${page}"`)&&markup.includes(`data-view="${page}"`));
  for(const script of ['workspace.js','help.js','play.js'])assert(markup.includes(`src="/${script}"`)&&fs.existsSync(path.join(root,'web',script)));
  const dashboard=harness();
  const waiting={settings_revision:'connection-1',revision:0,data:null,error:'',warning:'',waiting_for_save:true,slots:[],active_slot:null,backup_context:'first-context',
    modified:0,age_seconds:null,stale:true,catalog_version:'4.0.2',catalog_count:955,token:'fixture',
    settings:{mode:'save',slot:'auto',stop_at:'',reveal:false,save_root:'/synthetic/default',always_on_top:false},backup_health:{state:'waiting'}};
  dashboard.context.document={querySelector:dashboard.get,querySelectorAll:()=>[],addEventListener(){}};
  dashboard.context.window={addEventListener(){},scrollTo(){},focus(){},scrollY:0};
  dashboard.context.location={hash:''};dashboard.context.history={replaceState(_state,_title,url){dashboard.context.location.hash=url;},pushState(_state,_title,url){dashboard.context.location.hash=url;}};
  dashboard.context.crypto={randomUUID:()=> '0123456789abcdef'};
  dashboard.context.setInterval=()=>0;dashboard.context.setTimeout=()=>0;dashboard.context.clearTimeout=()=>{};
  dashboard.context.fetch=async url=>({ok:true,json:async()=>url==='/api/status'?structuredClone(waiting):{}});
  dashboard.get('#calc-level').value='0';dashboard.get('#calc-tier').value='3';
  dashboard.load('backups.js');dashboard.load('app.js');
  await new Promise(resolve=>setImmediate(resolve));
  // Global navigation must keep an unfinished modal choice visible and usable.
  let openDialogs=[];dashboard.context.document.activeElement={tagName:'DIV'};
  dashboard.context.document.querySelectorAll=selector=>selector==='dialog[open]'?openDialogs.filter(dialog=>dialog.open):[];
  dashboard.get('#library-search').select=()=>{dashboard.get('#library-search').selected=true;};
  for(const id of ['settings-recovery-dialog','session-exit-dialog','restore-dialog','manage-dialog','repair-dialog','plan-dialog','workspace-confirm']){
    for(const key of ['F1','f','/']){
      const modal=element(id);openDialogs=[modal];dashboard.run("view='settings'");
      dashboard.context.shortcutEvent={key,ctrlKey:key==='f',altKey:false,preventDefault(){this.prevented=true;}};
      dashboard.run('handlePageShortcut(shortcutEvent)');
      assert(dashboard.context.shortcutEvent.prevented);assert(modal.open,`${id} remains visible for ${key}`);
      assert.equal(dashboard.run('view'),'settings','a pending modal choice must not navigate away');
    }
  }
  const ordinaryDetail=element('detail-dialog');openDialogs=[ordinaryDetail];
  dashboard.context.shortcutEvent={key:'F1',preventDefault(){}};dashboard.run('handlePageShortcut(shortcutEvent)');
  assert(!ordinaryDetail.open);assert.equal(dashboard.run('view'),'help');
  ordinaryDetail.open=true;openDialogs=[ordinaryDetail];
  dashboard.context.shortcutEvent={key:'f',ctrlKey:true,altKey:false,preventDefault(){}};dashboard.run('handlePageShortcut(shortcutEvent)');
  assert(!ordinaryDetail.open);assert.equal(dashboard.run('view'),'library');assert(dashboard.get('#library-search').focused);assert(dashboard.get('#library-search').selected);
  openDialogs=[];dashboard.run("view='overview'");dashboard.context.document.activeElement={tagName:'INPUT'};
  dashboard.context.shortcutEvent={key:'/',preventDefault(){this.prevented=true;}};dashboard.run('handlePageShortcut(shortcutEvent)');
  assert.equal(dashboard.run('view'),'overview');assert(!dashboard.context.shortcutEvent.prevented);
  // Verify the inventory entry and shared lookup projection use the same field origins.
  const workspaceText=fs.readFileSync(path.join(root,'web','workspace.js'),'utf8');
  dashboard.run(workspaceText.slice(workspaceText.indexOf('function lookupCalculationOptions('),workspaceText.indexOf('function referenceList(')));
  dashboard.context.visibleCalculationContext=()=>({hp:10,max_hp:100});
  dashboard.context.calculationStamp=()=>({started:90,mode:'save',slot:2,revision:3,modified:100});
  dashboard.context.cancelNumericalDetail=()=>{};
  dashboard.context.loadNumericalDetail=(id,params,origin,options)=>{dashboard.context.itemLookup={id,params,origin,options};};
  for(const volume of [0,2,20]){
    dashboard.context.waterItem={key:'items.waterskin',name:'Water',description:'',location:'Bag',details:[],known:true,level_applicable:false,volume};
    dashboard.run('showItem(waterItem)');const call=dashboard.context.itemLookup;
    assert.equal(call.params.dew_volume,volume);assert.equal(call.options.fieldOrigins.dew_volume,'快照记录 · 水袋露珠量');
    assert.equal(call.options.sourceStamp.slot,2);assert.equal(call.options.sourceStamp.modified,100);
  }
  delete dashboard.context.waterItem.volume;dashboard.run('showItem(waterItem)');
  assert(!('dew_volume' in dashboard.context.itemLookup.params));assert(!('dew_volume' in dashboard.context.itemLookup.options.fieldOrigins));
  dashboard.context.document.activeElement=null;
  assert(dashboard.get('#connection-banner').textContent.includes('无需先配置'));
  assert(!dashboard.get('#connection-banner').className.includes('error'));
  assert(!dashboard.get('#connection-banner').textContent.includes('旧快照'));
  assert(!dashboard.get('#connection-banner').textContent.includes('1970'));
  assert.equal(dashboard.get('#empty-title').textContent,'已就绪，直接开始游戏');
  assert.equal(dashboard.get('#empty-options').open,false);
  dashboard.run("state.error='存档损坏，等待新的保存';state.waiting_for_save=false;render()");
  assert(dashboard.get('#connection-banner').className.includes('error'));
  assert.equal(dashboard.get('#empty-options').open,true);
  dashboard.run("state.error='';state.waiting_for_save=false;state.settings.mode='manual';state.revision++;render()");
  assert(dashboard.get('#advice-source').textContent.includes('你填写的局势'));
  assert(dashboard.get('#advice-source').textContent.includes('不会自动跟随游戏'));
  dashboard.run("state.settings.mode='save';state.revision++;render()");
  assert(dashboard.get('#advice-source').textContent.includes('最近保存'));
  dashboard.run("state.backup_health={state:'waiting',last_save_protected:true}");
  dashboard.run('renderBackupHealth()');
  assert(dashboard.get('#backup-health').textContent.includes('上次保存已备份'));
  dashboard.run('state.backup_health.last_save_protected=false');
  dashboard.run('renderBackupHealth()');
  assert(!dashboard.get('#backup-health').textContent.includes('上次保存已备份'));

  dashboard.context.fetch=async()=>{throw new Error('disconnected');};
  await dashboard.run('poll()');
  assert.equal(dashboard.get('#empty-title').textContent,'助手连接已中断');
  assert(dashboard.get('#backup-health').textContent.includes('服务未连接'));
  assert(!dashboard.get('#backup-health').textContent.includes('最近保存已备份'));
  dashboard.context.fetch=async url=>({ok:true,json:async()=>url==='/api/status'?structuredClone(waiting):{}});
  await dashboard.run('poll()');
  assert.equal(dashboard.get('#empty-title').textContent,'已就绪，直接开始游戏');
  dashboard.run("navigate('settings')");
  const saveRoot=dashboard.get('#save-root');saveRoot.value='/synthetic/draft';
  dashboard.get('#settings-form').listeners.input({target:saveRoot});
  dashboard.run("navigate('manual');state.settings.always_on_top=true;navigate('settings')");
  assert.equal(saveRoot.value,'/synthetic/draft','settings draft must survive navigation');
  assert.equal(dashboard.get('#always-top').checked,true,'unchanged fields follow saved preferences');
  assert(dashboard.get('#settings-draft-status').textContent.includes('尚未保存'));
  await dashboard.get('#settings-reset').listeners.click();
  assert.equal(saveRoot.value,'/synthetic/default');
  assert(!dashboard.get('#settings-draft-status').textContent.includes('尚未保存'));
  let resolveSettings,submittedSettings;
  dashboard.context.post=async(path,payload)=>path==='/api/settings'?new Promise(resolve=>{resolveSettings=resolve;submittedSettings=payload;}):{};
  saveRoot.value='/synthetic/first-edit';dashboard.get('#settings-form').listeners.input({target:saveRoot});
  dashboard.get('#settings-form').listeners.submit({preventDefault(){}});
  saveRoot.value='/synthetic/new-edit';dashboard.get('#settings-form').listeners.input({target:saveRoot});
  assert.equal(submittedSettings.save_root,'/synthetic/first-edit');assert.equal(submittedSettings.startup_surface,'panel');
  waiting.settings_revision='connection-2';waiting.settings.save_root='/synthetic/first-edit';
  resolveSettings({settings_revision:'connection-2'});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(saveRoot.value,'/synthetic/new-edit','late save acknowledgement must not erase newer edits');
  assert(dashboard.get('#settings-draft-status').textContent.includes('尚未保存'));

  assert.equal(submittedSettings.expected_revision,'connection-1');
  // Another panel changes the slot while this panel retains its unsaved root.
  waiting.settings_revision='connection-3';waiting.settings.slot=2;
  dashboard.context.post=async(path,payload)=>{if(path!=='/api/settings')return {};submittedSettings=payload;const error=new Error('连接设置已在其他位置更新，草稿仍保留');error.status=409;throw error;};
  await dashboard.get('#settings-form').listeners.submit({preventDefault(){}});
  assert.equal(submittedSettings.expected_revision,'connection-2');
  assert.equal(saveRoot.value,'/synthetic/new-edit');assert(dashboard.run('settingsConflict'));
  assert(dashboard.get('#settings-draft-status').textContent.includes('重新载入'));
  assert.equal(dashboard.run('settingsRevision'),'connection-2','a conflict must not silently rebase the draft');
  assert(!dashboard.get('#settings-error').hidden);
  await dashboard.get('#settings-reset').listeners.click();
  assert.equal(dashboard.get('#settings-slot').value,'2');assert.equal(saveRoot.value,'/synthetic/first-edit');
  assert.equal(dashboard.run('settingsRevision'),'connection-3');assert(!dashboard.run('settingsConflict'));
  const top=dashboard.get('#always-top');top.checked=true;dashboard.get('#settings-form').listeners.input({target:top});
  dashboard.context.post=async(path,payload)=>{if(path!=='/api/settings')return {};submittedSettings=payload;waiting.settings_revision='connection-4';waiting.settings.always_on_top=true;return {settings_revision:'connection-4'};};
  await dashboard.get('#settings-form').listeners.submit({preventDefault(){}});
  assert.equal(submittedSettings.slot,2);assert.equal(submittedSettings.expected_revision,'connection-3');
  assert.equal(dashboard.run('settingsDrafts.size'),0);
  // A response that began before a successful save must not restore old settings.
  let finishOldPoll;
  const oldPollState=structuredClone(waiting);
  dashboard.context.fetch=()=>new Promise(resolve=>finishOldPoll=resolve);
  const oldPoll=dashboard.run('poll()');
  saveRoot.value='/synthetic/saved-next';dashboard.get('#settings-form').listeners.input({target:saveRoot});
  dashboard.context.post=async(path,payload)=>{if(path!=='/api/settings')return {};submittedSettings=payload;waiting.settings_revision='connection-5';waiting.settings.save_root=payload.save_root;return {settings_revision:'connection-5'};};
  await dashboard.get('#settings-form').listeners.submit({preventDefault(){}});
  finishOldPoll({ok:true,json:async()=>oldPollState});await oldPoll;
  assert.equal(saveRoot.value,'/synthetic/saved-next');assert.equal(dashboard.run('settingsRevision'),'connection-5');
  // Explicit reload obtains fresh values and preserves edits made during its request.
  let finishSettingsReload;
  dashboard.context.fetch=()=>new Promise(resolve=>finishSettingsReload=resolve);
  const reload=dashboard.get('#settings-reset').listeners.click();
  saveRoot.value='/synthetic/typed-during-reload';dashboard.get('#settings-form').listeners.input({target:saveRoot});
  finishSettingsReload({ok:true,json:async()=>structuredClone(waiting)});await reload;
  assert.equal(saveRoot.value,'/synthetic/typed-during-reload');assert(dashboard.run('settingsDrafts.size')>0);
  assert(dashboard.get('#settings-error').textContent.includes('新修改'));

  const numeric=harness();numeric.load('rules.js');numeric.context.state=stamp();
  numeric.run("numericalDetail={identity:'example',inputs:[{key:'hp'},{key:'vial'}],origins:{hp:'快照',vial:'手填'},source:calculationStamp()};refreshNumericalOrigin()");
  assert(!numeric.get('#values-freshness').textContent.includes('旧快照'));
  numeric.context.state.data.buffs=[{kind:'Barrier',current_shield:7}];assert.equal(numeric.run('visibleCalculationContext().current_shield'),7);numeric.context.state.data.buffs.push({kind:'Barrier',current_shield:8});assert(!('current_shield' in numeric.run('visibleCalculationContext()')));numeric.context.state.data.buffs=[];
  numeric.context.state.stale=true;numeric.run('refreshNumericalOrigin()');
  assert(numeric.get('#values-freshness').textContent.includes('旧快照'));
  numeric.context.state=stamp();numeric.context.state.modified=110;numeric.context.state.data.hero.hp=5;
  numeric.run('refreshNumericalOrigin()');
  assert(numeric.get('#values-freshness').textContent.includes('已经变化'));
  numeric.run("numericalDetail.origins.hp='手填';refreshNumericalOrigin()");
  assert(!numeric.get('#values-freshness').textContent.includes('已经变化'));
  numeric.run('numericalDetail.dirty=true;refreshNumericalOrigin()');
  assert(numeric.get('#values-freshness').textContent.includes('修改前的结果'));
  numeric.context.state=null;numeric.run('refreshNumericalOrigin()');
  assert(numeric.get('#values-use-latest').disabled);

  // Exercise the actual calculate/latest handlers with isolated form elements.
  const drafts=harness();drafts.context.state=stamp();let formInputs=[];
  drafts.context.$$=()=>formInputs;
  Object.defineProperty(drafts.get('#detail-rules'),'innerHTML',{set(html){
    formInputs=[...html.matchAll(/<input data-value-key="([^"]+)"[^>]*value="([^"]+)"/g)].map(m=>{
      const input=element();input.dataset.valueKey=m[1];input.value=m[2];
      drafts.elements.set(`[data-value-key="${m[1]}"]`,input);return input;
    });
    drafts.get('#value-calculator').querySelectorAll=()=>formInputs;
  }});
  drafts.context.fetch=async url=>{
    const params=new URLSearchParams(url.split('?')[1]);
    return {ok:true,json:async()=>({status:'current',version:'4.0.2',blocks:[],notice:'',inputs:
      ['hero_level','max_hp','hp','vial'].map(key=>({key,label:key,min:-1,max:1000,value:params.get(key)??-1}))})};
  };
  drafts.load('rules.js');await drafts.run("loadNumericalDetail('items.potions.potionofhealing')");
  const vial=drafts.get('[data-value-key="vial"]');vial.value='2';vial.listeners.input();
  drafts.context.state.modified=130;drafts.context.state.data.hero.hp=5;
  drafts.get('#values-use-latest').listeners.click();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(Number(drafts.get('[data-value-key="hp"]').value),5);
  assert.equal(Number(drafts.get('[data-value-key="vial"]').value),2);
  assert.equal(drafts.run("numericalDetail.origins.vial"),'手填');
  drafts.run('cancelNumericalDetail()');await drafts.run("loadNumericalDetail('items.potions.potionofhealing')");
  assert.equal(Number(drafts.get('[data-value-key="vial"]').value),2);
  assert.equal(drafts.run("numericalDetail.origins.vial"),'手填','reopening an unsaved calculated session retains the committed source label');
  assert(drafts.run('numericalDetail.sessionUnsaved'),'unsaved calculated context must retain exit protection after reopen');
  let invalidRequests=0;
  const validFetch=drafts.context.fetch;
  drafts.context.fetch=async url=>{invalidRequests++;return validFetch(url);};
  const retainedVial=drafts.get('[data-value-key="vial"]');
  for(const [value,valid] of [['',false],[' ',true],['1001',false],['NaN',true]]){
    retainedVial.value=value;retainedVial.validity.valid=valid;retainedVial.listeners.input();
    drafts.get('#values-use-latest').listeners.click();await new Promise(resolve=>setImmediate(resolve));
    assert.equal(invalidRequests,0);assert.equal(drafts.run('numericalDetail.context.vial'),2);
    assert.equal(drafts.run("numericalDrafts.get('items.potions.potionofhealing').vial"),2);
    assert(drafts.get('#values-freshness').textContent.includes('补全'));
    assert(retainedVial.focused);
    drafts.get('#value-calculator').listeners.submit({preventDefault(){}});
    assert.equal(invalidRequests,0);
  }
  retainedVial.value='-1';retainedVial.validity.valid=true;
  drafts.get('[data-value-key="hp"]').value='';drafts.get('[data-value-key="hp"]').validity.valid=false;
  drafts.get('#values-use-latest').listeners.click();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(invalidRequests,1);
  assert.equal(Number(drafts.get('[data-value-key="vial"]').value),-1);
  assert.equal(Number(drafts.get('[data-value-key="hp"]').value),5);

  // Recalculation keeps keyboard continuation, but respects an explicit focus change.
  drafts.get('#value-calculator').contains=target=>formInputs.includes(target);
  drafts.context.document.body=element();drafts.get('#detail-dialog').scrollTop=87;
  const numericFetch=drafts.context.fetch;
  let finishNumeric;
  drafts.context.fetch=url=>new Promise(resolve=>finishNumeric=()=>numericFetch(url).then(resolve));
  for(const movedElsewhere of [false,true]){
    const currentHp=drafts.get('[data-value-key="hp"]');currentHp.value='3';currentHp.listeners.input();
    drafts.context.document.activeElement=currentHp;
    drafts.get('#value-calculator').listeners.submit({preventDefault(){}});
    drafts.context.document.activeElement=movedElsewhere?element():drafts.context.document.body;
    finishNumeric();await new Promise(resolve=>setImmediate(resolve));
    assert.equal(!!drafts.get('[data-value-key="hp"]').focused,!movedElsewhere);
    assert.equal(drafts.get('#detail-dialog').scrollTop,87);
  }
  drafts.context.fetch=async()=>{throw new Error('controlled calculation interruption');};
  const failedHp=drafts.get('[data-value-key="hp"]');failedHp.value='4';failedHp.listeners.input();
  drafts.context.document.activeElement=failedHp;
  drafts.get('#value-calculator').listeners.submit({preventDefault(){}});
  drafts.context.document.activeElement=drafts.context.document.body;
  await new Promise(resolve=>setImmediate(resolve));
  assert(failedHp.focused,'failed calculation must leave its input ready to retry');
  assert.equal(failedHp.value,'4');assert(!failedHp.disabled);
  assert(drafts.run('numericalDetail.dirty'),'a failed request must never label previous results as recalculated');
  assert(drafts.get('#values-freshness').textContent.includes('尚未计算'));
  drafts.context.fetch=validFetch;
  const pendingIdentity='items.potions.potionofhealing';
  for(const raw of ['7','','-','1e','10001','3.5']){
    const field=drafts.get('[data-value-key="hp"]');field.value=raw;field.validity.valid=true;field.listeners.input();
    const lastHP=drafts.run('numericalCalculated.get("items.potions.potionofhealing").params.hp');
    drafts.get('#detail-dialog').listeners.close();await drafts.run("loadNumericalDetail('another-reference')");drafts.run('cancelNumericalDetail()');
    await drafts.run("loadNumericalDetail('items.potions.potionofhealing')");
    assert.equal(drafts.get('[data-value-key="hp"]').value,raw,'unsubmitted original string must survive close, another reference, and reopen');
    assert(drafts.run('numericalDetail.origins.hp').includes('手填'));assert(drafts.get('#values-freshness').textContent.includes('尚未计算'));
    assert.equal(Number(drafts.run('numericalDetail.inputs.find(i=>i.key==="hp").value')),lastHP,'reopening pending input must retain the last computed result');
    if(raw!=='7'){assert.equal(drafts.run('validNumericalInputs($$("[data-value-key]"),numericalDetail)'),false);}
  }
  const pendingVial=drafts.get('[data-value-key="vial"]');pendingVial.value='-';pendingVial.validity.valid=true;pendingVial.listeners.input();
  drafts.context.state.data.hero.hp=9;drafts.get('#values-use-latest').listeners.click();
  assert.equal(drafts.get('[data-value-key="hp"]').value,'9');assert.equal(pendingVial.value,'-','explicit latest-state input retains an invalid independent condition');
  assert(drafts.get('#values-freshness').textContent.includes('修改前'));
  pendingVial.value='2';pendingVial.validity.valid=true;pendingVial.listeners.input();drafts.get('#values-use-latest').listeners.click();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(Number(drafts.get('[data-value-key="hp"]').value),9);assert.equal(Number(drafts.get('[data-value-key="vial"]').value),2);assert(!drafts.run('numericalDetail.dirty'));

  // A fixed plan has a separate raw and last-result draft from ordinary lookups and other plans.
  drafts.context.fixedPlan={id:'fixed-one',record_revision:'opened-revision',origin:{fields:{hp:'保存参数'}}};
  drafts.context.fixedArgs={hp:11,max_hp:40,hero_level:5,vial:-1};
  drafts.context.fixedResult=(await validFetch('/api/values?hp=11&max_hp=40&hero_level=5&vial=-1').then(r=>r.json()));
  drafts.run('cancelNumericalDetail()');
  for(const raw of ['27','','-']){
    await drafts.run("loadNumericalDetail('items.potions.potionofhealing',fixedArgs,'saved',{fixed:true,savedPlan:fixedPlan,result:fixedResult})");
    const hp=drafts.get('[data-value-key="hp"]');hp.value=raw;hp.listeners.input();
    drafts.run('cancelNumericalDetail()');await drafts.run("loadNumericalDetail('another-reference')");drafts.run('cancelNumericalDetail()');
    await drafts.run("loadNumericalDetail('items.potions.potionofhealing',fixedArgs,'saved',{fixed:true,savedPlan:fixedPlan,result:fixedResult})");
    assert.equal(drafts.get('[data-value-key="hp"]').value,raw);
    assert.equal(Number(drafts.run('numericalDetail.inputs.find(i=>i.key==="hp").value')),11);
    assert(drafts.run('numericalDetail.dirty'));assert(drafts.get('#values-freshness').textContent.includes('尚未保存'));
  }
  drafts.get('[data-value-key="hp"]').value='27';drafts.get('[data-value-key="hp"]').listeners.input();
  drafts.get('#value-calculator').listeners.submit({preventDefault(){}});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(Number(drafts.run('numericalDetail.inputs.find(i=>i.key==="hp").value')),27);
  drafts.run('cancelNumericalDetail()');
  drafts.context.secondFixedPlan={...drafts.context.fixedPlan,id:'fixed-two'};
  await drafts.run("loadNumericalDetail('items.potions.potionofhealing',fixedArgs,'saved',{fixed:true,savedPlan:secondFixedPlan,result:fixedResult})");
  assert.equal(Number(drafts.get('[data-value-key="hp"]').value),11);
  drafts.run('cancelNumericalDetail()');
  await drafts.run("loadNumericalDetail('items.potions.potionofhealing',fixedArgs,'saved',{fixed:true,savedPlan:fixedPlan,result:fixedResult})");
  assert.equal(Number(drafts.get('[data-value-key="hp"]').value),27);assert(drafts.get('#values-freshness').textContent.includes('尚未保存'));

  const compare=harness();compare.get('#compare-kind').value='weapon';compare.get('#compare-strength').value='10';
  compare.context.state=stamp();compare.context.calculationStamp=()=>({modified:compare.context.state?.modified,
    slot:compare.context.state?.active_slot,mode:compare.context.state?.settings.mode,
    revision:compare.context.state?.revision,started:compare.context.state?.started});
  compare.context.exampleHTML=()=>'';
  compare.context.state.data.items=[{known:true,available:true,key:'items.weapon.melee.shortsword',name:'短剑 +0',
    location:'主武器',level:0,mastery:false,augmentation:'NONE'}];
  compare.load('compare.js');await new Promise(resolve=>setImmediate(resolve));
  compare.run('renderEquipmentComparison()');
  assert.equal(Number(compare.get('#compare-level-a').value),0);
  compare.context.state.data.hero.strength=12;compare.run('renderEquipmentComparison()');
  assert.equal(Number(compare.get('#compare-strength').value),12);
  compare.context.fetch=async()=>({ok:true,json:async()=>({choices:[{name:'A',level:0,upgrade_risk:0},{name:'B',level:0,upgrade_risk:0}],rows:[]})});
  let resolveCompare;compare.context.fetch=()=>new Promise(resolve=>resolveCompare=resolve);
  const pending=compare.get('#equipment-comparison').listeners.submit({preventDefault(){}});
  compare.context.state.data.hero.strength=14;compare.run('renderEquipmentComparison()');
  resolveCompare({ok:true,json:async()=>({choices:[{name:'A',level:0},{name:'B',level:0}],rows:[]})});await pending;
  assert(compare.run('compareDirty'));
  const manualStrength=compare.get('#compare-strength');manualStrength.value='18';
  compare.get('#equipment-comparison').listeners.input({target:manualStrength});
  compare.context.state.data.hero.strength=16;compare.run('renderEquipmentComparison()');
  assert.equal(manualStrength.value,'18');assert(compare.get('#compare-status').textContent.includes('手填'));
  compare.get('#compare-follow-strength').listeners.click();
  assert.equal(Number(manualStrength.value),16);
  compare.context.state=null;compare.run('renderEquipmentComparison()');
  assert(compare.get('#compare-follow-strength').disabled);assert(compare.get('#compare-status').textContent.includes('示例'));
  compare.context.state=stamp();compare.context.state.data.items=[{known:true,available:true,key:'items.weapon.melee.shortsword',name:'短剑 +0',location:'主武器',level:0,mastery:false,augmentation:'NONE'}];
  compare.run('renderEquipmentComparison()');
  Object.assign(compare.context.state.data.items[0],{name:'短剑 +1',level:1,mastery:true,augmentation:'SPEED'});
  compare.context.state.modified=120;compare.run('renderEquipmentComparison()');
  assert.equal(Number(compare.get('#compare-level-a').value),1);
  assert(compare.get('#compare-mastery-a').checked);assert.equal(compare.get('#compare-augment-a').value,'SPEED');
  const manual=compare.get('#compare-level-a');manual.value='4';
  compare.get('#equipment-comparison').listeners.input({target:manual});
  compare.context.state.data.items[0].level=2;compare.run('renderEquipmentComparison()');
  assert.equal(manual.value,'4');assert(compare.get('#compare-origin-a').textContent.includes('手填'));
  compare.context.fetch=async()=>({ok:false,json:async()=>({error:'这件特殊装备尚不能比较'})});
  await compare.get('#equipment-comparison').listeners.submit({preventDefault(){}});
  compare.run('renderEquipmentComparison()');
  assert(compare.get('#compare-status').textContent.includes('尚不能比较'));

  // Defaults follow newly available equipment; explicit choices and drafts retain their meaning.
  async function freshComparison(snapshot){
    const component=harness();component.context.state=snapshot;
    component.get('#compare-kind').value='weapon';component.get('#compare-strength').value='10';
    component.context.fetch=async url=>({ok:true,json:async()=>({entries:String(url).includes('items.armor.')?
      [{id:'items.armor.leatherarmor',name:'皮甲'}]:
      [{id:'items.weapon.melee.battleaxe',name:'战斧'},{id:'items.weapon.melee.shortsword',name:'短剑'}]})});
    component.load('compare.js');await new Promise(resolve=>setImmediate(resolve));return component;
  }
  const ownedSword={known:true,available:true,key:'items.weapon.melee.shortsword',name:'短剑 +2',
    location:'主武器',level:2,mastery:true,augmentation:'SPEED'};
  const firstSave=stamp();firstSave.data.items=[{...ownedSword,name:'背包短剑 +9',level:9,location:'背包'},ownedSword];
  const firstComparison=await freshComparison(null);
  assert.equal(firstComparison.run('compareItems[Number($("#compare-a").value)].token'),'book:items.weapon.melee.battleaxe');
  firstComparison.context.state=firstSave;firstComparison.run('renderEquipmentComparison()');
  assert.equal(firstComparison.run('compareItems[Number($("#compare-a").value)].location'),'主武器');
  assert.equal(Number(firstComparison.get('#compare-level-a').value),2);
  assert(firstComparison.get('#compare-mastery-a').checked);assert.equal(firstComparison.get('#compare-augment-a').value,'SPEED');
  const alreadySaved=await freshComparison(firstSave);
  assert.equal(alreadySaved.run('compareItems[Number($("#compare-a").value)].location'),'主武器');
  const selectedExample=await freshComparison(null);
  selectedExample.get('#compare-a').listeners.change();
  selectedExample.context.state=firstSave;selectedExample.run('renderEquipmentComparison()');
  assert.equal(selectedExample.run('compareItems[Number($("#compare-a").value)].token'),'book:items.weapon.melee.battleaxe');
  const editedExample=await freshComparison(null),exampleLevel=editedExample.get('#compare-level-a');exampleLevel.value='8';
  editedExample.get('#equipment-comparison').listeners.input({target:exampleLevel});
  editedExample.context.state=firstSave;editedExample.run('renderEquipmentComparison()');
  assert.equal(editedExample.run('compareItems[Number($("#compare-a").value)].token'),'book:items.weapon.melee.battleaxe');
  assert.equal(exampleLevel.value,'8');
  const unknownEquipment=stamp();unknownEquipment.data.items=[{...ownedSword,name:'短剑 · 等级未知',level:null}];
  const unknownComparison=await freshComparison(unknownEquipment);
  assert.equal(Number(unknownComparison.get('#compare-level-a').value),0);
  assert(unknownComparison.get('#compare-origin-a').textContent.includes('等级未知'));
  firstComparison.context.state.data.items.push({known:true,available:true,key:'items.armor.leatherarmor',name:'背包皮甲',location:'背包',level:0},
    {known:true,available:true,key:'items.armor.leatherarmor',name:'皮甲 +3',location:'护甲',level:3});
  firstComparison.get('#compare-kind').value='armor';firstComparison.get('#compare-kind').listeners.change();
  assert.equal(firstComparison.run('compareItems[Number($("#compare-a").value)].location'),'护甲');
  assert.equal(Number(firstComparison.get('#compare-level-a').value),3);

  const changingInventory=stamp();changingInventory.data.items=[ownedSword,
    {...ownedSword,key:'items.weapon.melee.dagger',name:'匕首',location:'背包',level:0},
    {...ownedSword,key:'items.weapon.melee.longsword',name:'长剑',location:'背包',level:0},
    {...ownedSword,key:'items.weapon.melee.greatsword',name:'巨剑',location:'背包',level:0}];
  const heldComparison=await freshComparison(changingInventory);
  heldComparison.get('#compare-b').value='3';heldComparison.get('#compare-b').listeners.change();
  const heldLevel=heldComparison.get('#compare-level-b');heldLevel.value='7';
  heldComparison.get('#equipment-comparison').listeners.input({target:heldLevel});
  changingInventory.data.items.splice(1,1);heldComparison.run('renderEquipmentComparison()');
  assert.equal(heldComparison.run('readComparisonArgs().id_b'),'items.weapon.melee.greatsword');
  assert.equal(heldComparison.run('readComparisonArgs().level_b'),'7');
  assert(heldComparison.run('compareItems[Number($("#compare-b").value)].reference'));
  assert(heldComparison.get('#compare-origin-b').textContent.includes('固定装备参考'));
  changingInventory.data.items.pop();heldComparison.run('renderEquipmentComparison()');
  assert.equal(heldComparison.run('readComparisonArgs().id_b'),'items.weapon.melee.greatsword');
  assert.equal(heldComparison.run('readComparisonArgs().level_b'),'7');
  changingInventory.data.items.push({...ownedSword,key:'items.weapon.melee.greatsword',name:'另一巨剑',location:'背包',level:1});
  heldComparison.run('renderEquipmentComparison()');
  assert.equal(heldComparison.run('readComparisonArgs().level_b'),'7');
  heldComparison.get('#compare-b').value=String(heldComparison.run('compareItems.findIndex(item=>item.owned&&item.key==="items.weapon.melee.greatsword")'));
  heldComparison.get('#compare-b').listeners.change();
  assert.equal(Number(heldComparison.get('#compare-level-b').value),1);
  heldComparison.get('#compare-curse-b').dataset.manual='true';
  heldComparison.get('#compare-kind').value='armor';heldComparison.get('#compare-kind').listeners.change();
  assert(!heldComparison.get('#compare-b').dataset.edited);
  assert(!heldComparison.get('#compare-curse-b').dataset.manual);

  const budgetComparison=await freshComparison(firstSave);let budgetQuery;
  budgetComparison.context.displayNumber=String;budgetComparison.context.exampleHTML=()=>'';budgetComparison.context.inlineError=(target,message)=>{target.textContent=message;};budgetComparison.context.calculationStamp=()=>({modified:budgetComparison.context.state.modified,revision:budgetComparison.context.state.revision,mode:'save',slot:1,started:90});
  budgetComparison.context.fetch=async url=>{budgetQuery=new URLSearchParams(url.split('?')[1]);return {ok:true,json:async()=>({choices:[{name:'A',level:2},{name:'B',level:9}],rows:[]})};};
  await budgetComparison.get('#equipment-comparison').listeners.submit({preventDefault(){}});
  assert(!budgetQuery.has('planning'));assert(!budgetQuery.has('upgrade_budget'));
  budgetComparison.get('#compare-planning-enabled').checked=true;budgetComparison.get('#compare-upgrade-budget').value='3';budgetComparison.get('#compare-strength-budget').value='2';
  await budgetComparison.get('#equipment-comparison').listeners.submit({preventDefault(){}});
  assert.equal(budgetQuery.get('planning'),'1');assert.equal(budgetQuery.get('upgrade_budget'),'3');assert.equal(budgetQuery.get('strength_budget'),'2');
  assert.equal(budgetComparison.run('compareResultArgs.upgrade_budget'),3);assert.equal(budgetComparison.run('compareResultArgs.strength_budget'),2);
  budgetComparison.context.state.data.items.push({known:true,available:true,key:'items.scrolls.scrollofupgrade',quantity:4},{known:true,available:false,key:'items.scrolls.scrollofupgrade',quantity:99},{known:false,available:true,key:'items.potions.potionofstrength',quantity:99},{known:true,available:true,key:'items.potions.potionofstrength',quantity:1});
  budgetComparison.get('#compare-use-resources').listeners.click();assert.equal(budgetComparison.get('#compare-upgrade-budget').value,'4');assert.equal(budgetComparison.get('#compare-strength-budget').value,'1');
  budgetComparison.context.state.data.items[1].level=-1;budgetComparison.run('renderEquipmentComparison()');
  assert.equal(Number(budgetComparison.get('#compare-level-a').value),-1,'known negative levels must not become zero');

  // Parse the actual generated conditional controls so undo cannot pass by
  // restoring only static selects while leaving another item's schema behind.
  const undoCompare=harness(),dynamicCompare={a:[],b:[]};
  const comparisonMarkup=markup.split('<form id="equipment-comparison">')[1].split('</form>')[0];
  const comparisonControls=[...comparisonMarkup.matchAll(/<(input|select)\b[^>]*\bid="([^"]+)"[^>]*>/g)].map(match=>{
    const input=undoCompare.get('#'+match[2]);input.value=match[0].match(/\bvalue="([^"]*)"/)?.[1]||'';return input;
  });
  for(const side of ['a','b'])Object.defineProperty(undoCompare.get('#compare-context-'+side),'innerHTML',{
    get(){return this.html||'';},set(html){this.html=html;dynamicCompare[side]=[...html.matchAll(/<input[^>]*data-compare-key="([^"]+)"[^>]*value="([^"]*)"/g)].map(match=>{
      const input=element();input.dataset.compareKey=match[1];input.value=match[2];return input;
    });}
  });
  const allComparisonControls=()=>[...comparisonControls,...dynamicCompare.a,...dynamicCompare.b];
  undoCompare.context.$$=selector=>selector.startsWith('#compare-context-a')?dynamicCompare.a:selector.startsWith('#compare-context-b')?dynamicCompare.b:allComparisonControls();
  undoCompare.get('#equipment-comparison').querySelectorAll=allComparisonControls;
  Object.assign(undoCompare.context,{state:stamp(),calculationStamp:()=>({mode:'save',slot:1,modified:100}),displayNumber:String,
    inlineError:(target,message)=>{target.textContent=message;},
    fetch:async url=>({ok:true,json:async()=>({entries:String(url).includes('items.wands.')?[
      {id:'items.wands.wandoffireblast',name:'焰浪法杖'},{id:'items.wands.wandoftransfusion',name:'注魂法杖'}]:[]})}),
    getJSON:async url=>({inputs:String(url).includes('wandoftransfusion')?[
      {key:'max_hp',label:'生命上限',value:65,min:1,max:9999}]:[]})});
  undoCompare.get('#compare-kind').value='wand';undoCompare.get('#compare-strength').value='13';undoCompare.get('#compare-investment-mode').value='all';
  undoCompare.load('compare.js');await new Promise(resolve=>setImmediate(resolve));
  const chooseComparison=async identity=>{
    undoCompare.get('#compare-a').value=String(undoCompare.run(`compareItems.findIndex(item=>item.key===${JSON.stringify(identity)})`));
    undoCompare.get('#compare-a').listeners.change();await new Promise(resolve=>setImmediate(resolve));
  };
  await chooseComparison('items.wands.wandoffireblast');
  const charge=dynamicCompare.a.find(input=>input.dataset.compareKey==='charges_a');charge.value='3';
  undoCompare.get('#equipment-comparison').listeners.input({target:charge});
  const originalComparison=undoCompare.run('JSON.stringify(readComparisonArgs())');
  undoCompare.get('#compare-use-resources').listeners.click();
  await chooseComparison('items.wands.wandoftransfusion');
  assert(dynamicCompare.a.some(input=>input.dataset.compareKey==='max_hp_a'));
  undoCompare.get('#compare-undo-import').listeners.click();
  assert.equal(undoCompare.run('JSON.stringify(readComparisonArgs())'),originalComparison);
  assert.equal(dynamicCompare.a.find(input=>input.dataset.compareKey==='charges_a').dataset.manual,'true');
  undoCompare.run('renderEquipmentComparison()');
  assert.equal(undoCompare.run('JSON.stringify(readComparisonArgs())'),originalComparison,'ordinary render keeps restored context');
  for(const lateOk of [false,true]){
    undoCompare.get('#compare-use-resources').listeners.click();
    let finishComparison;
    undoCompare.context.fetch=()=>new Promise(resolve=>{finishComparison=resolve;});
    const submitting=undoCompare.get('#equipment-comparison').listeners.submit({preventDefault(){}});
    assert(undoCompare.run('comparePending'));
    undoCompare.get('#compare-undo-import').listeners.click();
    assert(!undoCompare.run('comparePending'));assert(!undoCompare.get('#compare-submit').disabled);
    assert(!dynamicCompare.a.find(input=>input.dataset.compareKey==='charges_a').disabled);
    finishComparison({ok:lateOk,json:async()=>lateOk?{choices:[],rows:[]}:{error:'obsolete calculation failure'}});
    await submitting;
    assert.equal(undoCompare.run('compareError'),'');
    assert.equal(undoCompare.run('JSON.stringify(readComparisonArgs())'),originalComparison);
  }
  for(const lateFailure of [false,true]){
    undoCompare.get('#compare-use-resources').listeners.click();
    let finishContext,failContext;
    undoCompare.context.getJSON=()=>new Promise((resolve,reject)=>{finishContext=resolve;failContext=reject;});
    await chooseComparison('items.wands.wandoftransfusion');
    undoCompare.get('#compare-undo-import').listeners.click();
    if(lateFailure)failContext(new Error('obsolete schema failure'));else finishContext({inputs:[]});
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(undoCompare.run('compareError'),'');
    assert.equal(undoCompare.run('JSON.stringify(readComparisonArgs())'),originalComparison);
  }

  const scoped=harness();scoped.load('backups.js');scoped.run('initializeBackups()');
  scoped.context.toast=()=>{};
  scoped.context.state={backup_context:'A',active_slot:4,settings:{save_root:'/synthetic/A'}};
  const scopeStatus=context=>({context,save_root:'/synthetic/'+context,enabled:true,health:'waiting',notice:'',error:'',
    storage_bytes:100,storage_limit:512*1048576,records_available:true,history:[],retained:[],undo:[],
    slots:[{slot:1,latest:null,nodes:[]},{slot:4,latest:null,nodes:[]}]});
  scoped.context.fetch=async()=>({ok:true,json:async()=>scopeStatus('A')});
  scoped.run("syncBackupContext('A')");await scoped.run('loadBackups()');
  assert.equal(scoped.get('#backup-slot').value,'4','first history defaults to the current run');
  scoped.get('#backup-slot').value='1';await scoped.run('loadBackups()');
  assert.equal(scoped.get('#backup-slot').value,'1','polling preserves an explicitly browsed history slot');
  scoped.context.state.active_slot=6;scoped.get('#backup-slot').value='';await scoped.run('loadBackups()');
  assert.equal(scoped.get('#backup-slot').value,'6','an active slot without archives is still the initial browsing context');
  assert(scoped.get('#backup-slot').innerHTML.includes('暂无活动备份'));
  scoped.run("openConfirm({id:'old',slot:4,class:'WARRIOR',depth:2,saved:100},'remove','A')");
  assert(!scoped.get('#restore-warning').textContent.includes('完全退出游戏'));
  assert(scoped.get('#restore-warning').textContent.includes('不改动当前游戏进度'));
  assert.equal(scoped.get('#close-restore')['aria-label'],'取消移出');
  let resolvePreview;
  scoped.context.fetch=()=>new Promise(resolve=>{resolvePreview=resolve;});
  const latePreview=scoped.run("openRestore({id:'old',slot:4},'A')");
  scoped.context.state.backup_context='B';scoped.run("syncBackupContext('B')");
  resolvePreview({ok:true,json:async()=>({context:'A',expected_current:'old',current:{},target:{}})});
  await assert.rejects(latePreview,/连接已变化/);
  assert(!scoped.get('#restore-dialog').open,'a late old-root preview cannot reopen the confirmation');
  assert.equal(scoped.run('restoreTarget'),null);
  let finishCancelledPreview;
  scoped.context.fetch=()=>new Promise(resolve=>{finishCancelledPreview=resolve;});
  const cancelledPreview=scoped.run("openRestore({id:'cancelled',slot:4},'B')");
  scoped.get('#close-restore').listeners.click();
  finishCancelledPreview({ok:true,json:async()=>({context:'B',expected_current:'old',current:{},target:{}})});
  await cancelledPreview;
  assert(!scoped.get('#restore-dialog').open,'a cancelled preview cannot reopen the dialog');
  scoped.context.state.backup_context='A';scoped.run("syncBackupContext('A')");
  let resolveList;
  scoped.context.fetch=()=>new Promise(resolve=>{resolveList=resolve;});
  const lateList=scoped.run('loadBackups()');
  scoped.context.state.backup_context='B';scoped.run("syncBackupContext('B')");
  resolveList({ok:true,json:async()=>scopeStatus('A')});await lateList;
  assert.equal(scoped.run('backupState'),null,'old-root history cannot replace the new browsing context');

  // An old modal response cannot close or contaminate a newly opened action.
  let finishManage;
  scoped.context.post=()=>new Promise(resolve=>{finishManage=resolve;});
  scoped.run("openManage({id:'first',slot:4},'B')");
  scoped.get('#backup-label').value='first label';
  scoped.get('#manage-form').listeners.submit({preventDefault(){}});
  scoped.get('#close-manage').listeners.click();
  scoped.run("openManage({id:'second',slot:6},'B')");
  scoped.get('#backup-label').value='second draft';
  finishManage({});await new Promise(resolve=>setImmediate(resolve));
  assert(scoped.get('#manage-dialog').open);
  assert.equal(scoped.get('#backup-label').value,'second draft');
  assert.equal(scoped.run('manageTarget.id'),'second');
  // A late acknowledgement confirms only the submitted metadata; newer text survives.
  const metadata=harness();metadata.context.state={backup_context:'metadata-context',settings:{save_root:'/synthetic/metadata'}};
  metadata.context.toast=()=>{};metadata.context.action=work=>work();metadata.load('backups.js');metadata.run('initializeBackups()');
  const metadataId='a'.repeat(64),metadataRow={id:metadataId,slot:1,label:'原名称',locked:false,metadata_revision:'1'.repeat(64)};
  const metadataResume=element();metadataResume.dataset.metadataResume='0';metadata.get('#backup-metadata-drafts').querySelectorAll=()=>[metadataResume];
  metadata.context.metadataRow=metadataRow;metadata.run("openManage(metadataRow,'metadata-context')");
  metadata.get('#backup-label').value='提交名称';metadata.get('#backup-label').listeners.input();
  let finishBackupMetadata;metadata.context.post=(url,payload)=>new Promise(resolve=>{finishBackupMetadata=resolve;});
  metadata.get('#manage-form').listeners.submit({preventDefault(){}});
  metadata.get('#backup-label').value='提交后继续输入';metadata.get('#backup-label').listeners.input();
  finishBackupMetadata({metadata:{...metadataRow,label:'提交名称',metadata_revision:'2'.repeat(64)},context:'metadata-context',save_root:'/synthetic/metadata'});
  await new Promise(resolve=>setImmediate(resolve));
  assert(metadata.get('#manage-dialog').open);assert.equal(metadata.get('#backup-label').value,'提交后继续输入');
  assert(metadata.get('#manage-error').textContent.includes('之后的新编辑仍未保存'));
  assert.equal(metadata.run('captureBackupMetadataDrafts()[0].expected_metadata_revision'),'2'.repeat(64));
  metadata.get('#close-manage').listeners.click();assert.equal(metadata.run('captureBackupMetadataDrafts()[0].raw.label'),'提交后继续输入');
  const preservedMetadata=JSON.parse(metadata.run('JSON.stringify(captureBackupMetadataDrafts())'));
  metadata.context.preservedMetadata=preservedMetadata;
  metadata.run("backupMetadataDrafts.clear();restoreBackupMetadataDrafts(preservedMetadata)");
  metadata.context.fetch=async()=>({ok:true,json:async()=>({context:'metadata-context',save_root:'/synthetic/metadata',history:[{...metadataRow,label:'另一窗口固定',locked:true,metadata_revision:'3'.repeat(64)}]})});
  metadata.context.document.createElement=()=>element();
  metadata.get('#manage-form').append=()=>{};
  // Same-directory restore retains its own revision instead of borrowing the newer protection.
  metadata.run('showLatestBackupMetadata=async()=>{}');await metadataResume.listeners.click();
  assert.equal(metadata.run('manageTarget.expected_metadata_revision'),'2'.repeat(64));assert.equal(metadata.get('#backup-label').value,'提交后继续输入');
  metadata.get('#close-manage').listeners.click();metadata.context.fetch=async()=>({ok:true,json:async()=>({context:'metadata-context',save_root:'/synthetic/moved',history:[metadataRow]})});
  const rebindChildren=[];metadata.context.document.createElement=()=>{const el=element();el.append=child=>rebindChildren.push(child);return el;};
  await metadata.run('resumeBackupMetadataDraft(preservedMetadata[0])');assert.equal(metadata.run('manageTarget.context'),null);assert(metadata.get('#manage-submit').disabled);
  const rebindButton=rebindChildren.find(el=>el.textContent.includes('将编辑关联'));assert(rebindButton);rebindButton.listeners.click();
  assert.equal(metadata.run('manageTarget.save_root'),'/synthetic/moved');assert.equal(metadata.run('manageTarget.context'),'metadata-context');
  assert.equal(metadata.run('captureBackupMetadataDrafts()[0].raw.label'),'提交后继续输入');
  metadata.get('#close-manage').listeners.click();metadata.context.invalidMetadata=[{...preservedMetadata[0],expected_metadata_revision:'bad'}];
  assert.throws(()=>metadata.run('restoreBackupMetadataDrafts(invalidMetadata)'),/身份或版本/);

  let failRepair;
  scoped.run("backupState={context:'B'}");
  scoped.context.post=()=>new Promise((resolve,reject)=>{failRepair=reject;});
  scoped.get('#repair-timeline').listeners.click();scoped.get('#repair-confirm').checked=true;
  scoped.get('#repair-form').listeners.submit({preventDefault(){},target:scoped.get('#repair-form')});
  scoped.get('#close-repair').listeners.click();scoped.get('#repair-timeline').listeners.click();
  failRepair(new Error('old operation failed'));await new Promise(resolve=>setImmediate(resolve));
  assert(scoped.get('#repair-dialog').open);
  assert(scoped.get('#repair-error').hidden);
  assert(!scoped.get('#repair-submit').disabled);

  // Undo enters through its real history button and requires a fresh current-slot preview.
  const undoFlow=harness();undoFlow.load('backups.js');undoFlow.load('backup-workflows.js');undoFlow.run('initializeBackups()');
  undoFlow.run("backupFlow.context='undo-root';loadBackupFlowStorage=async()=>{}");
  undoFlow.context.state={backup_context:'undo-root',active_slot:2,settings:{save_root:'/synthetic/undo-root'}};
  undoFlow.context.toast=()=>{};undoFlow.context.action=work=>work();
  const undoRow={id:'restore-journal',slot:2,time:100,before:{class:'MAGE',depth:4,hp:5,ht:30,equipment:[]}};
  const undoButton=element();undoButton.dataset.undo=undoRow.id;
  undoFlow.get('#backup-undo').querySelectorAll=selector=>selector==='[data-undo]'?[undoButton]:[];
  undoFlow.get('#backup-slot').value='2';
  undoFlow.context.undoStatus={...scopeStatus('undo-root'),undo:[undoRow]};
  undoFlow.run('backupState=undoStatus;renderBackups()');
  const undoRequests=[],undoPosts=[];let undoDigest='a'.repeat(64),failUndo=true;
  undoFlow.context.fetch=async url=>{
    undoRequests.push(url);
    if(url.startsWith('/api/backups/undo-preview?'))return {ok:true,json:async()=>({
      context:'undo-root',expected_current:undoDigest,original_existed:true,same_run:false,
      current:{class:'WARRIOR',depth:2,hp:20,ht:30,equipment:[]},target:undoRow.before})};
    assert(url.startsWith('/api/backups?'),'undo must request its own preview endpoint');
    return {ok:true,json:async()=>undoFlow.context.undoStatus};
  };
  undoFlow.context.post=async(url,payload)=>{
    undoPosts.push({url,payload});if(failUndo)throw new Error('当前进度已变化，请重新预览后再确认撤回');return {ok:true};
  };
  await undoButton.listeners.click();
  let undoQuery=new URLSearchParams(undoRequests[0].split('?')[1]);
  assert.equal(undoQuery.get('id'),undoRow.id);assert.equal(undoQuery.get('slot'),'2');assert.equal(undoQuery.get('context'),'undo-root');
  assert(undoFlow.get('#restore-description').innerHTML.includes('现在的进度'));
  assert(undoFlow.get('#restore-description').innerHTML.includes('撤回后回到的进度'));
  assert(undoFlow.get('#restore-description').innerHTML.includes('生命 20/30'));
  assert(undoFlow.get('#restore-description').innerHTML.includes('生命 5/30'));
  assert(undoFlow.get('#restore-dialog').open);assert(!undoFlow.get('#restore-repreview').hidden);
  assert.equal(undoFlow.run('restoreTarget.operation'),'undo');
  undoFlow.get('#restore-confirm').checked=true;
  undoFlow.get('#restore-form').listeners.submit({preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(undoPosts[0].url,'/api/backups');
  assert.deepEqual(JSON.parse(JSON.stringify(undoPosts[0].payload)),{
    action:'undo',slot:2,id:'restore-journal',context:'undo-root',expected_current:'a'.repeat(64),confirm:'撤回槽位 2'});
  assert(undoFlow.get('#restore-dialog').open);assert(!undoFlow.get('#restore-confirm').checked);
  assert(!undoFlow.get('#restore-error').hidden);assert(undoFlow.get('#restore-error').textContent.includes('当前进度已变化'));
  undoDigest='b'.repeat(64);undoFlow.get('#restore-confirm').checked=true;
  undoFlow.get('#restore-repreview').listeners.click();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(undoRequests.filter(url=>url.startsWith('/api/backups/undo-preview?')).length,2);
  assert.equal(undoFlow.run('restoreTarget.expected_current'),undoDigest);
  assert(!undoFlow.get('#restore-confirm').checked,'repreview must require confirmation of the new summary');
  assert(undoFlow.get('#restore-error').hidden);failUndo=false;
  undoFlow.get('#restore-confirm').checked=true;
  undoFlow.get('#restore-form').listeners.submit({preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(undoPosts[1].payload.expected_current,undoDigest);assert.equal(undoPosts[1].payload.action,'undo');
  assert(!undoFlow.get('#restore-dialog').open);assert.equal(undoFlow.run('restoreTarget'),null);

  const backups=harness();backups.load('backups.js');backups.load('backup-workflows.js');backups.run('initializeBackups()');
  backups.context.state={backup_context:'restore-root',settings:{save_root:'/synthetic/restore-root'}};
  backups.run("backupFlow.context='restore-root';openConfirm({id:'fixture',slot:2,expected_current:'a'.repeat(64)},'restore','restore-root')");
  backups.get('#restore-confirm').checked=true;
  backups.context.post=async()=>{throw new Error('请先完全退出游戏');};
  backups.get('#restore-form').listeners.submit({preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(backups.get('#restore-error').hidden,false);
  assert(backups.get('#restore-error').textContent.includes('请先完全退出游戏'));
  assert(backups.get('#restore-dialog').open);
  assert(!backups.get('#restore-confirm').checked,'restore failure must clear the old confirmation');
  backups.run("backupState={context:'restore-root',history:[],retained:[],undo:[],slots:[]};renderBackups()");
  assert(backups.get('#restore-error').textContent.includes('请先完全退出游戏'));
  const card=backups.run("backupCard({id:'fixture',saved:1,time:1,last_seen:1,class:'WARRIOR',depth:1,equipment:[]},['1 分钟前','50 秒前'],'node')");
  assert(card.includes('node-tags')&&card.includes('将回到')&&card.includes('1 分钟前')&&card.includes('50 秒前'));
  backups.run("backupState.retained=Array.from({length:45},(_,n)=>({file:'backup-'+n,bytes:100,time:1}));renderBackups()");
  assert.equal((backups.get('#backup-retained').innerHTML.match(/data-rejoin=/g)||[]).length,20);
  backups.get('#backup-retained-more').listeners.click();
  assert.equal((backups.get('#backup-retained').innerHTML.match(/data-rejoin=/g)||[]).length,40);
  const stableBackups=harness();stableBackups.load('backups.js');
  stableBackups.get('#backup-slot').value='2';
  let historyHTML='',historyWrites=0;
  Object.defineProperty(stableBackups.get('#backup-history'),'innerHTML',{
    get(){return historyHTML;},set(html){historyHTML=html;historyWrites++;}
  });
  stableBackups.run("backupState={slots:[],retained:[],undo:[],history:[{id:'fixture',slot:2,saved:100,time:100,last_seen:110,class:'WARRIOR',depth:1,equipment:[],label:'',locked:false}]};renderBackups()");
  stableBackups.run('backupState.history[0].last_seen=112;renderBackups();renderBackups()');
  assert.equal(historyWrites,1,'an unchanged backup row must keep its DOM across polls');
  stableBackups.run("backupState.history[0].label='重要进度';renderBackups()");
  assert.equal(historyWrites,2);assert(historyHTML.includes('重要进度'));
  stableBackups.get('#backup-search').value='不存在';stableBackups.run('renderBackups()');
  assert.equal(historyWrites,3);assert(historyHTML.includes('没有符合筛选'));
  // Fixed numeric plans use only stored inputs even with a conflicting current hero and draft.
  const fixed=harness();fixed.context.state=stamp();fixed.load('rules.js');
  fixed.run("numericalDrafts.set('items.potions.potionofhealing',{hp:999,hero_level:28,vial:3})");
  const storedParams={hp:7,max_hp:55,hero_level:6,vial:-1};
  fixed.context.planFixture={id:'stored',origin:{mode:'save',snapshot_at:80,slot:2,fields:{hp:'快照',vial:'手填'}}};
  fixed.context.numericResult={status:'current',version:'4.0.2',blocks:[],notice:'',inputs:Object.entries(storedParams).map(([key,value])=>({key,value,label:key,min:-1,max:10000}))};
  fixed.context.storedParams=storedParams;let unexpectedNumericFetch=0;
  fixed.context.fetch=async()=>{unexpectedNumericFetch++;throw new Error('stored result must not need current-state fetch');};
  await fixed.run("loadNumericalDetail('items.potions.potionofhealing',storedParams,'saved',{fixed:true,savedPlan:planFixture,result:numericResult})");
  assert.deepEqual(JSON.parse(fixed.run('JSON.stringify(numericalDetail.context)')),storedParams);
  assert.equal(unexpectedNumericFetch,0);assert.equal(fixed.run('numericalDetail.fixed'),true);
  fixed.context.state.modified=500;fixed.context.state.data.hero.hp=1;fixed.run('refreshNumericalOrigin()');
  assert(fixed.get('#values-source').textContent.includes('固定保存参数'));
  assert(fixed.get('#values-freshness').textContent.includes('不跟随'));
  assert.equal(fixed.run("numericalDetail.origins.vial"),'手填');
  fixed.context.fetch=async url=>({ok:true,json:async()=>({status:'current',version:'4.0.2',blocks:[],notice:'',inputs:[{key:'level',value:0,label:'level',min:0,max:99}]})});
  fixed.run('cancelNumericalDetail()');await fixed.run("loadNumericalDetail('items.weapon.melee.shortsword',{},'unknown')");
  assert(fixed.run('numericalDetail.origins.level').includes('等级未知'));
  assert.equal(fixed.run('displayNumber(1.23456789)'),'1.235');
  assert.equal(fixed.run('displayNumber(0.0011496)'),'0.00115');assert.equal(fixed.run('displayNumber(0.0015244)'),'0.001524');assert.equal(fixed.run('displayNumber(0.99951)'),'0.9995');
  assert.equal(fixed.run('displayNumber(0.000300729)'),'0.0003007');assert.equal(fixed.run('displayNumber(-0.000000300729)'),'-3.007e-7');
  assert.equal(fixed.run('displayNumber("3.00729e-7%")'),'3.007e-7%');assert.equal(fixed.run('displayNumber("25.123456%")'),'25.123%');
  assert.equal(fixed.run('displayNumber("1–10")'),'1–10');assert.equal(fixed.run('displayNumber("概率 < 0.001%")'),'概率 < 0.001%');
  assert.equal(fixed.run('sourceURL("https://github.com/00-Evan/shattered-pixel-dungeon/blob/abc/README.md")'),'https://github.com/00-Evan/shattered-pixel-dungeon/blob/abc/README.md');
  assert.equal(fixed.run('sourceURL("javascript:alert(1)")'),null);
  fixed.context.sourceStamp={mode:'save',slot:2,modified:77,started:90,revision:1};
  await fixed.run("loadNumericalDetail('items.waterskin',{dew_volume:6},'example',{ignoreDrafts:true,sourceStamp,fieldOrigins:{dew_volume:'快照记录 · 水袋露珠量'}})");
  assert.equal(fixed.run('numericalDetail.origins.dew_volume'),'快照记录 · 水袋露珠量');assert.equal(fixed.run('numericalDetail.source.modified'),77);
  fixed.run('cancelNumericalDetail()');await fixed.run("loadNumericalDetail('items.weapon.enchantments.blazing',{level:-1,hp:7},'known',{ignoreDrafts:true,capturedContext:true,sourceStamp})");
  assert.equal(fixed.run('numericalDetail.context.level'),-1);assert.equal(fixed.run('numericalDetail.context.hp'),7);
  assert(!fixed.run("'strength' in numericalDetail.context"),'captured item links must not borrow newer live fields under the older snapshot stamp');

  // Restoring a saved equipment plan preserves its exact independent conditions across polling.
  const savedComparison=await freshComparison(firstSave);
  savedComparison.load('rules.js');
  Object.assign(savedComparison.context,{navigationSerial:0,displayNumber:String,originLabel:()=> '过去来源：固定参考',inlineError:(target,message)=>{target.textContent=message;}});
  savedComparison.get('.comparison-panel').scrollIntoView=()=>{};
  const equipmentPlan={id:'equipment',kind:'equipment',name:'力量门槛',origin:{mode:'example',fields:{level_a:'等级未知 · +0示例'}},params:{strength:11,id_a:'items.weapon.melee.shortsword',id_b:'items.weapon.melee.battleaxe',level_a:0,level_b:5,tier_a:3,tier_b:3,mastery_a:'0',mastery_b:'1',augment_a:'NONE',augment_b:'SPEED'}};
  savedComparison.context.equipmentPlan=equipmentPlan;savedComparison.context.equipmentResult={family:'weapon',choices:[{name:'短剑',level:0,upgrade_risk:0},{name:'战斧',level:5,upgrade_risk:0}],rows:[],explanation:{tradeoff:'比较力量缺口',boundary:'不是绝对推荐',choices:[{choice:'A',name:'短剑',summary:'升级不跨门槛',timing_and_accuracy:'攻击耗时 1 → 1',upgrade_changes:[{label:'伤害',before:'1–10',after:'2–12'}]}]}};
  await savedComparison.run('openEquipmentPlan(equipmentPlan,equipmentResult,false)');
  savedComparison.context.state.data.hero.strength=99;savedComparison.context.state.modified=600;savedComparison.run('renderEquipmentComparison()');
  assert.equal(Number(savedComparison.get('#compare-strength').value),11);assert.equal(Number(savedComparison.get('#compare-level-a').value),0);assert.equal(Number(savedComparison.get('#compare-level-b').value),5);assert(savedComparison.get('#compare-mastery-b').checked);
  assert(savedComparison.get('#compare-origin-a').textContent.includes('等级未知'));assert(savedComparison.get('#compare-result').innerHTML.includes('升级不跨门槛'));assert(savedComparison.get('#compare-result').innerHTML.includes('不是最终命中概率'));
  assert(!fs.readFileSync(path.join(root,'web','compare.js'),'utf8').includes('function comparisonUnit('),'metric units must come from the structured backend, not text inference');

  function workspaceHarness(){
    const h=harness();Object.assign(h.context,{view:'overview',navigationSerial:0,detailEntry:null,token:'synthetic-token',
      inlineError:(target,message)=>{target.textContent=message;target.hidden=!message;},toast(){},
      document:{activeElement:null,createElement:()=>element(),addEventListener(){}},window:{addEventListener(){},requestAnimationFrame:fn=>fn()},panelClient:'0123456789abcdef',calculationStamp:()=>null});
    h.context.navigate=next=>{h.context.view=next;h.context.navigationSerial++;};h.load('workspace.js');return h;
  }
  const plans=workspaceHarness();const formValues=new Map();
  plans.get('#manual-form').elements={namedItem:key=>{if(!formValues.has(key))formValues.set(key,element(key));return formValues.get(key);}};
  const buffInputs=[{value:'Burning',checked:false},{value:'Roots',checked:false}],challengeInputs=[{value:'4',checked:false},{value:'1',checked:false}];
  plans.context.$$=selector=>selector.includes('name="buff"')?buffInputs:selector.includes('name="challenge"')?challengeInputs:[];
  const manualPlan={id:'manual',kind:'manual',name:'安全退路',origin:{mode:'manual',snapshot_at:90,slot:null},params:{class:'WARRIOR',hp:8,ht:30,depth:7,branch:0,level:5,strength:12,healing:1,hunger:null,buffs:['Roots'],challenges:4}};
  let manualPosts=0;plans.context.post=async()=>{manualPosts++;};plans.context.fetch=async()=>({ok:true,json:async()=>({plan:manualPlan,result:{},rules_changed:false})});
  await plans.run("openPlan('manual')");
  assert.equal(formValues.get('hp').value,'8');assert.equal(formValues.get('hunger').value,'unknown');
  assert(buffInputs[1].checked);assert(!buffInputs[0].checked);assert(challengeInputs[0].checked);assert.equal(manualPosts,0,'opening a manual plan never applies session state');
  let finishPlan;plans.context.fetch=()=>new Promise(resolve=>finishPlan=resolve);const stalePlan=plans.run("openPlan('manual')");plans.context.navigate('library');formValues.get('hp').value='17';finishPlan({ok:true,json:async()=>({plan:manualPlan})});await stalePlan;
  assert.equal(formValues.get('hp').value,'17','late plan reply cannot overwrite form after navigation');
  plans.context.numericDetail={inputs:[{key:'hp',value:7},{key:'vial',value:-1}],context:{hp:999,strength:1000}};
  assert.deepEqual(JSON.parse(plans.run('JSON.stringify(actualNumericalParams(numericDetail))')),{hp:7,vial:-1});
  let savedPayload;plans.context.post=async(path,payload)=>{savedPayload=payload;throw new Error('controlled full store');};
  plans.context.savedNumeric={id:'record',name:'原方案',record_revision:'opened-revision'};
  plans.run("openPlanSave({kind:'numeric',entry:'example',params:{hp:7},source:{mode:'example',snapshot_at:null,slot:null}},savedNumeric)");
  plans.get('#plan-name').value='修订方案';plans.get('#plan-note').value='条件待核对\n用于首领前';await plans.run('savePlan(true)');
  assert.equal(savedPayload.expected_record_revision,'opened-revision');assert.equal(savedPayload.record_id,'record');assert.equal(savedPayload.name,'修订方案');assert.equal(savedPayload.note,'条件待核对\n用于首领前');assert.equal(plans.get('#plan-name').value,'修订方案');assert(plans.get('#plan-error').textContent.includes('full store'));
  let finishSave;plans.context.post=()=>new Promise(resolve=>finishSave=resolve);const staleSave=plans.run('savePlan()');
  plans.get('#plan-dialog').listeners.close();plans.run("openPlanSave({kind:'numeric',entry:'other',params:{level:3},source:{mode:'example'}},null,'新的草稿')");finishSave({});await staleSave;
  assert(plans.get('#plan-dialog').open);assert.equal(plans.get('#plan-name').value,'新的草稿','late save cannot close a newer dialog');
  plans.context.numericalDetail=null;plans.run('loadWorkspace=async()=>{}');
  let finishMetadata;plans.context.post=()=>new Promise(resolve=>finishMetadata=resolve);
  plans.run("openPlanSave({kind:'numeric',entry:'metadata',params:{hp:7}},null,'提交时名称')");
  plans.get('#plan-note').value='提交时备注';const metadataSave=plans.run('savePlan()');
  plans.get('#plan-name').value='保存途中名称';plans.get('#plan-note').value='保存途中备注';plans.get('#plan-form').listeners.input();
  finishMetadata({plan:{id:'metadata-record',name:'提交时名称',note:'提交时备注',kind:'numeric',entry:'metadata',record_revision:'new-revision'}});await metadataSave;
  assert(plans.get('#plan-dialog').open);assert.equal(plans.get('#plan-note').value,'保存途中备注');
  assert.equal(plans.run("planDraft.existing.id"),'metadata-record');assert.equal(plans.run("planNoteDrafts.get('metadata-record')"),'保存途中备注');
  assert(!plans.run("planNameDrafts.has('numeric:metadata')"),'a save reply must move the newer draft to its new record identity without an orphan draft');

  const origin=plans.run("cleanStoredOrigin({mode:'save',snapshot_at:80,slot:2,kind:'saved_reference',fields:{level:'等级未知 · +0示例'},token:'secret'})");
  assert.deepEqual(JSON.parse(JSON.stringify(origin)),{mode:'save',snapshot_at:80,slot:2,fields:{level:'等级未知 · +0示例'}});

  // Diagnostic preview independently excludes arbitrary backend strings and nested data.
  const help=harness();Object.assign(help.context,{view:'overview',getJSON:async()=>({}),inlineError(){},names:{},sourceURL:()=>null});help.load('help.js');
  help.context.privateFixture={application_version:'/home/private-account',reference_version:'4.0.2',platform:'Windows',token:'opaque-secret',path:'C:\\private-account',connection:{mode:'save',state:'saved',active_slot:1,readable_slots:1,snapshot_age_seconds:40,version_mismatch:false,inventory:['private sword']},backup:{state:'waiting',error:'private log'},desktop:{play_available:true,hotkeys_unavailable_count:1},plans:[{params:{hp:4}}]};
  const diagnostic=help.run('diagnosticText(privateFixture)');
  for(const secret of ['private-account','opaque-secret','private sword','private log','plans','inventory','token'])assert(!diagnostic.includes(secret));
  assert(diagnostic.includes('4.0.2'));assert(diagnostic.includes('snapshot_age_seconds'));assert(diagnostic.includes('unknown'));

  // Every PlayPreferences field is writable, while revision conflicts retain independent edits.
  // Recovered settings retain their original scope and compare actual saved values,
  // even when a new process starts its preference generation at zero again.
  dashboard.load('workspace.js');
  let recoveryConnection={settings_revision:'recovery-original',settings:{save_root:'/synthetic/original',slot:'auto',mode:'save',startup_surface:'native',always_on_top:false,reveal:false,stop_at:''}};
  dashboard.context.recoveryConnection=recoveryConnection;dashboard.run('loadSettings(true,recoveryConnection)');
  dashboard.get('#always-top').checked=true;dashboard.get('#settings-form').listeners.input({target:dashboard.get('#always-top')});
  const connectionDraft=JSON.parse(dashboard.run('JSON.stringify(captureSettingsDraft())'));assert.deepEqual(connectionDraft.changed,['always-top']);
  recoveryConnection={settings_revision:'recovery-current',settings:{...recoveryConnection.settings,save_root:'/synthetic/current',slot:2,reveal:true}};
  dashboard.context.fetch=async()=>({ok:true,json:async()=>structuredClone(recoveryConnection)});
  dashboard.run('settingsDrafts.clear()');dashboard.context.recoveredConnectionDraft=connectionDraft;
  dashboard.context.preparedConnection=await dashboard.run("prepareSettingsRecovery('connection',recoveredConnectionDraft)");
  await dashboard.run('verifySettingsRecovery(preparedConnection)');dashboard.run('applySettingsRecovery(preparedConnection)');
  assert.equal(dashboard.get('#save-root').value,'/synthetic/current');assert.equal(dashboard.get('#settings-slot').value,'2');assert(dashboard.get('#reveal').checked);assert(dashboard.get('#always-top').checked);
  assert.deepEqual(JSON.parse(dashboard.run('JSON.stringify(captureSettingsDraft().changed)')),['always-top']);assert.equal(recoveryConnection.settings.always_on_top,false,'recovery cannot apply preferences');
  dashboard.context.recoveryConnection=recoveryConnection;dashboard.run('loadSettings(true,recoveryConnection)');
  dashboard.get('#save-root').value='/synthetic/draft-root';dashboard.get('#settings-form').listeners.input({target:dashboard.get('#save-root')});
  const rootDraft=JSON.parse(dashboard.run('JSON.stringify(captureSettingsDraft())'));dashboard.run('settingsDrafts.clear()');
  recoveryConnection={settings_revision:'recovery-competing',settings:{...recoveryConnection.settings,save_root:'/synthetic/another-window'}};
  dashboard.context.rootRecoveryDraft=rootDraft;
  const rootChoice=dashboard.run("prepareSettingsRecovery('connection',rootRecoveryDraft)");await new Promise(resolve=>setImmediate(resolve));
  assert(dashboard.run('settingsRecoveryChoice!==null'));assert(dashboard.get('#settings-recovery-fields').innerHTML.includes('/synthetic/draft-root'));
  dashboard.run("finishSettingsRecoveryChoice({'save-root':'draft'})");dashboard.context.preparedRoot=await rootChoice;
  recoveryConnection={settings_revision:'recovery-too-late',settings:{...recoveryConnection.settings,save_root:'/synthetic/newest'}};
  await assert.rejects(dashboard.run('verifySettingsRecovery(preparedRoot)'),/又有变化/);
  assert.equal(dashboard.get('#save-root').value,'/synthetic/another-window');
  const cancelledChoice=dashboard.run("prepareSettingsRecovery('connection',rootRecoveryDraft)");await new Promise(resolve=>setImmediate(resolve));dashboard.run('finishSettingsRecoveryChoice(null)');await assert.rejects(cancelledChoice,/取消载入/);
  dashboard.context.legacySettings=Object.fromEntries(Object.entries(rootDraft.raw).map(([key,value])=>[key,[{value:String(value),checked:typeof value==='boolean'?value:false}]]));
  assert.equal(dashboard.run('checkedSettingsRecovery(legacySettings,settingsFormValues()).changed.length'),7);
  dashboard.context.unknownBaseline={format:2,raw:{'save-root':'/synthetic/early-edit'},baseline:null,changed:['save-root']};
  assert(dashboard.run('checkedSettingsRecovery(unknownBaseline,settingsFormValues()).legacy'));
  assert.deepEqual(JSON.parse(dashboard.run('JSON.stringify(checkedSettingsRecovery(unknownBaseline,settingsFormValues()).changed)')),['save-root']);
  dashboard.context.partialLegacy={'save-root':[{value:'/synthetic/old-partial'}]};
  assert.deepEqual(JSON.parse(dashboard.run('JSON.stringify(checkedSettingsRecovery(partialLegacy,settingsFormValues()).changed)')),['save-root']);
  dashboard.context.badPrototype={format:2,raw:{constructor:'inherited'},baseline:null,changed:['constructor']};
  assert.throws(()=>dashboard.run('checkedSettingsRecovery(badPrototype,settingsFormValues())'),/字段不完整/);
  dashboard.context.invalidScope={...rootDraft,changed:['unsupported-field']};assert.throws(()=>dashboard.run('checkedSettingsRecovery(invalidScope,settingsFormValues())'),/修改范围/);
  dashboard.context.invalidScope={...rootDraft,format:900};assert.throws(()=>dashboard.run('checkedSettingsRecovery(invalidScope,settingsFormValues())'),/版本不兼容/);

  dashboard.context.document.createElement=()=>element();
  let relatedCalculation;
  dashboard.context.loadNumericalDetail=(id,params,origin,options)=>{relatedCalculation={id,params,origin,options};};
  dashboard.context.cancelNumericalDetail=()=>{};
  dashboard.context.numericalDetail=null;
  dashboard.context.calculationStamp=()=>({started:90,mode:'save',slot:1,revision:1,modified:100});
  dashboard.context.currentEquipment={name:'烈焰单手剑 +4',description:'已知附魔说明',location:'主武器',details:['附魔已硬化'],known:true,key:'items.weapon.melee.sword',level:4,level_applicable:true,tier:2,
    related:[{id:'items.weapon.enchantments.blazing',name:'烈焰附魔',description:'烈焰效果',conditions:'正常附魔'},
      {id:'items.scrolls.scrollofupgrade',name:'升级风险',description:'升级说明',conditions:'已硬化：先核对硬化保护损失分支'}]};
  dashboard.run('showItem(currentEquipment)');
  const relatedButtons=[...dashboard.get('#detail-related').children];
  assert.equal(relatedButtons.length,2);
  dashboard.run('renderDetailTools()');
  assert.equal(dashboard.get('#detail-related').children.length,2,'numeric/tool refresh must preserve item-related navigation');
  relatedButtons[1].listeners.click();
  assert.equal(relatedCalculation.id,'items.scrolls.scrollofupgrade');assert.equal(relatedCalculation.params.level,4);
  assert.equal(relatedCalculation.origin,'known');assert(relatedCalculation.options.ignoreDrafts);
  assert(relatedCalculation.options.capturedContext);
  assert.equal(relatedCalculation.options.sourceStamp.modified,100);
  assert(dashboard.get('#detail-context').textContent.includes('已硬化'));
  dashboard.run("showItem({...currentEquipment,name:'普通单手剑',related:[]})");
  assert.equal(dashboard.get('#detail-related').children.length,0,'another item must not retain previous equipment effect links');

  const play=harness();Object.assign(play.context,{view:'overview',inlineError:(target,message)=>{target.textContent=message;target.hidden=!message;},toast(){},getJSON:null});let bindings=[];
  play.context.$$=selector=>selector.includes('data-binding')?bindings:[];
  Object.defineProperty(play.get('#play-bindings'),'innerHTML',{set(html){bindings=[...html.matchAll(/data-binding="([^"]+)"[^>]*value="([^"]*)"/g)].map(m=>{const input=element();input.dataset.binding=m[1];input.value=m[2];return input;});}});
  const playSettings={enabled:true,alerts:true,anchor:'top_left',offset_x:16,offset_y:100,font_scale:1,opacity:.9,notice_seconds:5,bindings:{capture:'Ctrl+Alt+B',library:'Ctrl+Alt+H'}};
  let playServer={settings:playSettings,revision:1,error:'',desktop_available:false,desktop_status:{hotkeys_ready:false,bindings:{}}};play.context.getJSON=async()=>structuredClone(playServer);play.load('play.js');await play.run('loadPlaySettings()');
  assert(play.get('#play-runtime').textContent.includes('尚未确认'));assert(play.get('#play-runtime').textContent.includes('下次启用'));
  assert.deepEqual(Object.keys(JSON.parse(play.run('JSON.stringify(playFormValues())'))).sort(),Object.keys(playSettings).sort());
  play.get('#play-offset_x').value='777';play.get('#play-form').listeners.input();playServer.revision=2;await play.run('loadPlaySettings()');
  assert.equal(play.get('#play-offset_x').value,'777');assert(play.run('playConflict'));assert.equal(play.run('playRevision'),1);
  await play.run('loadPlaySettings(true)');assert.equal(Number(play.get('#play-offset_x').value),16);assert(!play.run('playDirty'));
  let finishPlay,playPosted;play.context.post=(path,payload)=>new Promise(resolve=>{playPosted=payload;finishPlay=resolve;});play.get('#play-offset_x').value='120';play.get('#play-form').listeners.input();
  const pendingPlay=play.get('#play-form').listeners.submit({preventDefault(){}});play.get('#play-offset_x').value='121';play.get('#play-form').listeners.input();
  finishPlay({settings:structuredClone(playPosted.settings),revision:3,desktop_available:true,desktop_status:{applied_revision:3,hotkeys_ready:true,bindings:playSettings.bindings}});await pendingPlay;
  assert.equal(playPosted.settings.offset_x,120);assert.equal(playPosted.revision,2);assert.equal(play.get('#play-offset_x').value,'121');assert(play.run('playDirty'));
  assert(play.get('[data-binding-state="capture"]').textContent.includes('已注册'));
  let finishOldPlay;play.context.getJSON=()=>new Promise(resolve=>finishOldPlay=resolve);const latePlayRead=play.run('loadPlaySettings()');
  play.context.post=async(path,payload)=>({settings:structuredClone(payload.settings),revision:4,desktop_available:false,desktop_status:{}});await play.get('#play-form').listeners.submit({preventDefault(){}});
  finishOldPlay({settings:{...playSettings,offset_x:999},revision:2,desktop_available:false,desktop_status:{}});await latePlayRead;
  assert.equal(play.run('playRevision'),4,'older read cannot overwrite a successful save acknowledgement');assert.equal(play.get('#play-offset_x').value,'121');
  play.context.post=async()=>{throw new Error('revision conflict，请重新读取');};await play.get('#play-form').listeners.submit({preventDefault(){}});
  assert.equal(play.get('#play-offset_x').value,'121');assert(play.run('playConflict'));assert(!play.get('#play-error').hidden);
  let reloadPayload;play.context.getJSON=async()=>({...playServer,revision:12});play.context.post=async(path,payload)=>{reloadPayload={path,payload};return {...playServer,revision:13};};
  await play.get('#play-reload').listeners.click();assert.equal(reloadPayload.path,'/api/play-settings/reload');assert.equal(reloadPayload.payload.revision,12);assert.equal(play.run('playRevision'),13);assert(!play.run('playDirty'));assert(play.get('#play-error').hidden,'ordinary reload must not report its own read as a newer edit');
  let finishReload;play.context.post=(path,payload)=>new Promise(resolve=>finishReload=resolve);const activeReload=play.get('#play-reload').listeners.click();await new Promise(resolve=>setImmediate(resolve));play.get('#play-offset_x').value='999';play.get('#play-form').listeners.input();finishReload({...playServer,revision:14});await activeReload;
  assert.equal(play.get('#play-offset_x').value,'999');assert(play.run('playDirty'),'edits during explicit disk reload must survive its response');
  play.context.post=async()=>({...playServer,revision:15,error:'游玩设置无法读取，显示已暂停',settings:{...playSettings,enabled:false}});
  await play.get('#play-reload').listeners.click();
  assert.equal(play.get('#play-offset_x').value,'999','corrupt disk reload must retain the current draft');assert.equal(play.run('playRevision'),15);assert(!play.run('playConflict'));assert(play.get('#play-error').textContent.includes('草稿保留'));
  const recoveredPlay=workspaceHarness();let recoveryBindings=[];
  recoveredPlay.context.$$=selector=>selector.includes('data-binding')?recoveryBindings:[];
  Object.defineProperty(recoveredPlay.get('#play-bindings'),'innerHTML',{set(html){recoveryBindings=[...html.matchAll(/data-binding="([^"]+)"[^>]*value="([^"]*)"/g)].map(m=>{const input=element();input.dataset.binding=m[1];input.value=m[2];return input;});}});
  let recoveredPlayServer={settings:structuredClone(playSettings),revision:0,error:'',desktop_status:{}};
  recoveredPlay.context.fetch=async()=>({ok:true,json:async()=>structuredClone(recoveredPlayServer)});
  recoveredPlay.load('play.js');await recoveredPlay.run('loadPlaySettings()');
  recoveredPlay.get('#play-offset_x').value='777';recoveredPlay.get('#play-form').listeners.input();
  recoveredPlay.context.scopedPlayDraft=JSON.parse(recoveredPlay.run('JSON.stringify(capturePlayDraft())'));
  assert.deepEqual(recoveredPlay.context.scopedPlayDraft.changed,['play-offset_x']);
  recoveredPlayServer={...recoveredPlayServer,settings:{...playSettings,anchor:'bottom_right',offset_y:222,bindings:{...playSettings.bindings,capture:'Ctrl+Alt+X'}}};
  await recoveredPlay.run('loadPlaySettings(true)');
  recoveredPlay.context.preparedPlay=await recoveredPlay.run("prepareSettingsRecovery('play',scopedPlayDraft)");
  const benignGeneration=recoveredPlay.run('playDraftGeneration');await recoveredPlay.run('loadPlaySettings()');assert.equal(recoveredPlay.run('playDraftGeneration'),benignGeneration,'identical navigation/background read cannot invalidate recovery');
  await recoveredPlay.run('verifySettingsRecovery(preparedPlay)');recoveredPlay.run('applySettingsRecovery(preparedPlay)');
  assert.equal(recoveredPlay.get('#play-offset_x').value,'777');assert.equal(recoveredPlay.get('#play-anchor').value,'bottom_right');assert.equal(recoveredPlay.get('#play-offset_y').value,'222');assert.equal(recoveryBindings.find(input=>input.dataset.binding==='capture').value,'Ctrl+Alt+X');
  assert.equal(recoveredPlay.run('playRevision'),0);assert.deepEqual(JSON.parse(recoveredPlay.run('JSON.stringify(capturePlayDraft().changed)')),['play-offset_x']);
  assert.equal(recoveredPlayServer.settings.offset_x,16,'loading a recovered form must not save it');
  recoveredPlayServer={...recoveredPlayServer,revision:1,settings:{...recoveredPlayServer.settings,offset_x:333}};await recoveredPlay.run('loadPlaySettings(true)');
  const playChoice=recoveredPlay.run("prepareSettingsRecovery('play',scopedPlayDraft)");await new Promise(resolve=>setImmediate(resolve));
  assert(recoveredPlay.run('settingsRecoveryChoice!==null'));
  recoveredPlay.run("finishSettingsRecoveryChoice({'play-offset_x':'draft'})");recoveredPlay.context.preparedPlay=await playChoice;
  await recoveredPlay.run('verifySettingsRecovery(preparedPlay)');
  recoveredPlay.get('#play-offset_y').value='999';recoveredPlay.get('#play-form').listeners.input();
  assert.throws(()=>recoveredPlay.run('applySettingsRecovery(preparedPlay)'),/新设置编辑/);assert.equal(recoveredPlay.get('#play-offset_y').value,'999');
  await recoveredPlay.run('loadPlaySettings(true)');
  recoveredPlay.get('#play-offset_x').value='778';recoveredPlay.get('#play-form').listeners.input();recoveredPlay.get('#play-offset_x').value='333';recoveredPlay.get('#play-form').listeners.input();assert(!recoveredPlay.run('playDirty'),'editing then reverting a settings form must become clean');
  console.log('PASS: existing first-launch, numeric draft, comparison and backup checks; C-01 raw/empty/partial/out-of-range draft reopening and computed-result isolation; fixed saved numeric parameters and origins; input-only plan payload; manual reopen without submission; navigation and dialog response races; explicit plan updates and retained errors; strict diagnostic redaction; all play fields, concurrent draft preservation and explicit disk reload');
})().catch(error=>{console.error(error);process.exitCode=1;});
