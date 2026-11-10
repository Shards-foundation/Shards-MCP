import Link from "next/link";
import { ConnectionWizard } from "./wizard";

export const metadata = {
  title: "Connect your AI agent | Shards MCP",
  description: "Install Shards MCP with Claude, ChatGPT, Codex or Cursor using official client instructions and OAuth.",
};

export default function GettingStarted() {
  return <main className="public-shell">
    <header className="public-header"><Link className="public-brand" href="/"><span className="public-logo">S</span> SHARDS <span className="brand-sub">/ CONNECTIVITY</span></Link><nav><Link href="/">Overview</Link><Link href="/account">Account</Link><a href="https://github.com/Shards-foundation/Shards-MCP" rel="noopener noreferrer" target="_blank">Source</a></nav></header>
    <div className="page-intro"><span className="eyebrow">ONBOARD / AGENT CONNECTION</span><h1>Connect your intelligence.</h1><p>Choose your client, import its supported MCP configuration and authorise only the permissions you need. No copy-pasted API secrets.</p></div>
    <ConnectionWizard />
    <section className="public-section"><div className="eyebrow">SECURITY BY DEFAULT</div><h2>Identity is not authority.</h2><div className="feature-grid"><article><strong>01 / Identify</strong><p>Authenticate using a configured identity provider and receive a verified, server-managed session.</p></article><article><strong>02 / Authorise</strong><p>Remote MCP clients must complete a compliant OAuth flow with scoped, audience-bound tokens.</p></article><article><strong>03 / Govern</strong><p>The gateway restricts each agent to its enrolled identity, permissions and auditable execution boundary.</p></article></div><p className="muted">Connection configurations are real formats, but server reachability and client authentication depend on the live service deployment. No connection is claimed successful until the client completes its own handshake and tool invocation.</p></section>
  </main>;
}
