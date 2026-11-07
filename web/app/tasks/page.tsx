import { ConsoleLayout } from "../console-layout";

export default function Tasks() {
  return <ConsoleLayout active="/tasks"><div className="page-heading"><div><div className="eyebrow">EXECUTION / WORK QUEUE</div><h1>Task orchestration</h1><p className="muted">Worker claims, checkpoints and execution outcomes.</p></div></div>
    <div className="panel"><div className="eyebrow">GATEWAY INTEGRATION REQUIRED</div><h2>Task queue not connected</h2><p>The gateway supports task lifecycle operations, but the web console has not yet been granted a scoped server-side operator interface. Tasks and worker states are deliberately not simulated.</p></div>
    <div className="module-grid"><section className="panel"><h2>Execution lifecycle</h2><p>Queued → claimed → running → completed or failed, with explicit worker ownership and lease handling.</p></section><section className="panel"><h2>Recovery</h2><p>Checkpoints and task history should remain visible through retries and process restarts.</p></section></div>
  </ConsoleLayout>;
}