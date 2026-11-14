import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {webcrypto} from "node:crypto";

const source=fs.readFileSync(new URL("./worker.js",import.meta.url),"utf8");
const sandbox={Request,Response,Headers,URL,TextEncoder,TextDecoder,crypto:webcrypto,AbortSignal,atob,
  fetch:async()=>{throw Error("unexpected upstream network call")}};
vm.runInNewContext(source.replace("export default {","globalThis.__edge = {"),sandbox,{filename:"worker.js"});
const worker=sandbox.__edge;
const base="https://mcp.shardsinc.co.uk";
const agentId="agent-123456789012";

test("workspace serves a mobile client without exposing message contents in the public shell",async()=>{
 const r=await worker.fetch(new Request(base+"/manage/workspace"),{});
 assert.equal(r.status,200);
 assert.match(r.headers.get("content-type"),/text\/html/);
 assert.match(r.headers.get("content-security-policy"),/script-src 'self'/);
 const html=await r.text();
 assert.match(html,/Direct conversations/);
 assert.match(html,/id="composer"/);
 assert.match(html,/id="taskList"/);
 assert.match(html,/id="agentList"/);
 assert.match(html,/not verified online/);
 assert.match(html,/Not connected/);
 assert.doesNotMatch(html,/<script(?![^>]*src=)/);
 const js=await worker.fetch(new Request(base+"/manage/workspace.js"),{});
 assert.equal(js.status,200);
 const code=await js.text();
 assert.doesNotThrow(()=>new vm.Script(code));
 assert.match(code,/manage\/api\/workspace/);
 assert.match(code,/credentials:'same-origin'/);
 assert.match(code,/crypto.randomUUID/);
 assert.match(code,/textContent=/);
 assert.doesNotMatch(code,/\.innerHTML\s*=|localStorage|sessionStorage|smcp_[a-zA-Z0-9]/);
 const entry=await worker.fetch(new Request(base+"/"),{});
 assert.match(await entry.text(),/href="\/manage\/workspace">WORKSPACE/);
 const other=await worker.fetch(new Request("https://example.test/manage/workspace"),{});
 assert.equal(other.status,404);
});

test("operator-only workspace uses a real signed admin identity and stores scoped messages idempotently",async()=>{
 const keys=await webcrypto.subtle.generateKey({name:"RSASSA-PKCS1-v1_5",modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:"SHA-256"},true,["sign","verify"]);
 const jwk=await webcrypto.subtle.exportKey("jwk",keys.publicKey);jwk.kid="workspace-kid";
 const issuer="https://workspace-integration.cloudflareaccess.com";
 const originalFetch=sandbox.fetch;
 sandbox.fetch=async url=>{
   assert.equal(url,issuer+"/cdn-cgi/access/certs");
   return {ok:true,json:async()=>({keys:[jwk]})};
 };
 const encode=x=>Buffer.from(JSON.stringify(x)).toString("base64url");
 async function jwt(changes={}){
   const now=Math.floor(Date.now()/1000);
   const payload={iss:issuer,aud:["operator-audience"],sub:"operator-person",exp:now+1800,nbf:now-10,...changes};
   const head=encode({alg:"RS256",kid:jwk.kid})+"."+encode(payload);
   const signature=await webcrypto.subtle.sign("RSASSA-PKCS1-v1_5",keys.privateKey,new TextEncoder().encode(head));
   return head+"."+Buffer.from(signature).toString("base64url");
 }
 const agents=[{id:agentId,tenant_id:"shards-internal",name:"ExternalWorker",client:"claude",created_at:"2026-11-13T12:00:00Z",disabled_at:null}];
 const messages=[],tasks=[],audits=[];
 const env={ACCESS_TEAM:"workspace-integration",ACCESS_AUD:"operator-audience",CONNECT_ACCESS_AUD:"connect-audience",EDGE_DB:{
  prepare(sql){
   const make=(args=[])=>({
     async first(){
       if(sql.includes("SELECT id FROM agents WHERE id=?"))return agents.find(a=>a.id===args[0]&&a.tenant_id==="shards-internal"&&!a.disabled_at&&a.client!=="operator-ui")||null;
       if(sql.includes("SELECT id,body,recipient_id FROM agent_messages"))return messages.find(m=>m.tenant_id==="shards-internal"&&m.sender_id===args[0]&&m.request_key===args[1])||null;
       throw Error("Unexpected first SQL: "+sql);
     },
     async run(){
       if(sql.startsWith("INSERT OR IGNORE INTO agents")){
         const [id,name,ownerHash,createdAt]=args;
         if(!agents.some(x=>x.id===id))agents.push({id,tenant_id:"shards-internal",name,client:"operator-ui",created_by:ownerHash,scopes:"[]",created_at:createdAt,disabled_at:null});
         return {meta:{changes:1}};
       }
       if(sql.startsWith("INSERT OR IGNORE INTO agent_messages")){
         const [id,sender,recipient,body,created,key]=args;
         if(!messages.some(m=>m.sender_id===sender&&m.request_key===key))messages.push({id,tenant_id:"shards-internal",sender_id:sender,recipient_id:recipient,body,created_at:created,request_key:key,read_at:null});
         return {meta:{changes:1}};
       }
       if(sql.startsWith("INSERT INTO audit_events")){audits.push(args);return {meta:{changes:1}}}
       throw Error("Unexpected run SQL: "+sql);
     },
     async all(){
       if(sql.startsWith("SELECT id,name,client,created_at FROM agents"))return {results:agents.map(({id,name,client,created_at})=>({id,name,client,created_at}))};
       if(sql.startsWith("SELECT m.id,m.sender_id"))return {results:messages.map(m=>({...m,sender_name:agents.find(a=>a.id===m.sender_id)?.name,recipient_name:agents.find(a=>a.id===m.recipient_id)?.name}))};
       if(sql.startsWith("SELECT t.id,t.creator_id"))return {results:tasks};
       throw Error("Unexpected all SQL: "+sql);
     },
   });
   return {bind:(...args)=>make(args),...make()};
  }
 }};
 const api=base+"/manage/api/workspace";
 const req=(method,url,token,body=null,origin=base)=>new Request(url,{method,headers:{...(token?{"cf-access-jwt-assertion":token}:{}),...(body!==null?{"content-type":"application/json",origin}: {})},...(body!==null?{body:JSON.stringify(body)}:{})});
 try{
   const noLogin=await worker.fetch(req("GET",api,null),env);
   assert.equal(noLogin.status,401);
   const nonAdmin=await worker.fetch(req("GET",api,await jwt({aud:["connect-audience"]})),env);
   assert.equal(nonAdmin.status,401);
   const user=await jwt();
   const initial=await worker.fetch(req("GET",api,user),env);
   assert.equal(initial.status,200);
   const snapshot=await initial.json();
   assert.equal(snapshot.agents.length,1);
   assert.equal(snapshot.messages.length,0);
   assert.equal(snapshot.tasks.length,0);
   assert.equal(typeof snapshot.operator_id,"string");
   assert.equal(agents.length,1,"GET cannot mutate tenant");
   assert.doesNotMatch(JSON.stringify(snapshot),/cf-access|access_tokens|token_sha256|smcp_/);
   const recipient=agentId,requestId="request-1234567890";
   const payload={recipient_agent_id:recipient,body:"Please report your status from your own runtime.",request_id:requestId};
   const endpoint=api+"/messages";
   const badOrigin=await worker.fetch(req("POST",endpoint,user,payload,"https://untrusted.example"),env);
   assert.equal(badOrigin.status,403);
   const invalid=await worker.fetch(req("POST",endpoint,user,{...payload,recipient_agent_id:"another-tenant-agent-id"}),env);
   assert.equal(invalid.status,404);
   const off=await worker.fetch(req("POST",endpoint,user,{...payload,body:""}),env);
   assert.equal(off.status,400);
   const unknown=await worker.fetch(req("POST",endpoint,user,{...payload,evil:true}),env);
   assert.equal(unknown.status,400);
   assert.equal(messages.length,0);
   const first=await worker.fetch(req("POST",endpoint,user,payload),env);
   assert.equal(first.status,201);
   const firstData=await first.json();
   assert.equal(firstData.stored,true);
   assert.equal(firstData.idempotent,false);
   assert.equal(messages.length,1);
   assert.equal(agents.length,2,"operator principal is created on first authenticated send only");
   assert.equal(messages[0].sender_id,snapshot.operator_id);
   assert.equal(messages[0].recipient_id,recipient);
   assert.equal(agents.find(a=>a.id===snapshot.operator_id).client,"operator-ui");
   assert.equal(audits.length,1);
   const second=await worker.fetch(req("POST",endpoint,user,payload),env);
   assert.equal(second.status,200);
   assert.equal((await second.json()).idempotent,true);
   assert.equal(messages.length,1);
   assert.equal(audits.length,1);
   const collision=await worker.fetch(req("POST",endpoint,user,{...payload,body:"Different text"}),env);
   assert.equal(collision.status,409);
   const after=await worker.fetch(req("GET",api,user),env);
   const feed=await after.json();
   assert.equal(feed.messages.length,1);
   assert.equal(feed.messages[0].body,payload.body);
   assert.equal(feed.messages[0].sender_name,agents.find(a=>a.id===snapshot.operator_id).name);
 }finally{sandbox.fetch=originalFetch}
});
