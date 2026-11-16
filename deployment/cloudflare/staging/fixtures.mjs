import {randomBytes,createHash} from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {ROOT,SOURCE} from './build.mjs';
export function fixtures(){
  const now=new Date(),expires=new Date(now.getTime()+3600000).toISOString();
  const roles={observer:['agent:identity'],reader:['agent:identity','agent:list','message:read'],
    foreign:['agent:identity','agent:list'],revocable:['agent:identity'],expired:['agent:identity'],disabled:['agent:identity']};
  const agents=Object.entries(roles).map(([role,scopes])=>({role,id:`stage_${role}_00001`,tenant:role==='foreign'?'staging-b':'staging-a',
    scopes,token:'smcp_'+randomBytes(32).toString('base64url'),expires:role==='expired'?new Date(now.getTime()-60000).toISOString():expires}));
  return {source_commit:SOURCE,created:now.toISOString(),agents};
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
