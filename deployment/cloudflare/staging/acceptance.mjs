import fs from 'node:fs';
import {fileURLToPath} from 'node:url';
import {SOURCE,NAME,hash,pinned} from './build.mjs';
class GateFailure extends Error {}
class GateBlocked extends Error {}
const ensure=(ok,code)=>{if(!ok)throw new GateFailure(code);};
export function stagingUrl(value,fault=false){
  const u=new URL(value);
  ensure(u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&!u.search&&!u.hash&&u.pathname==='/', 'INVALID_STAGING_URL');
  ensure(new RegExp(`^${NAME}${fault?'-fault':''}\\.[a-z0-9-]+\\.workers\\.dev$`).test(u.hostname),'NOT_A_DEDICATED_STAGING_WORKER');
  return u.origin;
}
export async function accept({base,faultBase,fixtures,fetchImpl=fetch,revoked=false,access}){
  base=stagingUrl(base);if(faultBase){faultBase=stagingUrl(faultBase,true);ensure(faultBase===base.replace(NAME+'.',NAME+'-fault.'),'FAULT_ACCOUNT_MISMATCH');}
  ensure(fixtures.source_commit===SOURCE,'WRONG_FIXTURE_SOURCE');
  const results=[];
  const record=async(name,fn)=>{
    try{const blocked=await fn();results.push({case:name,status:blocked?'BLOCKED':'PASS',evidence:blocked||'expected boundary observed'});}
    catch(e){results.push({case:name,status:e instanceof GateBlocked?'BLOCKED':'FAIL',evidence:e instanceof GateFailure?e.message:e instanceof GateBlocked?'TRANSPORT_UNAVAILABLE':'UNEXPECTED_RESPONSE_OR_HARNESS_ERROR'});}
  };
  const request=async(origin,url,options={})=>{
    let response;try{response=await fetchImpl(origin+url,{...options,redirect:'manual',signal:AbortSignal.timeout(8000)});}catch{throw new GateBlocked();}
    const reader=response.body?.getReader();let text='',size=0;
    if(reader){const decoder=new TextDecoder();while(true){const part=await reader.read();if(part.done)break;size+=part.value.byteLength;if(size>32000){await reader.cancel();throw new GateFailure('RESPONSE_LIMIT');}text+=decoder.decode(part.value,{stream:true});}text+=decoder.decode();}
    let body;try{body=JSON.parse(text);}catch{}
    return {status:response.status,headers:response.headers,body,text};
  };
  const role=name=>{const a=fixtures.agents.find(a=>a.role===name);ensure(a&&/^smcp_[A-Za-z0-9_-]{43}$/.test(a.token),'INVALID_FIXTURE');return a;};
  const rpc=(method,params={},token,origin=base,extra={})=>request(origin,'/mcp',{method:'POST',headers:{'content-type':'application/json',...(token?{authorization:'Bearer '+token}:{}),...extra},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params})});
  const call=(name,token)=>rpc('tools/call',{name,arguments:{}},token);
  // Establish staging identity before any credential leaves this process.
  let ready=false;
  await record('pinned staging artifact',async()=>{
    const r=await request(base,'/_staging/manifest');ensure(r.status===200&&r.body?.source_commit===SOURCE&&r.body?.source_sha256===hash(pinned('deployment/cloudflare/worker.js'))&&r.body?.schema_sha256===hash(pinned('deployment/cloudflare/schema.sql'))&&r.body?.origin===base&&r.body?.fault===false,'STAGING_MANIFEST_MISMATCH');ready=true;
  });
  if(!ready)return {source_commit:SOURCE,results};
  await record('invalid, expired and disabled bearer',async()=>{
    for(const token of ['invalid','smcp_'+'z'.repeat(43),role('expired').token,role('disabled').token]){
      for(const method of ['initialize','tools/list']){
        const r=await rpc(method,{},token);ensure(r.status===401&&r.headers.get('www-authenticate')==='Bearer realm="shards-mcp", error="invalid_token"','INVALID_BEARER_NOT_DENIED');
      }
    }
  });
  await record('anonymous public discovery and protected denial',async()=>{
    const r=await rpc('tools/list');ensure(r.status===200&&r.body?.result?.tools?.length===7&&r.body.result.tools.every(t=>!t.name.startsWith('shards_agent')),'ANONYMOUS_DISCOVERY');
    const denied=await call('shards_agent_identity');ensure(denied.status===200&&denied.body?.result?.isError===true,'ANONYMOUS_PRIVATE_ACCESS');
    const publicCall=await call('shards_gateway_status');ensure(publicCall.status===200&&publicCall.body?.result?.isError===false,'PUBLIC_CALL_UNAVAILABLE');
  });
  await record('valid bearer identity and exact scope discovery',async()=>{
    for(const name of ['observer','reader','foreign']){
      const a=role(name),r=await call('shards_agent_identity',a.token),who=r.body?.result?.structuredContent;
      ensure(r.status===200&&r.body?.result?.isError===false&&who?.id===a.id&&who?.tenant===a.tenant&&Array.isArray(who.scopes)&&JSON.stringify([...who.scopes].sort())===JSON.stringify([...a.scopes].sort()),'IDENTITY_OR_SCOPE_MISMATCH');
      const list=await rpc('tools/list',{},a.token),names=list.body?.result?.tools?.map(t=>t.name).sort();
      const publicNames=['shards_gateway_status','shards_systems_catalog','shards_dns_lookup','shards_skill_search','shards_skill_read','shards_repo_document','shards_open_prs'];
      const expected=[...publicNames,'shards_agent_identity','shards_audit_tail',...(a.scopes.includes('agent:list')?['shards_agents_list']:[]),...(a.scopes.includes('message:read')?['shards_message_inbox']:[])].sort();
      ensure(list.status===200&&JSON.stringify(names)===JSON.stringify(expected),'SCOPE_DISCOVERY_MISMATCH');
    }
  });
  await record('scope and tenant isolation on calls',async()=>{
    const denied=await call('shards_message_inbox',role('observer').token);ensure(denied.body?.result?.isError===true,'SCOPE_ESCALATION');
    const allowed=await call('shards_message_inbox',role('reader').token);ensure(allowed.body?.result?.isError===false&&allowed.body.result.structuredContent.messages.length===0,'READER_INBOX');
    for(const name of ['reader','foreign']){
      const a=role(name),r=await call('shards_agents_list',a.token),agents=r.body?.result?.structuredContent?.agents;
      const visible=fixtures.agents.filter(x=>x.tenant===a.tenant&&x.role!=='disabled').map(x=>x.id).sort();
      ensure(r.body?.result?.isError===false&&JSON.stringify(agents?.map(x=>x.id).sort())===JSON.stringify(visible),'CROSS_TENANT_DISCLOSURE');
    }
  });
  await record(revoked?'revocation denies subsequent requests':'revocable bearer before revocation',async()=>{
    for(let i=0;i<2;i++){const r=await rpc('tools/list',{},role('revocable').token);ensure(r.status===(revoked?401:200),'REVOCATION_STATE_MISMATCH');}
  });
  await record('OAuth authority isolation',async()=>{
    for(const p of ['/.well-known/oauth-protected-resource','/.well-known/oauth-protected-resource/mcp','/.well-known/oauth-authorization-server']){
      const r=await request(base,p);ensure(r.status===404&&!r.headers.has('location')&&!r.headers.has('www-authenticate')&&r.headers.get('cache-control')==='no-store','OAUTH_AUTHORITY_CONFUSION');
    }
  });
  await record('/connect metadata and challenge',async()=>{
    if(!access?.issuer)return 'ISOLATED_ACCESS_APPLICATION_NOT_CONFIGURED';
    for(const p of ['/.well-known/oauth-protected-resource/connect','/.well-known/cloudflare-access-protected-resource/connect']){
      const r=await request(base,p);ensure(r.status===200&&r.body?.resource===base+'/connect'&&JSON.stringify(r.body.authorization_servers)===JSON.stringify([access.issuer]),'CONNECT_METADATA_MISMATCH');
    }
    const r=await request(base,'/connect',{method:'POST'});
    ensure(r.status===401&&r.headers.get('www-authenticate')?.includes('resource_metadata="'+base+'/.well-known/cloudflare-access-protected-resource/connect"'),'CONNECT_CHALLENGE_MISMATCH');
  });
  await record('/connect signed identity and no agent privilege',async()=>{
    if(!access?.token)return 'ISOLATED_ACCESS_LOGIN_REQUIRED';
    const r=await request(base,'/connect',{method:'POST',headers:{'content-type':'application/json','cf-access-jwt-assertion':access.token},body:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'shards_user_identity',arguments:{}}})});
    ensure(r.status===200&&r.body?.result?.isError===false&&r.body?.result?.structuredContent?.authenticated===true&&r.body.result.structuredContent.privileged_scopes.length===0,'CONNECT_IDENTITY_MISMATCH');
    const denied=await request(base,'/connect',{method:'POST',headers:{'content-type':'application/json','cf-access-jwt-assertion':access.token},body:JSON.stringify({jsonrpc:'2.0',id:2,method:'tools/call',params:{name:'shards_task_create',arguments:{}}})});
    ensure(denied.body?.result?.isError===true,'CONNECT_AGENT_SCOPE_ESCALATION');
  });
  await record('storage failure returns sanitized 503',async()=>{
    if(!faultBase)return 'SEPARATE_FAULT_WORKER_REQUIRED';
    const m=await request(faultBase,'/_staging/manifest');ensure(m.status===200&&m.body?.source_commit===SOURCE&&m.body?.origin===faultBase&&m.body?.fault===true,'FAULT_MANIFEST_MISMATCH');
    const r=await rpc('tools/list',{},role('observer').token,faultBase);
    ensure(r.status===503&&r.text==='{"error":"Authentication storage unavailable"}'&&r.headers.get('cache-control')==='no-store','STORAGE_FAILURE_BOUNDARY');
  });
  return {source_commit:SOURCE,results};
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
  try{
    const fixturePath=process.env.STAGING_FIXTURES_FILE;
    ensure(fixturePath&&(fs.statSync(fixturePath).mode&0o077)===0,'FIXTURE_FILE_PERMISSIONS');
    const f=JSON.parse(fs.readFileSync(fixturePath,'utf8'));
    let access;
    if(process.env.STAGING_ACCESS_FILE){ensure((fs.statSync(process.env.STAGING_ACCESS_FILE).mode&0o077)===0,'ACCESS_FILE_PERMISSIONS');access=JSON.parse(fs.readFileSync(process.env.STAGING_ACCESS_FILE,'utf8'));}
    const report=await accept({base:process.env.STAGING_URL,faultBase:process.env.STAGING_FAULT_URL,fixtures:f,revoked:process.argv.includes('--revoked'),access});
    console.log(JSON.stringify(report,null,2));process.exitCode=report.results.some(r=>r.status==='FAIL')?1:report.results.some(r=>r.status==='BLOCKED')?2:0;
  }catch{console.error('BLOCKED: invalid staging target, protected fixture file or runtime');process.exitCode=2;}
}
