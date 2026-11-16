import {fileURLToPath} from 'node:url';
import {SOURCE,hash,pinned} from './build.mjs';
import {stagingUrl,validateApproval,GateFailure,GateBlocked,ensure} from './policy.mjs';
import {verifyDeployment,readProtected} from './verify-deployment.mjs';
import {checkVisibility} from './visibility.mjs';
import {responseBytes} from './response-body.mjs';
import {writeReceipt} from './protected-file.mjs';
import {localTransport} from './harness.mjs';
export {stagingUrl} from './policy.mjs';
export async function accept(options){
  let {base,faultBase,fixtures,approval,fetchImpl=fetch,revoked=false,access,readCloudflare}=options;
  const local=localTransport(options),localRuntime=!!local;
  ensure(!options.localRuntime&&!options.verifyIdentity,'UNSUPPORTED_IDENTITY_BYPASS');
  if(local)fetchImpl=local;
  const verifyIdentity=()=>verifyDeployment(approval,{read:readCloudflare});
  validateApproval(approval);base=stagingUrl(base,approval);if(faultBase)faultBase=stagingUrl(faultBase,approval,true);
  ensure(fixtures.source_commit===SOURCE&&fixtures.fixture_version===2,'WRONG_FIXTURE_VERSION');
  const results=[];
  const record=async(name,fn)=>{
    try{const blocked=await fn();results.push({case:name,status:blocked?'BLOCKED':'PASS',evidence:blocked||'expected boundary observed'});}
    catch(e){results.push({case:name,status:e instanceof GateBlocked?'BLOCKED':'FAIL',evidence:e instanceof GateFailure?e.message:e instanceof GateBlocked?e.message:'UNEXPECTED_RESPONSE_OR_HARNESS_ERROR'});}
  };
  const request=async(origin,url,options={})=>{
    let response;try{response=await fetchImpl(origin+url,{...options,redirect:'manual',signal:AbortSignal.timeout(8000)});}catch{throw new GateBlocked('TRANSPORT_UNAVAILABLE');}
    const text=(await responseBytes(response,{limit:32000,limitError:new GateFailure('RESPONSE_LIMIT'),transportCode:'TRANSPORT_UNAVAILABLE'})).toString('utf8');
    let body;try{body=JSON.parse(text);}catch{}
    return {status:response.status,headers:response.headers,body,text};
  };
  const role=name=>{const a=fixtures.agents.find(a=>a.role===name);ensure(a&&/^smcp_[A-Za-z0-9_-]{43}$/.test(a.token),'INVALID_FIXTURE');return a;};
  const rpc=(method,params={},token,origin=base,extra={})=>request(origin,'/mcp',{method:'POST',headers:{'content-type':'application/json',...(token?{authorization:'Bearer '+token}:{}),...extra},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params})});
  const call=(name,token,args={})=>rpc('tools/call',{name,arguments:args},token);
  const authReason='AUTH_REQUIRED: This tool needs a valid, separately provisioned scoped bearer key. Sign in at '+base+'/manage to enrol an agent. ChatGPT OAuth for private tools is not available yet.';
  const denied=(r,reason,code)=>ensure(r.status===200&&r.body?.result?.isError===true&&r.body?.result?.content?.length===1&&r.body.result.content[0].type==='text'&&r.body.result.content[0].text===reason,code);
  const publicNames=['shards_gateway_status','shards_systems_catalog','shards_dns_lookup','shards_skill_search','shards_skill_read','shards_repo_document','shards_open_prs'];
  const taskArgs={assignee_agent_id:role('reader').id,title:'Synthetic denied task',input:{fixture:true},request_id:'pr47-denial-task-0001'};
  // Establish staging identity before any credential leaves this process.
  let ready=false,identity;
  await record('independent deployed identity',async()=>{
    if(localRuntime){ready=true;return 'LOCAL_WORKERD_NOT_HOSTED';}
    identity=await verifyIdentity();ready=true;
  });
  if(!ready)return {source_commit:SOURCE,environment:localRuntime?'local-workerd':'hosted',results};
  ready=false;
  await record('supplementary worker manifest',async()=>{
    const r=await request(base,'/_staging/manifest');ensure(r.status===200&&r.body?.source_commit===SOURCE&&r.body?.source_sha256===hash(pinned('deployment/cloudflare/worker.js'))&&r.body?.schema_sha256===hash(pinned('deployment/cloudflare/schema.sql'))&&r.body?.origin===base&&r.body?.fault===false,'STAGING_MANIFEST_MISMATCH');ready=true;
  });
  if(!ready)return {source_commit:SOURCE,results};
  await record('invalid credentials across MCP methods',async()=>{
    const headers=['Basic invalid','Bearer','Bearer  invalid','Token invalid','Bearer invalid','Bearer smcp_'+'z'.repeat(43),'Bearer '+role('expired').token,'Bearer '+role('disabled').token];
    for(const [headerIndex,authorization] of headers.entries()){
      for(const method of ['initialize','tools/list','tools/call','ping','notifications/initialized','notifications/cancelled']){
        const r=await rpc(method,method==='tools/call'?{name:'shards_agent_identity',arguments:{}}:{},undefined,base,{authorization});
        ensure(r.status===401&&r.headers.get('www-authenticate')==='Bearer realm="shards-mcp", error="invalid_token"'&&r.headers.get('cache-control')==='no-store'&&!r.headers.has('location')&&r.text==='{"error":"Invalid or expired agent credential"}','INVALID_BEARER_NOT_DENIED_'+headerIndex+'_'+method.replaceAll('/','_'));
      }
    }
  });
  await record('empty Authorization transport boundary',async()=>{
    // The local HTTP adapter drops this header before workerd sees the Request;
    // a separate echo-runtime test verifies that limitation. Do not call it PASS.
    if(localRuntime)return 'LOCAL_ADAPTER_DROPS_EMPTY_AUTHORIZATION';
    const r=await rpc('ping',{},undefined,base,{authorization:''});
    ensure(r.status===401,'EMPTY_AUTHORIZATION_NOT_DENIED');
  });
  await record('anonymous public discovery and protected denial',async()=>{
    const r=await rpc('tools/list');ensure(r.status===200&&JSON.stringify(r.body?.result?.tools?.map(t=>t.name).sort())===JSON.stringify([...publicNames].sort()),'ANONYMOUS_DISCOVERY');
    denied(await call('shards_agent_identity'),authReason,'ANONYMOUS_PRIVATE_ACCESS');
    const publicCall=await call('shards_gateway_status');ensure(publicCall.status===200&&publicCall.body?.result?.isError===false,'PUBLIC_CALL_UNAVAILABLE');
  });
  await record('valid bearer identity and exact scope discovery',async()=>{
    for(const name of ['observer','reader','foreign']){
      const a=role(name),r=await call('shards_agent_identity',a.token),who=r.body?.result?.structuredContent;
      ensure(r.status===200&&r.body?.result?.isError===false&&who?.id===a.id&&who?.tenant===a.tenant&&Array.isArray(who.scopes)&&JSON.stringify([...who.scopes].sort())===JSON.stringify([...a.scopes].sort()),'IDENTITY_OR_SCOPE_MISMATCH');
      const list=await rpc('tools/list',{},a.token),names=list.body?.result?.tools?.map(t=>t.name).sort();
      const expected=[...publicNames,'shards_agent_identity','shards_audit_tail',...(a.scopes.includes('agent:list')?['shards_agents_list']:[]),...(a.scopes.includes('message:read')?['shards_message_inbox']:[]),...(a.scopes.includes('task:read')?['shards_task_inbox']:[])].sort();
      ensure(list.status===200&&JSON.stringify(names)===JSON.stringify(expected),'SCOPE_DISCOVERY_MISMATCH');
    }
  });
  await record('scope and tenant isolation on calls',async()=>{
    for(const name of ['shards_message_inbox','shards_task_inbox'])denied(await call(name,role('observer').token),authReason,'SCOPE_ESCALATION');
    denied(await call('shards_task_create',role('observer').token,taskArgs),authReason,'MUTATION_SCOPE_ESCALATION');
    await checkVisibility(call,fixtures);
    for(const name of ['reader','foreign']){
      const a=role(name),r=await call('shards_agents_list',a.token),agents=r.body?.result?.structuredContent?.agents;
      const visible=fixtures.agents.filter(x=>x.tenant===a.tenant&&x.role!=='disabled').map(x=>x.id).sort();
      ensure(r.body?.result?.isError===false&&JSON.stringify(agents?.map(x=>x.id).sort())===JSON.stringify(visible),'CROSS_TENANT_DISCLOSURE');
    }
  });
  await record(revoked?'revocation denies subsequent requests':'revocable bearer before revocation',async()=>{
    // A 401 proves revocation only while this credential is otherwise valid.
    const live=()=>{if(!(Date.parse(role('revocable').expires)>Date.now()+30000))throw new GateBlocked('REVOCABLE_FIXTURE_EXPIRING_OR_EXPIRED');};
    live();
    const replies=await Promise.all(Array.from({length:4},()=>rpc('tools/list',{},role('revocable').token)));
    live();
    ensure(replies.every(r=>r.status===(revoked?401:200)),'REVOCATION_STATE_MISMATCH');
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
    const forbidden=await request(base,'/connect',{method:'POST',headers:{'content-type':'application/json','cf-access-jwt-assertion':access.token},body:JSON.stringify({jsonrpc:'2.0',id:2,method:'tools/call',params:{name:'shards_task_create',arguments:taskArgs}})});
    denied(forbidden,'PERMISSION_DENIED: Social login has no internal agent privileges','CONNECT_AGENT_SCOPE_ESCALATION');
  });
  await record('joint Access and bearer boundaries',async()=>{
    const good=await rpc('tools/call',{name:'shards_agent_identity',arguments:{}},role('observer').token,base,{'cf-access-jwt-assertion':'invalid.jwt'});
    ensure(good.status===200&&good.body?.result?.structuredContent?.id===role('observer').id,'BEARER_PRINCIPAL_CONFUSION');
    if(!access?.token)return 'ISOLATED_ACCESS_LOGIN_REQUIRED';
    const bad=await rpc('ping',{},'invalid',base,{'cf-access-jwt-assertion':access.token});ensure(bad.status===401,'ACCESS_TO_BEARER_FALLBACK');
    const wrong=await request(base,'/connect',{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+role('observer').token,'cf-access-jwt-assertion':'invalid.jwt'},body:JSON.stringify({jsonrpc:'2.0',id:1,method:'ping'})});ensure(wrong.status===401,'BEARER_TO_ACCESS_FALLBACK');
    const session=await request(base,'/connect',{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer invalid','cf-access-jwt-assertion':access.token},body:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/list'})});
    const names=session.body?.result?.tools?.map(t=>t.name)||[];
    ensure(session.status===200&&names.length===8&&names.includes('shards_user_identity')&&!names.includes('shards_agent_identity'),'SIGNED_ACCESS_SCOPE_CONFUSION');
  });
  await record('storage failure returns sanitized 503',async()=>{
    if(!faultBase)return 'SEPARATE_FAULT_WORKER_REQUIRED';
    const invalid=await rpc('ping',{},'invalid',faultBase);ensure(invalid.status===401,'FAULT_INVALID_CREDENTIAL_NOT_DENIED');
    const m=await request(faultBase,'/_staging/manifest');ensure(m.status===200&&m.body?.source_commit===SOURCE&&m.body?.origin===faultBase&&m.body?.fault===true,'FAULT_MANIFEST_MISMATCH');
    for(const method of ['initialize','tools/list','tools/call','ping','notifications/initialized','notifications/cancelled']){
    const replies=await Promise.all(Array.from({length:3},()=>rpc(method,{name:'shards_agent_identity',arguments:{}},role('observer').token,faultBase)));
    ensure(replies.every(r=>r.status===503&&r.text==='{"error":"Authentication storage unavailable"}'&&r.headers.get('cache-control')==='no-store'),'STORAGE_FAILURE_BOUNDARY');
    }
  });
  await record('deployment identity stable after acceptance',async()=>{
    if(localRuntime)return 'LOCAL_WORKERD_NOT_HOSTED';
    const after=await verifyIdentity();ensure(JSON.stringify(identity)===JSON.stringify(after),'DEPLOYMENT_CHANGED_DURING_ACCEPTANCE');
  });
  return {source_commit:SOURCE,environment:localRuntime?'local-workerd':'hosted',results};
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
  try{
    if(!process.argv.includes('--receipt'))throw new GateBlocked('PROTECTED_RECEIPT_REQUIRED');
    const f=JSON.parse(readProtected(process.env.STAGING_FIXTURES_FILE));
    const approval=JSON.parse(readProtected(process.env.STAGING_APPROVAL_FILE));
    let access;
    if(process.env.STAGING_ACCESS_FILE)access=JSON.parse(readProtected(process.env.STAGING_ACCESS_FILE));
    const report=await accept({base:process.env.STAGING_URL,faultBase:process.env.STAGING_FAULT_URL,fixtures:f,approval,revoked:process.argv.includes('--revoked'),access});
    writeReceipt(process.argv[process.argv.indexOf('--receipt')+1],report);console.log('Staging receipt written');process.exitCode=report.results.some(r=>r.status==='FAIL')?1:report.results.some(r=>r.status==='BLOCKED')?2:0;
  }catch{console.error('BLOCKED: invalid staging target, protected fixture file or runtime');process.exitCode=2;}
}
