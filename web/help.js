'use strict';
let helpRequest=0,helpDiagnostic='';
const helpReadingLabels={'configuration-error':'连接设置需要修正','read-error':'存档暂不可读','waiting-for-save':'已就绪，等待游戏保存','manual-stale':'手填局势已过期',manual:'手填局势，不自动跟随','saved-stale':'旧存档快照',saved:'最近保存的快照'};
function diagnosticText(raw){
  // An explicit allowlist: never serialize a raw status, exception, path, or token.
  const version=value=>typeof value==='string'&&/^[\w.+-]{1,50}$/.test(value)?value:'unknown';
  const flag=value=>typeof value==='boolean'?value:null;
  const integer=(value,max)=>Number.isInteger(value)&&value>=0&&value<=max?value:null;
  const choice=(value,values)=>values.includes(value)?value:'unknown';
  const r=raw||{},c=r.connection||{},b=r.backup||{},d=r.desktop||{};
  return JSON.stringify({format:1,application:'灯火',application_version:version(r.application_version),reference_version:version(r.reference_version),platform:choice(r.platform,['Windows','Linux','Darwin']),connection:{mode:choice(c.mode,['save','manual']),state:choice(c.state,Object.keys(helpReadingLabels)),active_slot:integer(c.active_slot,6),readable_slots:integer(c.readable_slots,6),snapshot_age_seconds:integer(c.snapshot_age_seconds,1e12),version_mismatch:flag(c.version_mismatch)},backup:{state:choice(b.state,['unknown','waiting','ready','protected','watching','paused','failed','blocked','disabled','working','ok']),has_problem:flag(b.has_problem),last_save_protected:flag(b.last_save_protected)},desktop:{manager_available:flag(d.manager_available),play_available:flag(d.play_available),tray_available:flag(d.tray_available),hotkeys_ready:flag(d.hotkeys_ready),hotkeys_unavailable_count:integer(d.hotkeys_unavailable_count,100)},privacy:'本地摘要；不包含个人路径、存档、背包、方案参数、日志原文或连接口令'},null,2);
}
async function loadHelp(){
  const seq=++helpRequest;
  try{
    const result=await getJSON('/api/help');if(seq!==helpRequest)return;
    $('#help-versions').textContent=`灯火 ${result.application_version} · 游戏规则资料 ${result.reference_version} · ${helpReadingLabels[result.reading_state]||'状态待核对'}`;
    $('#help-native-accessibility').textContent='桌面管理、数值速查、方案与游玩设置使用 Windows 原生控件，可用 Tab / Shift+Tab 移动焦点；按钮获得焦点后用空格操作。数值速查可用 Ctrl+F 返回搜索框、向下键进入结果、回车选择条目；Escape 会隐藏常规工具窗口，关闭管理窗口后可从托盘重新打开。托盘的「打开完整面板」和管理窗口的「完整面板」会打开或复用系统浏览器中的完整网页界面；在连接设置也可选择启动时打开完整网页面板。网页提供标题、表单标签、状态提示和地图坐标文字入口。键盘路径已按控件与事件核对；尚未完成屏幕阅读器、中文输入法和多显示器组合实测，读屏体验仍需核对。';
    const next=$('#help-next');next.replaceChildren();
    if(!result.next_steps?.length)next.innerHTML='<p class="muted">当前没有发现需要恢复的问题。游戏画面与快照不一致时，先在游戏中保存，再核对更新时间。</p>';
    for(const step of result.next_steps||[]){const row=document.createElement('article');row.className='support-step';row.innerHTML=`<h3>${escapeHTML(step.title)}</h3><p>${escapeHTML(step.body)}</p><button class="secondary">打开${escapeHTML(names[step.page]||'冒险概览')}</button>`;row.querySelector('button').addEventListener('click',()=>navigate(step.page));next.append(row);}
    $('#help-shortcut-state').textContent=result.shortcut_state==='defaults-unconfirmed'?'没有读取到原生注册状态；默认快捷键仅作参考。请在游玩设置查看实际注册或占用。':'已读取桌面配置；配置值与实际注册状态分开，打开游玩设置核对是否已生效。';
    $('#help-faq').innerHTML=(result.faq||[]).map(row=>`<details class="faq"><summary>${escapeHTML(row.title)}</summary><p>${escapeHTML(row.body)}</p><button class="secondary" data-help-page="${escapeHTML(row.page)}">打开${escapeHTML(names[row.page]||'相关页面')}</button></details>`).join('');$$('[data-help-page]').forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.helpPage)));
    helpDiagnostic=diagnosticText(result.diagnostic);$('#help-diagnostic').textContent=helpDiagnostic;
    const links=$('#help-links');links.replaceChildren();for(const link of result.links||[]){const url=sourceURL(link.url);if(!url)continue;const anchor=document.createElement('a');anchor.href=url;anchor.textContent=link.label;anchor.className='secondary';anchor.target='_blank';anchor.rel='noreferrer';links.append(anchor);}inlineError($('#help-error'),'');
  }catch(error){if(seq===helpRequest)inlineError($('#help-error'),error.message);}
}
$('#help-refresh').addEventListener('click',loadHelp);
$('#help-copy').addEventListener('click',async()=>{try{if(!helpDiagnostic)throw new Error('先读取排查摘要再复制');await navigator.clipboard.writeText(helpDiagnostic);$('#help-copy-status').textContent='已复制预览中的脱敏摘要；没有自动发送。';}catch(error){$('#help-copy-status').textContent=error.message+'。可在预览中选取文本复制。';}});
for(const [id,action] of [['help-open-data','open-data'],['help-open-log','open-log']])$('#'+id).addEventListener('click',async()=>{const button=$('#'+id);button.disabled=true;try{await post('/api/support',{action});inlineError($('#help-location-error'),'');toast('已请求打开本次助手的本地位置');}catch(error){inlineError($('#help-location-error'),error.message);}finally{button.disabled=false;}});
if(view==='help')loadHelp();
