/**
 * Read-only post-deployment identity gate for the Shards MCP Worker.
 * Authoritative evidence: Cloudflare deployments and custom domain mapping.
 * This does not prove script byte provenance or authenticated tenant isolation.
 */
import fs from "node:fs";
import { pathToFileURL } from "node:url";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const HOST="mcp.shardsinc.co.uk";
const WORKER="shards-mcp-edge";
const API="https://api.cloudflare.com/client/v4";

function requireUuid(value,label) {
  if(typeof value!=="string"||!UUID.test(value))throw Error(label+" must be a real version UUID");
}
async function apiJson(fetchImpl,url,token) {
  const response=await fetchImpl(url,{method:"GET",headers:{
    Authorization:"Bearer "+token,
    Accept:"application/json",
  },redirect:"error",signal:AbortSignal.timeout(12000)});
  if(!response.ok)throw Error("Cloudflare API request failed: HTTP "+response.status);
  const payload=await response.json();
  if(payload?.success!==true)throw Error("Cloudflare API did not confirm successful read");
  return payload.result;
}
export function verifySnapshot(actual,recorded){
  if(!recorded||typeof recorded!=="object"||
    actual.version_id!==recorded.version_id||
    actual.deployment_id!==recorded.deployment_id||
    actual.domain_id!==recorded.domain_id||
    actual.hostname!==recorded.hostname||
    actual.service!==recorded.service||
    actual.traffic_percent!==recorded.traffic_percent)
    throw Error("ACTIVE_DEPLOYMENT_CHANGED: live Cloudflare version or domain routing differs from initial release evidence");
}
/**
 * Fails closed on missing credentials, a stale manually entered version,
 * split traffic, or a hostname pointing at another Worker/account.
 * No Cloudflare mutations are performed.
 */
export async function verifyRelease({accountId,token,expectedVersion,fetchImpl=fetch}){
  requireUuid(expectedVersion,"Expected deployed Worker version");
  if(typeof accountId!=="string"||!UUID.test(accountId)) {
    // Account IDs are 32 hexadecimal characters, not UUIDs.
    if(!/^[0-9a-f]{32}$/i.test(accountId||""))throw Error("Expected Cloudflare account ID is missing or invalid");
  }
  if(typeof token!=="string"||!token.trim())throw Error("BLOCKED: Cloudflare read-only API token secret not configured");
  const base=API+"/accounts/"+accountId+"/workers";
  const result=await apiJson(fetchImpl,base+"/scripts/"+WORKER+"/deployments?per_page=10",token);
  if(!Array.isArray(result?.deployments)||!result.deployments.length)throw Error("No authoritative Worker deployment records");
  const sorted=[...result.deployments].sort((a,b)=>Date.parse(b.created_on||0)-Date.parse(a.created_on||0));
  const latest=sorted[0];
  if(!UUID.test(latest?.id||"")||!Number.isFinite(Date.parse(latest?.created_on||"")))
    throw Error("Invalid latest Cloudflare deployment metadata");
  if(!Array.isArray(latest.versions)||latest.versions.length!==1||
     latest.versions[0].percentage!==100)
    throw Error("Split, missing or partial Cloudflare deployment: exactly one 100% version required");
  const active=latest.versions[0].version_id;
  requireUuid(active,"Active Cloudflare Worker version");
  if(active.toLowerCase()!==expectedVersion.toLowerCase())
    throw Error("DEPLOYED_VERSION_MISMATCH: requested "+expectedVersion+" but Cloudflare active is "+active);
  const domains=await apiJson(fetchImpl,base+"/domains?hostname="+encodeURIComponent(HOST),token);
  if(!Array.isArray(domains))throw Error("Cloudflare domain mapping missing");
  const matches=domains.filter(d=>d.hostname===HOST&&d.service===WORKER&&
    d.environment==="production"&&d.enabled===true);
  if(matches.length!==1||domains.some(d=>d.hostname===HOST&&!matches.includes(d)))
    throw Error("DOMAIN_ROUTE_MISMATCH: mcp.shardsinc.co.uk is not uniquely bound to the intended production Worker");
  if(typeof matches[0].id!=="string"||!matches[0].id)throw Error("Cloudflare domain mapping has no identity");
  return {
    version_id:active.toLowerCase(),deployment_id:latest.id,
    domain_id:matches[0].id,hostname:HOST,service:WORKER,traffic_percent:100,
    deployed_at:latest.created_on, verified_with:"Cloudflare Workers Deployments and Custom Domains APIs"
  };
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  const env=process.env;
  const snapshotPath="/tmp/shards-cf-release-deployment.json";
  try{
    const actual=await verifyRelease({
      accountId:env.SHARDS_CF_ACCOUNT_ID,
      token:env.SHARDS_CF_READ_TOKEN,
      expectedVersion:env.EXPECTED_WORKER_VERSION
    });
    if(process.argv.includes("--compare")){
      const previous=JSON.parse(fs.readFileSync(snapshotPath,"utf8"));
      verifySnapshot(actual,previous);
      console.log("PASS: release version, deployment ID and domain association stayed unchanged during the live checks");
    }else{
      fs.writeFileSync(snapshotPath,JSON.stringify(actual,null,2)+"\n",{mode:0o600});
      console.log("PASS: Cloudflare confirms exact active Worker version "+actual.version_id+
        " (deployment "+actual.deployment_id+", 100% traffic, correct domain)");
    }
  }catch(error){
    console.error("RELEASE GATE BLOCKED: "+String(error?.message||error));
    process.exitCode=1;
  }
}
