import {randomBytes,createHash} from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {ROOT,SOURCE} from './build.mjs';
export function fixtures(){
  const now=new Date(),expires=new Date(now.getTime()+3600000).toISOString();
  const roles={observer:['agent:identity'],reader:['agent:identity','agent:list','message:read','task:read'],
    foreign:['agent:identity','agent:list','message:read','task:read'],peer:['agent:identity'],revocable:['agent:identity'],expired:['agent:identity'],disabled:['agent:identity']};
  const agents=Object.entries(roles).map(([role,scopes])=>({role,id:`stage_${role}_00001`,tenant:['foreign','peer'].includes(role)?'staging-b':'staging-a',
    scopes,token:'smcp_'+randomBytes(32).toString('base64url'),expires:role==='expired'?new Date(now.getTime()-60000).toISOString():expires}));
  return {source_commit:SOURCE,fixture_version:2,created:now.toISOString(),agents};
}
const quote=s=>"'"+String(s).replaceAll("'","''")+"'";
export function seedStatements(f){
  const statements=['PRAGMA foreign_keys=ON'];
  for(const tenant of ['staging-a','staging-b'])statements.push(`INSERT INTO tenants VALUES(${quote(tenant)},'Synthetic acceptance',${quote(f.created)})`);
  for(const a of f.agents){
    statements.push(`INSERT INTO agents(id,tenant_id,name,client,scopes,created_by,created_at,disabled_at) VALUES(${[a.id,a.tenant,a.role,'acceptance',JSON.stringify(a.scopes),'synthetic-operator',f.created].map(quote).join(',')},${a.role==='disabled'?quote(f.created):'NULL'})`);
    const digest=createHash('sha256').update(a.token).digest('hex');
    statements.push(`INSERT INTO access_tokens(id,token_sha256,agent_id,created_at,expires_at) VALUES(${['token_'+a.role,digest,a.id,f.created,a.expires].map(quote).join(',')})`);
  }
  for(const role of ['reader','foreign']){
    const owner=f.agents.find(a=>a.role===role),other=f.agents.find(a=>a.role===(role==='reader'?'observer':'peer'));
    const foreign=owner.tenant==='staging-a'?'staging-b':'staging-a';
    // Deliberately inconsistent tenant/owner canaries are schema-permitted. They
    // isolate each SQL predicate; normal globally unique IDs otherwise mask it.
    for(const [kind,tenant,recipient] of [['own',owner.tenant,owner.id],['other-agent',owner.tenant,other.id],['foreign-owner',foreign,owner.id],['foreign-other',foreign,other.id]]){
      const id=role+'_'+kind,body='synthetic '+id;
      statements.push(`INSERT INTO agent_messages(id,tenant_id,sender_id,recipient_id,body,created_at) VALUES(${[id,tenant,other.id,recipient,body,f.created].map(quote).join(',')})`);
      statements.push(`INSERT INTO agent_tasks(id,tenant_id,creator_id,assignee_id,title,input_json,state,created_at) VALUES(${[id,tenant,other.id,recipient,body,JSON.stringify({canary:id}),'queued',f.created].map(quote).join(',')})`);
      statements.push(`INSERT INTO audit_events(id,tenant_id,agent_id,action,object_id,status,created_at) VALUES(${[id,tenant,recipient,'fixture_'+kind,id,'synthetic',f.created].map(quote).join(',')})`);
    }
  }
  return statements;
}
export function revocationSql(){return "UPDATE access_tokens SET revoked_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id='token_revocable';";}
if(process.argv[1]===fileURLToPath(import.meta.url)){
  try{
    const out=path.resolve(process.argv[2]||'');
    if(!out.startsWith(path.join(ROOT,'work')+path.sep))throw Error();
    fs.mkdirSync(out,{recursive:true,mode:0o700});
    const f=fixtures();
    for(const [name,body] of Object.entries({'fixtures.json':JSON.stringify(f),'seed.sql':seedStatements(f).join(';\n')+';\n','revoke.sql':revocationSql()})){
      fs.writeFileSync(path.join(out,name),body,{mode:0o600,flag:'wx'});
    }
    console.log('PASS: synthetic fixtures created in protected files; no credentials printed');
  }catch{console.error('BLOCKED: use a new directory under work; existing fixtures are never overwritten');process.exitCode=2;}
}
