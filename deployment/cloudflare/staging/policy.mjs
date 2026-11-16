import {artifact,hash,NAME,DB_NAME,originFor} from './artifact.mjs';
import {ensure} from './errors.mjs';
export {ensure,GateFailure,GateBlocked} from './errors.mjs';
const uuid=s=>typeof s==='string'&&/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(s)&&!/^0{8}-0{4}-0{4}-0{4}-0{12}$/.test(s);
export function validateApproval(a){
  ensure(a&&typeof a.approval_id==='string'&&a.approval_id.length>10,'OPERATOR_APPROVAL_REQUIRED');
  ensure(['same-account-staging','separate-account-staging'].includes(a.mode),'EXPLICIT_ACCOUNT_MODE_REQUIRED');
  ensure(typeof a.account_id==='string'&&/^[a-f0-9]{32}$/.test(a.account_id)&&typeof a.account_name==='string'&&a.account_name.length>0,'EXPECTED_ACCOUNT_REQUIRED');
  ensure(uuid(a.database_id)&&a.database_name===DB_NAME&&a.jurisdiction==='eu','EXPECTED_STAGING_D1_REQUIRED');
  ensure(typeof a.subdomain==='string'&&/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(a.subdomain),'EXPECTED_SUBDOMAIN_REQUIRED');
  if(a.access!==undefined)ensure(a.access&&typeof a.access==='object'&&!Array.isArray(a.access)&&typeof a.access.team==='string'&&/^[a-z0-9-]{1,63}$/.test(a.access.team)&&['audience','connect_audience'].every(k=>typeof a.access[k]==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(a.access[k])),'EXPECTED_ACCESS_CONFIGURATION_REQUIRED');
  ensure(Array.isArray(a.workers)&&a.workers.length===2,'EXACT_WORKER_PAIR_REQUIRED');
  for(const [i,w] of a.workers.entries()){
    ensure(w&&typeof w==='object'&&!Array.isArray(w),'EXACT_WORKER_PAIR_REQUIRED');
    ensure(w.name===NAME+(i?'-fault':'')&&w.origin===originFor(a.subdomain,!!i),'EXACT_HOST_APPROVAL_REQUIRED');
    ensure(uuid(w.deployment_id)&&uuid(w.version_id)&&w.module_name==='worker.js','EXPECTED_DEPLOYMENT_VERSION_REQUIRED');
    ensure(w.artifact_sha256===hash(artifact(a.subdomain,{fault:!!i}).script),'APPROVED_ARTIFACT_DIGEST_MISMATCH');
  }
  return a;
}
export function stagingUrl(value,a,fault=false){
  validateApproval(a);const expected=a.workers[fault?1:0].origin;
  ensure(value===expected||value===expected+'/','UNAPPROVED_STAGING_HOST');
  return expected;
}
