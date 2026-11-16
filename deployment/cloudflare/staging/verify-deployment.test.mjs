import test from 'node:test';
import assert from 'node:assert/strict';
import {artifact,SOURCE,pinned} from './build.mjs';
import {localApproval,runtime} from './harness.mjs';
import {verifyDeployment,moduleDigest,cloudflareReader,readProtected} from './verify-deployment.mjs';
import {GateBlocked} from './policy.mjs';
import {accept} from './acceptance.mjs';
import {fakeApi} from './api-fixture.mjs';
test('independent API proof checks both exact artifacts, bindings and 100% versions',async()=>{
  const a=localApproval();const before=await verifyDeployment(a,{read:fakeApi(a)}),after=await verifyDeployment(a,{read:fakeApi(a)});
  assert.deepEqual(before,after);assert.equal(before.account_id,a.account_id);assert.equal(before.workers.length,2);
});

test('wrong account, host, D1, deployment, traffic, binding or downloaded bytes fail closed',async()=>{
  const a=localApproval();
  const mutations=[
    [p=>p==='/accounts/'+a.account_id,x=>({...x,id:'2'.repeat(32)})],
    [p=>p.endsWith('/workers/subdomain'),x=>({...x,subdomain:'unexpected'})],
    [p=>p.includes('/d1/database/'),x=>({...x,uuid:'different-database'})],
    [p=>p.endsWith('/deployments'),x=>({...x,deployments:[{...x.deployments[0],id:'different-deployment'}]})],
    [p=>p.endsWith('/deployments'),x=>({...x,deployments:[{...x.deployments[0],versions:[{version_id:a.workers[0].version_id,percentage:50}]}]})],
    [p=>p.endsWith('/settings'),x=>({...x,bindings:[...x.bindings,{name:'PRODUCTION',type:'secret_text'}]})],
    [p=>p.endsWith('/settings')&&p.includes('-fault/'),x=>({...x,bindings:[...x.bindings,{name:'EDGE_DB',type:'d1',id:a.database_id}]})],
    [p=>p.endsWith('/settings'),x=>({...x,bindings:x.bindings.map(b=>b.type==='d1'?{...b,id:'wrong-database'}:b)})],
    [p=>p.includes('/versions/'),x=>({...x,resources:{bindings:[{name:'STAGING_ACCEPTANCE',type:'plain_text',text:'wrong'}]}})],
  ];
  for(const [where,mutate] of mutations)await assert.rejects(verifyDeployment(a,{read:fakeApi(a,{change:(p,x)=>where(p)?mutate(x):x})}));
  await assert.rejects(verifyDeployment(a,{read:fakeApi(a,{scriptChange:s=>s+'\n'})}),e=>e.message==='DEPLOYED_ARTIFACT_DIGEST_MISMATCH');
});

test('unavailable bytes are BLOCKED, disabled URLs are BLOCKED, and changing active version is FAIL',async()=>{
  const a=localApproval();
  await assert.rejects(verifyDeployment(a,{read:fakeApi(a,{missingBytes:true})}),e=>e instanceof GateBlocked&&e.message==='DEPLOYED_MODULE_BYTES_UNAVAILABLE');
  await assert.rejects(verifyDeployment(a,{read:fakeApi(a,{enabled:false})}),e=>e instanceof GateBlocked&&e.message==='STAGING_PUBLIC_URLS_DISABLED');
  let reads=0;
  await assert.rejects(verifyDeployment(a,{read:fakeApi(a,{change:(p,x)=>{
    if(p.endsWith('/deployments')&&++reads===2)x.deployments[0].versions[0].version_id='changed';return x;
  }})}),e=>e.message==='ACTIVE_DEPLOYMENT_MISMATCH');
});

test('multipart text modules are hashed without trusting etags or manifest claims',async()=>{
  const a=localApproval(),script=artifact('local').script;
  const raw='--fixture\r\nContent-Disposition: form-data; name="worker.js"\r\nContent-Type: application/javascript\r\n\r\n'+script+'\r\n--fixture--\r\n';
  assert.equal(await moduleDigest(new Response(raw,{headers:{'content-type':'multipart/form-data; boundary=fixture'}}),'worker.js'),a.workers[0].artifact_sha256);
  const form=new FormData();form.set('unexpected','untrusted');await assert.rejects(moduleDigest(new Response(form),'worker.js'));
});

test('read-only API client rejects redirects and permissions without echoing credentials',async()=>{
  for(const status of [302,403]){
    const read=cloudflareReader('synthetic-never-logged',async(url,options)=>{
      assert.equal(new URL(url).origin,'https://api.cloudflare.com');assert.equal(options.method,'GET');assert.equal(options.redirect,'manual');
      return new Response('private diagnostic',{status,headers:{location:'https://unapproved.example'}});
    });
    await assert.rejects(read('/accounts/'+'1'.repeat(32)),e=>!e.message.includes('private')&&!e.message.includes('synthetic-never'));
  }
  await assert.rejects(async()=>cloudflareReader(''));
});

test('post-acceptance deployment change invalidates the gate',async()=>{
  const r=await runtime();let proof=0;
  try{
    const report=await accept({...r.options,fetchImpl:r.fetchImpl,readCloudflare:fakeApi(r.options.approval,{change:(p,x)=>{if(p.endsWith('/accounts/'+r.options.approval.account_id)&&++proof===2)x.id='changed';return x;}})});
    assert.equal(report.results.at(-1).status,'FAIL');assert.equal(report.results.at(-1).evidence,'ACCOUNT_IDENTITY_MISMATCH');
  }finally{await r.dispose();}
});


test('missing immutable source is BLOCKED and never falls back to checkout files',()=>{
  assert.throws(()=>pinned('deliberately-missing-artifact'),e=>e instanceof GateBlocked&&e.message==='PINNED_SOURCE_UNAVAILABLE');
});
