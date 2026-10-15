'use strict';
// Execute the production update UI with a synthetic transport; never contact a server.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const nodes=new Map(),requests=[];
function node(id){if(!nodes.has(id))nodes.set(id,{hidden:false,disabled:false,textContent:'',listeners:{},classList:{toggle(){}},addEventListener(kind,fn){this.listeners[kind]=fn;},scrollIntoView(){}});return nodes.get(id);}
let reportedRevision=7,revision=7,pending=null;
const c=vm.createContext({console,$:node,state:{update:{state:'current',current_version:'0.7.0',message:'已是最新版本',can_install:true}},
  navigate(){},inlineError(element,message){element.textContent=message;},webSurfaceId:'test-web',currentWebDraft:()=>({revision,dirty:true,draft:{text:'unsaved'}}),
  post:async(url,payload)=>{requests.push({url,payload});if(url==='/api/session-exit')return {exit:{participants:[{surface_id:'test-web',revision:reportedRevision,dirty:true,has_reported_draft:true}]}};if(pending)return new Promise(resolve=>{pending=resolve;});return {update:{...c.state.update,state:payload.action==='download'?'downloading':'checking'}};}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/updates.js'),'utf8'),c);
const run=code=>vm.runInContext(code,c);
(async()=>{
  run('renderUpdate()');assert.equal(node('#update-entry').textContent,'检查更新');assert(node('#update-download').hidden);
  c.state.update={state:'available',current_version:'0.7.0',latest_version:'0.8.0',message:'新版 0.8.0 可用',notes:'a',can_install:true};
  run('renderUpdate()');assert.equal(node('#update-entry').textContent,'更新 0.8.0');assert(!node('#update-download').hidden);assert(node('#update-install').hidden);
  c.state.update.state='ready';run('renderUpdate()');assert(!node('#update-install').hidden);
  reportedRevision=6;await run("updateAction('install')");assert.equal(requests.filter(r=>r.url==='/api/update').length,0);assert.match(node('#update-error').textContent,/输入发生变化/);
  reportedRevision=revision;await run("updateAction('install')");assert.equal(requests.at(-1).payload.surface_id,'test-web');assert.equal(requests.at(-1).payload.action,'install');
  c.state.update.state='available';pending=true;const first=run("updateAction('download')");assert(node('#update-download').disabled);await run("updateAction('download')");assert.equal(requests.filter(r=>r.payload.action==='download').length,1);pending({update:{...c.state.update,state:'downloading',progress:47}});await first;pending=null;assert.match(node('#update-status').textContent,/47%/);
  c.state=null;run('renderUpdate()');assert(node('#update-entry').disabled);assert(node('#update-install').hidden);
  console.log('Update UI: compact status, explicit actions, draft reporting and single-flight requests passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
