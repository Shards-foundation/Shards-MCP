import Link from "next/link";
import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";
import { authOptions } from "@/lib/auth";
import { SignInButtons } from "./signin-buttons";

const errors: Record<string, string> = {
  OAuthSignin: "Could not start provider sign-in.",
  OAuthCallback: "The identity provider rejected the callback.",
  OAuthAccountNotLinked: "That email is associated with another sign-in method. Sign in using the original provider.",
  AccessDenied: "The identity provider denied access.",
  Configuration: "Sign-in is not configured on this deployment.",
  Default: "Sign-in failed. Try again.",
};
export default async function SignInPage({ searchParams }: { searchParams?: { error?: string; callbackUrl?: string } }) {
  const session = await getServerSession(authOptions);
  const target = searchParams?.callbackUrl?.startsWith("/") && !searchParams.callbackUrl.startsWith("//")
    ? searchParams.callbackUrl : "/account";
  if (session?.user) redirect(target);
  return <main className="public-shell"><header className="public-header"><Link className="public-brand" href="/"><span className="public-logo">S</span> SHARDS <span className="brand-sub">/ SIGN IN</span></Link><nav><Link href="/get-started">Get started</Link></nav></header>
    <section className="account-card"><div className="eyebrow">IDENTITY / SECURE SESSION</div><h1>Access your workspace.</h1><p>Sign in through a configured identity provider. Your identity does not automatically grant gateway or agent permissions.</p>
      {searchParams?.error && <p role="alert">{errors[searchParams.error] ?? errors.Default}</p>}
      {authOptions.providers.length === 0 ? <p role="alert">No identity providers are configured on this deployment. An operator must register OAuth applications and configure server-side credentials.</p> :
        <SignInButtons callbackUrl={target} providers={authOptions.providers.map(p => ({ id: p.id, name: p.name }))} />}
      <p className="muted">Sign in with ChatGPT is available only to approved OpenAI partners with registered OAuth credentials. It appears here only when configured.</p>
    </section></main>;
}
