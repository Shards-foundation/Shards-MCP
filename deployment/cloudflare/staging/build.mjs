import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {SOURCE,ROOT,NAME,artifact,hash,pinned} from './artifact.mjs';
import {readProtected} from './protected-file.mjs';
import {validateApproval} from './policy.mjs';
export * from './artifact.mjs';
export async function configuration(approval,{fault=false}={}){
  validateApproval(approval);
  return {name:NAME+(fault?'-fault':''),main:fault?'fault/worker.js':'main/worker.js',compatibility_date:'2025-06-18',no_bundle:true,
    account_id:approval.account_id,workers_dev:false,preview_urls:false,routes:[],
    vars:{STAGING_ACCEPTANCE:SOURCE},observability:{enabled:false},
    ...(fault?{}:{d1_databases:[{binding:'EDGE_DB',database_name:approval.database_name,database_id:approval.database_id}]})};
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
  try{
    const args=process.argv.slice(2);const get=n=>args[args.indexOf(n)+1];
    if(!args.includes('--out')||!args.includes('--approval'))throw Error('Use --out work/path --approval operator-approved.json');
    const out=path.resolve(get('--out'));
    if(!out.startsWith(path.join(ROOT,'work')+path.sep))throw Error('OUTPUT_MUST_BE_UNDER_REPOSITORY_WORK');
    const approvalFile=get('--approval');
    const example=path.resolve(approvalFile)===fileURLToPath(new URL('./local-target.example.json',import.meta.url));
    const approval=JSON.parse(example?fs.readFileSync(approvalFile,'utf8'):readProtected(approvalFile));
    const subdomain=approval.subdomain;
    const normalConfig=await configuration(approval),faultConfig=await configuration(approval,{fault:true});
    const main=artifact(subdomain),fault=artifact(subdomain,{fault:true});
    fs.mkdirSync(out,{recursive:true,mode:0o700});
    fs.mkdirSync(path.join(out,'main'),{recursive:true,mode:0o700});
    fs.mkdirSync(path.join(out,'fault'),{recursive:true,mode:0o700});
    for(const [name,body] of Object.entries({'main/worker.js':main.script,'fault/worker.js':fault.script,
      'schema.sql':pinned('deployment/cloudflare/schema.sql'),'wrangler.json':JSON.stringify(normalConfig,null,2),
      'wrangler-fault.json':JSON.stringify(faultConfig,null,2),'manifest.json':JSON.stringify({...main.manifest,artifact_sha256:hash(main.script),fault_artifact_sha256:hash(fault.script)},null,2)})){
      fs.writeFileSync(path.join(out,name),body,{mode:0o600});
    }
    console.log('PASS: pinned staging artifacts generated locally; nothing deployed');
  }catch{console.error('BLOCKED: invalid build options or pinned Git source unavailable');process.exitCode=2;}
}
