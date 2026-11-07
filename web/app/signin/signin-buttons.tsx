"use client";
import { signIn } from "next-auth/react";

export function SignInButtons({ providers }: { providers: Array<{ id: string; name: string }> }) {
  return <>{providers.map(provider =>
    <button className="action" type="button" key={provider.id}
      onClick={() => void signIn(provider.id, { callbackUrl: "/" })}>
      Continue with {provider.name}
    </button>)}</>;
}
