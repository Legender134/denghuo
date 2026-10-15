'use strict';
// One set of public encyclopedia links, with opt-in disclosure kept in showItem.
let referenceImages = null, referenceImageLoad = null, detailReferenceSerial = 0;
let referenceHoverSerial = 0, referenceHoverTarget = null, referenceHideTimer;
const referenceCache = new Map();
function referenceIntroText(text){
  const paragraph=String(text||'').trim().split(/\n\s*\n/)[0];
  return paragraph.match(/^[\s\S]*?[。！？](?:[”」』"])?/)?.[0]||paragraph;
}
function setReferenceIntro(text){
  const target=document.querySelector('#detail-intro');if(target)target.textContent=referenceIntroText(text);
}
function publicReferenceId(item){
  if(item.appearance_id)return item.appearance_id;
  if(item.known||item.revealed===true)return item.key;
  return item.kind==='UnknownPotion'?'unknown.potion':item.kind==='UnknownScroll'?'unknown.scroll':item.kind==='UnknownRing'?'unknown.ring':'unknown.item';
}
function referenceImageHTML(identity,name='',portrait=false){
  const row=referenceImages?.entries?.[identity],url=row?.url;
  const alt=portrait?name:'';
  const artwork=url&&/^\/reference-images\/[A-Za-z0-9_.-]+\.png$/.test(url),unknown=String(identity||'').startsWith('unknown.');
  const content=artwork?`<img src="${escapeHTML(url)}" alt="${escapeHTML(alt)}" decoding="async">`:unknown?'<span aria-hidden="true">?</span>':'';
  return `<span class="reference-image${portrait?' reference-portrait':''}" data-reference-image="${escapeHTML(identity||'')}" data-reference-alt="${escapeHTML(alt)}"${!artwork&&!unknown?' hidden':''}>${content}</span>`;
}
function referenceNameHTML(identity,name){return referenceImageHTML(identity,name)+`<span class="reference-name">${escapeHTML(name)}</span>`;}
function bindReferencePreview(element,row,options={}){element._referencePreview={row,...options};}
async function loadReferenceImages(){
  if(referenceImages)return referenceImages;
  if(!referenceImageLoad)referenceImageLoad=fetch('/api/reference-images').then(async response=>{if(!response.ok)throw new Error('图像暂时不可用');return response.json();}).then(result=>{
    referenceImages=result;refreshReferenceImages();return result;
  }).catch(()=>{referenceImageLoad=null;return null;});
  return referenceImageLoad;
}
function refreshReferenceImages(){
  for(const target of document.querySelectorAll('[data-reference-image]')){
    const row=referenceImages?.entries?.[target.dataset.referenceImage];
    if(!row?.url||!/^\/reference-images\/[A-Za-z0-9_.-]+\.png$/.test(row.url))continue;
    const image=document.createElement('img');image.src=row.url;image.alt=target.dataset.referenceAlt||'';image.decoding='async';target.replaceChildren(image);target.hidden=false;
    target.title=row.kind==='identity-icon'?'官方效果图标；瓶色、符文或宝石由每局随机对应':row.kind==='placeholder'?'通用外观占位图':row.kind==='representative-sprite'?'代表外观，实际颜色或形态可变化':'官方游戏图像';
  }
}
function setReferencePortrait(identity,name){
  const target=document.querySelector('#detail-image');if(!target)return;
  target.hidden=!String(identity||'').startsWith('unknown.')&&!referenceImages?.entries?.[identity]?.url;
  target.innerHTML=referenceImageHTML(identity,name,true);void loadReferenceImages().then(()=>{
    if(target.querySelector('[data-reference-image]')?.dataset.referenceImage!==identity)return;
    target.hidden=!String(identity||'').startsWith('unknown.')&&!referenceImages?.entries?.[identity]?.url;
    target.querySelector('.reference-art-caption')?.remove();
    const kind=referenceImages?.entries?.[identity]?.kind;
    if(['identity-icon','placeholder','representative-sprite'].includes(kind)){const note=document.createElement('small');note.className='reference-art-caption';note.textContent=kind==='identity-icon'?'效果图标 · 本局外观随机':kind==='representative-sprite'?'代表外观 · 形态可变化':'通用外观';target.append(note);}
  });
}
async function encyclopediaEntry(identity){
  if(referenceCache.has(identity))return referenceCache.get(identity);
  const response=await fetch('/api/reference?'+new URLSearchParams({id:identity})),row=await response.json();
  if(!response.ok)throw new Error(row.error||'图鉴暂时无法读取');
  referenceCache.set(identity,row);return row;
}
function renderReferenceEncounters(row){
  const target=document.querySelector('#detail-encounters');if(!target)return;
  target.replaceChildren();target.hidden=!row.encounters?.length;if(target.hidden)return;
  const summary=document.createElement('summary');summary.textContent='出现楼层与生成条件';
  const note=document.createElement('p');note.className='muted';note.textContent=row.encounter_note;
  const list=document.createElement('ul');
  for(const encounter of row.encounters){const item=document.createElement('li');item.textContent=`第 ${encounter.depth} 层${encounter.branch?'支线':''} · ${encounter.group}：${encounter.condition}`;list.append(item);}
  target.append(summary,note,list);
}
async function hydrateReference(row,serial){
  try{
    const full=await encyclopediaEntry(row.id);
    if(serial!==detailReferenceSerial||!document.querySelector('#detail-dialog').open)return;
    const description=[row.context_description,full.description,full.hint].filter(Boolean).join('\n\n');
    if(description&&!row.preserve_description){document.querySelector('#detail-text').textContent=description;setReferenceIntro(description);}
    document.querySelector('#detail-category').textContent=full.display_hint||full.type_label||full.category||'图鉴';
    renderReferenceEncounters(full);setReferencePortrait(row.appearance_id||row.id,full.name||row.name);
  }catch(error){
    if(serial===detailReferenceSerial&&document.querySelector('#detail-dialog').open){const status=document.querySelector('#detail-reference-status');if(status){status.hidden=false;status.textContent=error.message;}}
  }
}
function hideReferencePreview(){
  clearTimeout(referenceHideTimer);referenceHoverSerial++;
  const target=document.querySelector('#reference-preview');if(target)target.hidden=true;
  if(referenceHoverTarget){const ids=(referenceHoverTarget.getAttribute('aria-describedby')||'').split(' ').filter(id=>id&&id!=='reference-preview');if(ids.length)referenceHoverTarget.setAttribute('aria-describedby',ids.join(' '));else referenceHoverTarget.removeAttribute('aria-describedby');}
  referenceHoverTarget=null;
}
function positionReferencePreview(target){
  const preview=document.querySelector('#reference-preview'),rect=target.getBoundingClientRect(),width=preview.offsetWidth,height=preview.offsetHeight;
  preview.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-width-8))+'px';
  preview.style.top=Math.max(8,Math.min(rect.bottom+8+height>window.innerHeight?rect.top-height-8:rect.bottom+8,window.innerHeight-height-8))+'px';
}
async function showReferencePreview(target){
  if(referenceHoverTarget===target){clearTimeout(referenceHideTimer);return;}
  hideReferencePreview();referenceHoverTarget=target;const serial=referenceHoverSerial,preview=document.querySelector('#reference-preview');if(!preview)return;
  const dialog=document.querySelector('#detail-dialog');(dialog?.open&&dialog.contains(target)?dialog:document.body).append(preview);
  const {row,item,params={}}=target._referencePreview,identity=item?item.key:row.id,imageIdentity=item?publicReferenceId(item):row.id;
  const name=item?.name||row.name||identity;
  const unknown=item&&!item.known&&item.revealed!==true;
  const context=unknown?'效果未知':row.condition||row.lookup_context?.conditions||'基础参考';
  preview.innerHTML=`<div class="reference-preview-heading">${referenceImageHTML(imageIdentity,name,true)}<div><strong>${escapeHTML(name)}</strong><small>${escapeHTML(Array.isArray(context)?context.join('；'):context)}</small></div></div><p>${escapeHTML(unknown?referenceIntroText(item.description)||'尚未鉴定':'正在读取…')}</p><div class="reference-preview-values"></div><small class="muted">${unknown?'点击查看公开资料；隐藏效果需主动揭示':'点击查看完整机制与条件 →'}</small>`;
  preview.hidden=false;target.setAttribute('aria-describedby',[target.getAttribute('aria-describedby'),'reference-preview'].filter(Boolean).join(' '));positionReferencePreview(target);void loadReferenceImages();
  // The public unknown object has no true identity: hovering never requests hidden data.
  if(item&&!item.known&&item.revealed!==true)return;
  try{
    const full=await encyclopediaEntry(identity);
    const valueParams={...params,...(item?.level==null?{}:{level:item.level}),...(item?.tier?{tier:item.tier}:{})};
    const response=await fetch('/api/values?'+new URLSearchParams({id:identity,...valueParams})),detail=await response.json();
    if(serial!==referenceHoverSerial||referenceHoverTarget!==target||!target.isConnected)return;
    if(!response.ok)throw new Error('数值摘要暂时不可用');
    const blocks=detail.blocks||[],mechanism=blocks.find(block=>block.reading_notes?.length);
    const combat=blocks.find(block=>block.title==='常规战斗数值'),npc=identity.startsWith('actors.mobs.npcs.')&&!combat;
    const selected=blocks.find(block=>block.primary_values?.length)||blocks.find(block=>block.values?.length);
    const notes=mechanism?.reading_notes.slice(0,2)||[];
    const paragraph=preview.querySelector('p'),box=preview.querySelector('.reference-preview-values');box.replaceChildren();
    let values=npc||notes.length?[]:(selected?.primary_values||selected?.values||[]).slice(0,2);
    if(combat&&['actors.mobs.rat','actors.mobs.gnoll','actors.mobs.crab'].includes(identity)){
      values=['基础伤害范围','基础减伤范围','基础速度倍率'].map(label=>combat.values.find(value=>value.label===label)).filter(Boolean);
    }
    paragraph.textContent=notes.length?notes.join('\n'):values.length?'':referenceIntroText(item?.description||full.description||'');
    paragraph.hidden=!paragraph.textContent;
    for(const value of values){const line=document.createElement('p');line.textContent=`${value.label}：${displayNumber(value.value)} ${value.unit||''}${value.condition?'；'+value.condition:''}`;box.append(line);}
    const scope=mechanism?.summary_note??selected?.summary_note??referenceIntroText(selected?.note);
    if(scope&&!npc){const line=document.createElement('p');line.className='muted';line.textContent=scope;box.append(line);}
    positionReferencePreview(target);
  }catch{if(serial===referenceHoverSerial){preview.querySelector('p').textContent=referenceIntroText(item?.description||row.description)||'摘要暂时不可用，点击查看完整图鉴。';positionReferencePreview(target);}}
}
function referencePreviewTrigger(node){for(let current=node;current&&current!==document;current=current.parentElement)if(current._referencePreview)return current;return null;}
document.addEventListener('pointerover',event=>{const target=referencePreviewTrigger(event.target);if(target)void showReferencePreview(target);});
document.addEventListener('focusin',event=>{const target=referencePreviewTrigger(event.target);if(target)void showReferencePreview(target);else hideReferencePreview();});
document.addEventListener('pointerout',event=>{const target=referencePreviewTrigger(event.target);if(target&&!target.contains(event.relatedTarget))referenceHideTimer=setTimeout(hideReferencePreview,160);});
document.addEventListener('focusout',event=>{if(referencePreviewTrigger(event.target))hideReferencePreview();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&referenceHoverTarget){event.preventDefault();event.stopImmediatePropagation();hideReferencePreview();}},true);
document.addEventListener('click',()=>hideReferencePreview());
function referenceTextHTML(value){
  const text=String(value??''),entries=Object.entries(referenceImages?.entries||{}).filter(([id,row])=>row.name===text&&!id.startsWith('unknown.')&&!id.startsWith('appearance.'));
  const candidates=entries.filter(([id])=>id.startsWith('items.')&&!id.includes('$'));
  const selected=candidates.length===1?candidates[0]:entries.length===1?entries[0]:null;
  return selected?`<button type="button" class="reference-link" data-encyclopedia-id="${escapeHTML(selected[0])}" data-encyclopedia-name="${escapeHTML(text)}">${referenceNameHTML(selected[0],text)}</button>`:escapeHTML(value);
}
document.addEventListener('click',event=>{const target=event.target.closest?.('[data-encyclopedia-id]');if(target){event.preventDefault();showReference({id:target.dataset.encyclopediaId,name:target.dataset.encyclopediaName});}});
document.addEventListener('pointerover',event=>{const target=event.target.closest?.('[data-encyclopedia-id]');if(target&&!target._referencePreview){bindReferencePreview(target,{id:target.dataset.encyclopediaId,name:target.dataset.encyclopediaName});void showReferencePreview(target);}});
document.addEventListener('focusin',event=>{const target=event.target.closest?.('[data-encyclopedia-id]');if(target&&!target._referencePreview){bindReferencePreview(target,{id:target.dataset.encyclopediaId,name:target.dataset.encyclopediaName});void showReferencePreview(target);}});
window.addEventListener('resize',hideReferencePreview);window.addEventListener('scroll',()=>{
  // Focusing an offscreen card scrolls it into view after focusin. Keep that
  // keyboard summary attached, while dismissing previews during pointer scroll.
  if(referenceHoverTarget?.contains(document.activeElement)){
    const rect=referenceHoverTarget.getBoundingClientRect();
    if(rect.bottom>0&&rect.top<window.innerHeight){positionReferencePreview(referenceHoverTarget);return;}
  }
  hideReferencePreview();
},true);
document.addEventListener('DOMContentLoaded',()=>{void loadReferenceImages();document.querySelector('#detail-dialog')?.addEventListener('close',()=>{detailReferenceSerial++;hideReferencePreview();});});
