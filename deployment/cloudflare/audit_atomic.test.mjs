import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { webcrypto } from "node:crypto";

const source=fs.readFileSync(new URL("./worker.js",import.meta.url),"utf8");
const sandbox={Request,Response,Headers,URL,TextEncoder,TextDecoder,crypto:webcrypto,AbortSignal,atob,
  fetch:async()=>{throw Error("Network access forbidden by test")}};
vm.runInNewContext(source.replace("export default {","globalThis.__edge = {")+
  "\nglobalThis.__runTool=runTool;",sandbox,{filename:"worker.js"});
const runTool=sandbox.__runTool;
const actor={
  id:"agent_sender_00001",tenant_id:"shards-internal",name:"Synthetic sender",client:"test",
  scopeSet:new Set(["message:send","task:create","task:claim","task:complete"])
};
const recipient="agent_recipient_00001";
const taskId="11111111-1111-4111-8111-111111111111";
const reqId="req-audit-0001";

function makeDB({auditFailure=false,task=null}={}){
  const state={messages:[],tasks:task?[structuredClone(task)]:[],audits:[],batches:[],standaloneMutations:0};
  const database={
    prepare(sql){return {bind(...params){
      const stmt={sql,params};
      return {...stmt,
        async run(){
          if(sql.startsWith("INSERT INTO route_budgets"))return {meta:{changes:1}};
          state.standaloneMutations++;
          throw Error("Protected writes must be batched");
        },
        async first(){
          if(sql.startsWith("SELECT id FROM agents"))return {id:params[0]};
          if(sql.includes("FROM agent_messages")){
            return state.messages.find(m=>m.tenant_id===params[0]&&m.sender_id===params[1]&&m.request_key===params[2])||null;
          }
          if(sql.startsWith("SELECT state FROM agent_tasks WHERE id=?")){
            return state.tasks.find(t=>t.id===params[0]&&t.tenant_id===params[1]&&t.assignee_id===params[2])||null;
          }
          if(sql.includes("FROM agent_tasks")){
            return state.tasks.find(t=>t.tenant_id===params[0]&&t.creator_id===params[1]&&t.request_key===params[2])||null;
          }
          throw Error("Unexpected first query: "+sql);
        }
      };
    }}},
    async batch(stmts){
      assert.equal(stmts.length,2,"effect and audit must be a single batch");
      const [effect,audit]=stmts;
      assert.match(audit.sql,/^INSERT INTO audit_events/);
      state.batches.push({effect:effect.sql,audit:audit.sql});
      // The test models Cloudflare D1's transactional rollback on a failed statement.
      // No change to state may be applied when the audit insert is rejected.
      if(auditFailure)throw Error("INJECTED_AUDIT_D1_FAILURE");
      let rows=[];
      if(effect.sql.startsWith("INSERT OR IGNORE INTO agent_messages")){
        const [id,tenant_id,sender_id,recipient_id,body,created_at,request_key]=effect.params;
        assert.match(audit.sql,/\(SELECT tenant_id FROM agent_messages WHERE/);
        if(!state.messages.some(m=>m.tenant_id===tenant_id&&m.sender_id===sender_id&&m.request_key===request_key))
          state.messages.push({id,tenant_id,sender_id,recipient_id,body,created_at,request_key});
      }else if(effect.sql.startsWith("INSERT OR IGNORE INTO agent_tasks")){
        const [id,tenant_id,creator_id,assignee_id,title,input_json,current_state,created_at,request_key]=effect.params;
        assert.match(audit.sql,/\(SELECT tenant_id FROM agent_tasks WHERE/);
        if(!state.tasks.some(t=>t.tenant_id===tenant_id&&t.creator_id===creator_id&&t.request_key===request_key))
          state.tasks.push({id,tenant_id,creator_id,assignee_id,title,input_json,state:current_state,created_at,request_key});
      }else if(effect.sql.startsWith("UPDATE agent_tasks")){
        assert.match(audit.sql,/CASE WHEN changes\(\)=1 THEN \? ELSE NULL END/);
        if(effect.sql.includes("SET state='claimed'")){
          const [time,id,tenant,assignee]=effect.params;
          const t=state.tasks.find(t=>t.id===id&&t.tenant_id===tenant&&t.assignee_id===assignee&&t.state==="queued");
          if(!t)throw Error("No matching transition: audit NOT NULL guard rolls back batch");
          t.state="claimed";t.claimed_at=time;
          rows=[{id:t.id,title:t.title,input_json:t.input_json,state:t.state}];
        }else if(effect.sql.includes("SET state='completed'")){
          const [time,data,id,tenant,assignee]=effect.params;
          const t=state.tasks.find(t=>t.id===id&&t.tenant_id===tenant&&t.assignee_id===assignee&&t.state==="claimed");
          if(!t)throw Error("No matching transition: audit NOT NULL guard rolls back batch");
          t.state="completed";t.completed_at=time;t.result_json=data;
          rows=[{id:t.id,state:t.state}];
        }else throw Error("Unknown state transition");
      }else throw Error("Unexpected mutation: "+effect.sql);
      state.audits.push({statement:audit.sql,params:audit.params});
      return [{success:true,results:rows,meta:{changes:1}},{success:true,meta:{changes:1},results:[]}];
    }
  };
  return {state,EDGE_DB:database};
}

function seededTask(){
  return {id:taskId,tenant_id:actor.tenant_id,creator_id:actor.id,assignee_id:actor.id,
    state:"queued",title:"Synthetic task",input_json:'{"action":"read"}',
    created_at:"2026-11-15T00:00:00.000Z",request_key:"existing-task-request"};
}
const request=new Request("https://mcp.shardsinc.co.uk/mcp",{method:"POST"});

test("Message write and its audit share one D1 transaction; audit failure leaves no message",async()=>{
  const env=makeDB({auditFailure:true});
  const args={recipient_agent_id:recipient,body:"synthetic test",request_id:reqId};
  const denied=await runTool("shards_message_send",args,actor,env,request);
  assert.equal(denied.isError,true);
  assert.match(denied.content[0].text,/Atomic mutation or audit unavailable/);
  assert.doesNotMatch(denied.content[0].text,/INJECTED_AUDIT_D1_FAILURE|audit_events|D1_ERROR/);
  assert.equal(env.state.messages.length,0);
  assert.equal(env.state.audits.length,0);
  assert.equal(env.state.standaloneMutations,0);
  assert.equal(env.state.batches.length,1);
  const ok=makeDB();
  const accepted=await runTool("shards_message_send",args,actor,ok,request);
  assert.equal(accepted.isError,false);
  assert.equal(accepted.structuredContent.delivered,true);
  assert.equal(ok.state.messages.length,1);
  assert.equal(ok.state.audits.length,1);
  const replay=await runTool("shards_message_send",args,actor,ok,request);
  assert.equal(replay.structuredContent.idempotent,true);
  assert.equal(ok.state.messages.length,1);
  const conflict=await runTool("shards_message_send",{...args,body:"different"},actor,ok,request);
  assert.equal(conflict.isError,true);
  assert.equal(ok.state.messages.length,1);
});
test("Task create audit rollback and idempotent replay",async()=>{
  const args={assignee_agent_id:recipient,title:"Synthetic task",input:{review:"only"},request_id:reqId};
  const fail=makeDB({auditFailure:true});
  assert.equal((await runTool("shards_task_create",args,actor,fail,request)).isError,true);
  assert.equal(fail.state.tasks.length,0);
  assert.equal(fail.state.audits.length,0);
  const ok=makeDB();
  assert.equal((await runTool("shards_task_create",args,actor,ok,request)).isError,false);
  assert.equal(ok.state.tasks.length,1);
  assert.equal(ok.state.audits.length,1);
  assert.equal((await runTool("shards_task_create",args,actor,ok,request)).structuredContent.idempotent,true);
  assert.equal(ok.state.tasks.length,1);
});
test("Task claim audit failure cannot transition queued state",async()=>{
  const fail=makeDB({auditFailure:true,task:seededTask()});
  const denied=await runTool("shards_task_claim",{task_id:taskId},actor,fail,request);
  assert.equal(denied.isError,true);
  assert.equal(fail.state.tasks[0].state,"queued");
  assert.equal(fail.state.audits.length,0);
  const ok=makeDB({task:seededTask()});
  const result=await runTool("shards_task_claim",{task_id:taskId},actor,ok,request);
  assert.equal(result.isError,false);
  assert.equal(result.structuredContent.state,"claimed");
  assert.equal(ok.state.tasks[0].state,"claimed");
  assert.equal(ok.state.audits.length,1);
  const lostRace=await runTool("shards_task_claim",{task_id:taskId},actor,ok,request);
  assert.equal(lostRace.isError,true);
  assert.match(lostRace.content[0].text,/Task unavailable, already claimed or not assigned/);
  assert.doesNotMatch(lostRace.content[0].text,/NOT NULL|D1_ERROR|audit_events/);
});
test("Task completion audit failure cannot transition claimed state",async()=>{
  const claimed={...seededTask(),state:"claimed"};
  const args={task_id:taskId,result:{done:true}};
  const fail=makeDB({auditFailure:true,task:claimed});
  assert.equal((await runTool("shards_task_complete",args,actor,fail,request)).isError,true);
  assert.equal(fail.state.tasks[0].state,"claimed");
  assert.equal(fail.state.audits.length,0);
  const ok=makeDB({task:claimed});
  const accepted=await runTool("shards_task_complete",args,actor,ok,request);
  assert.equal(accepted.isError,false);
  assert.equal(accepted.structuredContent.state,"completed");
  assert.equal(ok.state.audits.length,1);
  const replay=await runTool("shards_task_complete",args,actor,ok,request);
  assert.equal(replay.isError,true);
  assert.match(replay.content[0].text,/Task not claimed by this agent/);
  assert.doesNotMatch(replay.content[0].text,/NOT NULL|D1_ERROR|audit_events/);
});
test("Write tools fail closed when the database lacks transactional batch",async()=>{
  const env=makeDB();
  delete env.EDGE_DB.batch;
  const denied=await runTool("shards_message_send",{recipient_agent_id:recipient,body:"hello",request_id:reqId},actor,env,request);
  assert.equal(denied.isError,true);
  assert.match(denied.content[0].text,/Atomic D1 batch is unavailable/);
  assert.equal(env.state.messages.length,0);
  assert.equal(env.state.standaloneMutations,0);
});
