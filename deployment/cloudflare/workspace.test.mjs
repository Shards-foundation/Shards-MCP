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
 assert.match(html,/presence not tracked/);

 assert.match(html,/Not connected/);
 assert.doesNotMatch(html,/<script(?![^>]*src=)/);
 const js=await worker.fetch(new Request(base+"/manage/workspace.js"),{});
 assert.equal(js.status,200);
 const code=await js.text();
 assert.doesNotThrow(()=>new vm.Script(code));
 assert.match(code,/manage\/api\/workspace/);
 assert.match(code,/credentials:'same-origin'/);
 assert.match(code,/crypto.randomUUID/);
 assert.match(code,/online unverified/);
 assert.match(code,/no inbox scope/);
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
 const agents=[{id:agentId,tenant_id:"shards-internal",name:"ExternalWorker",client:"claude",scopes:JSON.stringify(["agent:identity","message:read","message:send"]),created_at:"2026-11-13T12:00:00Z",disabled_at:null}];
 agents.push({id:"foreign-agent-123456",tenant_id:"another-tenant",name:"ForeignWorker",client:"claude",scopes:JSON.stringify(["message:read"]),created_at:"2026-11-13T12:00:00Z",disabled_at:null});
 const messages=[],tasks=[],audits=[];
 let auditFailure=false;
 const env={ACCESS_TEAM:"workspace-integration",ACCESS_AUD:"operator-audience",CONNECT_ACCESS_AUD:"connect-audience",EDGE_DB:{
  async batch(statements){
    const savedMessages=messages.slice(),savedAudits=audits.slice();
    try{const output=[];for(const stmt of statements)output.push(await stmt.run());return output}
    catch(e){messages.splice(0,messages.length,...savedMessages);audits.splice(0,audits.length,...savedAudits);throw e}
  },
  prepare(sql){
   const make=(args=[])=>({
     async first(){
       if(sql.includes("SELECT id,scopes FROM agents WHERE id=?"))return agents.find(a=>a.id===args[0]&&a.tenant_id==="shards-internal"&&!a.disabled_at&&a.client!=="operator-ui")||null;
       if(sql.includes("SELECT id,body,recipient_id FROM agent_messages"))return messages.find(m=>m.tenant_id==="shards-internal"&&m.sender_id===args[0]&&m.request_key===args[1])||null;
       if(sql.includes("SELECT disabled_at,client FROM agents"))return agents.find(a=>a.id===args[0]&&a.tenant_id==="shards-internal")||null;
       throw Error("Unexpected first SQL: "+sql);
     },
     async run(){
       if(sql.startsWith("INSERT OR IGNORE INTO agents")){
         const [id,name,ownerHash,createdAt]=args;
         if(!agents.some(x=>x.id===id))agents.push({id,tenant_id:"shards-internal",name,client:"operator-ui",created_by:ownerHash,scopes:"[]",created_at:createdAt,disabled_at:null});
         return {meta:{changes:1}};
       }
       if(sql.startsWith("INSERT OR IGNORE INTO agent_messages")){
         assert.match(sql,/JOIN agents r ON/,"Writes must atomically check active operator and recipient identities");
         assert.match(sql,/EXISTS\(SELECT 1 FROM json_each\(r\.scopes\) WHERE value='message:read'\)/,"Atomic insert requires recipient inbox capability in SQL");
         const [id,body,created,key,recipient,sender]=args;
         const from=agents.find(a=>a.id===sender&&a.tenant_id==="shards-internal"&&!a.disabled_at&&a.client==="operator-ui");
         const to=agents.find(a=>a.id===recipient&&a.tenant_id==="shards-internal"&&!a.disabled_at&&a.client!=="operator-ui");
         if(from&&to&&JSON.parse(to.scopes||"[]").includes("message:read")&&!messages.some(m=>m.sender_id===sender&&m.request_key===key))messages.push({id,tenant_id:"shards-internal",sender_id:sender,recipient_id:recipient,body,created_at:created,request_key:key,read_at:null});
         return {meta:{changes:from&&to?1:0}};
       }
       if(sql.startsWith("INSERT INTO audit_events")){
         if(auditFailure)throw Error("Injected D1 audit failure");
         const saved=messages.some(m=>m.id===args[4]&&m.tenant_id==="shards-internal");
         if(saved)audits.push(args);
         return {meta:{changes:saved?1:0}};
       }
       throw Error("Unexpected run SQL: "+sql);
     },
     async all(){
       if(sql.startsWith("SELECT id,name,client,scopes,created_at FROM agents"))return {results:agents.filter(a=>a.tenant_id==="shards-internal"&&!a.disabled_at).map(({id,name,client,scopes,created_at})=>({id,name,client,scopes,created_at}))};
       if(sql.startsWith("SELECT m.id,m.sender_id")){
         assert.match(sql,/m\.sender_id=\? OR m\.recipient_id=\?/,"D1 must page the selected agent only");
         return {results:messages.filter(m=>m.sender_id===args[0]||m.recipient_id===args[1]).slice(-200).reverse().map(m=>({...m,sender_name:agents.find(a=>a.id===m.sender_id)?.name,recipient_name:agents.find(a=>a.id===m.recipient_id)?.name}))};
       }
       if(sql.startsWith("SELECT t.id,t.creator_id")){
         assert.match(sql,/t\.creator_id=\? OR t\.assignee_id=\?/);
         return {results:tasks.filter(t=>t.creator_id===args[0]||t.assignee_id===args[1]).slice(-80).reverse()};
       }
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
   const sharedAudience=await worker.fetch(req("GET",api,await jwt()),{...env,CONNECT_ACCESS_AUD:"operator-audience"});
   assert.equal(sharedAudience.status,503,"Shared operator and Connect audience is a fatal configuration error");
   const user=await jwt();
   const initial=await worker.fetch(req("GET",api,user),env);
   assert.equal(initial.status,200);
   const snapshot=await initial.json();
   assert.equal(snapshot.agents.length,1);
   assert.equal(snapshot.messages.length,0);
   assert.equal(snapshot.tasks.length,0);
   assert.equal(typeof snapshot.operator_id,"string");
   assert.equal(agents.length,2,"GET cannot mutate tenant or provision an operator");
   assert.equal(snapshot.focus_id,agentId);
   assert.equal(snapshot.agents.find(a=>a.id===agentId).can_receive_messages,true);
   const wrongTenantAgent=await worker.fetch(req("GET",api+"?agent_id=agent-not-enrolled-12345",user),env);
   assert.equal(wrongTenantAgent.status,404);
   const invalidFilter=await worker.fetch(req("GET",api+"?agent_id=%3Cscript%3E",user),env);
   assert.equal(invalidFilter.status,400);
   assert.doesNotMatch(JSON.stringify(snapshot),/cf-access|access_tokens|token_sha256|smcp_/);
   const recipient=agentId,requestId="request-1234567890";
   const payload={recipient_agent_id:recipient,body:"Please report your status from your own runtime.",request_id:requestId};
   const endpoint=api+"/messages";
   const badOrigin=await worker.fetch(req("POST",endpoint,user,payload,"https://untrusted.example"),env);
   assert.equal(badOrigin.status,403);
   const invalid=await worker.fetch(req("POST",endpoint,user,{...payload,recipient_agent_id:"foreign-agent-123456"}),env);
   assert.equal(invalid.status,404,"Real other-tenant recipient must be denied");
   const off=await worker.fetch(req("POST",endpoint,user,{...payload,body:""}),env);
   assert.equal(off.status,400);
   const unknown=await worker.fetch(req("POST",endpoint,user,{...payload,evil:true}),env);
   assert.equal(unknown.status,400);
   const oversize=await worker.fetch(req("POST",endpoint,user,{...payload,body:"x".repeat(20000)}),env);
   assert.equal(oversize.status,400,"Streaming request must be rejected before an oversized JSON body is fully buffered");
   const longUtf8=await worker.fetch(req("POST",endpoint,user,{...payload,body:"😀".repeat(1500)}),env);
   assert.equal(longUtf8.status,400,"UTF-16 message length limit must reject oversized emoji payload");
   const recipientMissingScope=agents.find(a=>a.id===agentId);
   const originalScopes=recipientMissingScope.scopes;
   recipientMissingScope.scopes=JSON.stringify(["agent:identity"]);
   const noInbox=await worker.fetch(req("POST",endpoint,user,payload),env);
   assert.equal(noInbox.status,409,"Recipient without message:read must not be sent an unreadable inbox record");
   recipientMissingScope.scopes=originalScopes;
   assert.equal(messages.length,0);
   const first=await worker.fetch(req("POST",endpoint,user,payload),env);
   assert.equal(first.status,201);
   const firstData=await first.json();
   assert.equal(firstData.stored,true);
   assert.equal(firstData.idempotent,false);
   assert.equal(messages.length,1);
   assert.equal(agents.length,3,"operator principal is created on first authenticated send only");
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
   const operatorAccount=agents.find(a=>a.id===snapshot.operator_id);
   operatorAccount.disabled_at=new Date().toISOString();
   const disabled=await worker.fetch(req("POST",endpoint,user,{...payload,request_id:"second-request-12345"}),env);
   assert.equal(disabled.status,403,"Revoking the operator principal must deny further sends");
   assert.equal(messages.length,1,"No message is stored from a revoked sender");
   operatorAccount.disabled_at=null;
   const recipientAccount=agents.find(a=>a.id===agentId);
   recipientAccount.disabled_at=new Date().toISOString();
   const revokedTarget=await worker.fetch(req("POST",endpoint,user,{...payload,request_id:"third-request-123456"}),env);
   assert.equal(revokedTarget.status,404,"Revoked recipient must not receive new messages");
   const replayAfterRevoke=await worker.fetch(req("POST",endpoint,user,payload),env);
   assert.equal(replayAfterRevoke.status,200,"A committed request can be confirmed after recipient revocation");
   assert.equal((await replayAfterRevoke.json()).idempotent,true);
   recipientAccount.disabled_at=null;
   const after=await worker.fetch(req("GET",api,user),env);
   const feed=await after.json();
   assert.equal(feed.messages.length,1);
   assert.equal(feed.messages[0].body,payload.body);
   assert.equal(feed.messages[0].sender_name,agents.find(a=>a.id===snapshot.operator_id).name);
   const otherId="second-agent-123456";
   agents.push({id:otherId,tenant_id:"shards-internal",name:"AnotherWorker",client:"codex",scopes:JSON.stringify(["message:read"]),created_at:"2026-11-13T13:00:00Z",disabled_at:null});
   messages.push({id:"old-message-for-other",tenant_id:"shards-internal",sender_id:otherId,recipient_id:otherId,body:"Only for second agent",created_at:"2026-11-13T13:00:00Z",request_key:"outside",read_at:null});
   const focused=await worker.fetch(req("GET",api+"?agent_id="+agentId,user),env);
   const direct=await focused.json();
   assert.equal(direct.messages.length,1,"Only chosen agent messages returned");
   assert.equal(direct.messages[0].body,payload.body);
   const secondFeed=await worker.fetch(req("GET",api+"?agent_id="+otherId,user),env);
   assert.equal((await secondFeed.json()).messages[0].body,"Only for second agent");
   auditFailure=true;
   const broken=await worker.fetch(req("POST",endpoint,user,{...payload,request_id:"audit-failure-request-123"}),env);
   assert.equal(broken.status,503,"Audit failure must reject the message");
   assert.equal(messages.filter(m=>m.request_key==="audit-failure-request-123").length,0,"D1 batch rolls back message on audit failure");
   auditFailure=false;
   const recovered=await worker.fetch(req("POST",endpoint,user,{...payload,request_id:"audit-failure-request-123"}),env);
   assert.equal(recovered.status,201,"A clean retry may now commit message and audit atomically");
   assert.equal(messages.filter(m=>m.request_key==="audit-failure-request-123").length,1);
   assert.equal(audits.length,2,"Every successful new message has exactly one audit entry");
   const escapedBody=String.fromCharCode(34).repeat(2000);
   const escaped=await worker.fetch(req("POST",endpoint,user,{...payload,body:escapedBody,request_id:"escaped-2000-char-unique"}),env);
   assert.equal(escaped.status,201,"Valid 2000-character JSON-escaped message must not be rejected by transport size cap");
   assert.equal(messages.find(m=>m.request_key==="escaped-2000-char-unique").body.length,2000);
 }finally{sandbox.fetch=originalFetch}
});
