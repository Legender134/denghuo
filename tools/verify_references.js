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
  console.log('PASS: unknown hover makes no identity request; dismiss and late-response isolation; contextual public appearance; stale encyclopedia hydration; safe item links');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
