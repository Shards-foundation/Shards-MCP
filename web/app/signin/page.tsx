import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";
import { authOptions } from "@/lib/auth";
import { SignInButtons } from "./signin-buttons";

const errors: Record<string, string> = {
  OAuthSignin: "Could not start provider sign-in.",
  OAuthCallback: "The identity provider rejected the callback.",
  OAuthAccountNotLinked: "This email is linked to a different sign-in method.",
  AccessDenied: "Access was denied by the identity provider.",
  Configuration: "Sign-in is not configured correctly.",
  Default: "Sign-in failed. Try again or contact the operator.",
};

export default async function SignInPage({
  searchParams,
}: { searchParams?: { error?: string } }) {
  const session = await getServerSession(authOptions);
  if (session?.user) redirect("/");
  return <main className="shell"><div className="eyebrow">SHARDS / IDENTITY</div>
    <h1>Sign in to the control plane</h1>
    <p>Social sign-in authenticates you to the console. It does not grant gateway administrator or agent permissions.</p>
    {searchParams?.error && <p role="alert">{errors[searchParams.error] ?? errors.Default}</p>}
    <section className="panel">
      {authOptions.providers.length === 0
        ? <p>No identity providers configured. Set the OAuth client IDs and secrets on the server.</p>
        : <SignInButtons providers={authOptions.providers.map(provider => ({ id: provider.id, name: provider.name }))} />}
    </section>
    <p className="muted">ChatGPT connects to the gateway as an AI client through MCP; it is not a social sign-in provider here.</p>
  </main>;
}
