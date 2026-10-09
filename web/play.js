'use strict';
let playSaved=null,playRevision=null,playSeenRevision=null,playRequest=0,playDraftGeneration=0,playDirty=false,playConflict=false,playRuntime=null;
const playFields=['enabled','alerts','anchor','offset_x','offset_y','font_scale','opacity','notice_seconds'];
const bindingLabels={capture:'立即备份',show:'显示完整管理面板',library:'桌面资料速查',backups:'存档时光机',play_toggle:'临时显示 / 隐藏游玩窗',quick:'打开优先建议速查'};
function playFormValues(){
  const result={};for(const key of playFields){const input=$('#play-'+key);result[key]=['enabled','alerts'].includes(key)?input.checked:key==='anchor'?input.value:Number(input.value);}
  result.bindings=Object.fromEntries($$('#play-bindings [data-binding]').map(input=>[input.dataset.binding,input.value]));return result;
}
function renderPlayDraftNotice(){
  $('#play-draft-status').textContent=playConflict?'其他窗口已修改设置；你的草稿保留。请核对后明确「重新读取已保存设置」，再修改和保存。':playDirty?'有尚未保存的游玩设置；切换页面与重连保留草稿，保存才应用。':'按已保存配置显示；实际桌面应用与快捷键注册见上方状态。';
}
function renderPlayRuntime(result){
  const caps=result.desktop_status||{},live=result.desktop_available===true;
  const applied=live&&Number.isInteger(caps.applied_revision)&&caps.applied_revision===result.revision;
  $('#play-runtime').textContent=(live?(applied?'桌面游玩窗口已应用当前保存配置。':'桌面游玩窗口可用，当前配置应用状态尚未确认。'):'当前没有可用的原生游玩窗口；设置会保存供下次启用。')+(caps.hotkeys_ready===true?' 全局快捷键注册已完成；各项状态见表单。':' 全局快捷键注册尚未确认，配置键不能视为已生效。')+(caps.error?' '+caps.error:'');
  for(const input of $$('#play-bindings [data-binding]')){const key=input.dataset.binding,configured=result.settings?.bindings?.[key]||'',actual=caps.bindings?.[key]||'',unavailable=(caps.hotkeys_unavailable||[]).some(item=>typeof item==='string'?(item===key||item===configured):(item.action===key||item.name===key||item.key===key));const status=$(`[data-binding-state="${key}"]`);if(status)status.textContent=!configured?'已禁用':unavailable?'注册失败或被占用，请更换后保存':caps.hotkeys_ready===true&&actual===configured?`已注册：${actual}`:`已配置：${configured}；注册未确认`;}
}
async function loadPlaySettings(force=false){
  const seq=++playRequest;
  try{
    const result=await getJSON('/api/play-settings');if(seq!==playRequest)return;applyPlayRead(result,force||!playDirty);
  }catch(error){if(seq===playRequest)inlineError($('#play-error'),error.message);}
}
function applyPlayRead(result,replaceDraft){
  playRuntime=result;playSeenRevision=result.revision;
  if(replaceDraft){
    playSaved=result.settings;playRevision=result.revision;playDirty=false;playConflict=false;playDraftGeneration++;
    for(const key of playFields)$('#play-'+key)[['enabled','alerts'].includes(key)?'checked':'value']=result.settings[key];
    $('#play-bindings').innerHTML=Object.entries(result.settings.bindings).map(([key,value])=>`<label>${escapeHTML(bindingLabels[key]||key)}<input type="text" data-binding="${escapeHTML(key)}" maxlength="60" value="${escapeHTML(value)}" aria-label="${escapeHTML(bindingLabels[key]||key)}快捷键"><small data-binding-state="${escapeHTML(key)}"></small></label>`).join('');
    inlineError($('#play-error'),result.error||'');
  }else if(result.revision!==playRevision)playConflict=true;
  renderPlayRuntime(result);renderPlayDraftNotice();
}
async function reloadPlaySettings(){
  const operation=++playRequest,generation=playDraftGeneration;$('#play-reload').disabled=true;
  try{const latest=await getJSON('/api/play-settings');if(operation!==playRequest)return;const result=await post('/api/play-settings/reload',{revision:latest.revision});if(operation!==playRequest)return;if(result.error){applyPlayRead(result,false);playRevision=result.revision;playConflict=false;renderPlayDraftNotice();inlineError($('#play-error'),result.error+' 当前表单草稿保留；核对后可保存修正配置。');return;}applyPlayRead(result,generation===playDraftGeneration);if(generation!==playDraftGeneration)inlineError($('#play-error'),'磁盘配置已重新读取；操作期间的新编辑保留为草稿，请核对后再明确重新读取。');}
  catch(error){if(operation===playRequest)inlineError($('#play-error'),error.message);}
  finally{$('#play-reload').disabled=false;}
}
function refreshPlaySettings(){if(state&&state.play_revision!==playSeenRevision)loadPlaySettings();}
$('#play-form').addEventListener('input',()=>{playDirty=true;playDraftGeneration++;renderPlayDraftNotice();});
$('#play-reload').addEventListener('click',reloadPlaySettings);
$('#play-form').addEventListener('submit',async event=>{
  event.preventDefault();if(playRevision===null){inlineError($('#play-error'),'请先读取已保存设置，不能把默认值当作当前配置。');return;}if(playConflict){inlineError($('#play-error'),'其他窗口已修改配置；草稿保留，请明确重新读取再保存。');return;}
  const operation=++playRequest,generation=playDraftGeneration,settings=playFormValues(),revision=playRevision;$('#play-save').disabled=true;
  try{
    const result=await post('/api/play-settings',{settings,revision});if(operation!==playRequest)return;playRevision=result.revision;playSeenRevision=result.revision;playSaved=result.settings||settings;playConflict=false;
    if(generation===playDraftGeneration)playDirty=false;
    inlineError($('#play-error'),'');renderPlayDraftNotice();if(result.desktop_status)renderPlayRuntime({...result,settings:playSaved});else await loadPlaySettings();toast(playDirty?'配置已保存；你之后输入的新修改仍是草稿':'已保存配置；请核对桌面应用与注册状态');
  }catch(error){if(operation===playRequest){inlineError($('#play-error'),error.message);if(/其他|变化|冲突|重新读取/.test(error.message))playConflict=true;renderPlayDraftNotice();}}
  finally{$('#play-save').disabled=false;}
});
if(view==='play-settings')loadPlaySettings();
