import Link from "next/link";
import { CLIENTS } from "@/lib/connectors";

export default function Home() {
  return <main className="public-shell">
    <header className="public-header"><Link className="public-brand" href="/"><span className="public-logo">S</span> SHARDS <span className="brand-sub">/ MCP GATEWAY</span></Link><nav><Link href="/get-started">Get started</Link><Link href="/account">Account</Link><a href="https://github.com/Shards-foundation/Shards-MCP" rel="noopener noreferrer" target="_blank">GitHub</a></nav></header>
    <section className="public-hero">
      <div className="public-hero-copy"><div className="eyebrow">UNIVERSAL AI CONNECTIVITY / SHARDS FOUNDATION</div>
        <h1>One gateway.<br/><em>Every agent.</em></h1><p>Connect your AI clients to a governed MCP control plane. Standard transports, scoped identities, durable tasks and inspectable audit evidence — without handing every agent your infrastructure keys.</p>
        <div className="hero-buttons"><Link className="primary-cta" href="/get-started">Connect your agent <span aria-hidden="true">↗</span></Link><a className="secondary-cta" href="https://github.com/Shards-foundation/Shards-MCP" target="_blank" rel="noopener noreferrer">Explore the source</a></div>
        <div className="hero-chips"><span>Streamable HTTP</span><span>Identity-bound tools</span><span>Open source</span></div>
      </div>
      <div className="network-art" aria-label="Visual illustration of clients connected through a single gateway" role="img"><div className="art-grid"/><div className="art-ring ring-one"/><div className="art-ring ring-two"/><div className="art-center"><strong>S</strong><small>GATEWAY</small></div><span className="satellite sat-one">CLAUDE</span><span className="satellite sat-two">CODEX</span><span className="satellite sat-three">CURSOR</span><span className="satellite sat-four">CHATGPT</span><span className="art-caption">MCP / SHARDS / CONNECT</span></div>
    </section>
    <section className="public-section"><div className="section-heading"><div><div className="eyebrow">SUPPORTED ONBOARDING PATHS</div><h2>Your tools. One connection protocol.</h2></div><Link className="secondary-cta" href="/get-started">View client setup</Link></div><div className="public-client-grid">{CLIENTS.map(c => <Link key={c.id} href="/get-started" className="public-client"><strong>{c.name}</strong><small>{c.category}</small><span>↗</span></Link>)}</div></section>
    <section className="public-section"><div className="eyebrow">ARCHITECTURE</div><h2>Identity, tools, authority. Separate by design.</h2><div className="feature-grid"><article><strong>01 / AUTHENTICATE</strong><p>Sign in to the portal; MCP clients use their own OAuth authorization flow.</p></article><article><strong>02 / CONNECT</strong><p>Use native client MCP configuration and real transport adapters — not a proprietary SDK lock-in.</p></article><article><strong>03 / CONTROL</strong><p>Enforce individual agent scopes, durable task boundaries and audit trails server-side.</p></article></div></section>
    <footer className="public-footer"><span>SHARDS / OPEN INFRASTRUCTURE</span><Link href="/get-started">Connect</Link><Link href="/account">Identity</Link><a href="https://github.com/Shards-foundation/Shards-MCP">Source</a></footer>
  </main>;
}
