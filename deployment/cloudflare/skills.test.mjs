import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
const source=fs.readFileSync(new URL('./worker.js',import.meta.url),'utf8');
const sandbox={Request,Response,Headers,URL,TextEncoder,TextDecoder,atob,btoa,crypto:webcrypto,AbortSignal,fetch:async()=>{throw Error('Network call unexpectedly attempted')}};
vm.runInNewContext(source.replace('export default {','globalThis.__edge = {'),sandbox,{filename:'worker.js'});
const worker=sandbox.__edge,base='https://mcp.shardsinc.co.uk';

test('Skills UI has file upload, GitHub import and Shards Explore with a parseable client',async()=>{
 const page=await worker.fetch(new Request(base+'/manage/settings'),{});
 assert.equal(page.status,200);
 const html=await page.text();
 for(const label of ['data-tab="skills"','skillUploadForm','skillImportForm','skillsExploreList','skillsMyList','Shards Foundation Skills'])assert.ok(html.includes(label),label);
 assert.match(page.headers.get('content-security-policy'),/script-src 'self'/);
 const client=await worker.fetch(new Request(base+'/manage/skills.js'),{});
 assert.equal(client.status,200);
 const js=await client.text();assert.doesNotThrow(()=>new vm.Script(js));
 assert.match(js,/credentials:'same-origin'/);
 assert.match(js,/textContent/);
 assert.doesNotMatch(js,/\.innerHTML\s*=/);
});

test('operator skill registry requires cryptographic Access identity, persists scoped Markdown, and securely imports public SKILL.md',async()=>{
 const pair=await webcrypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
 const jwk=await webcrypto.subtle.exportKey('jwk',pair.publicKey);jwk.kid='skills-key';
 const b64=o=>Buffer.from(JSON.stringify(o)).toString('base64url');
 const now=Math.floor(Date.now()/1000);
 const jwt=async(sub='skill-user',aud='operator-audience')=>{
  const header=b64({alg:'RS256',kid:jwk.kid}),payload=b64({iss:'https://skill-test.cloudflareaccess.com',aud:[aud],sub,email:'operator@example.test',nbf:now-5,exp:now+1800});
  const part=header+'.'+payload,sig=await webcrypto.subtle.sign('RSASSA-PKCS1-v1_5',pair.privateKey,new TextEncoder().encode(part));
  return part+'.'+Buffer.from(sig).toString('base64url');
 };
 const records={accounts:[],skills:[],audits:[]};
 let changed=0;
 const db={
  prepare(sql){return {bind(...args){return {
   async first(){
    if(sql.includes('FROM operator_accounts WHERE id=?'))return records.accounts.find(a=>a.id===args[0])||null;
    if(sql.includes('FROM operator_skills WHERE owner_id=? AND id=?'))return records.skills.find(s=>s.owner_id===args[0]&&s.id===args[1])||null;
    throw Error('Unknown SQL first: '+sql);
   },
   async all(){
    if(sql.includes('FROM operator_skills WHERE owner_id=?'))return {results:records.skills.filter(s=>s.owner_id===args[0])};
    throw Error('Unknown SQL all: '+sql);
   },
   async run(){
    if(sql.startsWith('INSERT OR IGNORE INTO operator_accounts')){
     if(!records.accounts.some(a=>a.id===args[0]))records.accounts.push({id:args[0],email:args[1],created_at:args[2],updated_at:args[3],deleted_at:null});
     return {meta:{changes:1}};
    }
    if(sql.startsWith('INSERT OR IGNORE INTO operator_skills')){
     assert.match(sql,/NOT NULL|deleted_at IS NULL/,'Creation must test tombstone atomically');
     assert.match(sql,/COUNT\(\*\) FROM operator_skills/,'Enforce 100-skill limit in SQL insert');
     const [id,owner_id,name,description,category,source_type,source_url,content,content_sha256,created_at]=args;
     if(!records.accounts.some(a=>a.id===owner_id&&!a.deleted_at)||records.skills.length>=100||records.skills.some(s=>s.owner_id===owner_id&&source_url!==null&&s.source_url===source_url))return {meta:{changes:0}};
     records.skills.push({id,owner_id,name,description,category,source_type,source_url,content,content_sha256,created_at});return {meta:{changes:1}};
    }
    if(sql.startsWith('DELETE FROM operator_skills')){
     const i=records.skills.findIndex(s=>s.owner_id===args[0]&&s.id===args[1]);if(i>=0)records.skills.splice(i,1);return {meta:{changes:i>=0?1:0}};
    }
    if(sql.startsWith('INSERT INTO audit_events')){
     if(sql.includes('WHERE changes()=1')&&changed!==1)return {meta:{changes:0}};
     records.audits.push(args);return {meta:{changes:1}};
    }
    throw Error('Unknown SQL run: '+sql);
   }
  }},async first(){throw Error('Bind required')},async all(){throw Error('Bind required')}}},
  async batch(stmts){const saved=JSON.stringify(records),output=[];try{for(const stmt of stmts){const r=await stmt.run();changed=r?.meta?.changes??0;output.push(r)}return output}catch(e){Object.assign(records,JSON.parse(saved));throw e}}
 };
 const env={ACCESS_TEAM:'skill-test',ACCESS_AUD:'operator-audience',CONNECT_ACCESS_AUD:'connect-audience',EDGE_DB:db};
 const original=sandbox.fetch;
 const catalogue={skills:[{name:'example',path:'skills/agent-system-design',category:'engineering',description:'Example skill',status:'review'}]};
 const remote='---\nname: sample-github-skill\ndescription: Imported from a public GitHub repository\n---\n# Instructions\nRead and review only.\n';
 let fetched=0;
 sandbox.fetch=async url=>{
  url=String(url);
  if(url==='https://skill-test.cloudflareaccess.com/cdn-cgi/access/certs')return {ok:true,json:async()=>({keys:[jwk]})};
  if(url==='https://raw.githubusercontent.com/Shards-foundation/shards-skills/main/catalogue/catalogue.json')return new Response(JSON.stringify(catalogue),{status:200});
  if(url==='https://raw.githubusercontent.com/Shards-foundation/shards-skills/main/skills/agent-system-design/SKILL.md'){fetched++;return new Response(remote,{status:200})}
  throw Error('Unexpected URL: '+url);
 };
 const req=(suffix,method,token,body,origin=base)=>{
  const headers={'cf-access-jwt-assertion':token||''};
  if(body!==undefined){headers.origin=origin;headers['content-type']='application/json'}
  return new Request(base+'/manage/api/skills'+suffix,{method,headers,body:body===undefined?undefined:JSON.stringify(body)});
 };
 const good=await jwt(),other=await jwt('other-operator'),wrongAud=await jwt('skill-user','connect-audience');
 try{
  let resp=await worker.fetch(req('','GET',null),env);assert.equal(resp.status,401);
  resp=await worker.fetch(req('','GET',wrongAud),env);assert.equal(resp.status,401);
  resp=await worker.fetch(req('','GET',good),env);assert.equal(resp.status,200);assert.equal((await resp.json()).skills.length,0);
  resp=await worker.fetch(req('','POST',good,{name:'Personal skill',content:'# Example\nTest this real account-controlled Markdown skill.'},'https://evil.example'),env);assert.equal(resp.status,403);
  resp=await worker.fetch(req('','POST',good,{name:'Personal skill',description:'Upload',content:'# Example\nTest this real account-controlled Markdown skill.'}),env);
  assert.equal(resp.status,201);const uploaded=(await resp.json()).skill;
  assert.equal(records.skills.length,1);assert.equal(records.skills[0].content_sha256.length,64);
  resp=await worker.fetch(req('','GET',other),env);assert.equal((await resp.json()).skills.length,0,'Other user must not enumerate skill');
  resp=await worker.fetch(req('/'+uploaded.id,'GET',other),env);assert.equal(resp.status,404);
  resp=await worker.fetch(req('/'+uploaded.id,'GET',good),env);assert.equal((await resp.json()).skill.content,records.skills[0].content);
  resp=await worker.fetch(req('/catalog?q=example','GET',good),env);assert.equal(resp.status,200);
  const found=await resp.json();assert.equal(found.total,1);assert.equal(found.items[0].name,'example');
  resp=await worker.fetch(req('/import','POST',good,{url:'https://evil.example/attack/SKILL.md'}),env);assert.equal(resp.status,400);
  resp=await worker.fetch(req('/import','POST',good,{url:'https://github.com/Shards-foundation/shards-skills/blob/main/skills/agent-system-design/SKILL.md'}),env);
  assert.equal(resp.status,201);const imported=await resp.json();assert.equal(imported.skill.source_type,'github');assert.equal(fetched,1);
  resp=await worker.fetch(req('/import','POST',good,{url:imported.skill.source_url}),env);assert.equal(resp.status,409,'Duplicate import must not create a second record');
  assert.equal(records.skills.length,2);
  resp=await worker.fetch(req('/'+uploaded.id,'DELETE',other),env);assert.equal(resp.status,200);assert.equal((await resp.json()).deleted,false);
  assert.equal(records.skills.length,2,'Cross-owner removal must do nothing');
  resp=await worker.fetch(req('/'+uploaded.id,'DELETE',good),env);assert.equal(resp.status,200);assert.equal((await resp.json()).deleted,true);
  assert.equal(records.skills.length,1);
  records.accounts[0].deleted_at=new Date().toISOString();
  resp=await worker.fetch(req('','GET',good),env);assert.equal(resp.status,410,'Account tombstone blocks skill access');
 }finally{sandbox.fetch=original}
});

test('Skills D1 migration matches fresh schema and account deletion includes skill removal',()=>{
 const migration=fs.readFileSync(new URL('./migrations/0003_operator_skills.sql',import.meta.url),'utf8');
 const schema=fs.readFileSync(new URL('./schema.sql',import.meta.url),'utf8');
 const start='CREATE TABLE IF NOT EXISTS operator_skills';
 assert.equal(schema.slice(schema.indexOf(start)).trim(),migration.slice(migration.indexOf(start)).trim());
 assert.match(source,/DELETE FROM operator_skills WHERE owner_id=\?/);
 assert.match(migration,/UNIQUE\(owner_id,source_url\)/);
 assert.match(migration,/CHECK\(length\(content\) BETWEEN 20 AND 65000\)/);
});
