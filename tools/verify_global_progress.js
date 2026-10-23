// Actual migration component in a synthetic VM DOM; no browser or personal files.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const nodes=new Map(),requests=[],posts=[];
function element(id=''){
  const node={id,value:'',textContent:'',children:[],dataset:{},listeners:{},disabled:false,checked:false,hidden:false,
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=[...items];},
    addEventListener(event,fn){this.listeners[event]=fn;},focus(){},click(){return this.listeners.click?.({target:this});}};
  if(id)nodes.set(id,node);return node;
}
function all(node){return [node,...node.children.flatMap(child=>child.children?all(child):[child])];}
function get(selector){const id=selector.replace(/^#/,'');for(const node of nodes.values()){const found=all(node).find(item=>item.id===id);if(found)return found;}if(id==='migration-global-confirm')return null;return nodes.get(id)||element(id);}
const globalRow={key:'global:badges.dat',group:'global',label:'badges.dat',valid:true,detail:'来源版本由用户声明',target_exists:true,source_version:'4.0.2',target:'synthetic/saves/badges.dat',summary:{badges:2}};
const preference={key:'preference:font_scale',group:'preference',label:'字号',valid:true,detail:'1.3'};
const status={rows:[globalRow,preference],save_root:'synthetic/saves',backup_target:'synthetic/backups',application_version:'1.0',rules_version:'4.0.2',note:'optional'};
const preview={...status,source:{application_version:'1.0',rules_version:'4.0.2'},current_application_version:'1.0',current_rules_version:'4.0.2',expected:'preview-1'};
const ctx=vm.createContext({console,Map,Set,JSON,String,Promise,Date,URL:{},setTimeout,token:'synthetic-token',view:'other',
  bindingLabels:{capture:'立即备份已保存进度',show:'显示随行助手'},planLabels:{numeric:'数值计算'},
  document:{createElement:()=>element(),createTextNode:text=>({textContent:text})},$ :get,
  inlineError:(node,text)=>node.textContent=text,navigate(){},
  post:async(url,payload)=>{posts.push({url,payload});if(url.endsWith('/global-recovery-preview'))return {pending:true,directory:'synthetic/retained',files:['badges.dat'],effect:'恢复导入前原件',expected:'recover-1'};if(url.endsWith('/global-recovery'))return {pending:false,directory:'synthetic/retained',message:'已恢复原件'};const rows=structuredClone(status.rows.filter(row=>payload.selected.includes(row.key)));return {expected:'export-1',count:rows.length,bytes:123,note:'explicit',rows};},
  fetch:async(url,options)=>{requests.push({url,options});if(url.endsWith('/preview'))return {ok:true,json:async()=>structuredClone(preview)};if(url.endsWith('/import'))return {ok:true,json:async()=>({results:[{key:globalRow.key,ok:true,saved:true,message:'原字节已保存'}],success_count:1,failure_count:0,note:'原件仍保留'})};return {ok:true,json:async()=>structuredClone(status)};}});
const run=code=>vm.runInContext(code,ctx);
vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../web/migration.js'),'utf8'),ctx);
async function click(id){await get('#'+id).listeners.click({target:get('#'+id)});}
function choose(input,type='import'){get('#view-migration').listeners.change({target:input});}
function globalCheck(type){return all(get('#migration-'+type+'-list')).find(node=>node.dataset?.key===globalRow.key);}
async function main(){
  await run('loadMigration()');
  // Display formatting must preserve migration direction, selected invalid rows and their errors.
  ctx.displayHost=element();ctx.displayRows=[
    {key:'preference:enabled',group:'preference',label:'游玩显示开关',valid:false,error:'文件已变化，重新预览',detail:'{"当前":true,"导入":false}'},
    {key:'preference:font_scale',group:'preference',label:'字号比例',valid:true,detail:'{"当前":1.0,"导入":1.3}'},
    {key:'preference:bindings',group:'preference',label:'全局快捷键',valid:true,detail:'{"当前":{"capture":"Ctrl+Alt+B","show":"Ctrl+Alt+L"},"导入":{"capture":"Alt+B","show":"Alt+L"}}'},
    {key:'plan:test',group:'plan',label:'我的方案',valid:true,detail:'numeric · 资料版本 4.0.2'}];
  for(const row of ctx.displayRows.filter(row=>row.group==='preference'))row.target='synthetic/play-mode.json';
  run('migrationRows(displayHost,displayRows,new Set(["preference:enabled"]),"import")');
  const displayed=all(ctx.displayHost),visibleText=displayed.map(node=>node.textContent).join('\n');
  assert.match(visibleText,/当前 已开启 → 导入 已关闭/);assert.match(visibleText,/当前 100% → 导入 130%/);
  assert.match(visibleText,/立即备份已保存进度/);assert.match(visibleText,/Ctrl\+Alt\+B → Alt\+B/);
  assert.match(visibleText,/数值计算 · 资料版本 4.0.2/);assert.match(visibleText,/文件已变化，重新预览/);
  const invalidSelected=displayed.find(node=>node.dataset?.key==='preference:enabled');
  assert(invalidSelected.checked);assert(!invalidSelected.disabled,'selected invalid item can still be deselected');
  assert.equal(displayed.filter(node=>node.textContent==='synthetic/play-mode.json').length,1,'shared target is retained once');
  const targetDetails=displayed.find(node=>node.children?.some(child=>child.textContent==='本机保存位置'));
  assert(targetDetails&&!targetDetails.open,'complete shared target is available on demand');
  ctx.displayRows[1].target='synthetic/other-play.json';run('migrationRows(displayHost,displayRows,new Set(["preference:enabled"]),"import")');
  const distinctTargets=all(ctx.displayHost).map(node=>node.textContent);
  assert.equal(distinctTargets.filter(text=>text==='本机目标：synthetic/play-mode.json').length,2);
  assert(distinctTargets.includes('本机目标：synthetic/other-play.json'),'different destinations remain explicit per item');
  assert.deepEqual([...run('migrationExportSelection')],[preference.key]);
  assert.equal(globalCheck('export').checked,false);
  await click('migration-export-all');assert(!run('migrationExportSelection.has("global:badges.dat")'));
  const sourceCheck=globalCheck('export');sourceCheck.checked=true;choose(sourceCheck,'export');
  const exportNodes=all(get('#migration-export-list'));
  const version=exportNodes.find(node=>node.listeners?.change&&node.children?.some(child=>child.value==='unknown'));
  version.value='4.0.2';version.listeners.change();
  const declared=exportNodes.find(node=>node.type==='checkbox'&&!node.dataset?.key);declared.checked=true;declared.listeners.change();
  await click('migration-export-preview');
  const exportRequest=posts.find(row=>row.url.endsWith('/export-preview'));
  assert.equal(exportRequest.payload.global_version,'4.0.2');assert.equal(exportRequest.payload.global_version_confirmed,true);
  assert(exportRequest.payload.selected.includes(globalRow.key));
  get('#migration-file').files=[{name:'synthetic-global.zip',size:123}];get('#migration-file').listeners.change();
  await click('migration-preview');
  assert.deepEqual([...run('migrationImportSelection')],[preference.key]);assert.equal(globalCheck('import').checked,false);
  await click('migration-import-all');assert(!run('migrationImportSelection.has("global:badges.dat")'));
  const importCheck=globalCheck('import');importCheck.checked=true;choose(importCheck);
  const choice=all(get('#migration-import-list')).find(node=>node.children?.some(child=>child.value==='replace'));
  assert.equal(choice.value,'');choice.value='replace';choice.listeners.change();
  assert.equal(get('#migration-global-confirm').checked,false);
  get('#migration-global-confirm').checked=true;get('#migration-global-confirm').listeners.change();
  get('#migration-confirm').checked=true;
  await click('migration-import');
  const sent=requests.find(row=>row.url.endsWith('/import'));
  assert.equal(sent.options.headers['X-Companion-Migration-Global-Confirmed'],'true');
  assert.deepEqual(JSON.parse(sent.options.headers['X-Companion-Migration-Global-Choices']),{'global:badges.dat':'replace'});
  assert.equal(run('migrationGlobalConfirmed'),true); // Receipt reflects submitted confirmation; new preview resets it.
  await click('migration-preview');assert.equal(run('migrationGlobalConfirmed'),false);assert.equal(get('#migration-global-confirm').checked,false);
  run('migrationGlobalConfirmed=true; migrationEdited("import")');assert.equal(run('migrationGlobalConfirmed'),false);
  const panel=element('recovery-host');ctx.recoveryHost=panel;
  run('renderMigrationGlobalRecovery(recoveryHost,{directory:"synthetic/retained",effect:"originals retained"})');
  const recoveryPanel=panel.children[0];await recoveryPanel.children.find(node=>node.listeners?.click).click();
  const recoveryConfirm=all(recoveryPanel).find(node=>node.type==='checkbox');
  const recoveryApply=all(recoveryPanel).find(node=>node.textContent==='确认恢复全局原件');
  assert(recoveryApply.disabled);assert(!posts.some(row=>row.url.endsWith('/global-recovery')));
  recoveryConfirm.checked=true;recoveryConfirm.listeners.change();await recoveryApply.click();
  const recovered=posts.find(row=>row.url.endsWith('/global-recovery'));
  assert.deepEqual(JSON.parse(JSON.stringify(recovered.payload)),{expected:'recover-1',confirmed:true});
  run('migrationGlobalVersion="4.0.2";migrationGlobalVersionConfirmed=true;migrationGlobalConfirmed=true;migrationGlobalChoices.set("global:badges.dat","replace");migrationDirty=true');
  const draft=run('captureMigrationDraft()');ctx.savedDraft=draft;
  await run('restoreMigrationDraft(savedDraft)');
  assert.equal(run('migrationGlobalVersion'),'unknown');assert.equal(run('migrationGlobalVersionConfirmed'),false);assert.equal(run('migrationGlobalConfirmed'),false);assert.equal(run('migrationGlobalChoices.size'),0);
  assert.equal(get('#migration-confirm').checked,false);assert.match(get('#migration-import-info').textContent,/重新选择.*确认已清除/);
  // Exercise the real confirmation handler, not just the selection-list formatter.
  status.rows=[
    {key:'preference:enabled',group:'preference',label:'游玩显示',valid:true,detail:'true'},
    {key:'preference:font_scale',group:'preference',label:'字号',valid:true,detail:'1.0'},
    {key:'preference:opacity',group:'preference',label:'透明度',valid:true,detail:'0.9'},
    {key:'preference:notice_seconds',group:'preference',label:'提示时长',valid:true,detail:'5'},
    {key:'preference:bindings',group:'preference',label:'全局快捷键',valid:true,detail:'{"capture":"Ctrl+Alt+B","show":"Ctrl+Alt+L"}'},
    {key:'plan:test',group:'plan',label:'我的方案',valid:true,detail:'numeric · 资料版本 4.0.2'}];
  ctx.exportKeys=status.rows.map(row=>row.key);run('migrationExportSelection=new Set(exportKeys)');
  await click('migration-export-preview');
  const confirmed=all(get('#migration-export-records')),confirmationText=confirmed.map(node=>node.textContent).join('\n');
  assert.equal(get('#migration-export-records').children.length,status.rows.length);
  for(const text of ['已开启','100%','90%','5 秒','2 项快捷键','数值计算 · 资料版本 4.0.2','立即备份已保存进度','Ctrl+Alt+B'])assert(confirmationText.includes(text),text);
  assert(!/\btrue\b|\bfalse\b|"capture"|\bnumeric\b/.test(confirmationText),confirmationText);
  const shortcutDetails=confirmed.find(node=>node.children?.some(child=>child.textContent==='快捷键'));
  assert(shortcutDetails&&!shortcutDetails.open,'shortcut confirmation remains collapsed initially');
  assert.equal(get('#migration-error').textContent,'');assert(!get('#migration-export-download').disabled);
  console.log(JSON.stringify({ok:true,checks:14,scope:'migration VM, optional globals/version/conflicts/headers/recovery/draft reset and readable export confirmation'}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
