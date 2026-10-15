// Production hover and hydration handlers: isolated transport, no personal saves.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
function element(){return {dataset:{},children:[],hidden:false,open:true,isConnected:true,textContent:'',innerHTML:'',style:{},offsetWidth:300,offsetHeight:200,attrs:{},
  append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},contains(){return false;},
  getAttribute(key){return this.attrs[key]||null;},setAttribute(key,value){this.attrs[key]=value;},removeAttribute(key){delete this.attrs[key];},
  getBoundingClientRect(){return {left:20,top:20,bottom:50};},addEventListener(){},querySelector(selector){return this.parts?.[selector]||null;}};}
function harness(){
  const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);},requests=[];
  const preview=get('#reference-preview');preview.parts={'p':element(),'.reference-preview-values':element()};
  const context=vm.createContext({URLSearchParams,Map,Object,Number,String,Promise,console,setTimeout,clearTimeout,
    escapeHTML:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),displayNumber:String,
    document:{body:element(),querySelector:get,querySelectorAll:()=>[],createElement:element,addEventListener(){}},
    window:{innerWidth:390,innerHeight:700,addEventListener(){}},
    fetch:url=>new Promise(resolve=>requests.push({url,resolve:body=>resolve({ok:true,json:async()=>body})}))});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/references.js'),'utf8'),context);
  const run=code=>vm.runInContext(code,context);run("referenceImages={entries:{'unknown.potion':{url:'/reference-images/unknown-potion.png'}}}");
  return {context,get,run,requests};
}
async function main(){
  const h=harness(),unknown=element();h.context.target=unknown;
  h.run("bindReferencePreview(target,{id:'items.potions.potion',name:'乳白药剂'},{item:{key:'items.potions.potion',kind:'UnknownPotion',name:'乳白药剂',known:false,details:['效果未知'],description:'尚未鉴定'}})");
  await h.run('showReferencePreview(target)');assert.equal(h.requests.length,0);assert(!h.get('#reference-preview').hidden);
  assert(!h.get('#reference-preview').innerHTML.includes('potionofhealing'));
  assert.equal(h.run("publicReferenceId({kind:'UnknownPotion',known:false,key:'items.potions.potion'})"),'unknown.potion');
  h.run('hideReferencePreview()');assert(h.get('#reference-preview').hidden);assert(!unknown.getAttribute('aria-describedby'));
  const known=element();h.context.target=known;h.run("bindReferencePreview(target,{id:'actors.mobs.rat',name:'啮齿小鼠'})");
  const reading=h.run('showReferencePreview(target)');assert.match(h.requests[0].url,/\/api\/reference\?/);
  h.run('hideReferencePreview()');h.requests.shift().resolve({name:'啮齿小鼠',description:'原始说明'});
  await new Promise(resolve=>setImmediate(resolve));h.requests.shift().resolve({blocks:[{values:[{label:'生命',value:8,unit:'HP'}]}]});await reading;
  assert(h.get('#reference-preview').hidden);assert.equal(h.get('#reference-preview').parts.p.textContent,'');
  const hydrate=h.run("hydrateReference({id:'actors.mobs.rat',name:'啮齿小鼠'},detailReferenceSerial)");await hydrate;
  assert.equal(h.get('#detail-text').textContent,'原始说明');
  const old=h.run("hydrateReference({id:'actors.mobs.gnoll',name:'豺狼'},detailReferenceSerial)");
  h.run('detailReferenceSerial++');h.get('#detail-text').textContent='新条目';h.requests.shift().resolve({name:'豺狼',description:'迟到说明'});await old;
  assert.equal(h.get('#detail-text').textContent,'新条目');
  h.run("referenceImages.entries['items.food.food']={name:'口粮',url:'/reference-images/food.png'}");
  assert.match(h.run("referenceTextHTML('口粮')"),/data-encyclopedia-id="items.food.food"/);
  assert.equal(h.run("referenceTextHTML('<script>')"),'&lt;script&gt;');
  for(const [identity,blocks,expected,absent] of [
    ['actors.mobs.goo',[{title:'常规战斗数值',reading_notes:['准备2次攻击行动；弹道须可达。','水中每次自身行动恢复1 HP。'],
      summary_note:'普通基础参考',values:[{label:'初始生命',value:100}]}],'准备2次','初始生命'],
    ['actors.mobs.rat',[{title:'常规战斗数值',values:[{label:'初始生命',value:8},{label:'基础伤害范围',value:'1–4'},
      {label:'基础减伤范围',value:'0–1'},{label:'基础速度倍率',value:1}]}],'基础伤害范围','初始生命'],
    ['items.potions.elixirs.elixirofaquaticrejuvenation',[{primary_values:[{label:'治疗池',value:150,unit:'HP',condition:'站在水中且未漂浮；药水恐惧下不治疗'}]}],'未漂浮','长篇背景'],
    ['actors.mobs.npcs.ghost',[{values:[{label:'初始生命',value:1}]}],'这是公开介绍。','初始生命'],
  ]){
    const preview=harness(),target=element();preview.context.target=target;preview.context.entry={id:identity,name:'合成条目'};
    preview.run('bindReferencePreview(target,entry)');const pending=preview.run('showReferencePreview(target)');
    preview.requests.shift().resolve({description:'这是公开介绍。长篇背景不在悬停时重复。'});
    await new Promise(resolve=>setImmediate(resolve));preview.requests.shift().resolve({blocks});await pending;
    const parts=preview.get('#reference-preview').parts;
    const text=[parts.p.textContent,...parts['.reference-preview-values'].children.map(row=>row.textContent)].join('\n');
    assert.match(text,new RegExp(expected));assert(!text.includes(absent));
  }
  // A current-resource entry gets imagery/encounters without replacing its captured calculation context.
  const opening=harness();let loaded=null;opening.context.ref={entry:'items.waterskin',name:'水袋',note:'已捕获的露珠条件',params:{hp:20},source_label:'旧快照'};
  Object.assign(opening.context,{showDetail:(name,note)=>opening.get('#detail-text').textContent=note,
    showDetailContext:text=>opening.get('#detail-context').textContent=text,setDetailEntry(){},
    lookupCalculationOptions:()=>({source:{label:'旧快照'}}),loadNumericalDetail:(...args)=>loaded=args});
  const workflow=fs.readFileSync(path.join(__dirname,'../web/workspace.js'),'utf8');
  vm.runInContext(workflow.slice(workflow.indexOf('function openDecisionReference('),workflow.indexOf('function refreshWorkspaceViews(')),opening.context);
  opening.run("openDecisionReference(ref,'resource')");
  opening.requests.shift().resolve({description:'百科背景',encounters:[{depth:1,group:'参考',condition:'合成条件'}]});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(opening.get('#detail-text').textContent,'已捕获的露珠条件\n\n百科背景');
  assert(!opening.get('#detail-encounters').hidden);assert.equal(loaded[1].hp,20);
  assert(loaded[3].capturedContext&&loaded[3].ignoreDrafts);assert.equal(loaded[3].source.label,'旧快照');
  opening.context.ref={entry:'items.food.food',name:'口粮',note:'已捕获的进食条件',
    food_reference:{primary_values:[{label:'每份参考饱食',value:'100',unit:'点'}],summary_note:'饥饿游戏；非即时回血'}};
  opening.run("openDecisionReference(ref,'resource')");
  assert.equal(loaded[3].foodReference.primary_values[0].value,'100');
  assert.match(loaded[3].foodReference.summary_note,/饥饿游戏/);
  console.log('PASS: unknown hover makes no identity request; dismiss and late-response isolation; contextual public appearance; stale encyclopedia hydration; safe item links');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
