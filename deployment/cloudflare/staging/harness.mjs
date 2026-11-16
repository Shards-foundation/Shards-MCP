// Local test adapter only. No Cloudflare API, remote database or credential store.
import {webcrypto} from 'node:crypto';
import {Miniflare,createFetchMock} from 'miniflare';
import {artifact,hash,pinned,SOURCE,NAME} from './build.mjs';
import {fixtures,seedStatements} from './fixtures.mjs';
const transports=new WeakMap();
export const localTransport=options=>transports.get(options);
export function localApproval(){
  const workers=[false,true].map(fault=>{const a=artifact('local',{fault});return {name:NAME+(fault?'-fault':''),origin:a.manifest.origin,deployment_id:fault?'22222222-2222-4222-8222-222222222222':'11111111-1111-4111-8111-111111111111',version_id:fault?'44444444-4444-4444-8444-444444444444':'33333333-3333-4333-8333-333333333333',module_name:'worker.js',artifact_sha256:hash(a.script)};});
  return {approval_id:'Synthetic local test approval only',mode:'same-account-staging',account_id:'1'.repeat(32),account_name:'Local fixture',subdomain:'local',database_id:'55555555-5555-4555-8555-555555555555',database_name:NAME,jurisdiction:'eu',workers};
}
export async function runtime({mutate=s=>s}={}){
  const approval=localApproval(),main=artifact('local'),fault=artifact('local',{fault:true});
  const key=await webcrypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
  const jwk=await webcrypto.subtle.exportKey('jwk',key.publicKey);jwk.kid='staging-synthetic-key';
  const issuer='https://isolated-fixture.cloudflareaccess.com';
  const mock=createFetchMock();mock.disableNetConnect();mock.get(issuer).intercept({path:'/cdn-cgi/access/certs'}).reply(200,{keys:[jwk]}).persist();
  const bindings={STAGING_ACCEPTANCE:SOURCE,ACCESS_TEAM:'isolated-fixture',ACCESS_AUD:'synthetic-operator-audience',CONNECT_ACCESS_AUD:'synthetic-connect-audience'};
  const mf=new Miniflare({modules:true,script:mutate(main.script),compatibilityDate:'2025-06-18',d1Databases:['EDGE_DB'],d1Persist:false,bindings,fetchMock:mock});
  const broken=new Miniflare({modules:true,script:fault.script,compatibilityDate:'2025-06-18',bindings,fetchMock:mock});
  const dispose=async()=>{await Promise.all([mf.dispose(),broken.dispose()]);await mock.close();};
  try{
    const db=await mf.getD1Database('EDGE_DB');
    const schema=pinned('deployment/cloudflare/schema.sql').replace(/^--.*$/gm,'').split(';').map(s=>s.replace(/\s+/g,' ').trim()).filter(Boolean);
    for(const sql of schema)await db.prepare(sql).run();
    const f=fixtures();for(const sql of seedStatements(f))await db.prepare(sql).run();
    const now=Math.floor(Date.now()/1000),bin=x=>Buffer.from(JSON.stringify(x)).toString('base64url');
    const partial=bin({alg:'RS256',kid:jwk.kid})+'.'+bin({iss:issuer,aud:['synthetic-connect-audience'],sub:'synthetic-staging-user',exp:now+300,nbf:now-10});
    const signature=await webcrypto.subtle.sign('RSASSA-PKCS1-v1_5',key.privateKey,new TextEncoder().encode(partial));
    const access={issuer,token:partial+'.'+Buffer.from(signature).toString('base64url')};
    const fetchImpl=(url,options)=>new URL(url).origin===fault.manifest.origin?broken.dispatchFetch(url,options):mf.dispatchFetch(url,options);
    const call=async(name,token,args={})=>{const r=await mf.dispatchFetch(main.manifest.origin+'/mcp',{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+token},body:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/call',params:{name,arguments:args}})});return {status:r.status,body:await r.json()};};
    const options={approval,base:main.manifest.origin,faultBase:fault.manifest.origin,fixtures:f,access};
    const localOptions=({revoked=false}={})=>{const o=Object.freeze({...options,revoked});transports.set(o,fetchImpl);return o;};
    return {db,fixtures:f,call,dispose,fetchImpl,localOptions,options:localOptions()};
  }catch(e){await dispose();throw e;}
}
