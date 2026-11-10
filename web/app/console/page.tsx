import Link from "next/link";
import { ConsoleLayout } from "../console-layout";
import { GatewayHealth } from "../status";

const modules = [
  { href: "/connections", title: "IDE connections", description: "Generate client configurations for Cursor, Claude Code, Codex, VS Code and more.", category: "INTEGRATIONS" },
  { href: "/agents", title: "Agent registry", description: "Inspect gateway identity capabilities and operator provisioning requirements.", category: "IDENTITY" },
  { href: "/tasks", title: "Task orchestration", description: "Review worker and task lifecycle integration requirements.", category: "EXECUTION" },
  { href: "/audit", title: "Audit and events", description: "Review security-ledger and telemetry integration requirements.", category: "OBSERVABILITY" },
];

export default function Home() {
  return <ConsoleLayout active="/console">
    <div className="page-heading"><div><div className="eyebrow">OPERATIONS / OVERVIEW</div><h1>Control plane</h1><p className="muted">Your central workspace for Shards MCP clients, agents, tasks and security.</p></div>
      <Link className="action" href="/connections">Connect an IDE</Link></div>
    <div className="overview-hero"><div><div className="eyebrow">GATEWAY STATUS</div><h2>Infrastructure reachability</h2>
      <GatewayHealth /><p className="muted">Authenticated server-side liveness check. Gateway credentials are never sent to the browser.</p></div>
      <div className="hero-metadata"><span>CONSOLE ACCESS</span><strong>Identity-gated</strong><span>OPERATIONS API</span><strong>Not connected</strong></div></div>
    <div className="section-heading"><h2>Workspace modules</h2><span className="muted">Available and planned capabilities</span></div>
    <div className="module-grid">{modules.map(module => <Link key={module.href} href={module.href} className="module-card">
      <span className="eyebrow">{module.category}</span><h3>{module.title}</h3><p>{module.description}</p><span className="module-arrow">Explore →</span>
    </Link>)}</div>
    <div className="panel"><div className="eyebrow">DEPLOYMENT NOTE</div><h2>Operator actions are not enabled</h2>
      <p>This interface currently provides authenticated diagnostics and connection templates. Live agent management, task execution and audit queries require a dedicated authorised gateway API bridge. No sample data is presented as real telemetry.</p></div>
  </ConsoleLayout>;
}
