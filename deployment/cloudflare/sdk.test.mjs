import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { webcrypto } from "node:crypto";
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
    assert.deepEqual(names,["shards_gateway_status","shards_systems_catalog","shards_dns_lookup","shards_user_identity"]);
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
