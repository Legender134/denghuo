'use strict';
// One bounded job per worker; cancellation terminates the entire instance.
self.onmessage=async event=>{
  try{
    const {seed,depth}=event.data;
    if(typeof seed!=='string'||!/^\d{1,16}$/.test(seed)||!Number.isInteger(depth)||depth<1||depth>24)throw Error('种子或楼层范围无效。');
    const raw=BigInt(seed);if(raw<0n||raw>0xffffffffffffffffn)throw Error('种子超出计算范围。');
    const response=await fetch('/forecast.wasm');if(!response.ok)throw Error('本地预测模块缺失，请完整解压助手。');
    const bytes=await response.arrayBuffer();if(bytes.byteLength>2*1024*1024)throw Error('本地预测模块大小异常。');
    const {instance}=await WebAssembly.instantiate(bytes,{}),length=instance.exports.forecast(Number(raw&0xffffffffn),Number(raw>>32n),depth);
    if(!Number.isInteger(length)||length<1||length>8*1024*1024)throw Error('预测结果大小异常。');
    const pointer=instance.exports.result_ptr(),memory=instance.exports.memory.buffer;
    if(pointer+length>memory.byteLength||memory.byteLength>128*1024*1024)throw Error('预测内存范围异常。');
    const result=JSON.parse(new TextDecoder().decode(new Uint8Array(memory,pointer,length)));
    if(result.error)throw Error('此种子暂不支持计算：'+result.error);
    self.postMessage({ok:true,result});
  }catch(error){self.postMessage({ok:false,error:'离线预测未完成：'+(error?.message||'计算失败')});}
};
