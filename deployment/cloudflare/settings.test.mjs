import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {webcrypto} from "node:crypto";
const src=fs.readFileSync(new URL("./worker.js",import.meta.url),"utf8");
const sandbox={Request,Response,Headers,URL,TextEncoder,TextDecoder,atob,btoa,crypto:webcrypto,AbortSignal,
  fetch:async()=>{throw Error("Unexpected network call")}};
vm.runInNewContext(src.replace("export default {","globalThis.__edge = {"),sandbox,{filename:"worker.js"});
const worker=sandbox.__edge,base="https://mcp.shardsinc.co.uk";

test("account settings UI exposes real labelled controls, secure CSP and script",async()=>{
 const r=await worker.fetch(new Request(base+"/manage/settings"),{});
 assert.equal(r.status,200);
 const html=await r.text();
 assert.match(html,/Account settings/);
 for(const t of ["Full name","Email address","Avatar","High contrast","Two-factor authentication","API key","CLI token","SSH public keys","Delete Shards account"])assert.ok(html.includes(t),t);
 assert.match(r.headers.get("content-security-policy"),/script-src 'self'/);
 const js=await worker.fetch(new Request(base+"/manage/settings.js"),{});
 assert.equal(js.status,200);
 const code=await js.text();
 assert.doesNotThrow(()=>new vm.Script(code));
 assert.match(code,/credentials:'same-origin'/);
 assert.match(code,/DELETE MY SHARDS ACCOUNT/);
 assert.doesNotMatch(code,/localStorage|sessionStorage|\.innerHTML\s*=/);
 const forbidden=await worker.fetch(new Request("https://malicious.example/manage/settings"),{});
 assert.equal(forbidden.status,404);
});

test("real signed Access profile, key lifecycle, SSH key records and local account deletion are isolated",async()=>{
 const pair=await webcrypto.subtle.generateKey({name:"RSASSA-PKCS1-v1_5",modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:"SHA-256"},true,["sign","verify"]);
 const jwk=await webcrypto.subtle.exportKey("jwk",pair.publicKey);jwk.kid="account-test-kid";
 const original=sandbox.fetch;
 sandbox.fetch=async url=>{assert.equal(String(url),"https://test-account.cloudflareaccess.com/cdn-cgi/access/certs");return {ok:true,json:async()=>({keys:[jwk]})}};
 const b64=x=>Buffer.from(JSON.stringify(x)).toString("base64url");
 const now=Math.floor(Date.now()/1000);
 const jwt=async(sub="account-subject",aud="operator-aud")=>{
   const head=b64({alg:"RS256",kid:jwk.kid}),payload=b64({iss:"https://test-account.cloudflareaccess.com",sub,email:"person@example.test",aud:[aud],exp:now+1800,nbf:now-2});
   const input=head+"."+payload;
   const sig=await webcrypto.subtle.sign("RSASSA-PKCS1-v1_5",pair.privateKey,new TextEncoder().encode(input));
   return input+"."+Buffer.from(sig).toString("base64url");
 };
 const records={accounts:[],keys:[],ssh:[],audits:[],agents:[]};
 let failAudit=false;
 const db={
   prepare(sql){
     const ctx=(args=[])=>({
       async first(){
         if(sql.includes("FROM operator_accounts WHERE id=?"))return records.accounts.find(x=>x.id===args[0])||null;
         if(sql.includes("COUNT(*) AS n FROM operator_api_keys"))return {n:records.keys.filter(x=>x.owner_id===args[0]&&!x.revoked_at&&x.expires_at>args[1]).length};
         if(sql.includes("COUNT(*) AS n FROM operator_ssh_keys"))return {n:records.ssh.filter(x=>x.owner_id===args[0]).length};
         if(sql.includes("FROM operator_api_keys k JOIN operator_accounts a")){
           const key=records.keys.find(k=>k.token_sha256===args[0]&&!k.revoked_at&&k.expires_at>args[1]);
           const account=records.accounts.find(x=>x.id===key?.owner_id&&!x.deleted_at);
           return key&&account?{...key,full_name:account.full_name}:null;
         }
         throw Error("Unknown query: "+sql);
       },
       async all(){
         if(sql.includes("FROM operator_api_keys WHERE owner_id=?"))return {results:records.keys.filter(k=>k.owner_id===args[0]).map(k=>({...k,token_sha256:undefined}))};
         if(sql.includes("FROM operator_ssh_keys WHERE owner_id=?"))return {results:records.ssh.filter(k=>k.owner_id===args[0])};
         if(sql.includes("FROM agents a LEFT JOIN access_tokens t"))return {results:records.agents.filter(a=>a.created_by===args[1])};
         throw Error("Unknown all: "+sql);
       },
       async run(){
         if(sql.startsWith("INSERT OR IGNORE INTO operator_accounts")){
           const [id,email,created_at,updated_at]=args;
           if(!records.accounts.some(x=>x.id===id))records.accounts.push({id,email,full_name:"",avatar_data:null,theme:"system",created_at,updated_at,deleted_at:null});
           return {meta:{changes:1}};
         }
         if(sql.startsWith("UPDATE operator_accounts SET full_name")){
           const row=records.accounts.find(x=>x.id===args[5]&&!x.deleted_at);
           if(row)Object.assign(row,{full_name:args[0],email:args[1],avatar_data:args[2],theme:args[3],updated_at:args[4]});
           return {meta:{changes:row?1:0}};
         }
         if(sql.startsWith("INSERT INTO audit_events")){
           if(failAudit)throw Error("Injected audit failure");
           records.audits.push(args);return {meta:{changes:1}};
         }
         if(sql.startsWith("INSERT INTO operator_api_keys")){
           const [id,owner_id,kind,label,token_sha256,prefix,scopes,created_at,expires_at]=args;
           if(records.keys.some(k=>k.token_sha256===token_sha256))throw Error("Duplicate key");
           records.keys.push({id,owner_id,kind,label,token_sha256,prefix,scopes,created_at,expires_at,last_used_at:null,revoked_at:null});
           return {meta:{changes:1}};
         }
         if(sql.startsWith("INSERT INTO operator_ssh_keys")){
           const [id,owner_id,label,public_key,fingerprint,created_at]=args;
           if(records.ssh.some(k=>k.owner_id===owner_id&&k.fingerprint===fingerprint))throw Error("Duplicate SSH key");
           records.ssh.push({id,owner_id,label,algorithm:"ssh-ed25519",public_key,fingerprint,created_at});
           return {meta:{changes:1}};
         }
         if(sql.startsWith("UPDATE operator_api_keys SET last_used_at")){
           const row=records.keys.find(k=>k.id===args[1]&&!k.revoked_at);if(row)row.last_used_at=args[0];return {meta:{changes:row?1:0}};
         }
         if(sql.startsWith("UPDATE operator_api_keys SET revoked_at=? WHERE id=?")){
           const row=records.keys.find(k=>k.id===args[1]&&k.owner_id===args[2]&&!k.revoked_at);if(row)row.revoked_at=args[0];return {meta:{changes:row?1:0}};
         }
         if(sql.startsWith("DELETE FROM operator_ssh_keys WHERE id=?")){
           const i=records.ssh.findIndex(k=>k.id===args[0]&&k.owner_id===args[1]);if(i>=0)records.ssh.splice(i,1);return {meta:{changes:i>=0?1:0}};
         }
         if(sql.startsWith("UPDATE operator_api_keys SET revoked_at=? WHERE owner_id=?")){
           let n=0;for(const k of records.keys)if(k.owner_id===args[1]&&!k.revoked_at){k.revoked_at=args[0];n++}return {meta:{changes:n}};
         }
         if(sql.startsWith("DELETE FROM operator_ssh_keys WHERE owner_id=?")){
           const before=records.ssh.length;records.ssh=records.ssh.filter(k=>k.owner_id!==args[0]);return {meta:{changes:before-records.ssh.length}};
         }
         if(sql.startsWith("UPDATE operator_accounts SET email=NULL")){
           const row=records.accounts.find(x=>x.id===args[2]);if(row)Object.assign(row,{email:null,full_name:"",avatar_data:null,theme:"system",deleted_at:args[0],updated_at:args[1]});return {meta:{changes:row?1:0}};
         }
         if(sql.startsWith("UPDATE access_tokens")||sql.startsWith("UPDATE agents SET disabled_at"))return {meta:{changes:0}};
         throw Error("Unknown run: "+sql);
       }
     });
     return {bind:(...args)=>ctx(args),...ctx()};
   },
   async batch(stmts){
     const snap=JSON.stringify(records);
     const output=[];try{for(const s of stmts)output.push(await s.run());return output}
     catch(e){const old=JSON.parse(snap);for(const key of Object.keys(records))records[key]=old[key];throw e}
   }
 };
 const env={ACCESS_TEAM:"test-account",ACCESS_AUD:"operator-aud",CONNECT_ACCESS_AUD:"connect-aud",EDGE_DB:db};
 const url=base+"/manage/api/account";
 const make=(path,method,token,body,origin=base)=>{
   const headers={"cf-access-jwt-assertion":token||""};
   if(body!==undefined){headers["content-type"]="application/json";headers.origin=origin}
   return new Request(path,{method,headers,...(body===undefined?{}:{body:JSON.stringify(body)})});
 };
 try{
   const good=await jwt(),other=await jwt("other-user"),connect=await jwt("account-subject","connect-aud");
   let res=await worker.fetch(make(url,"GET",null),env);assert.equal(res.status,401);
   res=await worker.fetch(make(url,"GET",connect),env);assert.equal(res.status,401);
   res=await worker.fetch(make(url,"GET",good),{...env,CONNECT_ACCESS_AUD:"operator-aud"});assert.equal(res.status,401);
   res=await worker.fetch(make(url,"GET",good),env);
   const empty=await res.json();assert.equal(res.status,200);
   assert.equal(empty.profile.email,"person@example.test");
   assert.equal(empty.profile.theme,"system");
   assert.equal(records.accounts.length,0,"GET does not provision account or mutate storage");
   assert.equal(empty.security.two_factor,"identity_provider");
   const profile={full_name:"Tester Name",theme:"contrast",avatar_data:null};
   res=await worker.fetch(make(url+"/profile","PUT",good,profile,"https://evil.example"),env);assert.equal(res.status,403);
   res=await worker.fetch(make(url+"/profile","PUT",good,{...profile,email:"fake@attacker.test"}),env);assert.equal(res.status,400);
   res=await worker.fetch(make(url+"/profile","PUT",good,profile),env);assert.equal(res.status,200);
   assert.equal(records.accounts[0].theme,"contrast");assert.equal(records.accounts[0].email,"person@example.test");
   const badAvatar=await worker.fetch(make(url+"/profile","PUT",good,{...profile,avatar_data:"data:image/svg+xml;base64,PHN2Zz4="}),env);
   assert.equal(badAvatar.status,400,"SVG avatars must not be accepted");
   const invalidName=await worker.fetch(make(url+"/profile","PUT",good,{...profile,full_name:"<script>"}),env);assert.equal(invalidName.status,400);
   const badKey=await worker.fetch(make(url+"/keys","POST",good,{kind:"api",label:"Valid Name",expires_days:365}),env);assert.equal(badKey.status,400);
   failAudit=true;
   const failed=await worker.fetch(make(url+"/keys","POST",good,{kind:"cli",label:"Android Termux",expires_days:30}),env);
   assert.equal(failed.status,503);
   assert.equal(records.keys.length,0,"Audit failure rolls back credential creation");
   failAudit=false;
   res=await worker.fetch(make(url+"/keys","POST",good,{kind:"cli",label:"Android Termux",expires_days:30}),env);
   assert.equal(res.status,201);const issued=await res.json();
   assert.match(issued.token,/^smcp_cli_[0-9a-f]{64}$/);assert.deepEqual(Array.from(issued.scopes),["account:read"]);
   assert.equal(records.keys.length,1);
   assert.equal(records.keys[0].token_sha256.length,64);
   assert.ok(!JSON.stringify(records).includes(issued.token),"Plaintext token must not be retained");
   const who=await worker.fetch(new Request(base+"/v1/account/whoami",{headers:{authorization:"Bearer "+issued.token}}),env);
   assert.equal(who.status,200);assert.equal((await who.json()).can_call_agent_tools,false);
   assert.ok(records.keys[0].last_used_at,"Real account-token use updates last-used field");
   const wrong=await worker.fetch(new Request(base+"/v1/account/whoami",{headers:{authorization:"Bearer smcp_cli_"+("f".repeat(64))}}),env);
   assert.equal(wrong.status,401);
   res=await worker.fetch(make(url,"GET",other),env);assert.equal((await res.json()).api_keys.length,0,"Second signed subject cannot see first account keys");
   // Valid OpenSSH public key with algorithm-prefixed 32-byte Ed25519 key material.
   const blob=(s)=>{const b=Buffer.from(s),len=Buffer.alloc(4);len.writeUInt32BE(b.length);return Buffer.concat([len,b])};
   const ssh="ssh-ed25519 "+Buffer.concat([blob("ssh-ed25519"),blob(Buffer.alloc(32,7))]).toString("base64")+" phone-key";
   res=await worker.fetch(make(url+"/ssh","POST",good,{label:"Termux Phone",public_key:ssh}),env);
   assert.equal(res.status,201);const added=await res.json();
   assert.match(added.fingerprint,/^SHA256:/);assert.equal(added.ssh_authorises_access,false);
   assert.equal(records.ssh.length,1);
   const privateKey=await worker.fetch(make(url+"/ssh","POST",good,{label:"Private",public_key:"-----BEGIN OPENSSH PRIVATE KEY-----"}),env);
   assert.equal(privateKey.status,400);
   res=await worker.fetch(make(url+"/ssh/"+added.id,"DELETE",good,{}),env);assert.equal(res.status,200);
   assert.equal(records.ssh.length,0);
   res=await worker.fetch(make(url+"/keys/"+issued.id,"DELETE",other,{}),env);
   assert.equal((await res.json()).deleted,false,"Other operator cannot revoke owner key");
   res=await worker.fetch(make(url+"/keys/"+issued.id,"DELETE",good,{}),env);
   assert.equal((await res.json()).deleted,true);
   const revoked=await worker.fetch(new Request(base+"/v1/account/whoami",{headers:{authorization:"Bearer "+issued.token}}),env);
   assert.equal(revoked.status,401);
   res=await worker.fetch(make(url,"DELETE",good,{confirm:"DELETE"}),env);assert.equal(res.status,400);
   res=await worker.fetch(make(url,"DELETE",good,{confirm:"DELETE MY SHARDS ACCOUNT"}),env);
   assert.equal(res.status,200);
   assert.equal((await res.json()).identity_provider_deleted,false);
   assert.equal(records.accounts[0].email,null);
   assert.ok(records.accounts[0].deleted_at);
   res=await worker.fetch(make(url,"GET",good),env);
   assert.equal(res.status,410,"Deleted Shards-local account cannot be silently recreated");
 }finally{sandbox.fetch=original}
});