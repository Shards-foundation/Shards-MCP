// Synthetic read-only API fixture for tests; no network.
import assert from 'node:assert/strict';
import {artifact,SOURCE} from './build.mjs';
const envelope=result=>Response.json({success:true,result});
export function fakeApi(a,{change=(p,x)=>x,scriptChange=s=>s,missingBytes=false,enabled=true}={}){
  const root='/accounts/'+a.account_id;
  return async p=>{
    let result;
    if(p===root)result={id:a.account_id,name:a.account_name};
    else if(p===root+'/workers/subdomain')result={subdomain:a.subdomain};
    else if(p===root+'/d1/database/'+a.database_id)result={uuid:a.database_id,name:a.database_name,jurisdiction:'eu'};
    else{
      const i=a.workers.findIndex(w=>p===root+'/workers/scripts/'+w.name||p.startsWith(root+'/workers/scripts/'+w.name+'/'));
      assert.ok(i>=0,'Only approved script endpoints can be read');const w=a.workers[i],base=root+'/workers/scripts/'+w.name;
      const bindings=[{type:'plain_text',name:'STAGING_ACCEPTANCE',text:SOURCE},...(!i&&a.access?Object.entries({ACCESS_TEAM:a.access.team,ACCESS_AUD:a.access.audience,CONNECT_ACCESS_AUD:a.access.connect_audience}).map(([name,text])=>({type:'plain_text',name,text})):[]),...(i?[]:[{type:'d1',name:'EDGE_DB',id:a.database_id}])];
      if(p===base+'/deployments')result={deployments:[{id:w.deployment_id,created_on:'2026-11-16T19:26:00Z',versions:[{version_id:w.version_id,percentage:100}]}]};
      else if(p===base+'/settings')result={bindings};
      else if(p===base+'/versions/'+w.version_id)result={id:w.version_id,resources:{bindings}};
      else if(p===base+'/subdomain')result={enabled,previews_enabled:false};
      else if(p===base){
        if(missingBytes)return Response.json({success:true});
        const form=new FormData();form.set('worker.js',new Blob([scriptChange(artifact(a.subdomain,{fault:!!i}).script)],{type:'application/javascript'}),'worker.js');return new Response(form);
      }else throw Error('Unexpected fixture API path');
    }
    return envelope(change(p,structuredClone(result)));
  };
}
