import type { NextAuthOptions } from "next-auth";
import GoogleProvider from "next-auth/providers/google";
import GitHubProvider from "next-auth/providers/github";
import DiscordProvider from "next-auth/providers/discord";
import AppleProvider from "next-auth/providers/apple";

function credentials(name: string) {
  const clientId = process.env[name + "_CLIENT_ID"];
  const clientSecret = process.env[name + "_CLIENT_SECRET"];
  return clientId && clientSecret ? { clientId, clientSecret } : null;
}

const google = credentials("GOOGLE");
const github = credentials("GITHUB");
const discord = credentials("DISCORD");
const apple = credentials("APPLE");
const chatgpt = credentials("CHATGPT");
const chatgptIssuer = process.env.CHATGPT_OIDC_ISSUER;
// Sign in with ChatGPT is partner-gated. No fake button or fabricated issuer.
const chatgptEnabled = Boolean(chatgpt && chatgptIssuer && /^https:\/\/[^/]+\/?$/.test(chatgptIssuer));

function operatorSubjects() {
  return new Set((process.env.SHARDS_CONSOLE_ALLOWED_IDENTITIES ?? "")
    .split(",").map(x => x.trim()).filter(Boolean));
}

export const authOptions: NextAuthOptions = {
  providers: [
    ...(google ? [GoogleProvider(google)] : []),
    ...(github ? [GitHubProvider(github)] : []),
    ...(discord ? [DiscordProvider(discord)] : []),
    ...(apple ? [AppleProvider(apple)] : []),
    ...(chatgptEnabled && chatgpt ? [{
      id: "chatgpt",
      name: "ChatGPT",
      type: "oauth" as const,
      wellKnown: `${chatgptIssuer!.replace(/\/$/, "")}/.well-known/openid-configuration`,
      idToken: true,
      checks: ["pkce", "state"] as Array<"pkce" | "state">,
      clientId: chatgpt.clientId,
      clientSecret: chatgpt.clientSecret,
      authorization: { params: { scope: "openid profile email" } },
      profile(profile: Record<string, unknown>) {
        return {
          id: String(profile.sub),
          name: typeof profile.name === "string" ? profile.name : null,
          email: typeof profile.email === "string" ? profile.email : null,
          image: typeof profile.picture === "string" ? profile.picture : null,
        };
      },
    }] : []),
  ],
  session: { strategy: "jwt", maxAge: 60 * 60 * 8 },
  pages: { signIn: "/signin" },
  callbacks: {
    async jwt({ token, account }) {
      // Never derive access from user-editable email or display name.
      if (account?.provider && account.providerAccountId) {
        Object.assign(token, { shardsIdentity: `${account.provider}:${account.providerAccountId}` });
      }
      return token;
    },
    async session({ session, token }) {
      const identity = typeof token.shardsIdentity === "string" ? token.shardsIdentity : "";
      // Ordinary authenticated users may access onboarding and /account only.
      // Operator authority is recomputed from server configuration on every session read.
      return Object.assign(session, { shardsOperator: Boolean(identity && operatorSubjects().has(identity)) });
    },
  },
};
