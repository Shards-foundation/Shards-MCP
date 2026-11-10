import Link from "next/link";
import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";
import { authOptions } from "@/lib/auth";
import { operatorSession } from "@/lib/operator-access";
import { SignOutButton } from "./signout-button";

const navigation = [
  { href: "/", title: "Overview", detail: "Gateway status and operational readiness" },
  { href: "/connections", title: "Connections", detail: "Configure MCP clients and IDEs" },
  { href: "/agents", title: "Agents", detail: "Agent identities and gateway diagnostics" },
  { href: "/tasks", title: "Tasks", detail: "Task execution and worker orchestration" },
  { href: "/audit", title: "Audit", detail: "Security events and operational history" },
];

export async function ConsoleLayout({ children, active }: { children: React.ReactNode; active: string }) {
  const session = await getServerSession(authOptions);
  if (!session?.user || !operatorSession(session)) redirect("/signin");
  return <main className="console-layout">
    <aside className="console-sidebar">
      <Link href="/" className="console-brand"><span className="brand-mark">S</span><span><strong>SHARDS</strong><small>MCP CONTROL PLANE</small></span></Link>
      <div className="sidebar-label">WORKSPACE</div>
      <nav className="console-nav" aria-label="Primary navigation">
        {navigation.map(item => <Link key={item.href} href={item.href} className={active === item.href ? "nav-link active" : "nav-link"} aria-current={active === item.href ? "page" : undefined}>
          <span>{item.title}</span><small>{item.detail}</small>
        </Link>)}
      </nav>
      <div className="sidebar-footer"><span className="sidebar-label">AUTHENTICATED SESSION</span>
        <p>{session.user.email ?? session.user.name ?? "Signed-in operator"}</p>
        <SignOutButton />
      </div>
    </aside>
    <div className="console-content">{children}</div>
  </main>;
}
