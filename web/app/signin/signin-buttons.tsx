"use client";
import { signIn } from "next-auth/react";
export function SignInButtons({ providers, callbackUrl }: { providers: Array<{ id: string; name: string }>; callbackUrl: string }) {
  return <div className="signin-providers">{providers.map(provider =>
    <button className="provider-button" type="button" key={provider.id}
      onClick={() => void signIn(provider.id, { callbackUrl })}>
      Continue with {provider.name} <span aria-hidden="true">↗</span>
    </button>)}</div>;
}
