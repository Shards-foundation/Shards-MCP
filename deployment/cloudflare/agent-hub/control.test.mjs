import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { generateKeyPairSync, sign, createHash, webcrypto } from 'node:crypto';
import hub from './worker.mjs';

// Import the actual gateway module without relying on repository-wide module settings.
const source = await readFile(new URL('../worker.js', import.meta.url), 'utf8');
globalThis.crypto ??= webcrypto;
const {default: edge} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const {privateKey, publicKey} = generateKeyPairSync('rsa', {modulusLength:2048});
const jwk={...publicKey.export({format:'jwk'}),kid:'test-key'};
const issuer='https://dashboard-test.cloudflareaccess.com';
const audience='hub-test-audience';
const envBase={ACCESS_TEAM:'dashboard-test',HUB_REGISTRY_AUD:audience,ACCESS_AUD:'mcp-audience',CONNECT_ACCESS_AUD:'connect-audience'};
const encode=o=>Buffer.from(JSON.stringify(o)).toString('base64url');
function token(overrides={}, key=privateKey) {
 const p=encode({alg:'RS256',kid:'test-key'})+'.'+encode({iss:issuer,aud:[audience],sub:'owner-a',exp:Math.floor(Date.now()/1000)+300,...overrides});
 return p+'.'+sign('RSA-SHA256',Buffer.from(p),key).toString('base64url');
}
const originalFetch=globalThis.fetch;
globalThis.fetch=async url=>{
 assert.equal(String(url),issuer+'/cdn-cgi/access/certs');
 return Response.json({keys:[jwk]});
};
test.after(()=>{globalThis.fetch=originalFetch});
const digest=s=>createHash('sha256').update(s).digest('hex');
function fakeDB({deleted=false,fail=false,agents=[],tasks=[]}={}){
 const calls=[];
 const db={prepare(sql){
  assert.match(sql,/^SELECT /i);
  return {bind(...args){
   calls.push({sql,args});
   return {first:async()=>deleted?{deleted_at:'2026-01-01'}:null,
    all:async()=>({success:!fail,results:sql.includes('FROM agent_tasks t')?tasks:agents})};
  }};
 }};
 return {calls,db};
}
const internal='https://agent-hub-registry.internal/dashboard';
const dashboard='https://agents.shardsinc.co.uk/api/control';
const request=(url,jwt,method='GET')=>new Request(url,{method,headers:jwt?{'Cf-Access-Jwt-Assertion':jwt}:{}});
test('reject missing, wrong-audience, expired and forged assertions before storage',async()=>{
 const {calls,db}=fakeDB();
 const forged=generateKeyPairSync('rsa',{modulusLength:2048}).privateKey;
 for(const jwt of [null,token({aud:['wrong']}),token({exp:1}),token({},forged)]){
  assert.equal((await edge.fetch(request(internal,jwt),{...envBase,EDGE_DB:db})).status,401);
 }
 assert.equal(calls.length,0);
});
test('reject deleted operator before directory or task queries',async()=>{
 const {calls,db}=fakeDB({deleted:true});
 assert.equal((await edge.fetch(request(internal,token()),{...envBase,EDGE_DB:db})).status,410);
 assert.equal(calls.length,1);
});
test('signed owner binds all selects, bounds records, returns private snapshot',async()=>{
 const agents=Array.from({length:101},(_,i)=>({id:String(i),scopes:'["message:read"]'}));
 const tasks=Array.from({length:101},(_,i)=>({id:String(i),state:'queued'}));
 const {calls,db}=fakeDB({agents,tasks});
 const res=await edge.fetch(request(internal,token()),{...envBase,EDGE_DB:db});
 assert.equal(res.status,200);
 assert.match(res.headers.get('cache-control'),/no-store/);
 const data=await res.json();
 assert.equal(data.agents.length,100);assert.equal(data.tasks.length,100);
 assert.equal(data.limits.agents_truncated,true);assert.equal(data.limits.tasks_truncated,true);
 assert.deepEqual(data.agents[0].scopes,['message:read']);
 assert.equal(data.presence,'unverified');
 assert.equal(calls.length,3);
 for(const c of calls)assert.deepEqual(c.args,[digest('owner-a')]);
 assert.match(calls[1].sql,/a\.created_by=\?/);
 assert.match(calls[2].sql,/own\.created_by=\?/);
 assert.match(calls[2].sql,/own\.id=t\.creator_id OR own\.id=t\.assignee_id/);
});
test('failed database result fails closed; POST is not dashboard access',async()=>{
 const {db}=fakeDB({fail:true});
 assert.equal((await edge.fetch(request(internal,token()),{...envBase,EDGE_DB:db})).status,503);
 assert.equal((await edge.fetch(request(internal,token(),'POST'),{...envBase,EDGE_DB:db})).status,404);
});
test('hub forwards assertion through private binding, never trusts client owner parameter',async()=>{
 const {calls,db}=fakeDB();
 const binding={fetch:async req=>edge.fetch(req,{...envBase,EDGE_DB:db})};
 const jwt=token();
 const res=await hub.fetch(request(dashboard+'?owner=owner-b',jwt),{MCP_GATEWAY:binding});
 assert.equal(res.status,200);assert.deepEqual((await res.json()).agents,[]);
 for(const c of calls)assert.deepEqual(c.args,[digest('owner-a')]);
 assert.equal((await hub.fetch(request(dashboard,null),{MCP_GATEWAY:binding})).status,401);
 assert.equal((await hub.fetch(request(dashboard,jwt,'POST'),{MCP_GATEWAY:binding})).status,404);
 assert.equal((await hub.fetch(request('https://other.example/api/control',jwt),{MCP_GATEWAY:binding})).status,404);
});
test('hub page and script require signed session, retain restrictive response headers',async()=>{
 const {db}=fakeDB();const binding={fetch:async req=>edge.fetch(req,{...envBase,EDGE_DB:db})};
 for(const path of ['/control','/control.js']){
  const url='https://agents.shardsinc.co.uk'+path;
  assert.equal((await hub.fetch(request(url,'invalid'),{MCP_GATEWAY:binding})).status,401);
  const res=await hub.fetch(request(url,token()),{MCP_GATEWAY:binding});
  assert.equal(res.status,200);
  assert.match(res.headers.get('content-security-policy'),/frame-ancestors 'none'/);
  assert.match(res.headers.get('cache-control'),/no-store/);
  const body=await res.text();
  if(path==='/control.js'){assert.match(body,/textContent/);assert.doesNotMatch(body,/innerHTML/);}
  else assert.match(body,/Control centre/);
 }
});
test('upstream redirect or invalid response never becomes successful data',async()=>{
 for(const response of [()=>new Response(null,{status:302,headers:{location:'https://other.example'}}),()=>Response.json({unexpected:true}),()=>new Response('broken')]){
  const res=await hub.fetch(request(dashboard,token()),{MCP_GATEWAY:{fetch:async()=>response()}});
  assert.ok(res.status>=400);
 }
});
