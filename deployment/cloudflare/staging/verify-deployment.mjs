import {fileURLToPath} from 'node:url';
import {SOURCE,hash} from './build.mjs';
import {validateApproval,ensure,GateBlocked,GateFailure} from './policy.mjs';
const API='https://api.cloudflare.com/client/v4';
import {responseBytes} from './response-body.mjs';
import {readProtected,reserveReceipt,receiptArgument} from './protected-file.mjs';
export {readProtected} from './protected-file.mjs';
export function cloudflareReader(token,fetchImpl=fetch){
  if(typeof token!=='string'||!token.trim())throw new GateBlocked('CLOUDFLARE_READ_CREDENTIAL_REQUIRED');
  return async path=>{
    ensure(path.startsWith('/accounts/'),'INVALID_API_PATH');
    let r;try{r=await fetchImpl(API+path,{method:'GET',headers:{authorization:'Bearer '+token.trim(),accept:'application/json, multipart/form-data'},redirect:'manual',signal:AbortSignal.timeout(12000)});}
    catch{throw new GateBlocked('CLOUDFLARE_READ_UNAVAILABLE');}
    if(r.status===401||r.status===403)throw new GateBlocked('CLOUDFLARE_READ_PERMISSION');
    ensure(r.status<300||r.status>=400,'CLOUDFLARE_REDIRECT_DENIED');
    if(!r.ok)throw new GateBlocked('CLOUDFLARE_RESOURCE_UNAVAILABLE');
    const bytes=await responseBytes(r,{limit:3000000,limitError:new GateBlocked('CLOUDFLARE_RESPONSE_LIMIT'),transportCode:'CLOUDFLARE_READ_UNAVAILABLE'});
    return new Response(bytes,{headers:r.headers});
  };
}
const json=async readPath=>{const r=await readPath;let j;try{j=await r.json();}catch{throw new GateBlocked('CLOUDFLARE_JSON_UNAVAILABLE');}ensure(j.success===true&&j.result,'CLOUDFLARE_ENVELOPE');return j.result;};
function bindings(rows,a,fault){
  const access=!fault&&a.access?{ACCESS_TEAM:a.access.team,ACCESS_AUD:a.access.audience,CONNECT_ACCESS_AUD:a.access.connect_audience}:{};
  ensure(Array.isArray(rows)&&rows.length===(fault?1:2)+Object.keys(access).length,'BINDING_SET_MISMATCH');
  for(const [name,text] of Object.entries(access))ensure(rows.some(b=>b.name===name&&b.type==='plain_text'&&b.text===text),'ACCESS_BINDING_MISMATCH');
  const marker=rows.find(b=>b.name==='STAGING_ACCEPTANCE');
  ensure(marker?.type==='plain_text'&&marker.text===SOURCE,'STAGING_MARKER_MISMATCH');
  if(!fault){const d=rows.find(b=>b.name==='EDGE_DB');ensure(d?.type==='d1'&&(d.id!==undefined||d.database_id!==undefined)&&(d.id===undefined||d.id===a.database_id)&&(d.database_id===undefined||d.database_id===a.database_id),'STAGING_D1_BINDING_MISMATCH');}
  ensure(new Set(rows.map(b=>b.name)).size===rows.length,'DUPLICATE_BINDING');
}
export async function moduleDigest(response,moduleName){
  const type=response.headers.get('content-type')||'';
  if(!type.startsWith('multipart/form-data'))throw new GateBlocked('DEPLOYED_MODULE_BYTES_UNAVAILABLE');
  // Cloudflare's download may use text parts with application/javascript and no
  // filename. Node 22 formData() rejects that valid shape. Parse the single module
  // as bytes: never normalize source newlines or trust a script-supplied digest.
  const boundary=type.match(/boundary=(?:"([^"\r\n]+)"|([^;\s]+))/i);
  const b=boundary?.[1]||boundary?.[2];
  if(!b||b.length>70)throw new GateBlocked('DEPLOYED_MODULE_BYTES_UNAVAILABLE');
  const data=await responseBytes(response,{limit:3000000,limitError:new GateBlocked('CLOUDFLARE_RESPONSE_LIMIT'),transportCode:'CLOUDFLARE_READ_UNAVAILABLE'});
  if(data.length>3000000)throw new GateBlocked('CLOUDFLARE_RESPONSE_LIMIT');
  const prefix=Buffer.from('--'+b+'\r\n'),delimiter=Buffer.from('\r\n--'+b);
  if(!data.subarray(0,prefix.length).equals(prefix))throw new GateBlocked('DEPLOYED_MODULE_BYTES_UNAVAILABLE');
  const split=data.indexOf(Buffer.from('\r\n\r\n'),prefix.length);
  if(split<0||split>8000)throw new GateBlocked('DEPLOYED_MODULE_BYTES_UNAVAILABLE');
  const headers=data.subarray(prefix.length,split).toString('latin1');
  const disposition=headers.split('\r\n').filter(h=>/^content-disposition:/i.test(h));
  ensure(disposition.length===1&&disposition[0].match(/;\s*name="([^"]+)"/i)?.[1]===moduleName,'DEPLOYED_MODULE_SET_MISMATCH');
  const end=data.indexOf(delimiter,split+4);
  ensure(end>=0,'DEPLOYED_MODULE_SET_MISMATCH');
  const tail=data.subarray(end+delimiter.length).toString('latin1');
  ensure(tail==='--\r\n'||tail==='--','DEPLOYED_MODULE_SET_MISMATCH');
  return hash(data.subarray(split+4,end));
}
function active(d,w){
  ensure(Array.isArray(d.deployments)&&d.deployments.length>0,'DEPLOYMENT_RECORD_MISSING');
  ensure(d.deployments.every(x=>Number.isFinite(Date.parse(x.created_on))),'DEPLOYMENT_TIMESTAMP_MISSING');
  const sorted=[...d.deployments].sort((x,y)=>Date.parse(y.created_on)-Date.parse(x.created_on));const latest=sorted[0];
  ensure(Number.isFinite(Date.parse(latest.created_on))&&latest.id===w.deployment_id&&latest.versions?.length===1&&latest.versions[0].version_id===w.version_id&&latest.versions[0].percentage===100,'ACTIVE_DEPLOYMENT_MISMATCH');
  return latest.id;
}
export async function verifyDeployment(approval,{read,requireReachable=true}={}){
  const a=validateApproval(approval);
  if(!read)read=cloudflareReader(readProtected(process.env.STAGING_CF_READ_TOKEN_FILE));
  const root='/accounts/'+a.account_id;
  const account=await json(read(root));ensure(account.id===a.account_id&&account.name===a.account_name,'ACCOUNT_IDENTITY_MISMATCH');
  const domain=await json(read(root+'/workers/subdomain'));ensure(domain.subdomain===a.subdomain,'ACCOUNT_SUBDOMAIN_MISMATCH');
  const db=await json(read(root+'/d1/database/'+a.database_id));ensure(db.uuid===a.database_id&&db.name===a.database_name&&db.jurisdiction===a.jurisdiction,'DATABASE_IDENTITY_MISMATCH');
  const workers=[];
  for(const [i,w] of a.workers.entries()){
    const base=root+'/workers/scripts/'+w.name;
    active(await json(read(base+'/deployments')),w);
    const version=await json(read(base+'/versions/'+w.version_id));ensure(version.id===w.version_id,'VERSION_IDENTITY_MISMATCH');
    bindings(version.resources?.bindings,a,!!i);
    const settings=await json(read(base+'/settings'));bindings(settings.bindings,a,!!i);
    const hosts=await json(read(base+'/subdomain'));
    ensure(typeof hosts.enabled==='boolean'&&hosts.previews_enabled===false,'WORKER_HOST_CONFIGURATION');
    const digest=await moduleDigest(await read(base),w.module_name);
    ensure(digest===w.artifact_sha256,'DEPLOYED_ARTIFACT_DIGEST_MISMATCH');
    // Download endpoint describes current script: bracket it with active-deployment reads.
    active(await json(read(base+'/deployments')),w);
    workers.push({name:w.name,origin:w.origin,version_id:w.version_id,deployment_id:w.deployment_id,sha256:digest,public_enabled:hosts.enabled});
  }
  if(requireReachable&&!workers.every(w=>w.public_enabled))throw new GateBlocked('STAGING_PUBLIC_URLS_DISABLED');
  return {account_id:a.account_id,database_id:a.database_id,approval_sha256:hash(JSON.stringify(a)),workers};
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
  let complete,report;
  try{complete=reserveReceipt(receiptArgument(process.argv.slice(2)));const a=JSON.parse(readProtected(process.env.STAGING_APPROVAL_FILE));const proof=await verifyDeployment(a,{requireReachable:false});report={status:'PASS',evidence:proof};}
  catch(e){report={status:e instanceof GateBlocked?'BLOCKED':'FAIL',evidence:e instanceof GateBlocked||e instanceof GateFailure?e.message:'VERIFIER_RUNTIME_UNAVAILABLE'};process.exitCode=e instanceof GateBlocked?2:1;}
  try{if(!complete)throw new GateBlocked('PROTECTED_RECEIPT_REQUIRED');complete(report);console.log('Deployment receipt written');}
  catch{console.log('BLOCKED: protected receipt unavailable');process.exitCode=2;}
}
