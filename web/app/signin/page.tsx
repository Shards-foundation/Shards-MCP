import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";
import { authOptions } from "@/lib/auth";

export default async function SignInPage() {
  const session = await getServerSession(authOptions);
  if (session?.user) redirect("/");
  return <main className="shell"><div className="eyebrow">SHARDS / IDENTITY</div>
    <h1>Sign in to the control plane</h1>
    <p>Social sign-in authenticates you to the console. It does not grant gateway administrator or agent permissions.</p>
    <section className="panel">
      {authOptions.providers.length === 0
        ? <p>No identity providers configured. Set the OAuth client IDs and secrets on the server.</p>
        : authOptions.providers.map(provider =>
          <a className="action" key={provider.id} href={`/api/auth/signin/${provider.id}`}>Continue with {provider.name}</a>)}
    </section>
    <p className="muted">ChatGPT connects to the gateway as an AI client through MCP; it is not a social sign-in provider here.</p>
  </main>;
}
