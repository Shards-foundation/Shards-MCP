import {GateBlocked} from './errors.mjs';
// Covers failures after headers as well as initial fetch rejection. Never include
// remote diagnostics in a receipt. Assertion/size-limit errors keep their verdict.
export async function responseBytes(response,{limit,limitError,transportCode}){
  let reader;const chunks=[];let size=0;
  try{
    reader=response.body?.getReader();
    if(reader)while(true){
      const part=await reader.read();if(part.done)break;
      size+=part.value.byteLength;
      if(size>limit){try{await reader.cancel();}catch{}throw limitError;}
      chunks.push(part.value);
    }
    return Buffer.concat(chunks);
  }catch(e){if(e===limitError)throw e;throw new GateBlocked(transportCode);}
  finally{reader?.releaseLock();}
}
