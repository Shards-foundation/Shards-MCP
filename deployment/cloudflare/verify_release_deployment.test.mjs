import test from "node:test";
import assert from "node:assert/strict";
import { verifyRelease,verifySnapshot } from "./verify_release_deployment.mjs";

const accountId="7a2355b21ed76c3aa60e8bdf3a9a5c8a";
const token="fixture-only";
const expectedVersion="1417254b-dbe8-4e9b-b479-b5d474ca6726";
const deploymentId="386e4e82-5c97-4224-bef0-866512e151b3";
const domainId="89878e6714e4f9b2a5488c8035390e50e8cff13f";
const deployment={id:deploymentId,created_on:"2026-11-15T10:24:00Z",versions:[{version_id:expectedVersion,percentage:100}]};
const domain={id:domainId,hostname:"mcp.shardsinc.co.uk",service:"shards-mcp-edge",environment:"production",enabled:true};

function fakeCloudflare({deployments=[deployment],domains=[domain],status=200,success=true}={}){
  const calls=[];
  const fetchImpl=async (url,options)=>{
    calls.push({url,options});
    assert.equal(options.headers.Authorization,"Bearer "+token);
    assert.equal(options.method,"GET");
    assert.equal(options.redirect,"error");
    assert.ok(options.signal instanceof AbortSignal);
    const result=url.includes("/deployments?")?{deployments}:url.includes("/domains?")?domains:null;
    if(result===null)throw Error("Unlisted API URL: "+url);
    return new Response(JSON.stringify({success,result}),{status});
  };
  return {calls,fetchImpl};
}
const check=fetchImpl=>verifyRelease({accountId,token,expectedVersion,fetchImpl});
test("Active version is independently verified, not just a well-shaped UUID",async()=>{
  const mock=fakeCloudflare();
  const actual=await check(mock.fetchImpl);
  assert.equal(actual.version_id,expectedVersion);
  assert.equal(actual.deployment_id,deploymentId);
  assert.equal(actual.traffic_percent,100);
  assert.equal(actual.domain_id,domainId);
  assert.equal(mock.calls.length,2);
  assert.ok(mock.calls[0].url.includes("/scripts/shards-mcp-edge/deployments?per_page=10"));
  assert.ok(mock.calls[1].url.includes("/domains?hostname=mcp.shardsinc.co.uk"));
});
test("A supplied but stale UUID is rejected even if it has correct syntax",async()=>{
  const stale={...deployment,versions:[{version_id:"ff6379db-06fc-4053-87b0-c06010bb2cdb",percentage:100}]};
  await assert.rejects(check(fakeCloudflare({deployments:[stale]}).fetchImpl),/DEPLOYED_VERSION_MISMATCH/);
});
test("A live traffic split, missing version, and malformed deployment are rejected",async()=>{
  const variants=[
    {...deployment,versions:[{version_id:expectedVersion,percentage:70},{version_id:"ff6379db-06fc-4053-87b0-c06010bb2cdb",percentage:30}]},
    {...deployment,versions:[{version_id:expectedVersion,percentage:99}]},
    {...deployment,versions:[]},
    {...deployment,created_on:"invalid"}
  ];
  for(const item of variants)await assert.rejects(check(fakeCloudflare({deployments:[item]}).fetchImpl),/deployment|metadata/i);
});
test("Old deployment cannot masquerade as the active one",async()=>{
  const newer={...deployment,id:"40000000-0000-4000-8000-000000000001",created_on:"2026-11-16T00:00:00Z",
    versions:[{version_id:"ff6379db-06fc-4053-87b0-c06010bb2cdb",percentage:100}]};
  await assert.rejects(check(fakeCloudflare({deployments:[deployment,newer]}).fetchImpl),/DEPLOYED_VERSION_MISMATCH/);
});
test("A custom domain bound to another Worker is a release failure",async()=>{
  const bads=[
    [{...domain,service:"other-service"}],
    [{...domain,environment:"staging"}],
    [{...domain,enabled:false}],
    [],
    [domain,{...domain,id:"duplicate-domain",service:"other-service"}]
  ];
  for(const domains of bads)await assert.rejects(check(fakeCloudflare({domains}).fetchImpl),/DOMAIN_ROUTE_MISMATCH/);
});
test("Unauthorised API, absent token and API denial fail closed",async()=>{
  await assert.rejects(verifyRelease({accountId,token:"",expectedVersion,fetchImpl:fakeCloudflare().fetchImpl}),/BLOCKED/);
  await assert.rejects(check(fakeCloudflare({status:401}).fetchImpl),/HTTP 401/);
  await assert.rejects(check(fakeCloudflare({success:false}).fetchImpl),/did not confirm successful read/);
});
test("The active deployment must remain identical across the entire MCP smoke sequence",async()=>{
  const snapshot=await check(fakeCloudflare().fetchImpl);
  verifySnapshot(snapshot,snapshot);
  assert.throws(()=>verifySnapshot({...snapshot,deployment_id:"new-deployment"},snapshot),/ACTIVE_DEPLOYMENT_CHANGED/);
  assert.throws(()=>verifySnapshot({...snapshot,version_id:"ff6379db-06fc-4053-87b0-c06010bb2cdb"},snapshot),/ACTIVE_DEPLOYMENT_CHANGED/);
  assert.throws(()=>verifySnapshot({...snapshot,domain_id:"different"},snapshot),/ACTIVE_DEPLOYMENT_CHANGED/);
});
test("Verification does not contact API on a malformed version",async()=>{
  const mock=fakeCloudflare();
  await assert.rejects(verifyRelease({accountId,token,expectedVersion:"not-a-uuid",fetchImpl:mock.fetchImpl}),/version UUID/);
  assert.equal(mock.calls.length,0);
});
