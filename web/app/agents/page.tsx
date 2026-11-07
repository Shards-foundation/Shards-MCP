import { ConsoleLayout } from "../console-layout";

export default function Agents() {
  return <ConsoleLayout active="/agents"><div className="page-heading"><div><div className="eyebrow">IDENTITY / AGENTS</div><h1>Agent registry</h1><p className="muted">Identity, permissions, heartbeats and client lifecycle.</p></div></div>
    <div className="panel"><div className="eyebrow">GATEWAY INTEGRATION REQUIRED</div><h2>Agent inventory unavailable</h2><p>The console does not currently hold an authorised agent-registry credential. Live identities cannot be retrieved safely until the server-side operator API bridge and scoped permissions are configured.</p><p className="muted">No fabricated agent counts or heartbeat statuses are displayed.</p></div>
    <div className="module-grid"><section className="panel"><h2>Identity boundaries</h2><p>Use a distinct token and scoped permissions for every connected agent or IDE installation.</p></section><section className="panel"><h2>Operational controls</h2><p>Agent registration, heartbeat history, credential revocation and status monitoring will be exposed after the authorised gateway integration is complete.</p></section></div>
  </ConsoleLayout>;
}