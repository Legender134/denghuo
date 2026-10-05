// Isolated component tests: no browser, user settings, or game manipulation.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'..');
function element(id=''){
  return {id,value:'',textContent:'',className:'',innerHTML:'',childElementCount:0,hidden:false,disabled:false,
    checked:false,dataset:{},open:true,isConnected:true,listeners:{},
    validity:{valid:true},reportValidity(){return this.validity.valid;},focus(){this.focused=true;},
    addEventListener(name,fn){this.listeners[name]=fn;},querySelectorAll(){return [];},
    querySelector(){return null;},remove(){},insertAdjacentHTML(){}};
}
function harness(){
  const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,element(id.replace(/^#/,'')));return elements.get(id);};
  const context=vm.createContext({URLSearchParams,Map,Set,Number,String,Math,Promise,JSON,console,
    $:get,$$:()=>[],escapeHTML:String,fmtTime:String,state:null,fetch:async()=>({ok:true,json:async()=>({entries:[]})})});
  return {elements,get,context,run:code=>vm.runInContext(code,context),load:name=>vm.runInContext(fs.readFileSync(path.join(root,'web',name),'utf8'),context)};
}
function stamp(){return {modified:100,active_slot:1,settings:{mode:'save'},revision:1,started:90,stale:false,
  data:{hero:{level:1,ht:20,hp:10,strength:10},depth:1,items:[]}};}
(async()=>{
  const numeric=harness();numeric.load('rules.js');numeric.context.state=stamp();
  numeric.run("numericalDetail={identity:'example',inputs:[{key:'hp'},{key:'vial'}],origins:{hp:'快照',vial:'手填'},source:calculationStamp()};refreshNumericalOrigin()");
  assert(!numeric.get('#values-freshness').textContent.includes('旧快照'));
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
    return {ok:true,json:async()=>({status:'current',version:'4.0.1',blocks:[],notice:'',inputs:
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
  assert.equal(drafts.run("numericalDetail.origins.vial"),'手填保留');
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

  const backups=harness();backups.load('backups.js');backups.run('initializeBackups()');
  backups.run("restoreTarget={id:'fixture',slot:2,operation:'restore'}");
  backups.get('#restore-confirm').checked=true;
  backups.context.post=async()=>{throw new Error('请先完全退出游戏');};
  backups.get('#restore-form').listeners.submit({preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(backups.get('#restore-error').hidden,false);
  assert(backups.get('#restore-error').textContent.includes('请先完全退出游戏'));
  assert(backups.get('#restore-dialog').open);
  backups.run("backupState={history:[],retained:[],undo:[],slots:[]};renderBackups()");
  assert(backups.get('#restore-error').textContent.includes('请先完全退出游戏'));
  const card=backups.run("backupCard({id:'fixture',saved:1,time:1,last_seen:1,class:'WARRIOR',depth:1,equipment:[]},['1 分钟前','50 秒前'],'node')");
  assert(card.includes('node-tags')&&card.includes('将回到')&&card.includes('1 分钟前')&&card.includes('50 秒前'));
  backups.run("backupState.retained=Array.from({length:45},(_,n)=>({file:'backup-'+n,bytes:100,time:1}));renderBackups()");
  assert.equal((backups.get('#backup-retained').innerHTML.match(/data-rejoin=/g)||[]).length,20);
  backups.get('#backup-retained-more').listeners.click();
  assert.equal((backups.get('#backup-retained').innerHTML.match(/data-rejoin=/g)||[]).length,40);
  console.log('PASS: numerical origin freshness; new equipment sync and manual retention; durable restore error; wrapping node tags');
})().catch(error=>{console.error(error);process.exitCode=1;});
