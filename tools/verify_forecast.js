'use strict';
// Production DOM handlers plus the real local WASM worker under CLI Node/VM.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto');
const root=path.join(__dirname,'..'),source=fs.readFileSync(path.join(root,'web/forecast.js'),'utf8'),workerSource=fs.readFileSync(path.join(root,'web/forecast-worker.js'),'utf8');
const metadata=JSON.parse(fs.readFileSync(path.join(root,'data/forecast_items.json'),'utf8'));
const info={...metadata,maximum_depth:24,profile:'canonical-warrior-no-challenges-no-trinket',note:'独立新局参考',effects:{Weapon:{blazing:'烈焰'}}};
async function realWorker(seed,depth){
  const messages=[],requests=[],self={postMessage:message=>messages.push(message)};
  const context=vm.createContext({self,WebAssembly,TextDecoder,BigInt,Number,JSON,Error,
    fetch:async url=>{requests.push(url);return {ok:true,arrayBuffer:async()=>{const bytes=fs.readFileSync(path.join(root,'web/forecast.wasm'));return bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);}};}});
  vm.runInContext(workerSource,context);await self.onmessage({data:{seed,depth}});
  return {message:messages[0],requests};
}
function harness(){
  const nodes=new Map(),writes=[],workers=[],timers=[],details=[],calculations=[];
  function node(tag='div'){return {tagName:tag.toUpperCase(),value:'',textContent:'',checked:false,disabled:false,hidden:false,children:[],listeners:{},
    append(...values){this.children.push(...values);},replaceChildren(){this.children=[];},addEventListener(event,fn){this.listeners[event]=fn;}};}
  const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};get('#forecast-result').hidden=true;
  class Worker{constructor(url){this.url=url;workers.push(this);}postMessage(payload){this.payload=payload;}terminate(){this.terminated=true;}}
  const context=vm.createContext({console,JSON,Number,String,Object,Map,Set,BigInt,Date,WebAssembly,Worker,$:get,document:{createElement:node},
    state:{started:1,settings_revision:'r1',active_slot:1,run_id:'run1',revision:1,error:'',data:{},settings:{mode:'save'}},
    fmtTime:String,inlineError:(target,message)=>{target.textContent=message;target.hidden=!message;},
    post:(url,payload)=>new Promise((resolve,reject)=>writes.push({url,payload,resolve,reject})),api:async url=>{assert.equal(url,'/api/forecast');return info;},
    setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout:()=>{},
    showDetail:(...args)=>details.push(args),setDetailEntry:()=>{},loadNumericalDetail:(...args)=>calculations.push(args)});
  const run=code=>vm.runInContext(code,context);
  run('function scoutingContext(){return JSON.stringify([state?.started,state?.settings_revision,state?.active_slot,state?.run_id,state?.revision,state?.error,state?.settings?.mode]);}');run(source);
  return {context,run,get,writes,workers,timers,details,calculations};
}
function input(h,code='AAA-AAA-AAA'){h.get('#forecast-seed').value=code;h.get('#forecast-seed').listeners.input();h.get('#forecast-confirm').checked=true;h.get('#forecast-confirm').listeners.change();}
async function start(h){input(h);await h.run('runForecast()');assert.equal(h.workers.at(-1).url,'/forecast-worker.js');}
function allNodes(node){return [node,...node.children.flatMap(allNodes)];}
(async()=>{
  const receipt=JSON.parse(fs.readFileSync(path.join(root,'third_party/seed_seeker/source.json'),'utf8'));
  const bytes=fs.readFileSync(path.join(root,'web/forecast.wasm'));
  assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),receipt.wasm_sha256);
  const module=await WebAssembly.compile(bytes);assert.equal(WebAssembly.Module.imports(module).length,0);
  const actual=await realWorker('0',24);assert.equal(actual.message.ok,true);assert.equal(actual.requests.join(','),'/forecast.wasm');
  const result=actual.message.result;assert.equal(result.seed_code,'AAA-AAA-AAA');assert.equal(result.items.length,99);
  assert.equal((await realWorker('5429503678977',1)).message.ok,false,'daily identity must not be reduced modulo seed space');
  assert.equal((await realWorker('0',25)).message.ok,false);
  const h=harness();assert.equal(h.writes.length,0);assert.equal(h.workers.length,0);assert(h.get('#forecast-run').disabled);
  for(const [text,seed] of [['AAA-AAA-AAA','0'],['zzzzzzzzz','5429503678975'],['1970-01-01','5429503678976'],['2026-10-11','7221180478976']])assert.equal(h.run(`parseForecastSeed(${JSON.stringify(text)})`),seed);
  for(const text of ['','-1','123','2026-02-29','1969-12-31','AAAA-AAAAA','ABCDEF-GHI','<script>'])assert.throws(()=>h.run(`parseForecastSeed(${JSON.stringify(text)})`));
  input(h);assert.equal(h.get('#forecast-run').disabled,false);await h.run('runForecast()');
  const worker=h.workers.at(-1);assert.equal(worker.payload.seed,'0');assert.equal(worker.payload.depth,24);worker.onmessage({data:{ok:true,result}});
  assert.equal(h.get('#forecast-result').hidden,false);assert.match(h.get('#forecast-title').textContent,/4.0.2新局参考/);
  const buttons=allNodes(h.get('#forecast-floors')).filter(node=>node.tagName==='BUTTON');assert.equal(buttons.length,99);
  const choiceText=allNodes(h.get('#forecast-floors')).map(node=>node.textContent).join('\n');assert.match(choiceText,/互斥组/);assert.match(choiceText,/不能同时取得/);assert.match(choiceText,/隐藏/);
  buttons[0].listeners.click();const calculation=h.calculations[0];assert.equal(calculation[2],'assumed');assert.equal(calculation[3].capturedContext,true);assert.equal(calculation[3].ignoreDrafts,true);assert.equal(calculation[3].sourceStamp,null);assert.equal(calculation[1].strength,undefined);assert.match(calculation[3].fieldOrigins.level,/独立新局参考/);assert.match(h.details[0][3],/未持有/);
  const queriedName=info.items.find(item=>item.id===result.items[0].id).name;h.get('#forecast-query').value=queriedName;h.get('#forecast-query').listeners.input();const filtered=allNodes(h.get('#forecast-floors')).filter(node=>node.tagName==='BUTTON');assert(filtered.length>0&&filtered.every(node=>node.textContent.includes(queriedName)));
  h.get('#forecast-query').value='';h.get('#forecast-kind').value='Artifact';h.get('#forecast-kind').listeners.change();const artifacts=allNodes(h.get('#forecast-floors')).filter(node=>node.tagName==='BUTTON');assert(artifacts.length);artifacts[0].listeners.click();assert.equal(h.calculations.at(-1)[2],'unknown');assert.equal(h.calculations.at(-1)[1].level,undefined);
  assert.match(h.run("forecastAccess({type:'scenarios',group:8,mask:'5'})"),/可走路径 1、3/);
  await start(h);const stale=h.workers.at(-1);h.get('#forecast-confirm').checked=false;h.get('#forecast-confirm').listeners.change();assert(stale.terminated);stale.onmessage({data:{ok:true,result}});assert(h.get('#forecast-result').hidden);
  await start(h);const edited=h.workers.at(-1);h.get('#forecast-seed').value='ZZZ-ZZZ-ZZZ';h.get('#forecast-seed').listeners.input();edited.onmessage({data:{ok:true,result}});assert(h.get('#forecast-result').hidden);assert(h.get('#forecast-run').disabled);
  const handoff=h.run('readForecastSeed()');const request=h.writes.at(-1);assert.equal(request.url,'/api/forecast');assert.equal(request.payload.reveal,true);
  request.resolve({seed:'0',seed_code:'AAA-AAA-AAA',source:{slot:1,version:920,version_name:'4.0.1',depth:4,modified:100},note:'不能作为本局未来确定结果'});await handoff;assert.equal(h.get('#forecast-confirm').checked,false);assert.equal(h.get('#forecast-from').value,'5');assert.match(h.get('#forecast-origin').textContent,/4.0.1/);
  h.get('#forecast-confirm').checked=true;h.get('#forecast-confirm').listeners.change();await h.run('runForecast()');const slotWorker=h.workers.at(-1);h.context.state.active_slot=2;h.run('refreshForecastContext()');assert(slotWorker.terminated);slotWorker.onmessage({data:{ok:true,result}});assert(h.get('#forecast-result').hidden);assert(h.get('#forecast-run').disabled);
  await start(h);h.timers.at(-1)();assert(h.workers.at(-1).terminated);assert.match(h.get('#forecast-error').textContent,/15秒/);
  await start(h);h.workers.at(-1).onerror();assert(h.get('#forecast-result').hidden);assert.match(h.get('#forecast-error').textContent,/加载或运行失败/);
  await start(h);h.workers.at(-1).onmessage({data:{ok:true,result:{...result,seed:'1'}}});assert(h.get('#forecast-result').hidden);assert.match(h.get('#forecast-error').textContent,/校验失败/);
  console.log('PASS: shipped WASM checksum and real worker computation, exact seed/daily identities, opt-in UI, names/filters/numerics, acquisition constraints, cancellation, stale replies, slot changes, timeout and errors; CLI/VM only');
})().catch(error=>{console.error(error);process.exitCode=1;});
