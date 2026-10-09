// Isolated component tests: no browser, user settings, or game manipulation.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'..');
function element(id=''){
  return {id,value:'',textContent:'',className:'',innerHTML:'',childElementCount:0,hidden:false,disabled:false,
    checked:false,dataset:{},open:true,isConnected:true,listeners:{},
    classList:{toggle(){},contains(){return false;}},closest(){return this;},replaceChildren(){this.innerHTML='';this.childElementCount=0;},
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
    $:get,$$:()=>[],document:{activeElement:null},escapeHTML:String,fmtTime:String,state:null,fetch:async()=>({ok:true,json:async()=>({entries:[]})})});
  return {elements,get,context,run:code=>vm.runInContext(code,context),load:name=>vm.runInContext(fs.readFileSync(path.join(root,'web',name),'utf8'),context)};
}
function stamp(){return {modified:100,active_slot:1,settings:{mode:'save'},revision:1,started:90,stale:false,
  data:{hero:{level:1,ht:20,hp:10,strength:10},depth:1,items:[]}};}
(async()=>{
  const markup=fs.readFileSync(path.join(root,'web','index.html'),'utf8'),ids=[...markup.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
  assert.equal(new Set(ids).size,ids.length,'form and error targets require unique document IDs');
  for(const page of ['workspace','help','play-settings'])assert(markup.includes(`id="view-${page}"`)&&markup.includes(`data-view="${page}"`));
  for(const script of ['workspace.js','help.js','play.js'])assert(markup.includes(`src="/${script}"`)&&fs.existsSync(path.join(root,'web',script)));
  const dashboard=harness();
  const waiting={revision:0,data:null,error:'',warning:'',waiting_for_save:true,slots:[],active_slot:null,backup_context:'first-context',
    modified:0,age_seconds:null,stale:true,catalog_version:'4.0.2',catalog_count:955,token:'fixture',
    settings:{mode:'save',slot:'auto',stop_at:'',reveal:false,save_root:'/synthetic/default',always_on_top:false},backup_health:{state:'waiting'}};
  dashboard.context.document={querySelector:dashboard.get,querySelectorAll:()=>[],addEventListener(){}};
  dashboard.context.window={addEventListener(){},scrollTo(){},focus(){},scrollY:0};
  dashboard.context.location={hash:''};dashboard.context.history={replaceState(){}};
  dashboard.context.crypto={randomUUID:()=> '0123456789abcdef'};
  dashboard.context.setInterval=()=>0;dashboard.context.setTimeout=()=>0;dashboard.context.clearTimeout=()=>{};
  dashboard.context.fetch=async url=>({ok:true,json:async()=>url==='/api/status'?structuredClone(waiting):{}});
  dashboard.get('#calc-level').value='0';dashboard.get('#calc-tier').value='3';
  dashboard.load('backups.js');dashboard.load('app.js');
  await new Promise(resolve=>setImmediate(resolve));
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
  dashboard.get('#settings-reset').listeners.click();
  assert.equal(saveRoot.value,'/synthetic/default');
  assert(!dashboard.get('#settings-draft-status').textContent.includes('尚未保存'));
  let resolveSettings,submittedSettings;
  dashboard.context.post=async(path,payload)=>path==='/api/settings'?new Promise(resolve=>{resolveSettings=resolve;submittedSettings=payload;}):{};
  saveRoot.value='/synthetic/first-edit';dashboard.get('#settings-form').listeners.input({target:saveRoot});
  dashboard.get('#settings-form').listeners.submit({preventDefault(){}});
  saveRoot.value='/synthetic/new-edit';dashboard.get('#settings-form').listeners.input({target:saveRoot});
  assert.equal(submittedSettings.save_root,'/synthetic/first-edit');assert.equal(submittedSettings.startup_surface,'panel');
  resolveSettings({});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(saveRoot.value,'/synthetic/new-edit','late save acknowledgement must not erase newer edits');
  assert(dashboard.get('#settings-draft-status').textContent.includes('尚未保存'));

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
  const undoFlow=harness();undoFlow.load('backups.js');undoFlow.run('initializeBackups()');
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

  const backups=harness();backups.load('backups.js');backups.run('initializeBackups()');
  backups.run("restoreTarget={id:'fixture',slot:2,operation:'restore'}");
  backups.get('#restore-confirm').checked=true;
  backups.context.post=async()=>{throw new Error('请先完全退出游戏');};
  backups.get('#restore-form').listeners.submit({preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(backups.get('#restore-error').hidden,false);
  assert(backups.get('#restore-error').textContent.includes('请先完全退出游戏'));
  assert(backups.get('#restore-dialog').open);
  assert(!backups.get('#restore-confirm').checked,'restore failure must clear the old confirmation');
  backups.run("backupState={history:[],retained:[],undo:[],slots:[]};renderBackups()");
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
  finishPlay({settings:playSettings,revision:3,desktop_available:true,desktop_status:{applied_revision:3,hotkeys_ready:true,bindings:playSettings.bindings}});await pendingPlay;
  assert.equal(playPosted.settings.offset_x,120);assert.equal(playPosted.revision,2);assert.equal(play.get('#play-offset_x').value,'121');assert(play.run('playDirty'));
  assert(play.get('[data-binding-state="capture"]').textContent.includes('已注册'));
  let finishOldPlay;play.context.getJSON=()=>new Promise(resolve=>finishOldPlay=resolve);const latePlayRead=play.run('loadPlaySettings()');
  play.context.post=async()=>({settings:playSettings,revision:4,desktop_available:false,desktop_status:{}});await play.get('#play-form').listeners.submit({preventDefault(){}});
  finishOldPlay({settings:{...playSettings,offset_x:999},revision:2,desktop_available:false,desktop_status:{}});await latePlayRead;
  assert.equal(play.run('playRevision'),4,'older read cannot overwrite a successful save acknowledgement');assert.equal(play.get('#play-offset_x').value,'121');
  play.context.post=async()=>{throw new Error('revision conflict，请重新读取');};await play.get('#play-form').listeners.submit({preventDefault(){}});
  assert.equal(play.get('#play-offset_x').value,'121');assert(play.run('playConflict'));assert(!play.get('#play-error').hidden);
  let reloadPayload;play.context.getJSON=async()=>({...playServer,revision:12});play.context.post=async(path,payload)=>{reloadPayload={path,payload};return {...playServer,revision:13};};
  await play.get('#play-reload').listeners.click();assert.equal(reloadPayload.path,'/api/play-settings/reload');assert.equal(reloadPayload.payload.revision,12);assert.equal(play.run('playRevision'),13);assert(!play.run('playDirty'));
  let finishReload;play.context.post=(path,payload)=>new Promise(resolve=>finishReload=resolve);const activeReload=play.get('#play-reload').listeners.click();await new Promise(resolve=>setImmediate(resolve));play.get('#play-offset_x').value='999';play.get('#play-form').listeners.input();finishReload({...playServer,revision:14});await activeReload;
  assert.equal(play.get('#play-offset_x').value,'999');assert(play.run('playDirty'),'edits during explicit disk reload must survive its response');
  play.context.post=async()=>({...playServer,revision:15,error:'游玩设置无法读取，显示已暂停',settings:{...playSettings,enabled:false}});
  await play.get('#play-reload').listeners.click();
  assert.equal(play.get('#play-offset_x').value,'999','corrupt disk reload must retain the current draft');assert.equal(play.run('playRevision'),15);assert(!play.run('playConflict'));assert(play.get('#play-error').textContent.includes('草稿保留'));
  console.log('PASS: existing first-launch, numeric draft, comparison and backup checks; C-01 raw/empty/partial/out-of-range draft reopening and computed-result isolation; fixed saved numeric parameters and origins; input-only plan payload; manual reopen without submission; navigation and dialog response races; explicit plan updates and retained errors; strict diagnostic redaction; all play fields, concurrent draft preservation and explicit disk reload');
})().catch(error=>{console.error(error);process.exitCode=1;});
