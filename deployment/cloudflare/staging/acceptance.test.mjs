import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {Miniflare,createFetchMock} from 'miniflare';
import {artifact,configuration,pinned,originFor,SOURCE,PROD_DB} from './build.mjs';
import {fixtures,seedStatements,revocationSql} from './fixtures.mjs';
import {accept,stagingUrl} from './acceptance.mjs';

test('configuration and target guards cannot select production or shared routes',()=>{
  assert.throws(()=>stagingUrl('https://mcp.shardsinc.co.uk'));
  assert.throws(()=>stagingUrl('https://portal.shardsinc.co.uk'));
  assert.throws(()=>stagingUrl('https://shards-mcp-edge.bow-eucalyptus.workers.dev'));
  assert.throws(()=>stagingUrl(originFor('local')+'/?redirect=production'));
  assert.throws(()=>configuration('local',{databaseId:PROD_DB}));
  const c=configuration('local');
  assert.deepEqual(c.routes,[]);assert.equal(c.name,'shards-mcp-pr46-staging');
  assert.equal(c.d1_databases[0].database_name,'shards-mcp-pr46-staging');
  assert.equal(configuration('local',{fault:true}).d1_databases,undefined);
  assert.equal(c.vars.ACCESS_AUD,undefined);assert.equal(c.vars.CONNECT_ACCESS_AUD,undefined);
  const a=artifact('local');assert.ok(!a.script.includes('mcp.shardsinc.co.uk'));
  assert.equal(a.manifest.source_commit,SOURCE);
});

test('real workerd and isolated D1 exercise the complete acceptance matrix before and after revocation',async()=>{
  const main=artifact('local'),fault=artifact('local',{fault:true});
  const key=await webcrypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
  const jwk=await webcrypto.subtle.exportKey('jwk',key.publicKey);jwk.kid='staging-synthetic-key';
  const issuer='https://isolated-fixture.cloudflareaccess.com';
  const mock=createFetchMock();mock.disableNetConnect();
  mock.get(issuer).intercept({path:'/cdn-cgi/access/certs'}).reply(200,{keys:[jwk]}).persist();
  const bindings={STAGING_ACCEPTANCE:SOURCE,ACCESS_TEAM:'isolated-fixture',ACCESS_AUD:'synthetic-operator-audience',CONNECT_ACCESS_AUD:'synthetic-connect-audience'};
  const mf=new Miniflare({modules:true,script:main.script,compatibilityDate:'2025-06-18',d1Databases:['EDGE_DB'],d1Persist:false,bindings,fetchMock:mock});
  const broken=new Miniflare({modules:true,script:fault.script,compatibilityDate:'2025-06-18',bindings,fetchMock:mock});
  try{
    const db=await mf.getD1Database('EDGE_DB');
    // D1 exec accepts one statement per line; flatten known pinned schema statements.
    const schema=pinned('deployment/cloudflare/schema.sql').replace(/^--.*$/gm,'').split(';').map(s=>s.replace(/\s+/g,' ').trim()).filter(Boolean);
    for(const sql of schema)await db.prepare(sql).run();
    const f=fixtures();for(const sql of seedStatements(f))await db.prepare(sql).run();
    const now=Math.floor(Date.now()/1000),bin=x=>Buffer.from(JSON.stringify(x)).toString('base64url');
    const partial=bin({alg:'RS256',kid:jwk.kid})+'.'+bin({iss:issuer,aud:['synthetic-connect-audience'],sub:'synthetic-staging-user',exp:now+300,nbf:now-10});
    const signature=await webcrypto.subtle.sign('RSASSA-PKCS1-v1_5',key.privateKey,new TextEncoder().encode(partial));
    const access={issuer,token:partial+'.'+Buffer.from(signature).toString('base64url')};
    const fetchImpl=(url,options)=>new URL(url).origin===fault.manifest.origin?broken.dispatchFetch(url,options):mf.dispatchFetch(url,options);
    const opts={base:main.manifest.origin,faultBase:fault.manifest.origin,fixtures:f,fetchImpl,access};
    for(const revoked of [false,true]){
      if(revoked)await db.prepare(revocationSql()).run();
      const report=await accept({...opts,revoked});
      // Print only the safe matrix, never assertions over fixture objects or responses.
      console.log(JSON.stringify(report));
      assert.equal(report.results.length,10);
      assert.equal(report.results.every(r=>r.status==='PASS'),true,'Acceptance matrix contains a failure/blocker');
    }
    const blocked=await mf.dispatchFetch(main.manifest.origin+'/manage/api/agents');assert.equal(blocked.status,404);
    const wrong=await mf.dispatchFetch('https://mcp.shardsinc.co.uk/mcp');assert.equal(wrong.status,403);
  }finally{await Promise.all([mf.dispose(),broken.dispose()]);await mock.close();}
});


test('manifest mismatch stops the runner before sending credentials',async()=>{
  let requests=0;
  const f=fixtures();
  const report=await accept({base:originFor('local'),fixtures:f,fetchImpl:async(url,options)=>{
    requests++;
    assert.equal(new Headers(options.headers).has('authorization'),false);
    return Response.json({source_commit:'wrong-source'});
  }});
  assert.equal(requests,1);assert.equal(report.results[0].status,'FAIL');
  const rendered=JSON.stringify(report);
  assert.equal(f.agents.some(a=>rendered.includes(a.token)),false);
  await assert.rejects(accept({base:originFor('local'),faultBase:originFor('another',true),fixtures:f}));
});
