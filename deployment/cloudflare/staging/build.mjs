import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
export const SOURCE='c99fa809bc17e71859466ce23b5f306ed05118ff';
export const ROOT=fileURLToPath(new URL('../../../',import.meta.url));
export const NAME='shards-mcp-pr46-staging';
export const DB_NAME=NAME;
export const PROD_DB='d7ead592-e54b-4a26-b781-561f9d7da63f';
const placeholder='00000000-0000-0000-0000-000000000000';
export const hash=s=>createHash('sha256').update(s).digest('hex');
export function pinned(file){return execFileSync('git',['show',`${SOURCE}:${file}`],{cwd:ROOT,encoding:'utf8',maxBuffer:2000000});}
export function originFor(subdomain,fault=false){
  if(!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(subdomain))throw Error('INVALID_STAGING_SUBDOMAIN');
  return `https://${NAME}${fault?'-fault':''}.${subdomain}.workers.dev`;
}
export function artifact(subdomain,{fault=false}={}){
  const original=pinned('deployment/cloudflare/worker.js');
  const origin=originFor(subdomain,fault);
  const host=new URL(origin).hostname;
  // No production-file edit. Only the pinned origin/hostname and export are transformed.
  const source=original.replaceAll('mcp.shardsinc.co.uk',host).replace('export default {','const candidateWorker = {');
  const manifest={source_commit:SOURCE,source_sha256:hash(original),schema_sha256:hash(pinned('deployment/cloudflare/schema.sql')),origin,fault};
  const wrapper=`
const acceptanceManifest=${JSON.stringify(manifest)};
export default {async fetch(request,env){
  const u=new URL(request.url);
  if(u.origin!==acceptanceManifest.origin||env.STAGING_ACCEPTANCE!==acceptanceManifest.source_commit)return new Response('Staging guard denied',{status:403});
  if(u.pathname==='/_staging/manifest')return Response.json(acceptanceManifest,{headers:{'cache-control':'no-store'}});
  if(!['/mcp','/connect'].includes(u.pathname)&&!u.pathname.startsWith('/.well-known/'))return new Response('Not Found',{status:404});
  const isolated={...env};
  delete isolated.HUB_REGISTRY_AUD;
  ${fault?'delete isolated.EDGE_DB;':''}
  return candidateWorker.fetch(request,isolated);
}};
`;
  return {script:source+wrapper,manifest};
}
export function configuration(subdomain,{fault=false,databaseId=placeholder,accountId}={}){
  originFor(subdomain);
  if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(databaseId)||databaseId===PROD_DB)throw Error('INVALID_OR_PRODUCTION_DATABASE');
  if(accountId&&!/^[a-f0-9]{32}$/.test(accountId))throw Error('INVALID_ACCOUNT');
  return {name:NAME+(fault?'-fault':''),main:fault?'storage-failure.js':'worker.js',compatibility_date:'2025-06-18',
    ...(accountId?{account_id:accountId}:{}),workers_dev:true,preview_urls:false,routes:[],
    vars:{STAGING_ACCEPTANCE:SOURCE},observability:{enabled:false},
    ...(fault?{}:{d1_databases:[{binding:'EDGE_DB',database_name:DB_NAME,database_id:databaseId}]})};
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
  try{
    const args=process.argv.slice(2);const get=n=>args[args.indexOf(n)+1];
    if(!args.includes('--out')||!args.includes('--subdomain'))throw Error('Use --out work/path --subdomain NAME [--database-id UUID] [--account-id ID]');
    const out=path.resolve(get('--out'));
    if(!out.startsWith(path.join(ROOT,'work')+path.sep))throw Error('OUTPUT_MUST_BE_UNDER_REPOSITORY_WORK');
    const subdomain=get('--subdomain');
    const opts={databaseId:args.includes('--database-id')?get('--database-id'):placeholder,accountId:args.includes('--account-id')?get('--account-id'):undefined};
    const main=artifact(subdomain),fault=artifact(subdomain,{fault:true});
    const normalConfig=configuration(subdomain,opts),faultConfig=configuration(subdomain,{...opts,fault:true});
    fs.mkdirSync(out,{recursive:true,mode:0o700});
    for(const [name,body] of Object.entries({'worker.js':main.script,'storage-failure.js':fault.script,
      'schema.sql':pinned('deployment/cloudflare/schema.sql'),'wrangler.json':JSON.stringify(normalConfig,null,2),
      'wrangler-fault.json':JSON.stringify(faultConfig,null,2),'manifest.json':JSON.stringify({...main.manifest,artifact_sha256:hash(main.script),fault_artifact_sha256:hash(fault.script)},null,2)})){
      fs.writeFileSync(path.join(out,name),body,{mode:0o600});
    }
    console.log('PASS: pinned staging artifacts generated locally; nothing deployed');
  }catch{console.error('BLOCKED: invalid build options or pinned Git source unavailable');process.exitCode=2;}
}
