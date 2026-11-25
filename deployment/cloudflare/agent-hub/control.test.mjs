import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { generateKeyPairSync, sign, createHash, webcrypto } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { runInNewContext } from 'node:vm';
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
function token(overrides={}, key=privateKey, header={}) {
 const p=encode({alg:'RS256',kid:'test-key',...header})+'.'+encode({iss:issuer,aud:[audience],sub:'owner-a',exp:Math.floor(Date.now()/1000)+300,...overrides});
 return p+'.'+sign('RSA-SHA256',Buffer.from(p),key).toString('base64url');
}
const originalFetch=globalThis.fetch;
globalThis.fetch=async url=>{
 assert.equal(String(url),issuer+'/cdn-cgi/access/certs');
 return Response.json({keys:[jwk]});
};
test.after(()=>{globalThis.fetch=originalFetch});
const digest=s=>createHash('sha256').update(s).digest('hex');
function fakeDB({deleted=false,fail=false,rejectQuery=false,rejectAccount=false,agents=[],tasks=[]}={}){
 const calls=[];
 const db={prepare(sql){
  assert.match(sql,/^SELECT /i);
  return {bind(...args){
   calls.push({sql,args});
   return {first:async()=>{
     if(rejectAccount)throw Error('private account error');
     return deleted?{deleted_at:'2026-01-01'}:null;
    },
    all:async()=>{
     if(rejectQuery)throw Error('private storage error');
     return {success:!fail,results:sql.includes('FROM agent_tasks t')?tasks:agents};
    }};
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
test('unsuccessful and rejected dashboard reads return the same sanitized error',async()=>{
 for(const fixture of [{fail:true},{rejectQuery:true}]){
  const {db}=fakeDB(fixture);
  const res=await edge.fetch(request(internal,token()),{...envBase,EDGE_DB:db});
  assert.equal(res.status,503);
  assert.deepEqual(await res.json(),{error:'Dashboard data unavailable'});
 }
 const {calls,db}=fakeDB({rejectAccount:true});
 const res=await edge.fetch(request(internal,token()),{...envBase,EDGE_DB:db});
 assert.equal(res.status,503);
 assert.deepEqual(await res.json(),{error:'Operator account storage unavailable'});
 assert.equal(calls.length,1);
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
test('dashboard maps each upstream failure to its specific public response',async t=>{
 const cases=[
  ['redirect',new Response(null,{status:302,headers:{location:'https://other.example'}}),502,'Dashboard unavailable'],
  ['invalid shape',Response.json({unexpected:true}),502,'Invalid snapshot'],
  ['non-object JSON',Response.json(null),502,'Invalid snapshot'],
  ['invalid JSON',new Response('broken'),502,'Invalid snapshot'],
  ['storage unavailable',Response.json({error:'Private storage details'},{status:503}),503,'Dashboard unavailable'],
  ['expired session',new Response(null,{status:401}),401,'Dashboard unavailable'],
  ['deleted account',new Response(null,{status:410}),410,'Dashboard unavailable'],
 ];
 for(const [name,response,status,error] of cases){
  await t.test(name,async()=>{
   const fetch=async req=>{
    assert.equal(req.redirect,'manual');
    return response;
   };
   const res=await hub.fetch(request(dashboard,token()),{MCP_GATEWAY:{fetch}});
   assert.equal(res.status,status);
   assert.deepEqual(await res.json(),{error});
  });
 }
});

test('reject equal or missing Hub audience, public route and invalid JWT claims',async()=>{
 const {calls,db}=fakeDB();
 for(const aud of [undefined,envBase.ACCESS_AUD,envBase.CONNECT_ACCESS_AUD]){
  assert.equal((await edge.fetch(request(internal,token()),{...envBase,HUB_REGISTRY_AUD:aud,EDGE_DB:db})).status,503);
 }
 const now=Math.floor(Date.now()/1000);
 for(const jwt of [token({},privateKey,{alg:'none'}),token({nbf:now+300}),token({exp:now+86401})]){
  assert.equal((await edge.fetch(request(internal,jwt),{...envBase,EDGE_DB:db})).status,401);
 }
 assert.equal((await edge.fetch(request('https://mcp.shardsinc.co.uk/dashboard',token()),{...envBase,EDGE_DB:db})).status,404);
 assert.equal(calls.length,0);
});
test('cross-origin requests cannot reach private dashboard binding',async()=>{
 let calls=0;
 const binding={fetch:async()=>{calls++;return Response.json({agents:[],tasks:[],limits:{}})}};
 for(const headers of [{origin:'https://evil.example'},{'sec-fetch-site':'cross-site'},{'sec-fetch-site':'same-site'},{origin:'null'}]){
  const req=new Request(dashboard,{headers:{'Cf-Access-Jwt-Assertion':token(),...headers}});
  assert.equal((await hub.fetch(req,{MCP_GATEWAY:binding})).status,403);
 }
 assert.equal(calls,0);
 const req=new Request(dashboard,{headers:{'Cf-Access-Jwt-Assertion':token(),origin:'https://agents.shardsinc.co.uk','sec-fetch-site':'same-origin'}});
 assert.equal((await hub.fetch(req,{MCP_GATEWAY:binding})).status,200);
 assert.equal(calls,1);
});
test('real SQLite schema isolates two owners, excludes other tenants and private fields',async()=>{
 const sql=new DatabaseSync(':memory:');
 try {
  sql.exec(await readFile(new URL('../schema.sql',import.meta.url),'utf8'));
  const now='2026-11-25T00:00:00Z';
  sql.prepare('INSERT INTO tenants VALUES(?,?,?)').run('other-tenant','Other',now);
  const insert=sql.prepare('INSERT INTO agents(id,tenant_id,name,client,scopes,created_by,created_at) VALUES(?,?,?,?,?,?,?)');
  for(const [id,tenant,owner,client] of [
   ['a','shards-internal','owner-a','custom-mcp'],['b','shards-internal','owner-b','custom-mcp'],
   ['foreign','other-tenant','owner-a','custom-mcp'],['operator','shards-internal','owner-a','operator-ui']
  ])insert.run(id,tenant,id,client,'["message:read"]',digest(owner),now);
  const credential=sql.prepare('INSERT INTO access_tokens VALUES(?,?,?,?,?,?)');
  const issued='2026-11-25T00:10:00Z', expires='2026-12-25T00:10:00Z';
  credential.run('old-key',digest('old-key'),'a',now,'2026-12-30T00:00:00Z',null);
  credential.run('current-key',digest('current-key'),'a',issued,expires,null);
  credential.run('revoked-key',digest('revoked-key'),'a','2026-11-25T00:20:00Z','2026-12-30T00:00:00Z','2026-11-25T00:30:00Z');
  sql.prepare('INSERT INTO agent_connection_activity VALUES(?,?,?,?)').run('a',now,now,'mcp_request');
  const task=sql.prepare('INSERT INTO agent_tasks(id,tenant_id,creator_id,assignee_id,title,input_json,state,created_at,result_json) VALUES(?,?,?,?,?,?,?,?,?)');
  for(const [id,tenant,creator,assignee] of [['aa','shards-internal','a','a'],['bb','shards-internal','b','b'],['ab','shards-internal','a','b'],['ff','other-tenant','foreign','foreign']]){
   task.run(id,tenant,creator,assignee,id,'{"private":"input"}','queued',now,'{"private":"result"}');
  }
  const db={prepare(query){assert.match(query,/^SELECT /i);return {bind(...args){return {
   first:async()=>sql.prepare(query).get(...args)??null,
   all:async()=>({success:true,results:sql.prepare(query).all(...args)})
  }}}}};
  for(const [owner,agent,expected] of [['owner-a','a',['aa','ab']],['owner-b','b',['ab','bb']],['owner-c',null,[]]]){
   const res=await edge.fetch(request(internal,token({sub:owner})),{...envBase,EDGE_DB:db});
   assert.equal(res.status,200);
   const result=await res.json();
   assert.deepEqual(result.agents.map(a=>a.id),agent?[agent]:[]);
   assert.deepEqual(result.tasks.map(t=>t.id).sort(),expected);
   if(owner==='owner-a'){
    assert.equal(result.agents[0].credential_issued_at,issued);
    assert.equal(result.agents[0].credential_expires_at,expires);
    assert.equal(result.agents[0].last_authenticated_at,now);
    assert.equal(result.tasks.find(t=>t.id==='ab').assignee_name,'b');
   }
   if(owner==='owner-b'){
    assert.equal(result.agents[0].credential_issued_at,null);
    assert.equal(result.agents[0].credential_expires_at,null);
   }
   assert.doesNotMatch(JSON.stringify(result),/input_json|result_json|"private"|token_sha256|old-key|current-key|revoked-key/);
  }
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM agent_tasks').get().n,4);
 }finally{sql.close()}
});

async function loadControl(...responses){
 const elements=new Map();
 const make=()=>({
  children:[],listeners:{},value:'',
  get options(){return this.children;},
  get firstChild(){return this.children[0];},
  get childElementCount(){return this.children.length;},
  append(...children){this.children.push(...children);},
  replaceChildren(...children){this.children=children;},
  addEventListener(event,callback){this.listeners[event]=callback;}
 });
 const get=id=>{
  if(!elements.has(id))elements.set(id,make());
  return elements.get(id);
 };
 for(const id of ['agent-filter','task-filter','assignee'])get(id).value='all';
 const script=await hub.fetch(request('https://agents.shardsinc.co.uk/control.js',token()),{
  MCP_GATEWAY:{fetch:async()=>Response.json({authenticated:true})}
 });
 assert.equal(script.status,200);
 runInNewContext(await script.text(),{
  document:{getElementById:get,createElement:make},
  fetch:async path=>{assert.equal(path,'/api/control');return responses.shift();}
 });
 await new Promise(setImmediate);
 return get;
}
const snapshot=(agents,tasks=[])=>Response.json({
 agents,tasks,limits:{},checked_at:'2026-01-01T00:00:00Z'
});
test('authentication cards, count and filter agree on the current credential',async()=>{
 const agent={client:'custom-mcp',credential_issued_at:'2026-01-02T00:00:00Z',credential_expires_at:'2099-01-01T00:00:00Z'};
 const agents=[
  {id:'rotated',name:'Rotated',last_authenticated_at:'2026-01-01T00:00:00Z'},
  {id:'current',name:'Current',last_authenticated_at:agent.credential_issued_at},
  {id:'expired',name:'Expired',last_authenticated_at:agent.credential_issued_at,credential_expires_at:'2026-01-03T00:00:00Z'},
  {id:'revoked',name:'Revoked',last_authenticated_at:agent.credential_issued_at,disabled_at:'2026-01-03T00:00:00Z'},
  {id:'unknown',name:'Unknown issue time',last_authenticated_at:agent.credential_issued_at,credential_issued_at:null}
 ].map(entry=>({...agent,...entry}));
 const get=await loadControl(snapshot(agents));
 assert.deepEqual(get('agent-list').children.map(card=>card.firstChild.children[1].textContent),[
  'Awaiting authentication','Auth observed','Expired / no valid key','Revoked','Awaiting authentication'
 ]);
 assert.equal(get('verified').textContent,1);
 get('agent-filter').value='verified';
 get('agent-filter').listeners.change();
 assert.deepEqual(get('agent-list').children.map(card=>card.firstChild.firstChild.textContent),['Current']);
});
test('assignee filter deduplicates shared assignees and retains valid selections',async()=>{
 const agents=[{id:'owned',name:'Owned agent',client:'custom-mcp'}];
 const tasks=[
  {id:'other-1',title:'Shared task 1',assignee_id:'shared',assignee_name:'Shared assignee'},
  {id:'other-2',title:'Shared task 2',assignee_id:'shared',assignee_name:'Shared assignee'},
  {id:'self',title:'Own task',assignee_id:'owned',assignee_name:'Owned agent'}
 ];
 const get=await loadControl(snapshot(agents,tasks),snapshot(agents,tasks),snapshot(agents));
 const assignee=get('assignee');
 const options=()=>assignee.options.map(option=>[option.value,option.textContent]);
 const refresh=get('refresh').listeners.click;
 assert.deepEqual(options(),[['all','All assignees'],['owned','Owned agent'],['shared','Shared assignee']]);
 assignee.value='shared';
 assignee.listeners.change();
 assert.deepEqual(get('task-list').children.map(card=>card.firstChild.firstChild.textContent),['Shared task 1','Shared task 2']);
 await refresh();
 assert.equal(assignee.value,'shared');
 await refresh();
 assert.equal(assignee.value,'all');
 assert.deepEqual(options(),[['all','All assignees'],['owned','Owned agent']]);
});
test('failed refresh clears cached assignee options and selection',async()=>{
 const agents=[{id:'owned',name:'Owned agent',client:'custom-mcp'}];
 const get=await loadControl(snapshot(agents),new Response(null,{status:401}),snapshot(agents));
 const assignee=get('assignee');
 const options=()=>assignee.options.map(option=>[option.value,option.textContent]);
 assert.deepEqual(options(),[['all','All assignees'],['owned','Owned agent']]);
 assignee.value='owned';
 const refresh=get('refresh').listeners.click;
 await refresh();
 assert.deepEqual(options(),[['all','All assignees']]);
 assert.equal(assignee.value,'all');
 assert.equal(get('task-list').firstChild.textContent,'Task data unavailable.');
 assert.match(get('status').textContent,/HTTP 401/);
 await refresh();
 assert.deepEqual(options(),[['all','All assignees'],['owned','Owned agent']]);
});
