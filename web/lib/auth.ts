import type { NextAuthOptions } from "next-auth";
import GoogleProvider from "next-auth/providers/google";
import GitHubProvider from "next-auth/providers/github";
import DiscordProvider from "next-auth/providers/discord";

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
    async signIn({ user }) {
      // First deployment is private by default. Social authentication alone
      // must never make the operator console open to the entire internet.
      const allowed = new Set(
        (process.env.SHARDS_CONSOLE_ALLOWED_EMAILS ?? "")
          .split(",").map(email => email.trim().toLowerCase()).filter(Boolean),
      );
      const email = user.email?.trim().toLowerCase();
      return Boolean(email && allowed.has(email));
    },
    async session({ session }) {
      // Social login proves identity, not Shards operator/agent authority.
      // Never attach gateway tokens or provider access tokens to the session.
      return session;
    },
  },
};
