import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { webcrypto } from "node:crypto";

const source=fs.readFileSync(new URL("./worker.js",import.meta.url),"utf8");
const sandbox={
  Request, Response, Headers, URL, TextEncoder, TextDecoder, crypto:webcrypto,
  AbortSignal, atob,
  fetch:async()=>{throw Error("No network allowed in developer portal tests");}
};
vm.runInNewContext(source.replace("export default {","globalThis.__edge = {"),sandbox,{filename:"worker.js"});
const worker=sandbox.__edge;
const root="https://mcp.shardsinc.co.uk";

test("public homepage explains developer use without asking for credentials",async()=>{
  const response=await worker.fetch(new Request(root+"/"),{});
  assert.equal(response.status,200);
  assert.match(response.headers.get("content-security-policy"),/script-src 'self'/);
  const html=await response.text();
  assert.match(html,/Developers \| Shards MCP/);
  assert.match(html,/developer portal/i);
  assert.match(html,/https:\/\/agents.shardsinc.co.uk/);
  assert.match(html,/https:\/\/mcp.shardsinc.co.uk\/mcp/);
  assert.match(html,/\/manage\/connect-agents/);
  assert.match(html,/\/api\/status/);
  assert.match(html,/<script src="\/developer.js" defer><\/script>/);
  assert.doesNotMatch(html,/<script(?![^>]*src=)/);
  assert.doesNotMatch(html,/smcp_[A-Za-z0-9_-]{20}/);
});

test("developer alias works and status script is client-side read-only",async()=>{
  const page=await worker.fetch(new Request(root+"/developer"),{});
  assert.equal(page.status,200);
  assert.match(await page.text(),/Scoped access/);
  const script=await worker.fetch(new Request(root+"/developer.js"),{});
  assert.equal(script.status,200);
  assert.match(script.headers.get("content-type"),/javascript/);
  const js=await script.text();
  assert.match(js,/fetch\("\/api\/status"/);
  assert.doesNotMatch(js,/method\s*:\s*["']POST["']/i);
  new vm.Script(js);
});

test("legacy operator console and enrolment entrypoints remain available",async()=>{
  const legacy=await worker.fetch(new Request(root+"/manage"),{});
  assert.equal(legacy.status,200);
  const html=await legacy.text();
  assert.match(html,/ONE GATEWAY/);
  assert.match(html,/CONNECT AGENTS/);
  assert.match(html,/WORKSPACE/);
  const enroll=await worker.fetch(new Request(root+"/manage/connect-agents"),{});
  assert.equal(enroll.status,200);
  assert.match(await enroll.text(),/Enrol a real agent/);
});

test("reviewed source public MCP tool inventory remains unchanged without bearer authentication",async()=>{
  const request=new Request(root+"/mcp",{
    method:"POST",headers:{"content-type":"application/json"},
    body:JSON.stringify({jsonrpc:"2.0",id:7,method:"tools/list",params:{}})
  });
  const response=await worker.fetch(request,{});
  assert.equal(response.status,200);
  const result=await response.json();
  const names=Array.from(result.result.tools,x=>x.name).sort();
  assert.deepEqual(names,["shards_dns_lookup","shards_gateway_status","shards_systems_catalog","shards_skill_search","shards_skill_read","shards_repo_document","shards_open_prs"].sort());
});

test("developer page cannot bypass the protected MCP tool boundary",async()=>{
  const request=new Request(root+"/mcp",{
    method:"POST",headers:{"content-type":"application/json"},
    body:JSON.stringify({jsonrpc:"2.0",id:8,method:"tools/call",params:{name:"shards_agent_identity",arguments:{}}})
  });
  const response=await worker.fetch(request,{});
  assert.equal(response.status,200);
  const result=await response.json();
  assert.equal(result.result.isError,true);
});

test("public status metadata stays JSON and does not imply operator sign-in",async()=>{
  const env={EDGE_DB:{prepare(sql){
    assert.match(sql,/SELECT 1 AS ok/);
    return {async first(){return {ok:1};}};
  }}};
  const response=await worker.fetch(new Request(root+"/api/status"),env);
  assert.equal(response.status,200);
  const data=await response.json();
  assert.equal(data.endpoint,root+"/mcp");
  assert.equal(data.db,"connected");
  assert.ok(data.tools.some(t=>t.name==="shards_gateway_status"&&t.public));
});
