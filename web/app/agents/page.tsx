import { ConsoleLayout } from "../console-layout";
import { AgentInventory } from "./agent-inventory";

export default function Agents() {
  return <ConsoleLayout active="/agents">
    <div className="page-heading"><div><div className="eyebrow">IDENTITY / AGENTS</div><h1>Agent registry</h1><p className="muted">Scoped identities, granted permissions and recorded heartbeat state.</p></div></div>
    <AgentInventory />
    <div className="module-grid">
      <section className="panel"><h2>Identity boundaries</h2><p>Every connected agent or IDE installation requires its own least-privilege gateway credential. This view uses a separate server-only agent:read identity.</p></section>
      <section className="panel"><h2>Read-only controls</h2><p>Registration, token rotation and revocation remain out-of-band operator actions. Heartbeat observations do not prove that an agent is currently executing tasks.</p></section>
    </div>
  </ConsoleLayout>;
}
