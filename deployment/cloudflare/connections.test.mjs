import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
const source=fs.readFileSync(new URL('./worker.js',import.meta.url),'utf8');
const sandbox={Request,Response,Headers,URL,TextEncoder,TextDecoder,atob,btoa,crypto:webcrypto,AbortSignal,fetch:async()=>{throw Error('Unexpected network request')}};
vm.runInNewContext(source.replace('export default {','globalThis.__edge = {'),sandbox,{filename:'worker.js'});
const edge=sandbox.__edge,origin='https://mcp.shardsinc.co.uk';

test('Connect Agents serves real mobile wizard, has source parity, and never claims unverified presence',async()=>{
 const page=await edge.fetch(new Request(origin+'/manage/connect-agents'),{});
 assert.equal(page.status,200);
 const html=await page.text();
 assert.equal(html,fs.readFileSync(new URL('./connect-agents.html',import.meta.url),'utf8'));
 assert.match(html,/Pick your agent/);
 assert.match(html,/ENROL & CREATE TOKEN/);
 assert.match(html,/App integrations/);
 assert.match(page.headers.get('content-security-policy'),/script-src 'self'/);
 const script=await edge.fetch(new Request(origin+'/manage/connect-agents.js'),{});
 assert.equal(script.status,200);
 const js=await script.text();
 assert.equal(js,fs.readFileSync(new URL('./connect-agents.js',import.meta.url),'utf8'));
 assert.doesNotThrow(()=>new vm.Script(js,{filename:'connect-agents.js'}));
 assert.match(js,/credentials:'same-origin'/);
 assert.match(js,/last_authenticated_at/);
 assert.doesNotMatch(js,/localStorage|sessionStorage|innerHTML\s*=/);
});
test('Agent activity D1 migration matches the baseline and has no fabricated online flag',()=>{
 const sql=fs.readFileSync(new URL('./migrations/0004_agent_connection_activity.sql',import.meta.url),'utf8');
 const baseline=fs.readFileSync(new URL('./schema.sql',import.meta.url),'utf8');
 const marker='-- Authenticated MCP request receipts.';
 assert.equal(baseline.slice(baseline.indexOf(marker)).trim(),sql.slice(sql.indexOf(marker)).trim());
 assert.match(sql,/CREATE TABLE IF NOT EXISTS agent_connection_activity/);
 assert.match(sql,/PRIMARY KEY REFERENCES agents\(id\)/);
});
test('signed operator sees only owned agents, validated MCP bearer logs a receipt, cross-owner revocation denied',async()=>{
 const pair=await webcrypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
 const jwk=await webcrypto.subtle.exportKey('jwk',pair.publicKey);jwk.kid='connect-test';
 const b64=data=>Buffer.from(JSON.stringify(data)).toString('base64url');
 const stamp=Math.floor(Date.now()/1000);
 const jwt=async sub=>{
  const header=b64({alg:'RS256',kid:'connect-test'});
  const payload=b64({iss:'https://connect-test.cloudflareaccess.com',aud:['operator-audience'],sub,exp:stamp+1800,nbf:stamp-5,email:sub+'@example.test'});
  const text=header+'.'+payload,sig=await webcrypto.subtle.sign('RSASSA-PKCS1-v1_5',pair.privateKey,new TextEncoder().encode(text));
  return text+'.'+Buffer.from(sig).toString('base64url');
 };
 const sha=async text=>Buffer.from(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(text))).toString('hex');
 const owner=await sha('owner-one'),otherOwner=await sha('owner-two');
 const agents=[
  {id:'agent-owner-one-0001',name:'MyHermes',client:'hermes-agent',created_by:owner,tenant_id:'shards-internal',scopes:'["agent:identity","message:read"]',created_at:'2026-11-14T03:00:00Z',disabled_at:null},
  {id:'agent-owner-two-0002',name:'OtherAgent',client:'cursor',created_by:otherOwner,tenant_id:'shards-internal',scopes:'["agent:identity"]',created_at:'2026-11-14T03:00:00Z',disabled_at:null}
 ];
 const token='smcp_'+'a'.repeat(64),tokenHash=await sha(token);
 const tokens=[{agent_id:agents[0].id,token_sha256:tokenHash,revoked_at:null,expires_at:'2030-01-01T00:00:00Z'}];
 const receipts=[],audits=[];
 const mockPrepare=sql=>({
  bind:(...a)=>({
   first:async()=>{
    if(sql.includes('SELECT deleted_at FROM operator_accounts'))return null;
    if(sql.includes('FROM access_tokens t JOIN agents a ON t.agent_id=a.id')){
     const key=tokens.find(x=>x.token_sha256===a[0]&&!x.revoked_at&&x.expires_at>a[1]);
     return key?agents.find(x=>x.id===key.agent_id&&!x.disabled_at)||null:null;
    }
    throw Error('Unexpected SQL first: '+sql);
   },
   all:async()=>{
    if(sql.includes('FROM agents a LEFT JOIN agent_connection_activity c')){
     assert.match(sql,/a\.created_by=\?/,'Owner identity must scope listing');
     return {results:agents.filter(x=>x.created_by===a[0]).map(x=>({...x,last_authenticated_at:receipts.find(z=>z.id===x.id)?.at||null,last_operation:receipts.find(z=>z.id===x.id)?.method||null}))};
    }
    throw Error('Unexpected SQL all: '+sql);
   },
   run:async()=>{
    if(sql.startsWith('INSERT INTO agent_connection_activity')){
     const key=tokens.find(x=>x.token_sha256===a[3]&&!x.revoked_at&&x.expires_at>a[4]);
     if(key){const found=receipts.find(x=>x.id===key.agent_id);if(found){found.at=a[1];found.method=a[2]}else receipts.push({id:key.agent_id,at:a[1],method:a[2]})}
     return {meta:{changes:key?1:0}};
    }
    if(sql.startsWith('UPDATE access_tokens SET revoked_at')){
     assert.match(sql,/created_by=\?/,'Revoke must enforce ownership at SQL write time');
     const agent=agents.find(x=>x.id===a[1]&&x.created_by===a[3]&&!x.disabled_at);
     let n=0;if(agent)for(const t of tokens)if(t.agent_id===agent.id&&!t.revoked_at){t.revoked_at=a[0];n++}
     return {meta:{changes:n}};
    }
    if(sql.startsWith('UPDATE agents SET disabled_at')){
     assert.match(sql,/created_by=\?/,'Owner scoped revocation');
     const agent=agents.find(x=>x.id===a[1]&&x.created_by===a[2]&&!x.disabled_at);
     if(agent)agent.disabled_at=a[0];
     return {meta:{changes:agent?1:0}};
    }
    if(sql.startsWith('INSERT INTO audit_events')){audits.push(a);return {meta:{changes:1}}}
    throw Error('Unexpected SQL run: '+sql);
   }
  })
 });
 const env={ACCESS_TEAM:'connect-test',ACCESS_AUD:'operator-audience',CONNECT_ACCESS_AUD:'connect-audience',EDGE_DB:{
  prepare:mockPrepare,
  batch:async stmts=>{
   const previous=JSON.stringify({agents,tokens,receipts});
   try{const results=[];for(const statement of stmts)results.push(await statement.run());return results}
   catch(e){const v=JSON.parse(previous);agents.splice(0,agents.length,...v.agents);tokens.splice(0,tokens.length,...v.tokens);receipts.splice(0,receipts.length,...v.receipts);throw e}
  }
 }};
 const original=sandbox.fetch;
 sandbox.fetch=async url=>{
  if(String(url)==='https://connect-test.cloudflareaccess.com/cdn-cgi/access/certs')return {ok:true,json:async()=>({keys:[jwk]})};
  throw Error('Unexpected external request: '+url);
 };
 const signed1=await jwt('owner-one'),signed2=await jwt('owner-two');
 const make=(path,token,method='GET',body,source=origin)=>{
  const headers={'cf-access-jwt-assertion':token};
  if(method!=='GET')headers.origin=source;
  if(body!==undefined)headers['content-type']='application/json';
  return new Request(origin+path,{method,headers,body:body===undefined?undefined:JSON.stringify(body)});
 };
 try{
  let r=await edge.fetch(make('/manage/api/connections',''),env);assert.equal(r.status,401);
  r=await edge.fetch(make('/manage/api/connections',signed1),env);
  assert.equal(r.status,200);
  let body=await r.json();assert.equal(body.agents.length,1);assert.equal(body.agents[0].name,'MyHermes');assert.equal(body.agents[0].last_authenticated_at,null);
  const rpc=new Request(origin+'/mcp',{method:'POST',headers:{'authorization':'Bearer '+token,'content-type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/list',params:{}})});
  r=await edge.fetch(rpc,env);assert.equal(r.status,200);assert.equal(receipts.length,1);
  assert.equal(receipts[0].method,'tools/list');
  r=await edge.fetch(make('/manage/api/connections',signed1),env);body=await r.json();assert.ok(body.agents[0].last_authenticated_at);
  r=await edge.fetch(make('/manage/api/connections/revoke',signed2,'POST',{agent_id:agents[0].id}),env);
  assert.equal(r.status,200);assert.equal((await r.json()).revoked,false);assert.equal(tokens[0].revoked_at,null);
  r=await edge.fetch(make('/manage/api/connections/revoke',signed1,'POST',{agent_id:agents[0].id},'https://evil.example'),env);
  assert.equal(r.status,403);
  r=await edge.fetch(make('/manage/api/connections/revoke',signed1,'POST',{agent_id:agents[0].id}),env);
  assert.equal(r.status,200);assert.equal((await r.json()).revoked,true);assert.ok(tokens[0].revoked_at);
  r=await edge.fetch(new Request(origin+'/mcp',{method:'POST',headers:{'authorization':'Bearer '+token,'content-type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',id:2,method:'tools/list',params:{}})}),env);
  assert.equal(r.status,200);
  const data=await r.json();assert.equal(data.result.tools.some(x=>x.name==='shards_agent_identity'),false,'Revoked token must not expose private tools');
 }finally{sandbox.fetch=original}
});
