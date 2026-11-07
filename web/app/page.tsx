import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";
import { authOptions } from "@/lib/auth";
import { GatewayHealth } from "./status";
import { ConnectionHub } from "./connection-hub";
import { SignOutButton } from "./signout-button";

export default async function Home() {
  const session = await getServerSession(authOptions);
  if (!session?.user) redirect("/signin");
  return <main className="shell">
    <header><div><div className="eyebrow">SHARDS / MCP GATEWAY</div><h1>Operations console</h1></div>
      <SignOutButton /></header>
    <p className="muted">Signed in as {session.user.email ?? session.user.name ?? "authenticated user"}. Read-only diagnostics only.</p>
    <div className="grid">
      <section className="panel"><h2>Gateway reachability</h2><GatewayHealth /><p className="muted">Server-side liveness probe. No gateway credentials enter the browser.</p></section>
      <section className="panel"><h2>Connect an AI agent</h2>
        <p>Provision a scoped agent identity on the gateway host, then configure its MCP endpoint and token in the AI client's secure settings.</p>
        <p className="muted">Operator credential issuance and tenant isolation are not yet exposed through this console.</p></section>
      <section className="panel"><h2>Next operational modules</h2>
        <p>Agent registry · Task queue · Audit explorer · Connection diagnostics · Organisation roles</p>
        <p className="muted">These modules require an authorised gateway API bridge and are not yet active.</p></section>
      <section className="panel"><h2>ChatGPT integration</h2>
        <p>Connect ChatGPT as an MCP client after configuring a publicly reachable HTTPS gateway and appropriate OAuth resource-server support.</p>
        <p className="muted">Live ChatGPT interoperability is not yet verified.</p></section>
    </div>
    <ConnectionHub />
  </main>;
}
