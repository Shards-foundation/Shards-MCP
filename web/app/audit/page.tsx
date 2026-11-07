import { ConsoleLayout } from "../console-layout";

export default function Audit() {
  return <ConsoleLayout active="/audit"><div className="page-heading"><div><div className="eyebrow">OBSERVABILITY / SECURITY</div><h1>Audit and events</h1><p className="muted">Review agent activity and security-sensitive actions.</p></div></div>
    <div className="panel"><div className="eyebrow">GATEWAY INTEGRATION REQUIRED</div><h2>Audit stream not connected</h2><p>Security audit records and operational events must be queried through a permission-filtered backend. This page does not expose gateway administrator tokens or fabricate event history.</p></div>
    <div className="module-grid"><section className="panel"><h2>Audit integrity</h2><p>Preserve append-only evidence and verification metadata rather than transforming security records into editable UI state.</p></section><section className="panel"><h2>Operational events</h2><p>Event polling should use monotonic cursors to avoid missed updates and duplicate processing.</p></section></div>
  </ConsoleLayout>;
}