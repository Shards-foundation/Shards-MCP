import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {SOURCE,ROOT,NAME,artifact,hash,pinned} from './artifact.mjs';
import {readProtected,writeProtectedDirectory} from './protected-file.mjs';
import {validateApproval} from './policy.mjs';
export * from './artifact.mjs';
export async function configuration(approval,{fault=false}={}){
  validateApproval(approval);
  return {name:NAME+(fault?'-fault':''),main:fault?'fault/worker.js':'main/worker.js',compatibility_date:'2025-06-18',no_bundle:true,
    account_id:approval.account_id,workers_dev:false,preview_urls:false,routes:[],
    vars:{STAGING_ACCEPTANCE:SOURCE,...(!fault&&approval.access?{ACCESS_TEAM:approval.access.team,ACCESS_AUD:approval.access.audience,CONNECT_ACCESS_AUD:approval.access.connect_audience}:{})},observability:{enabled:false},
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
    // The public example is synthetic source, never an alternate operator profile.
    const approval=JSON.parse(example?readProtected(approvalFile,{publicExample:true}):readProtected(approvalFile));
    if(example&&(approval.account_id!=='1'.repeat(32)||approval.subdomain!=='local'||approval.approval_id!=='Synthetic local test approval only'))throw Error();
    const subdomain=approval.subdomain;
    const normalConfig=await configuration(approval),faultConfig=await configuration(approval,{fault:true});
    const main=artifact(subdomain),fault=artifact(subdomain,{fault:true});
    writeProtectedDirectory(out,{'main/worker.js':main.script,'fault/worker.js':fault.script,
      'schema.sql':pinned('deployment/cloudflare/schema.sql'),'wrangler.json':JSON.stringify(normalConfig,null,2),
      'wrangler-fault.json':JSON.stringify(faultConfig,null,2),'manifest.json':JSON.stringify({...main.manifest,artifact_sha256:hash(main.script),fault_artifact_sha256:hash(fault.script)},null,2)});
    console.log('PASS: pinned staging artifacts generated locally; nothing deployed');
  }catch{console.error('BLOCKED: invalid build options or pinned Git source unavailable');process.exitCode=2;}
}
