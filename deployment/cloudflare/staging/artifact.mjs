import {GateBlocked} from './errors.mjs';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
export const SOURCE='c99fa809bc17e71859466ce23b5f306ed05118ff';
export const ROOT=fileURLToPath(new URL('../../../',import.meta.url));
export const NAME='shards-mcp-pr46-staging';
export const DB_NAME=NAME;
export const hash=s=>createHash('sha256').update(s).digest('hex');
export function pinned(file){try{return execFileSync('git',['show',`${SOURCE}:${file}`],{cwd:ROOT,encoding:'utf8',maxBuffer:2000000,stdio:['ignore','pipe','pipe']});}catch{throw new GateBlocked('PINNED_SOURCE_UNAVAILABLE');}}
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
