import {ensure} from './policy.mjs';
const stable=value=>JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
export async function checkVisibility(call,f){
  for(const role of ['reader','foreign']){
    const a=f.agents.find(a=>a.role===role),other=f.agents.find(a=>a.role===(role==='reader'?'observer':'peer'));
    const id=role+'_own',body='synthetic '+id;
    const expected={messages:[{id,sender_id:other.id,body,created_at:f.created}],
      tasks:[{id,title:body,input:{canary:id},state:'queued',creator_id:other.id,created_at:f.created,claimed_at:null,completed_at:null,result:null}],
      events:[{action:'fixture_own',object_id:id,status:'synthetic',created_at:f.created}]};
    for(const [tool,key] of [['shards_message_inbox','messages'],['shards_task_inbox','tasks'],['shards_audit_tail','events']]){
      const r=await call(tool,a.token);
      ensure(r.status===200&&r.body?.result?.isError===false&&stable(r.body?.result?.structuredContent?.[key])===stable(expected[key]),'ROW_ISOLATION_'+key.toUpperCase());
    }
  }
}
