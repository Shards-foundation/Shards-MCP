import Link from "next/link";
import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";
import { authOptions } from "@/lib/auth";
import { operatorSession } from "@/lib/operator-access";
import { SignOutButton } from "../signout-button";

export const dynamic = "force-dynamic";
export default async function Account({ searchParams }: { searchParams?: { restricted?: string } }) {
  const session = await getServerSession(authOptions);
  if (!session?.user) redirect("/signin?callbackUrl=%2Faccount");
  const operator = operatorSession(session);
  return <main className="public-shell">
    <header className="public-header"><Link className="public-brand" href="/"><span className="public-logo">S</span> SHARDS <span className="brand-sub">/ IDENTITY</span></Link><nav><Link href="/get-started">Connections</Link><Link href="/">Overview</Link></nav></header>
    <section className="account-card"><div className="eyebrow">AUTHENTICATED SESSION</div><h1>{session.user.name ?? "Signed in"}</h1><p>{session.user.email ?? "Identity provider email not shared"}</p>{searchParams?.restricted && <p role="alert">This identity is authenticated but is not enrolled as a Shards operator.</p>}
      <div className="account-meta"><span>Account session</span><strong>Signed in</strong><span>Console authority</span><strong>{operator ? "Operator allowlisted" : "No operator permissions"}</strong></div>
      <div className="wizard-actions"><Link className="primary-cta" href="/get-started">Connect an AI client</Link>{operator && <Link className="secondary-cta" href="/console">Open operator console</Link>}<SignOutButton /></div>
      <p className="muted">Your social identity is not an MCP credential. Agent enrolment, scopes and OAuth access are governed separately. Persistent organisations, billing and account linking are not yet enabled.</p>
    </section>
  </main>;
}
