import { ConsoleLayout } from "../console-layout";
import { ConnectionHub } from "../connection-hub";

export default function Connections() {
  return <ConsoleLayout active="/connections"><div className="page-heading"><div><div className="eyebrow">INTEGRATIONS / MCP CLIENTS</div><h1>Connections</h1><p className="muted">Connect IDEs and AI systems through the shared gateway.</p></div></div>
    <ConnectionHub />
    <section className="panel"><div className="eyebrow">SECURITY MODEL</div><h2>Independent client identities</h2><p>Issue a separate least-privileged gateway token for each installation. Do not reuse administrator credentials. Disable a compromised token on the gateway without affecting other clients.</p><p className="muted">Automated credential provisioning, connection telemetry and revocation controls are not yet implemented in this console.</p></section>
  </ConsoleLayout>;
}