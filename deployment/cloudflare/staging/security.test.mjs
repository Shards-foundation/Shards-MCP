import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {spawnSync} from 'node:child_process';
import {ROOT,configuration} from './build.mjs';
import {readProtected,writeProtectedDirectory,writeReceipt,reserveReceipt} from './protected-file.mjs';
import {GateBlocked,GateFailure,validateApproval} from './policy.mjs';
import {accept} from './acceptance.mjs';
import {cloudflareReader,moduleDigest,verifyDeployment} from './verify-deployment.mjs';
import {localApproval,runtime} from './harness.mjs';
import {fixtures} from './fixtures.mjs';
import {fakeApi} from './api-fixture.mjs';
fs.mkdirSync(path.join(ROOT,'work'),{recursive:true,mode:0o700});
const scratch=()=>fs.mkdtempSync(path.join(ROOT,'work','security-'));
const cli=(script,args,env={})=>spawnSync(process.execPath,['deployment/cloudflare/staging/'+script,...args],{cwd:ROOT,encoding:'utf8',env:{...process.env,...env}});
const interrupted=kind=>{let first=true;return new Response(new ReadableStream({pull(c){if(first){first=false;c.enqueue(new TextEncoder().encode('partial'));}else c.error(kind==='abort'?new DOMException('private token diagnostic','AbortError'):Error('private token diagnostic'));}}),{headers:{'content-type':'multipart/form-data; boundary=test'}});};

test('body reset and abort after headers are BLOCKED in acceptance, API reader and module download',async()=>{
  for(const kind of ['reset','abort']){
    const a=localApproval(),f=fixtures();let requests=0;
    const r=await accept({approval:a,base:a.workers[0].origin,fixtures:f,readCloudflare:fakeApi(a),fetchImpl:async()=>{requests++;return interrupted(kind);}});
    assert.equal(requests,1);assert.deepEqual(r.results.at(-1),{case:'supplementary worker manifest',status:'BLOCKED',evidence:'TRANSPORT_UNAVAILABLE'});
    assert.ok(!JSON.stringify(r).includes('private'));
    const check=e=>e instanceof GateBlocked&&e.message==='CLOUDFLARE_READ_UNAVAILABLE';
    await assert.rejects(cloudflareReader('synthetic',async()=>interrupted(kind))('/accounts/fixture'),check);
    await assert.rejects(moduleDigest(interrupted(kind),'worker.js'),check);
  }
});

test('size-limit assertions survive cancellation errors; bad complete content remains FAIL',async()=>{
  const oversized=n=>new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array(n));},cancel(){throw Error('private cancel');}}));
  const a=localApproval(),f=fixtures();
  const r=await accept({approval:a,base:a.workers[0].origin,fixtures:f,readCloudflare:fakeApi(a),fetchImpl:async()=>oversized(32001)});
  assert.equal(r.results.at(-1).status,'FAIL');assert.equal(r.results.at(-1).evidence,'RESPONSE_LIMIT');
  await assert.rejects(cloudflareReader('synthetic',async()=>oversized(3000001))('/accounts/fixture'),e=>e instanceof GateBlocked&&e.message==='CLOUDFLARE_RESPONSE_LIMIT');
  const bad=await accept({approval:a,base:a.workers[0].origin,fixtures:f,readCloudflare:fakeApi(a),fetchImpl:async()=>new Response('{malformed')});
  assert.equal(bad.results.at(-1).status,'FAIL');
});

test('public localRuntime and verifier overrides cannot bypass independent verification',async()=>{
  const a=localApproval();let calls=0;const fetchImpl=async()=>{calls++;throw Error();};
  for(const bypass of [{localRuntime:true},{verifyIdentity:async()=>true}])await assert.rejects(accept({approval:a,base:a.workers[0].origin,fixtures:fixtures(),fetchImpl,...bypass}),e=>e instanceof GateFailure&&e.message==='UNSUPPORTED_IDENTITY_BYPASS');
  const report=await accept({approval:a,base:a.workers[0].origin,fixtures:fixtures(),fetchImpl,readCloudflare:async()=>{throw new GateBlocked('CLOUDFLARE_READ_UNAVAILABLE');}});
  assert.equal(calls,0);assert.equal(report.results[0].status,'BLOCKED');
});

test('malformed approval shapes consistently raise typed policy failures',()=>{
  for(const mutate of [a=>{a.subdomain=null;},a=>{a.subdomain=['local'];},a=>{a.subdomain={toString(){throw Error('coercion');}};},a=>{a.workers[0]=null;},a=>{a.workers[1]=[];},a=>{a.workers=[undefined,undefined];},a=>{a.access={team:[],audience:'a',connect_audience:'b'};}]){
    const a=localApproval();mutate(a);assert.throws(()=>validateApproval(a),e=>e instanceof GateFailure);
  }
});

test('approved optional Access bindings remain exact and default profiles reject extra Access bindings',async()=>{
  const a={...localApproval(),access:{team:'synthetic-staging',audience:'synthetic-aud',connect_audience:'synthetic-connect'}};
  const config=await configuration(a);assert.equal(config.vars.ACCESS_TEAM,a.access.team);assert.equal(config.vars.CONNECT_ACCESS_AUD,a.access.connect_audience);
  assert.equal((await configuration(a,{fault:true})).vars.ACCESS_TEAM,undefined);
  await verifyDeployment(a,{read:fakeApi(a)});
  for(const mode of ['wrong','missing','extra','secret'])await assert.rejects(verifyDeployment(a,{read:fakeApi(a,{change:(p,x)=>{
    if(p.endsWith('/settings')&&!p.includes('-fault/')){
      if(mode==='missing')x.bindings=x.bindings.filter(b=>b.name!=='ACCESS_AUD');
      if(mode==='extra')x.bindings.push({name:'UNAPPROVED',type:'plain_text',text:'value'});
      if(mode==='wrong')x.bindings.find(b=>b.name==='ACCESS_AUD').text='other';
      if(mode==='secret')x.bindings.find(b=>b.name==='ACCESS_AUD').type='secret_text';
    }return x;
  }})}),e=>e instanceof GateFailure);
  const original=localApproval();await assert.rejects(verifyDeployment(original,{read:fakeApi(original,{change:(p,x)=>{if(p.endsWith('/settings'))x.bindings.push({name:'ACCESS_TEAM',type:'plain_text',text:'unexpected'});return x;}})}),e=>e.message==='BINDING_SET_MISMATCH');
});

test('expired or nearly expired revocable fixtures cannot earn a revocation PASS',async()=>{
  const r=await runtime();try{
    // No revocation: the old runner falsely accepted expiry's 401 as revocation.
    for(const delta of [-1000,1000]){
      const expires=new Date(Date.now()+delta).toISOString();
      r.fixtures.agents.find(a=>a.role==='revocable').expires=expires;
      await r.db.prepare("UPDATE access_tokens SET expires_at=? WHERE id='token_revocable'").bind(expires).run();
      const report=await accept(r.localOptions({revoked:true})),row=report.results.find(x=>x.case==='revocation denies subsequent requests');
      assert.equal(row.status,'BLOCKED');assert.equal(row.evidence,'REVOCABLE_FIXTURE_EXPIRING_OR_EXPIRED');
    }
    const live=r.fixtures.agents.find(a=>a.role==='revocable');live.expires=new Date(Date.now()+3600000).toISOString();
    const report=await accept({...r.options,revoked:true,readCloudflare:fakeApi(r.options.approval),fetchImpl:async(url,opts)=>{const response=await r.fetchImpl(url,opts);if(new Headers(opts?.headers).get('authorization')==='Bearer '+live.token)live.expires=new Date(Date.now()-1000).toISOString();return response;}});
    assert.equal(report.results.find(x=>x.case==='revocation denies subsequent requests').evidence,'REVOCABLE_FIXTURE_EXPIRING_OR_EXPIRED');
  }finally{await r.dispose();}
  assert.equal(Date.parse(fixtures().agents[0].expires)-Date.parse(fixtures().created)>7199000,true);
  for(const lifetimeMinutes of [0,29,241,Infinity,'120'])assert.throws(()=>fixtures({lifetimeMinutes}));
});

test('protected reader uses validated descriptor despite a final-path swap',()=>{
  const dir=scratch(),file=path.join(dir,'approval.json'),other=path.join(dir,'other');const original=fs.fstatSync;
  try{
    fs.writeFileSync(file,'approved',{mode:0o600});fs.writeFileSync(other,'unapproved',{mode:0o600});let swapped=false;
    fs.fstatSync=function(fd,...args){const st=original(fd,...args);if(st.isFile()&&!swapped){swapped=true;fs.renameSync(file,file+'.old');fs.symlinkSync(other,file);}return st;};
    // Rename changes ctime on some filesystems: either read the validated bytes
    // or fail closed; the replacement must never be consumed.
    try{assert.equal(readProtected(file),'approved');}catch(e){assert.ok(e instanceof GateFailure&&e.message==='PROTECTED_FILE_CHANGED');}
    assert.equal(swapped,true);
  }finally{fs.fstatSync=original;fs.rmSync(dir,{recursive:true,force:true});}
});

test('protected reader rejects symlinks, hardlinks, public files and missing files with stable evidence',()=>{
  const dir=scratch();try{
    const file=path.join(dir,'private');fs.writeFileSync(file,'synthetic',{mode:0o600});assert.equal(readProtected(file),'synthetic');
    fs.symlinkSync(file,path.join(dir,'link'));assert.throws(()=>readProtected(path.join(dir,'link')),e=>e instanceof GateBlocked);
    fs.symlinkSync(dir,path.join(dir,'ancestor'));assert.throws(()=>readProtected(path.join(dir,'ancestor','private')),e=>e instanceof GateBlocked);
    fs.linkSync(file,path.join(dir,'hard'));assert.throws(()=>readProtected(file),e=>e instanceof GateFailure);fs.unlinkSync(path.join(dir,'hard'));
    fs.chmodSync(file,0o644);assert.throws(()=>readProtected(file),e=>e instanceof GateFailure&&e.message==='PROTECTED_FILE_PERMISSIONS');
    assert.throws(()=>readProtected(path.join(dir,'missing')),e=>e instanceof GateBlocked&&e.message==='PROTECTED_FILE_UNAVAILABLE');
    const receipt=path.join(dir,'missing-receipt.json'),r=cli('verify-deployment.mjs',['--receipt',receipt],{STAGING_APPROVAL_FILE:path.join(dir,'missing')});
    assert.equal(r.status,2);assert.deepEqual(JSON.parse(readProtected(receipt)),{status:'BLOCKED',evidence:'PROTECTED_FILE_UNAVAILABLE'});
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test('in-place read mutation and injected filesystem denial fail closed without diagnostics',()=>{
  const dir=scratch(),file=path.join(dir,'private'),read=fs.readSync,open=fs.openSync;
  try{
    fs.writeFileSync(file,'original',{mode:0o600});let once=false;
    fs.readSync=function(...args){if(!once){once=true;fs.appendFileSync(file,'changed');}return read(...args);};
    assert.throws(()=>readProtected(file),e=>e instanceof GateFailure&&e.message==='PROTECTED_FILE_CHANGED');fs.readSync=read;
    fs.openSync=()=>{throw Object.assign(Error('sensitive path'),{code:'EACCES'});};
    assert.throws(()=>readProtected(file),e=>e instanceof GateBlocked&&e.message==='PROTECTED_FILE_UNAVAILABLE');
  }finally{fs.readSync=read;fs.openSync=open;fs.rmSync(dir,{recursive:true,force:true});}
});

test('fixture and builder CLIs reject ancestor/final symlinks and existing public output without writing outside work',()=>{
  const dir=scratch(),outside=fs.mkdtempSync(path.join(os.tmpdir(),'shards-synthetic-'));
  try{
    fs.symlinkSync(outside,path.join(dir,'escape'));const existing=path.join(dir,'existing');fs.mkdirSync(existing,{mode:0o755});fs.writeFileSync(path.join(existing,'wrangler.json'),'unchanged',{mode:0o644});fs.chmodSync(existing,0o755);fs.chmodSync(path.join(existing,'wrangler.json'),0o644);
    for(const target of [path.join(dir,'escape','new'),path.join(dir,'escape'),existing])for(const script of ['fixtures.mjs','build.mjs']){
      const args=script==='fixtures.mjs'?[target]:['--out',target,'--approval','deployment/cloudflare/staging/local-target.example.json'];
      const r=cli(script,args);assert.equal(r.status,2);assert.ok(!r.stdout.includes('smcp_'));
    }
    assert.deepEqual(fs.readdirSync(outside),[]);assert.equal(fs.readFileSync(path.join(existing,'wrangler.json'),'utf8'),'unchanged');
    const out=path.join(dir,'fresh');writeProtectedDirectory(out,{'secret.json':'synthetic'});assert.equal(fs.statSync(out).mode&0o777,0o700);assert.equal(fs.statSync(path.join(out,'secret.json')).mode&0o777,0o600);
    assert.throws(()=>writeProtectedDirectory(out,{'secret.json':'overwrite'}));
    assert.throws(()=>writeProtectedDirectory(outside,{'secret.json':'synthetic'}));
  }finally{fs.rmSync(dir,{recursive:true,force:true});fs.rmSync(outside,{recursive:true,force:true});}
});

test('output ancestor replacement cannot redirect descriptor-relative writes',()=>{
  const dir=scratch(),outside=fs.mkdtempSync(path.join(os.tmpdir(),'shards-synthetic-')),mkdir=fs.mkdirSync;let swapped=false;
  try{
    const parent=path.join(dir,'parent');fs.mkdirSync(parent,{mode:0o700});
    fs.mkdirSync=function(p,...args){if(String(p).endsWith('/new')&&!swapped){swapped=true;fs.renameSync(parent,parent+'.old');fs.symlinkSync(outside,parent);}return mkdir(p,...args);};
    writeProtectedDirectory(path.join(parent,'new'),{'synthetic.json':'safe'});
    assert.equal(swapped,true);assert.deepEqual(fs.readdirSync(outside),[]);assert.equal(fs.readFileSync(path.join(parent+'.old','new','synthetic.json'),'utf8'),'safe');
  }finally{fs.mkdirSync=mkdir;fs.rmSync(dir,{recursive:true,force:true});fs.rmSync(outside,{recursive:true,force:true});}
});

test('receipt files are exclusive, protected and confined to work, regardless of umask',()=>{
  const dir=scratch(),old=process.umask(0);try{
    const file=path.join(dir,'receipt.json');writeReceipt(file,{status:'BLOCKED'});assert.equal(fs.statSync(file).mode&0o777,0o600);
    assert.throws(()=>writeReceipt(file,{status:'PASS'}));
    const reserved=path.join(dir,'reserved.json'),target=path.join(dir,'target.json'),complete=reserveReceipt(reserved);fs.writeFileSync(target,'unchanged',{mode:0o600});fs.renameSync(reserved,reserved+'.old');fs.symlinkSync(target,reserved);complete({status:'BLOCKED'});
    assert.equal(fs.readFileSync(target,'utf8'),'unchanged');assert.equal(JSON.parse(readProtected(reserved+'.old')).status,'BLOCKED');assert.throws(()=>complete({status:'PASS'}));
    fs.symlinkSync(dir,path.join(dir,'link'));assert.throws(()=>writeReceipt(path.join(dir,'link','escape.json'),{}));
    assert.throws(()=>writeReceipt(path.join(ROOT,'receipt.json'),{}));assert.ok(!fs.existsSync(path.join(ROOT,'receipt.json')));
  }finally{process.umask(old);fs.rmSync(dir,{recursive:true,force:true});}
});

test('documented commands use python3, protected receipts and verified pin digests',()=>{
  const doc=fs.readFileSync(new URL('./README.md',import.meta.url),'utf8');
  assert.equal(/^python /m.test(doc),false);assert.equal(/\.mjs(?: --revoked)? > work\//.test(doc),false);
  const pin=doc.match(/python3 - <<'PIN'\n([\s\S]*?)\nPIN/);assert.ok(pin);
  const checked=spawnSync('python3',['-c',pin[1]],{cwd:ROOT,encoding:'utf8'});assert.equal(checked.status,0,checked.stderr);assert.match(checked.stdout,/both pinned source digests match/);
  const wrong=spawnSync('python3',['-c',pin[1].replace('7a19a15a','00000000')],{cwd:ROOT,encoding:'utf8'});assert.equal(wrong.status,1);assert.match(wrong.stderr,/digest mismatch/);
});

test('clean checkout work creation is private; symlinked or public work roots are refused',async()=>{
  const dir=scratch(),root=path.join(dir,'isolated');fs.mkdirSync(root,{mode:0o700});
  try{
    fs.writeFileSync(path.join(root,'artifact.mjs'),'export const ROOT='+JSON.stringify(root)+';');
    for(const file of ['protected-file.mjs','errors.mjs'])fs.copyFileSync(new URL(file,import.meta.url),path.join(root,file));
    const helper=await import('file://'+path.join(root,'protected-file.mjs'));
    helper.writeReceipt(path.join(root,'work','receipt.json'),{status:'BLOCKED'});
    assert.equal(fs.statSync(path.join(root,'work')).mode&0o777,0o700);
    fs.rmSync(path.join(root,'work'),{recursive:true});fs.symlinkSync(dir,path.join(root,'work'));
    assert.throws(()=>helper.writeReceipt(path.join(root,'work','escape.json'),{}));
    assert.throws(()=>helper.writeProtectedDirectory(path.join(root,'work','escape'),{'secret.json':'synthetic'}));
    assert.equal(fs.existsSync(path.join(dir,'escape.json')),false);assert.equal(fs.existsSync(path.join(dir,'escape')),false);
    fs.unlinkSync(path.join(root,'work'));fs.mkdirSync(path.join(root,'work'),{mode:0o755});fs.chmodSync(path.join(root,'work'),0o755);
    assert.throws(()=>helper.writeReceipt(path.join(root,'work','receipt.json'),{}),e=>e instanceof Error&&e.message==='PROTECTED_DIRECTORY_PERMISSIONS');
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test('hosted CLIs reserve valid receipt descriptors before any network activity',()=>{
  const dir=scratch(),marker=path.join(dir,'network'),preload=path.join(dir,'preload.mjs');
  try{
    const approval=path.join(dir,'approval.json'),fixture=path.join(dir,'fixtures.json'),token=path.join(dir,'token');
    fs.writeFileSync(approval,JSON.stringify(localApproval()),{mode:0o600});fs.writeFileSync(fixture,JSON.stringify(fixtures()),{mode:0o600});fs.writeFileSync(token,'synthetic-read-token',{mode:0o600});
    fs.writeFileSync(preload,"import fs from 'node:fs';globalThis.fetch=async()=>{fs.writeFileSync("+JSON.stringify(marker)+",'requested');throw Error('synthetic private network diagnostic');};");
    const env={STAGING_APPROVAL_FILE:approval,STAGING_FIXTURES_FILE:fixture,STAGING_CF_READ_TOKEN_FILE:token,STAGING_URL:localApproval().workers[0].origin,NODE_OPTIONS:'--import='+preload};
    const existing=path.join(dir,'existing.json');fs.writeFileSync(existing,'unchanged',{mode:0o600});fs.symlinkSync(dir,path.join(dir,'link'));
    const denied=[[],['--receipt'],['--receipt','--revoked'],['--receipt',existing],['--receipt',path.join(ROOT,'forbidden.json')],['--receipt',path.join(dir,'link','escape.json')]];
    for(const script of ['acceptance.mjs','verify-deployment.mjs']){
      for(const args of denied){const r=cli(script,args,env);assert.equal(r.status,2);assert.equal(fs.existsSync(marker),false);assert.ok(!r.stdout.includes('synthetic-read-token'));}
      const receipt=path.join(dir,script+'.json'),r=cli(script,['--receipt',receipt],env);
      assert.equal(r.status,2);assert.equal(fs.existsSync(marker),true,'Control proves network interception is active');fs.unlinkSync(marker);
      const report=JSON.parse(readProtected(receipt));assert.equal(script==='acceptance.mjs'?report.results[0].status:report.status,'BLOCKED');assert.ok(!JSON.stringify(report).includes('private network diagnostic'));
    }
    assert.equal(fs.readFileSync(existing,'utf8'),'unchanged');assert.equal(fs.existsSync(path.join(ROOT,'forbidden.json')),false);
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test('documented private work initialization precedes npm cache creation under umask 022',()=>{
  const dir=scratch(),root=path.join(dir,'isolated');fs.mkdirSync(root,{mode:0o700});
  try{
    fs.writeFileSync(path.join(root,'artifact.mjs'),'export const ROOT='+JSON.stringify(root)+';');
    for(const file of ['protected-file.mjs','errors.mjs'])fs.copyFileSync(new URL(file,import.meta.url),path.join(root,file));
    const preload=path.join(root,'umask.mjs');fs.writeFileSync(preload,'process.umask(0o022);');
    const run=()=>spawnSync(process.execPath,['--import',preload,path.join(root,'protected-file.mjs'),'--init-work'],{encoding:'utf8'});
    assert.equal(run().status,0);assert.equal(fs.statSync(path.join(root,'work')).mode&0o777,0o700);
    assert.equal(run().status,0);fs.chmodSync(path.join(root,'work'),0o755);assert.equal(run().status,2);assert.equal(fs.statSync(path.join(root,'work')).mode&0o777,0o755);
    for(const name of ['README.md','REVIEW-REMEDIATION.md']){const doc=fs.readFileSync(new URL(name,import.meta.url),'utf8');assert.ok(doc.indexOf('protected-file.mjs --init-work')<doc.indexOf('npm ci'));}
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
