import type { NextAuthOptions } from "next-auth";
import GoogleProvider from "next-auth/providers/google";
import GitHubProvider from "next-auth/providers/github";
import DiscordProvider from "next-auth/providers/discord";
import { approvedOperator } from "./operator-access";

function credentials(id: string) {
  const clientId = process.env[id + "_CLIENT_ID"];
  const clientSecret = process.env[id + "_CLIENT_SECRET"];
  return clientId && clientSecret ? { clientId, clientSecret } : null;
}

const google = credentials("GOOGLE");
const github = credentials("GITHUB");
const discord = credentials("DISCORD");

export const authOptions: NextAuthOptions = {
  providers: [
    ...(google ? [GoogleProvider(google)] : []),
    ...(github ? [GitHubProvider(github)] : []),
    ...(discord ? [DiscordProvider(discord)] : []),
  ],
  session: { strategy: "jwt", maxAge: 60 * 60 * 8 },
  pages: { signIn: "/signin" },
  callbacks: {
    async signIn({ account }) {
      // Provider-scoped subject IDs, not email addresses, are the admission key.
      // Email may be unverified, mutable or shared across providers.
      const identity = account?.provider && account.providerAccountId
        ? `${account.provider}:${account.providerAccountId}` : null;
      return approvedOperator(identity, process.env.SHARDS_CONSOLE_ALLOWED_IDENTITIES);
    },
    async jwt({ token, account }) {
      if (account?.provider && account.providerAccountId) {
        Object.assign(token, { shardsIdentity: `${account.provider}:${account.providerAccountId}` });
      }
      return token;
    },
    async session({ session, token }) {
      // Recheck allowlist on each session read: removing an identity revokes console access.
      // A valid social session by itself must never authorise privileged gateway routes.
      const identity = typeof token.shardsIdentity === "string" ? token.shardsIdentity : null;
      return Object.assign(session, {
        shardsOperator: approvedOperator(identity, process.env.SHARDS_CONSOLE_ALLOWED_IDENTITIES),
      });
    },
  },
};
