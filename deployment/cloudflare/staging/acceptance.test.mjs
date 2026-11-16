import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {artifact,configuration,SOURCE,ROOT} from './build.mjs';
import {fixtures,revocationSql} from './fixtures.mjs';
import {accept,stagingUrl} from './acceptance.mjs';
import {GateBlocked} from './policy.mjs';
import {checkVisibility} from './visibility.mjs';
import {runtime,localApproval} from './harness.mjs';

test('exact approval is mandatory; approved same-account Free staging remains supported',async()=>{
  const a=JSON.parse(fs.readFileSync(new URL('./local-target.example.json',import.meta.url)));
  assert.equal(stagingUrl(a.workers[0].origin,a),a.workers[0].origin);
  for(const url of ['https://mcp.shardsinc.co.uk','https://portal.shardsinc.co.uk','https://shared-service.example.workers.dev',a.workers[0].origin.replace(a.subdomain,'another'),a.workers[0].origin+'/?redirect=production'])assert.throws(()=>stagingUrl(url,a));
  await assert.rejects(configuration());
  await assert.rejects(configuration({...a,account_id:undefined}));
  await assert.rejects(configuration({...a,database_id:'00000000-0000-0000-0000-000000000000'}));
  const c=await configuration(a);assert.equal(c.account_id,a.account_id);assert.equal(c.workers_dev,false);assert.deepEqual(c.routes,[]);
  assert.equal(c.d1_databases[0].database_id,a.database_id);assert.equal((await configuration(a,{fault:true})).d1_databases,undefined);
});

test('real workerd/D1 matrix and parallel post-revocation denial; hosted identity stays BLOCKED locally',async()=>{
  const r=await runtime();
  try{
    for(const revoked of [false,true]){
      if(revoked)await r.db.prepare(revocationSql()).run();
      const report=await accept({...r.options,revoked});console.log(JSON.stringify(report));
      assert.equal(report.results.length,14);
      assert.equal(report.results.filter(x=>x.status==='FAIL').length,0,'Local acceptance failure');
      assert.equal(report.results.filter(x=>x.status==='BLOCKED'&&x.evidence==='LOCAL_WORKERD_NOT_HOSTED').length,2);
      assert.equal(report.results.filter(x=>x.status==='PASS').length,11);
      assert.equal(report.results.find(x=>x.case==='empty Authorization transport boundary').evidence,'LOCAL_ADAPTER_DROPS_EMPTY_AUTHORIZATION');
    }
  }finally{await r.dispose();}
});

for(const [tool,owner,key] of [['shards_message_inbox','recipient_id','messages'],['shards_task_inbox','assignee_id','tasks'],['shards_audit_tail','agent_id','events']]){
  for(const predicate of ['tenant','owner'])test('mutation is killed: '+tool+' without '+predicate+' predicate',async()=>{
    const mutate=s=>{const line=s.split('\n').find(l=>l.startsWith("if(name==='"+tool+"')"));assert.ok(line,'Pinned SQL branch must be found');
      const altered=predicate==='tenant'?line.replace('tenant_id=? AND ','').replace('.bind(actor.tenant_id,actor.id)','.bind(actor.id)'):line.replace(' AND '+owner+'=?','').replace('.bind(actor.tenant_id,actor.id)','.bind(actor.tenant_id)');
      assert.notEqual(altered,line);return s.replace(line,altered);};
    const r=await runtime({mutate});
    try{await assert.rejects(checkVisibility(r.call,r.fixtures),e=>e.message==='ROW_ISOLATION_'+key.toUpperCase());}
    finally{await r.dispose();}
  });
}

test('independent preflight failure or unavailable bytes stops all Worker requests',async()=>{
  for(const blocked of [false,true]){
    let requests=0;
    const report=await accept({approval:localApproval(),base:localApproval().workers[0].origin,fixtures:fixtures(),fetchImpl:async()=>{requests++;throw Error();},verifyIdentity:async()=>{if(blocked)throw new GateBlocked('DEPLOYED_MODULE_BYTES_UNAVAILABLE');throw Error('private simulated diagnostic');}});
    assert.equal(requests,0);assert.equal(report.results[0].status,blocked?'BLOCKED':'FAIL');
    assert.equal(JSON.stringify(report).includes('private simulated diagnostic'),false);
  }
});

test('a forged or redirected manifest cannot override verification or leak a token',async()=>{
  for(const response of [()=>Response.json({source_commit:'wrong'}),()=>new Response(null,{status:302,headers:{location:'https://unapproved.example'}})]){
    let requests=0;const f=fixtures(),a=localApproval();
    const report=await accept({approval:a,base:a.workers[0].origin,fixtures:f,localRuntime:true,fetchImpl:async(url,options)=>{requests++;assert.equal(new Headers(options.headers).has('authorization'),false);assert.equal(options.redirect,'manual');return response();}});
    assert.equal(requests,1);assert.equal(report.results.at(-1).status,'FAIL');
    assert.equal(f.agents.some(a=>JSON.stringify(report).includes(a.token)),false);
  }
});

test('wrong denial reason is a failure even with isError true and valid forbidden arguments',async()=>{
  const r=await runtime();
  try{
    const original=r.options.fetchImpl;
    const fetchImpl=async(url,opts)=>{
      const body=opts?.body?JSON.parse(opts.body):{};
      if(body.params?.name==='shards_task_create'){
        assert.ok(body.params.arguments.title);assert.ok(body.params.arguments.input);assert.ok(body.params.arguments.request_id);
        return Response.json({result:{isError:true,content:[{type:'text',text:'Invalid arguments'}]}});
      }
      return original(url,opts);
    };
    const report=await accept({...r.options,fetchImpl});
    assert.equal(report.results.find(x=>x.case==='/connect signed identity and no agent privilege').status,'FAIL');
    assert.equal(report.results.find(x=>x.case==='scope and tenant isolation on calls').status,'FAIL');
  }finally{await r.dispose();}
});

test('root work ignore covers exclusive synthetic token fixture files',()=>{
  fs.mkdirSync(path.join(ROOT,'work'),{recursive:true});const dir=fs.mkdtempSync(path.join(ROOT,'work','ignore-fixture-'));
  try{
    execFileSync(process.execPath,['deployment/cloudflare/staging/fixtures.mjs',dir],{cwd:ROOT,stdio:'pipe'});
    const file=path.join(dir,'fixtures.json');assert.equal(fs.statSync(file).mode&0o077,0);
    const relative=path.relative(ROOT,file);const ignored=execFileSync('git',['check-ignore','--no-index',relative],{cwd:ROOT,encoding:'utf8'}).trim();assert.equal(ignored,relative);
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
});


test('independent echo runtime confirms empty Authorization cannot be exercised by the local adapter',async()=>{
  const {Miniflare}=await import('miniflare');
  const mf=new Miniflare({modules:true,script:'export default {fetch(request){return Response.json({present:request.headers.has("authorization")})}}'});
  try{const r=await mf.dispatchFetch('https://local.test',{headers:{authorization:''}});assert.equal((await r.json()).present,false);}
  finally{await mf.dispose();}
});


test('builder CLI requires explicit approval and writes disabled configs with expected artifact bytes',()=>{
  const dir=fs.mkdtempSync(path.join(ROOT,'work','builder-proof-'));
  try{
    assert.throws(()=>execFileSync(process.execPath,['deployment/cloudflare/staging/build.mjs','--out',dir],{cwd:ROOT,stdio:'pipe'}));
    execFileSync(process.execPath,['deployment/cloudflare/staging/build.mjs','--out',dir,'--approval','deployment/cloudflare/staging/local-target.example.json'],{cwd:ROOT,stdio:'pipe'});
    const c=JSON.parse(fs.readFileSync(path.join(dir,'wrangler.json')));assert.equal(c.workers_dev,false);assert.equal(c.account_id,'1'.repeat(32));
    assert.equal(fs.readFileSync(path.join(dir,'worker.js'),'utf8'),artifact('local').script);
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
