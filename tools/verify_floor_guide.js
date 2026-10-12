'use strict';
// DOM/transport controllers only. No browser, native window or game execution.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/floor-guide.js'),'utf8');
const scoutingSource=fs.readFileSync(path.join(__dirname,'../web/scouting.js'),'utf8');
function harness(){
  const nodes=new Map(),writes=[],reads=[],references=[];
  function node(tag='div'){return {tagName:tag.toUpperCase(),children:[],listeners:{},open:false,hidden:false,disabled:false,textContent:'',innerHTML:'',
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;this.innerHTML='';this.textContent='';},addEventListener(name,handler){this.listeners[name]=handler;},contains(item){return this===item||this.children.some(child=>child.contains?.(item));},focus(){context.document.activeElement=this;},getContext(){return {fillRect(){},strokeRect(){}};}};}
  const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
  const state={started:1,revision:1,settings_revision:'s1',active_slot:1,run_id:'run1',error:'',stale:false,
    settings:{mode:'save',save_root:'synthetic-only'},data:{depth:4,branch:0,version:922,hero:{level:5}}};
  const context=vm.createContext({console,JSON,String,Number,Object,Map,Set,URLSearchParams,state,$:get,view:'overview',
    document:{createElement:node},snapshotViewOwner:()=>JSON.stringify([state.started,state.settings.save_root,state.active_slot,state.run_id,state.settings.mode]),
    inlineError:(target,text)=>{target.textContent=text;target.hidden=!text;},fmtTime:String,
    escapeHTML:value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])),
    post:(url,payload)=>new Promise((resolve,reject)=>writes.push({url,payload,resolve,reject})),
    fetch:url=>new Promise((resolve,reject)=>reads.push({url,resolve,reject})),exampleHTML:block=>`<section>${block.title}</section>`,
    scoutCoordinate:row=>`(${row.x}, ${row.y})`,scoutingCards:()=>{},showScoutedItem:()=>{},showReference:(...args)=>references.push(args)});
  const run=code=>vm.runInContext(code,context);run(scoutingSource);
  context.navigate=view=>{context.view=view;run('loadScouting()');};
  run(source);return {context,state,get,writes,reads,references,run};
}
function catalog(){return {source:{slot:1,depth:4,branch:0,version:922,modified:100,expected:'a'.repeat(64),hero_level:5},supported:true,
  floors:[{depth:4,branch:0,current:true,available:true}],encounters:{note:'常规生成参考，不是本局实例',rows:[{id:'actors.mobs.crab',name:'螃蟹',hp:'15',damage:'1–7',dr:'0–4',condition:'每轮名额',group:'普通轮换'}]}};}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
async function load(h){h.writes.at(-1).resolve(catalog());await settle();}
const deadline=setTimeout(()=>{console.error('FAIL: floor guide verification did not complete');process.exitCode=1;},5000);
(async()=>{
  const h=harness();assert.equal(h.writes.length,1);assert.equal(h.writes[0].payload.action,'catalog');await load(h);
  assert.equal(h.writes.length,1,'automatic guide must never reveal a floor');assert.equal(h.reads.length,0,'collapsed cards must not fetch all numeric details');
  assert.equal(h.get('#floor-hidden-open').disabled,false);assert.equal(h.get('#floor-monsters-count').textContent,'1 种');
  const card=h.get('#floor-monsters-list').children[0];assert.equal(card.tagName,'DETAILS');assert.equal(card.open,false);assert.match(card.children[0].children[1].textContent,/生命 15.*普攻 1–7/);
  card.open=true;card.listeners.toggle();assert.equal(h.reads.length,1);const params=new URL(h.reads[0].url,'http://synthetic').searchParams;
  assert.equal(params.get('hero_level'),'5');assert.equal(params.get('loot_count'),'0');assert.equal(params.get('depth'),'4');
  h.reads[0].resolve({ok:true,json:async()=>({inputs:[{key:'target_hp',label:'分裂前生命',value:40},{key:'damage',label:'输入伤害',value:20}],blocks:[{title:'掉落物、数量与概率'}]})});await settle();assert.match(card.children[2].innerHTML,/掉落物、数量与概率/);
  assert.match(card.children[2].innerHTML,/本次参考参数：分裂前生命：40；输入伤害：20/);
  assert.match(card.children[2].innerHTML,/未读取敌人的当前状态/);
  card.open=false;card.listeners.toggle();card.open=true;card.listeners.toggle();assert.equal(h.reads.length,1);
  const reveal=h.run('revealFloorContents()');assert.equal(h.writes.length,2);assert.equal(h.writes[1].payload.reveal,true);assert.equal(h.writes[1].payload.expected,'a'.repeat(64));
  h.writes[1].resolve({depth:4,branch:0,source:{slot:1,floor_modified:100},map:{width:1,height:1,tiles:[1],hero:null},item_count:0,note:'已保存事实',features:[{terrain:16,name:'隐藏门',x:2,y:1,hidden:true}],traps:[{name:'毒镖陷阱',x:2,y:2,visible:false,active:true}],heaps:[{name:"木箱",x:1,y:2,items:[{name:"短剑",quantity:1}]},{name:"地面物品",x:2,y:2,items:[]}],mobs:[]});await reveal;
  assert.equal(h.get('#floor-hidden-content').hidden,false);assert.match(h.get('#floor-hidden-count').textContent,/1 门.*1 未显陷阱/);
  const hiddenNodes=h.get('#floor-hidden-content').children;
  const heapGroup=hiddenNodes.find(node=>node.id==='floor-hidden-heaps');
  assert(heapGroup,'all floor heaps share one disclosure');assert.equal(heapGroup.open,false);
  assert.match(heapGroup.children[0].textContent,/地上物品与容器.*2 处/);
  assert.equal(heapGroup.children.length,3,'one heading plus both heap disclosures');
  assert.equal(heapGroup.children[1].tagName,'DETAILS');assert.equal(heapGroup.children[1].open,false);
  assert.equal(heapGroup.children[2].open,false);assert.equal(hiddenNodes[0].tagName,'UL');
  assert.match(hiddenNodes[0].children[0].textContent,/隐藏门/);
  assert.match(hiddenNodes[0].children[1].textContent,/毒镖陷阱/);
  const requestsBeforeHeapOpen=h.writes.length;heapGroup.open=true;
  assert.equal(h.writes.length,requestsBeforeHeapOpen,'opening saved heap group performs no new reveal');
  const mapButton=h.get('#floor-hidden-content').children.at(-1);mapButton.listeners.click();
  assert.equal(h.get('#scout-reveal').checked,true);assert.equal(h.get('#scout-result').hidden,false);
  assert.match(h.get('#scout-source').textContent,/槽位 1.*第 4 层/);assert.equal(h.get('#scout-open').disabled,false);
  h.writes.at(-1).resolve(catalog());await settle();assert.equal(h.get('#scout-result').hidden,false,'late catalog must not clear revealed handoff');
  h.context.view='overview';
  h.state.revision++;h.run('refreshFloorGuide()');assert.equal(h.get('#floor-hidden-content').hidden,true);await load(h);
  assert.equal(h.get('#floor-monsters-list').children[0],card,'same-floor save refresh preserves open public monster cards');
  const old=h.run('revealFloorContents()');const pending=h.writes.at(-1);h.state.active_slot=2;h.state.run_id='run2';h.run('refreshFloorGuide()');
  pending.resolve({source:{floor_modified:100},features:[],traps:[],heaps:[],mobs:[]});await old;assert.equal(h.get('#floor-hidden-content').hidden,true);
  const newer=h.writes.at(-1);h.state.error='存档不可读';h.run('refreshFloorGuide()');newer.resolve(catalog());await settle();
  assert.equal(h.get('#floor-monsters-list').children.length,0);assert.equal(h.get('#floor-hidden-open').disabled,true);
  assert.match(h.get('#floor-monsters-brief').textContent,/游戏保存后/);
  const unsupported=harness(),unsupportedCatalog=catalog();unsupportedCatalog.supported=false;unsupportedCatalog.encounters.rows=[];unsupportedCatalog.encounters.note='当前版本未核对常规生成规则';
  unsupported.writes[0].resolve(unsupportedCatalog);await settle();assert.match(unsupported.get('#floor-monsters-brief').textContent,/当前版本未核对/);assert.equal(unsupported.get('#floor-hidden-open').disabled,true);
  const finalFloor=harness(),finalCatalog=catalog();finalCatalog.encounters.rows=[];finalCatalog.encounters.note='最终楼层不生成普通刷新怪物';finalFloor.writes[0].resolve(finalCatalog);await settle();assert.match(finalFloor.get('#floor-monsters-brief').textContent,/最终楼层不生成/);
  const retry=harness();await load(retry);const retryCard=retry.get('#floor-monsters-list').children[0];retryCard.open=true;retryCard.listeners.toggle();retry.reads[0].reject(new Error('离线'));await settle();
  assert.equal(retryCard.children[3].hidden,false);const retrying=retryCard.children[3].listeners.click();assert.equal(retry.reads.length,2);
  retry.state.data.depth=5;retry.state.revision++;retry.run('refreshFloorGuide()');retry.reads[1].resolve({ok:true,json:async()=>({blocks:[{title:'过期响应'}]})});await retrying;
  assert(!retryCard.children[2].innerHTML.includes('过期响应'));
  const grouped=harness(),groupedCatalog=catalog();
  groupedCatalog.encounters.rows.push(...['活化石像','巨型食人鱼'].map((name,index)=>({id:'special-'+index,name,hp:'30',damage:'随条件',dr:'0–4',group:'特殊房间',fold_group:'房间与任务条件',condition:'仅在对应房间出现'})));
  grouped.writes[0].resolve(groupedCatalog);await settle();
  const top=grouped.get('#floor-monsters-list').children;
  assert.equal(top.length,2,'one visible regular enemy and one conditional group');
  const group=top[1];assert.equal(group.tagName,'DETAILS');assert.equal(group.open,false);assert.match(group.children[0].textContent,/房间与任务条件.*2 种/);
  assert.equal(group.children[1].children.length,2);assert.equal(grouped.reads.length,0);
  group.open=true;assert.equal(grouped.reads.length,0,'opening a condition group must not load all enemy details');
  const nested=group.children[1].children[0];nested.open=true;nested.listeners.toggle();assert.equal(grouped.reads.length,1);
  grouped.reads[0].resolve({ok:true,json:async()=>({blocks:[{title:'掉落物、数量与概率'}]})});await settle();
  grouped.state.revision++;grouped.run('refreshFloorGuide()');grouped.writes.at(-1).resolve(groupedCatalog);await settle();
  assert.equal(grouped.get('#floor-monsters-list').children[1],group,'same-floor refresh retains group and nested expansion');
  assert.equal(group.open,true);assert.equal(nested.open,true);
  nested.children[2].children.at(-1).focus();
  grouped.state.data.hero.level=6;grouped.state.revision++;grouped.run('refreshFloorGuide()');
  assert.match(nested.children[2].textContent,/角色等级已变化/);
  assert.equal(nested.children[2].children.length,0,'retire old full-reference button before the new catalog arrives');
  const upgraded=JSON.parse(JSON.stringify(groupedCatalog));upgraded.source.hero_level=6;
  grouped.writes.at(-1).resolve(upgraded);await settle();
  const rebuiltGroup=grouped.get('#floor-monsters-list').children[1],rebuiltNested=rebuiltGroup.children[1].children[0];
  assert.notEqual(rebuiltGroup,group);assert.equal(rebuiltGroup.open,true);assert.equal(rebuiltNested.open,true);
  assert.equal(grouped.context.document.activeElement,rebuiltNested.children[0],'level-up restores identifiable focus to the same monster summary');
  assert.equal(grouped.reads.length,2,'open card refreshes its numeric conditions after level-up');
  assert.equal(new URL(grouped.reads[1].url,'http://synthetic').searchParams.get('hero_level'),'6');
  grouped.reads[1].resolve({ok:true,json:async()=>({blocks:[{title:'新等级掉落条件'}]})});await settle();
  assert.match(rebuiltNested.children[2].innerHTML,/新等级掉落条件/);
  grouped.state.data.depth=5;grouped.state.revision++;grouped.run('refreshFloorGuide()');
  upgraded.source.depth=5;grouped.writes.at(-1).resolve(upgraded);await settle();
  assert.equal(grouped.get('#floor-monsters-list').children[1].open,false,'different floor does not inherit expansion');
  const lateLevel=harness();await load(lateLevel);
  const lateCard=lateLevel.get('#floor-monsters-list').children[0];lateCard.open=true;lateCard.listeners.toggle();
  lateLevel.state.data.hero.level=6;lateLevel.state.revision++;lateLevel.run('refreshFloorGuide()');
  lateLevel.reads[0].resolve({ok:true,json:async()=>({blocks:[{title:'旧等级迟到结果'}]})});await settle();
  assert(!lateCard.children[2].innerHTML.includes('旧等级迟到结果'));
  const lateCatalog=catalog();lateCatalog.source.hero_level=6;lateLevel.writes.at(-1).resolve(lateCatalog);await settle();
  assert.equal(lateLevel.get('#floor-monsters-list').children[0].open,true);
  assert.equal(new URL(lateLevel.reads[1].url,'http://synthetic').searchParams.get('hero_level'),'6');
  const spectral=harness();spectral.state.data.depth=8;spectral.run('refreshFloorGuide()');
  const spectralCatalog=catalog();spectralCatalog.source.depth=8;spectralCatalog.floors[0].depth=8;
  spectralCatalog.encounters.rows=[{id:'actors.mobs.wraith',name:'怨灵',hp:'1',damage:'5–10',dr:'0',group:'特殊房间',condition:'本层房间'},
    {id:'actors.mobs.wraith',reference_key:'actors.mobs.wraith@spectral-summon',reference_depth:4,name:'怨灵（招魂法师召唤）',hp:'1',damage:'3–6',dr:'0',group:'任务房间',condition:'固定按等效第4层'}];
  spectral.writes.at(-1).resolve(spectralCatalog);await settle();
  const variants=spectral.get('#floor-monsters-list').children;assert.equal(variants.length,2);
  for(const variant of variants){variant.open=true;variant.listeners.toggle();}
  assert.equal(new URL(spectral.reads[0].url,'http://synthetic').searchParams.get('depth'),'8');
  assert.equal(new URL(spectral.reads[1].url,'http://synthetic').searchParams.get('depth'),'4');
  spectral.reads[1].resolve({ok:true,json:async()=>({blocks:[{title:'常规战斗数值'}]})});await settle();
  variants[1].children[2].children.at(-1).listeners.click();
  const captured=spectral.references[0][0];assert.equal(captured.id,'actors.mobs.wraith');
  assert.equal(captured.lookup_context.params.depth,4);assert.match(captured.lookup_context.conditions,/固定按等效第4层/);
  const challenged=harness();challenged.state.data.depth=20;challenged.state.data.challenges_mask=256;challenged.state.data.challenges_known=true;challenged.run('refreshFloorGuide()');
  const strongCatalog=catalog();Object.assign(strongCatalog.source,{depth:20,challenges_mask:256,challenges_known:true});strongCatalog.floors[0].depth=20;
  strongCatalog.encounters.rows=[{id:'actors.mobs.dwarfking',name:'矮人国王',hp:'450',damage:'15–25',dr:'0–10',group:'首领',condition:'绝命头目初始生命参考',reference_params:{stronger_bosses:1}},
    {id:'actors.mobs.dwarfking$dkgolem',name:'国王魔像',hp:'100',damage:'25–30',dr:'0–12',group:'挑战支援',fold_group:'绝命头目挑战支援',condition:'须满足召唤阶段'}];
  challenged.writes.at(-1).resolve(strongCatalog);await settle();
  const strongCards=challenged.get('#floor-monsters-list').children,strongCard=strongCards[0];
  assert.match(strongCard.children[0].children[1].textContent,/生命 450/);assert.equal(strongCards[1].open,false);
  strongCard.open=true;strongCard.listeners.toggle();assert.equal(new URL(challenged.reads[0].url,'http://synthetic').searchParams.get('stronger_bosses'),'1');
  challenged.reads[0].resolve({ok:true,json:async()=>({blocks:[{title:'强化初始生命450'}]})});await settle();
  strongCard.children[2].children.at(-1).listeners.click();
  assert.equal(challenged.references[0][0].lookup_context.params.stronger_bosses,1);
  assert.match(challenged.references[0][0].lookup_context.field_origins.stronger_bosses,/所选存档/);
  assert.deepEqual(Array.from(challenged.references[0][0].lookup_context.stamp),[1,'synthetic-only','save',1,1,100]);
  assert.equal(challenged.references[0][0].lookup_context.source,undefined,'known floor reference retains its exact saved-snapshot provenance');
  const oldButton=strongCard.children[2].children.at(-1);
  challenged.state.data.challenges_mask=0;challenged.run('refreshFloorGuide()');
  assert.equal(challenged.get('#floor-monsters-list').children.length,0,'same-floor challenge change invalidates old cached numeric cards even before revision changes');
  oldButton.listeners.click();assert.equal(challenged.references.length,1,'retired challenge reference cannot reopen');
  const normalCatalog=JSON.parse(JSON.stringify(strongCatalog));normalCatalog.source.challenges_mask=0;normalCatalog.encounters.rows[0].hp='300';normalCatalog.encounters.rows[0].reference_params.stronger_bosses=0;normalCatalog.encounters.rows.length=1;
  challenged.writes.at(-1).resolve(normalCatalog);await settle();
  const normalCard=challenged.get('#floor-monsters-list').children[0];assert.equal(normalCard.open,false);normalCard.open=true;normalCard.listeners.toggle();
  assert.equal(new URL(challenged.reads[1].url,'http://synthetic').searchParams.get('stronger_bosses'),'0');
  challenged.state.data.challenges_mask=256;challenged.run('refreshFloorGuide()');
  challenged.reads[1].resolve({ok:true,json:async()=>({blocks:[{title:'迟到普通生命300'}]})});await settle();
  assert(!normalCard.children[2].innerHTML.includes('迟到普通生命300'));
  challenged.writes.at(-1).resolve(normalCatalog);await settle();
  assert.match(challenged.get('#floor-guide-error').textContent,/挑战条件已变化/);
  const vault=harness(),vaultCatalog=catalog();vault.state.data.depth=17;vault.state.data.branch=1;vault.run('refreshFloorGuide()');Object.assign(vaultCatalog.source,{depth:17,branch:1});Object.assign(vaultCatalog.floors[0],{depth:17,branch:1});
  vaultCatalog.encounters.rows=['vaultsentry','vaultlaser'].map(id=>({id:'actors.mobs.npcs.'+id,name:id,hp:'不可破坏',damage:'不使用普通攻击',dr:'免疫伤害',group:'宝库机关',fold_group:'宝库机关/房间条件',condition:'由房间布置决定'}));
  vault.writes.at(-1).resolve(vaultCatalog);await settle();const vaultGroup=vault.get('#floor-monsters-list').children[0];
  assert.equal(vaultGroup.open,false);assert.match(vaultGroup.children[0].textContent,/宝库机关\/房间条件/);assert.equal(vault.reads.length,0);
  vaultGroup.open=true;assert.equal(vault.reads.length,0);const mechanism=vaultGroup.children[1].children[0];mechanism.open=true;mechanism.listeners.toggle();assert.equal(vault.reads.length,1);
  console.log(JSON.stringify({public_only_automatic:true,collapsed_lazy_numeric_and_loot:true,same_floor_expansion_preserved:true,explicit_hidden_opt_in:true,save_slot_error_and_late_response_invalidation:true,retry:true,conditional_groups_collapsed_and_lazy:true}));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>clearTimeout(deadline));
