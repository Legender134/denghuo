// Production numeric/reference handlers with real Python save/service fixtures; no GUI.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),os=require('node:os');
const root=path.resolve(__dirname,'..'),temporary=fs.mkdtempSync(path.join(os.tmpdir(),'lamp-public-skills-vm-'));
const python=process.env.FRONTEND_TEST_PYTHON||(process.platform==='win32'?'python':'python3');
const source=`import gzip,json,os
from pathlib import Path
from companion.engine import Catalog
from companion.service import Session
c=Catalog();base=Path(os.environ['PUBLIC_SKILL_TEST_ROOT']);saves=base/'synthetic-saves';slot=saves/'game1';slot.mkdir(parents=True)
config=base/'settings.json';config.write_text(json.dumps({'save_root':str(saves),'mode':'save','slot':1}),encoding='utf-8')
hero={'class':'CLERIC','subClass':'PRIEST','HP':30,'HT':50,'STR':12,'lvl':15,'inventory':[],'buffs':[],
      'talents_tier_1':{'HOLY_INTUITION':1},'talents_tier_2':{'SUNRAY':2,'DIVINE_SENSE':1,'BLESS':2},
      'talents_tier_3':{'HOLY_LANCE':2},'replacements':{}}
def write(fields,stamp):
    game={'version':c.data['version_code'],'depth':2,'challenges':0,'generated_levels':[2],'hero':dict(hero,**fields)}
    p=slot/'game.dat';p.write_bytes(gzip.compress(json.dumps(game).encode(),mtime=0));os.utime(p,(stamp,stamp))
write({},1700000000);s=Session(config,c);s.refresh();snapshots={'initial':s.snapshot()};current=s.workspace_status()['current']
for index,(name,fields) in enumerate((('rank1',{'talents_tier_2':{'SUNRAY':1,'DIVINE_SENSE':2}}),
    ('unlearned',{'talents_tier_2':{}}),('unknown',{'talents_tier_2':[]} ),('incompatible',{'class':'MAGE','subClass':'WARLOCK'}))):
    write(fields,1700000010+index);s.refresh();snapshots[name]=s.snapshot()
results={}
for name in ('sunray','divinesense','blessspell','holylance'):
    identity='actors.hero.spells.'+name
    results[identity]={str(rank):s.values.detail(identity,{'talent':rank}) for rank in (1,2)}
build_current={}
warrior={'class':'WARRIOR','subClass':'BERSERKER','HP':100,'HT':100,
    'talents_tier_1':{'HEARTY_MEAL':2},'talents_tier_2':{'RUNIC_TRANSFERENCE':2},'talents_tier_3':{'STRONGMAN':3},
    'armorAbility':{'__className':'com.shatteredpixel.shatteredpixeldungeon.actors.hero.abilities.warrior.HeroicLeap'}}
warden={'class':'HUNTRESS','subClass':'WARDEN','HP':100,'HT':100,'armorAbility':None,'talents_tier_1':{},'talents_tier_2':{}}
for index,(name,fields) in enumerate((('warrior3',dict(warrior,talents_tier_4={'BODY_SLAM':3})),
    ('warrior1',dict(warrior,talents_tier_4={'BODY_SLAM':1})),('warrior0',dict(warrior,talents_tier_4={})),
    ('warden3',dict(warden,talents_tier_3={'SHIELDING_DEW':3},inventory=[{'__className':'com.shatteredpixel.shatteredpixeldungeon.items.Waterskin','volume':20,'quantity':1}])),
    ('warden1',dict(warden,talents_tier_3={'SHIELDING_DEW':1},inventory=[{'__className':'com.shatteredpixel.shatteredpixeldungeon.items.Waterskin','volume':10,'quantity':1}])),
    ('wardenVial',dict(warden,talents_tier_3={'SHIELDING_DEW':3},inventory=[{'__className':'com.shatteredpixel.shatteredpixeldungeon.items.Waterskin','volume':20,'quantity':1},{'__className':'com.shatteredpixel.shatteredpixeldungeon.items.trinkets.VialOfBlood','level':2,'levelKnown':True}])),
    ('wardenUnknown',dict(warden,talents_tier_3=[],inventory=[{'__className':'com.shatteredpixel.shatteredpixeldungeon.items.Waterskin','volume':10,'quantity':1}])))):
    write(fields,1700000020+index);s.refresh();snapshots[name]=s.snapshot();build_current[name]=s.workspace_status()['current']
results['actors.hero.talent.body_slam']={str(rank):s.values.detail('actors.hero.talent.body_slam',{'talent':rank,'power':10}) for rank in range(5)}
results['items.waterskin']={str(rank)+'-'+str(volume)+'-'+str(vial):s.values.detail('items.waterskin',{'hp':100,'max_hp':100,'vial':vial,'current_shield':0,'shielding_dew':rank,'dew_volume':volume}) for rank in (0,1,3) for volume in (10,20) for vial in (-1,2)}
print(json.dumps({'snapshots':snapshots,'current':current,'results':results,'build_current':build_current}))`;
const child=require('node:child_process').spawnSync(python,['-B','-c',source],{cwd:root,encoding:'utf8',timeout:30000,maxBuffer:4*1024*1024,
  env:{...process.env,APPDATA:path.join(temporary,'appdata'),LOCALAPPDATA:path.join(temporary,'localappdata'),TMPDIR:os.tmpdir(),PUBLIC_SKILL_TEST_ROOT:temporary,PYTHONIOENCODING:'utf-8',PYTHONDONTWRITEBYTECODE:'1'}});
if(child.error)throw child.error;assert.equal(child.status,0,child.stderr);const fixture=JSON.parse(child.stdout),clone=value=>JSON.parse(JSON.stringify(value));
const checks=[],tick=()=>new Promise(resolve=>setImmediate(resolve));
function element(){return {value:'',textContent:'',className:'',disabled:false,open:true,isConnected:true,dataset:{},listeners:{},validity:{valid:true},
  querySelector(){return null;},querySelectorAll(){return [];},contains(){return false;},addEventListener(name,fn){this.listeners[name]=fn;},
  setCustomValidity(message){this.validity.valid=!message;},replaceChildren(){},append(){},showModal(){this.open=true;},focus(){},reportValidity(){},remove(){},insertAdjacentHTML(){}};}
function harness(){
  const elements=new Map(),get=key=>{if(!elements.has(key))elements.set(key,element());return elements.get(key);};let inputs=[];
  const requests=[],context=vm.createContext({URL,URLSearchParams,Map,Set,Number,String,Math,Promise,JSON,console,
    $:get,$$:selector=>selector==='[data-value-key]'?inputs:[],document:{activeElement:null,body:{},createElement:()=>element()},escapeHTML:String,fmtTime:String,
    state:clone(fixture.snapshots.initial),showDetail(){},setDetailEntry(){},showRelatedReferences(){},showItemNote(){},showDetailContext(text){get('#detail-context').textContent=text;}});
  const run=code=>vm.runInContext(code,context);
  Object.defineProperty(get('#detail-rules'),'innerHTML',{get(){return this.html||'';},set(html){this.html=html;inputs=[...html.matchAll(/<input data-value-key="([^"]+)"[^>]*value="([^"]*)"/g)].map(match=>{const input=element();input.dataset.valueKey=match[1];input.value=match[2];elements.set('[data-value-key="'+match[1]+'"]',input);return input;});}});
  const response=url=>{const params=Object.fromEntries(new URLSearchParams(url.split('?')[1]));requests.push(params);const key=params.id==='items.waterskin'?(params.shielding_dew||'0')+'-'+(params.dew_volume||'20')+'-'+(params.vial??'-1'):params.talent||'1';return {ok:true,json:async()=>clone(fixture.results[params.id][key])};};
  context.fetch=async url=>response(url);
  const workspace=fs.readFileSync(path.join(root,'web/workspace.js'),'utf8');
  run(workspace.slice(workspace.indexOf('function lookupCalculationOptions('),workspace.indexOf('function referenceList(')));
  run(fs.readFileSync(path.join(root,'web/rules.js'),'utf8'));
  const app=fs.readFileSync(path.join(root,'web/app.js'),'utf8');run(app.slice(app.indexOf('function itemSnapshotReference('),app.indexOf('// Async backup previews')));
  return {get,run,context,requests,response,edit(raw){const input=get('[data-value-key="talent"]');input.value=raw;input.listeners.input();},
    async open(identity){context.row={id:identity,name:identity,description:'',category:'牧师法术'};run('showReference(row)');await tick();},
    async latest(){get('#values-use-latest').listeners.click();await tick();},async undo(){get('#values-undo-import').listeners.click();await tick();},
    async calculate(){get('#value-calculator').listeners.submit({preventDefault(){}});await tick();}};
}
async function main(){
  const sunray='actors.hero.spells.sunray';
  {
    const h=harness();await h.open(sunray);
    assert.equal(h.requests.at(-1).talent,'2');assert.equal(h.get('[data-value-key="talent"]').value,'2');assert.match(h.get('[data-origin-key="talent"]').textContent||h.run('numericalDetail.origins.talent'),/已学 2/);
    assert.match(h.get('#detail-rules').innerHTML,/6–12/);checks.push('ordinary detail uses real rank 2 Sunray and 6–12');
    await h.open('actors.hero.spells.divinesense');assert.equal(h.requests.at(-1).talent,'1');checks.push('different spells retain their own ranks');
  }
  {
    const h=harness(),row=fixture.current.find(row=>row.id===sunray);h.context.row=clone(row);h.context.state=clone(fixture.snapshots.rank1);
    h.run('showReference(row)');await tick();assert.equal(h.requests.at(-1).talent,'2');assert.match(h.run('numericalDetail.origins.talent'),/已学 2/);
    assert.match(h.get('#detail-context').textContent,/投入 2/);checks.push('captured current reference keeps its rank and conditions after poll');
  }
  {
    const h=harness();await h.open(sunray);h.edit('1');await h.calculate();const prior=h.run('JSON.stringify(numericalDetail.calculated)');
    h.context.state=clone(fixture.snapshots.rank1);await h.latest();assert.equal(h.get('[data-value-key="talent"]').value,'1');assert.match(h.run('numericalDetail.origins.talent'),/已学 1/);
    await h.undo();assert.equal(h.run('JSON.stringify(numericalDetail.calculated)'),prior);assert.equal(h.run('numericalDetail.origins.talent'),'手填');
    checks.push('explicit latest and undo restore manual source and calculated result');
    h.context.state=clone(fixture.snapshots.unlearned);await h.latest();assert.equal(h.get('[data-value-key="talent"]').value,'1');assert.match(h.run('numericalDetail.origins.talent'),/尚未学会/);assert.match(h.get('#detail-context').textContent,/独立参考/);
    checks.push('known unlearned latest preserves manual value with explicit source');
    await h.undo();h.edit('-');const count=h.requests.length;await h.latest();assert.equal(h.requests.length,count);assert.equal(h.get('[data-value-key="talent"]').value,'-');await h.undo();assert.equal(h.get('[data-value-key="talent"]').value,'-');
    checks.push('invalid retained raw input is undoable and never submitted');
  }
  for(const name of ['unknown','incompatible','unlearned']){
    const h=harness();h.context.state=clone(fixture.snapshots[name]);await h.open(sunray);
    assert.equal(h.requests.at(-1).talent,undefined);assert.match(h.run('numericalDetail.origins.talent'),/^示例/);assert.match(h.get('#detail-context').textContent,/独立示例/);
    checks.push(name+' detail is an explicit independent example');
  }
  {
    const h=harness();await h.open(sunray);h.edit('1');await h.calculate();const conditions=h.get('#detail-context').textContent;
    h.context.state=clone(fixture.snapshots.unlearned);h.run('cancelNumericalDetail()');await h.open(sunray);
    assert.equal(h.get('[data-value-key="talent"]').value,'1');assert.equal(h.run('numericalDetail.origins.talent'),'手填');assert.equal(h.get('#detail-context').textContent,conditions);
    checks.push('reopened manual calculation retains captured skill conditions');
  }
  {
    const h=harness();await h.open(sunray);let release;h.context.fetch=url=>new Promise(resolve=>{release=()=>resolve(h.response(url));});
    h.context.state=clone(fixture.snapshots.rank1);h.get('#values-use-latest').listeners.click();await tick();
    h.context.fetch=async url=>h.response(url);await h.undo();release();await tick();assert.equal(h.get('[data-value-key="talent"]').value,'2');assert.match(h.run('numericalDetail.origins.talent'),/已学 2/);
    checks.push('late latest response cannot overwrite undo');
  }
  {
    const h=harness();h.context.saved={id:'fixed-sunray',name:'固定二点',params:{talent:2},origin:{mode:'save',fields:{talent:'快照 · 此技能已学 2 点'}}};h.context.savedResult=clone(fixture.results[sunray]['2']);
    h.context.state=clone(fixture.snapshots.rank1);await h.run(`loadNumericalDetail('${sunray}',saved.params,'saved',{fixed:true,savedPlan:saved,result:savedResult})`);
    assert.equal(h.get('[data-value-key="talent"]').value,'2');assert(h.run('numericalDetail.fixed'));await h.latest();assert.equal(h.get('[data-value-key="talent"]').value,'1');assert(!h.run('numericalDetail.fixed'));await h.undo();assert.equal(h.get('[data-value-key="talent"]').value,'2');assert(h.run('numericalDetail.fixed'));
    checks.push('fixed saved plan remains stable until explicit latest and undo');
  }
  {
    const identity='actors.hero.talent.body_slam',h=harness();h.context.state=clone(fixture.snapshots.warrior3);await h.open(identity);
    assert.equal(h.requests.at(-1).talent,'3');assert.match(h.run('numericalDetail.origins.talent'),/投入 3/);
    h.context.state=clone(fixture.snapshots.warrior1);await h.latest();assert.equal(h.get('[data-value-key="talent"]').value,'1');await h.undo();assert.equal(h.get('[data-value-key="talent"]').value,'3');
    h.context.state=clone(fixture.snapshots.warrior0);await h.latest();assert.equal(h.get('[data-value-key="talent"]').value,'0');assert.match(h.get('#detail-rules').innerHTML,/未投入/);await h.undo();assert.equal(h.get('[data-value-key="talent"]').value,'3');
    checks.push('ordinary talent rank, explicit zero, latest and undo use confirmed build projection');
    const captured=harness();captured.context.state=clone(fixture.snapshots.warrior1);captured.context.row=clone(fixture.build_current.warrior3.find(row=>row.id===identity));captured.run('showReference(row)');await tick();
    assert.equal(captured.requests.at(-1).talent,'3');assert.match(captured.get('#detail-context').textContent,/投入 3/);
    checks.push('current talent reference preserves captured rank across later polling');
    h.context.state=clone(fixture.snapshots.warrior3);const ability=h.run("currentSkillContext('actors.hero.abilities.warrior.heroicleap')");assert.equal(ability.state,'selected');assert.match(ability.conditions,/3 点/);assert.match(ability.conditions,/不代表当前可施放/);
    checks.push('selected armor ability exposes its own saved talent summary without readiness claims');
  }
  {
    const h=harness();h.context.state=clone(fixture.snapshots.warden3);await h.open('items.waterskin');
    assert.equal(h.requests.at(-1).shielding_dew,'3');assert.equal(h.requests.at(-1).dew_volume,'20');assert.equal(h.requests.at(-1).current_shield,'0');assert.equal(h.requests.at(-1).vial,'-1');assert.match(h.get('#detail-rules').innerHTML,/60/);
    h.context.state=clone(fixture.snapshots.warden1);await h.latest();assert.equal(h.get('[data-value-key="shielding_dew"]').value,'1');assert.equal(h.get('[data-value-key="dew_volume"]').value,'10');await h.undo();assert.equal(h.get('[data-value-key="shielding_dew"]').value,'3');assert.equal(h.get('[data-value-key="dew_volume"]').value,'20');
    checks.push('Warden water defaults carry real rank, volume, vial and known absent barrier; latest is undoable');
    h.context.state=clone(fixture.snapshots.wardenUnknown);h.get('[data-value-key="shielding_dew"]').value='-';h.get('[data-value-key="shielding_dew"]').listeners.input();const count=h.requests.length;await h.latest();assert.equal(h.requests.length,count);assert.equal(h.get('[data-value-key="shielding_dew"]').value,'-');await h.undo();assert.equal(h.get('[data-value-key="shielding_dew"]').value,'-');
    checks.push('unknown Warden talent retains invalid raw draft and blocks calculation through latest/undo');
  }
  for(const name of ['warden3','wardenVial','wardenUnknown']){
    const h=harness();h.context.state=clone(fixture.snapshots[name]);h.context.item=h.context.state.data.items.find(row=>row.key==='items.waterskin');
    h.run('showItem(item)');await tick();
    if(name==='wardenUnknown'){assert.equal(h.requests.at(-1).shielding_dew,undefined);assert.match(h.get('#detail-rules').innerHTML,/data-origin-key="shielding_dew">示例 · 请核对/);assert.match(h.get('#detail-context').textContent,/未确认/);}
    else{
      assert.equal(h.requests.at(-1).shielding_dew,'3');assert.equal(h.requests.at(-1).vial,name==='wardenVial'?'2':'-1');
      assert.equal(h.requests.at(-1).dew_volume,'20');assert.equal(h.requests.at(-1).current_shield,'0');
      assert.match(h.run('numericalDetail.origins.shielding_dew'),/投入 3/);assert.match(h.get('#detail-context').textContent,/3 点/);
      assert.match(h.get('#detail-rules').innerHTML,/60/);
    }
    checks.push(name+' actual inventory entry carries identity-specific conditions without applying unknown talents');
  }
  {
    const h=harness();h.context.state=clone(fixture.snapshots.warden3);h.context.item=h.context.state.data.items.find(row=>row.key==='items.waterskin');h.run('showItem(item)');await tick();
    h.get('[data-value-key="shielding_dew"]').value='-';h.get('[data-value-key="shielding_dew"]').listeners.input();
    h.context.state=clone(fixture.snapshots.warden1);h.context.item=h.context.state.data.items.find(row=>row.key==='items.waterskin');h.run('showItem(item)');await tick();
    assert.equal(h.get('[data-value-key="shielding_dew"]').value,'-');const count=h.requests.length;await h.calculate();assert.equal(h.requests.length,count);
    checks.push('reopening actual inventory preserves raw numeric drafts and blocks invalid calculation');
  }
  console.log(JSON.stringify({public_skill_checks:checks,fixture:'real synthetic gzip saves -> Session -> workspace/values',local_only:temporary},null,2));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
