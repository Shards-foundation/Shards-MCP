import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { webcrypto } from "node:crypto";
import { discoverOAuthProtectedResourceMetadata, discoverOAuthServerInfo } from "@modelcontextprotocol/sdk/client/auth.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const gateway = "https://mcp.shardsinc.co.uk/connect";
const source = fs.readFileSync(new URL("./worker.js", import.meta.url), "utf8");

test("official MCP TypeScript SDK v1 exchanges real protocol messages with a signed /connect identity", async () => {
  const keypair = await webcrypto.subtle.generateKey(
    {name:"RSASSA-PKCS1-v1_5",modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:"SHA-256"},true,["sign","verify"]);
  const publicJwk=await webcrypto.subtle.exportKey("jwk",keypair.publicKey);
  publicJwk.kid="sdk-integration-kid";
  const bin=x=>Buffer.from(JSON.stringify(x)).toString("base64url");
  const now=Math.floor(Date.now()/1000);
  const payload={iss:"https://sdk.cloudflareaccess.com",aud:["signed-connect-audience"],sub:"sdk-integration-principal",email:"sdk@example.test",exp:now+600,nbf:now-10};
  const signingInput=bin({alg:"RS256",kid:publicJwk.kid})+"."+bin(payload);
  const signature=await webcrypto.subtle.sign("RSASSA-PKCS1-v1_5",keypair.privateKey,new TextEncoder().encode(signingInput));
  const token=signingInput+"."+Buffer.from(signature).toString("base64url");
  const sandbox={
    Request,Response,Headers,URL,TextEncoder,TextDecoder,atob,crypto:webcrypto,AbortSignal,
    fetch:async url=>{
      assert.equal(String(url),"https://sdk.cloudflareaccess.com/cdn-cgi/access/certs");
      return {ok:true,json:async()=>({keys:[publicJwk]})};
    },
  };
  vm.runInNewContext(source.replace("export default {","globalThis.__edge = {"),sandbox,{filename:"worker.js"});
  const env={ACCESS_TEAM:"sdk",ACCESS_AUD:"protected-operator-audience",CONNECT_ACCESS_AUD:"signed-connect-audience"};
  const requests=[];
  const signedFetch=async(input,init)=>{
    const req=new Request(input,init);
    assert.equal(new URL(req.url).origin,"https://mcp.shardsinc.co.uk");
    requests.push({method:req.method,path:new URL(req.url).pathname});
    const headers=new Headers(req.headers);
    headers.set("cf-access-jwt-assertion",token);
    return sandbox.__edge.fetch(new Request(req,{headers}),env);
  };
  const client=new Client({name:"shards-real-sdk-acceptance",version:"1.0.0"});
  const transport=new StreamableHTTPClientTransport(new URL(gateway),{fetch:signedFetch});
  try{
    await client.connect(transport);
    const tools=await client.listTools();
    const names=tools.tools.map(t=>t.name);
    assert.deepEqual(names,["shards_gateway_status","shards_systems_catalog","shards_dns_lookup","shards_skill_search","shards_skill_read","shards_repo_document","shards_open_prs","shards_user_identity"]);
    const who=await client.callTool({name:"shards_user_identity",arguments:{}});
    assert.equal(who.isError,false);
    const verified=who.structuredContent||JSON.parse(who.content[0].text);
    assert.equal(verified.authenticated,true);
    assert.equal(verified.email,"sdk@example.test");
    assert.deepEqual(verified.privileged_scopes,[]);
    const denied=await client.callTool({name:"shards_task_create",arguments:{}});
    assert.equal(denied.isError,true);
    assert.match(denied.content[0].text,/PERMISSION_DENIED/);
    assert.ok(requests.filter(x=>x.method==="POST"&&x.path==="/connect").length>=4);
  }finally{await client.close();}
});


test("official SDK 401 discovery stops at /mcp metadata absence while /connect remains path-bound", async () => {
  const sandbox={Request,Response,Headers,URL,TextEncoder,TextDecoder,atob,crypto:webcrypto,AbortSignal,
    fetch:async()=>{throw Error("Discovery must not contact an external issuer");}};
  vm.runInNewContext(source.replace("export default {","globalThis.__edge = {"),sandbox,{filename:"worker.js"});
  const env={ACCESS_TEAM:"sdk",ACCESS_AUD:"operator-aud",CONNECT_ACCESS_AUD:"connect-aud"};
  const root="https://mcp.shardsinc.co.uk";
  const requests=[];
  const localFetch=async(input,init)=>{
    const request=new Request(input,init);
    assert.equal(new URL(request.url).origin,root,"No fallback can reach the Access issuer");
    requests.push(new URL(request.url).pathname);
    const response=await sandbox.__edge.fetch(request,env);
    assert.equal(response.headers.get("location"),null,"Discovery cannot redirect to another authority");
    return response;
  };
  const denied=await localFetch(root+"/mcp",{method:"POST",headers:{
    "content-type":"application/json",authorization:"Bearer invalid"},
    body:JSON.stringify({jsonrpc:"2.0",id:1,method:"tools/list",params:{}})});
  assert.equal(denied.status,401);
  assert.doesNotMatch(denied.headers.get("www-authenticate"),/resource_metadata|connect|cloudflareaccess/);
  requests.length=0;
  await assert.rejects(discoverOAuthProtectedResourceMetadata(root+"/mcp",{},localFetch),/does not implement/);
  assert.deepEqual(requests,["/.well-known/oauth-protected-resource/mcp","/.well-known/oauth-protected-resource"]);
  // SDKs with legacy fallback must not find the Access authorization server either.
  const info=await discoverOAuthServerInfo(root+"/mcp",{fetchFn:localFetch});
  assert.equal(info.resourceMetadata,undefined);
  assert.equal(info.authorizationServerMetadata,undefined);
  assert.equal(info.authorizationServerUrl,root+"/");
  assert.ok(requests.includes("/.well-known/oauth-authorization-server"));
  const challenge=await localFetch(root+"/connect",{method:"POST"});
  assert.equal(challenge.status,401);
  const resourceMetadataUrl=new URL(challenge.headers.get("www-authenticate").match(/resource_metadata="([^"]+)"/)[1]);
  for(const opts of [{},{resourceMetadataUrl}]) {
    const metadata=await discoverOAuthProtectedResourceMetadata(root+"/connect",opts,localFetch);
    assert.equal(metadata.resource,root+"/connect");
    assert.deepEqual(metadata.authorization_servers,["https://sdk.cloudflareaccess.com"]);
  }
});
