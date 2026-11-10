import type { Metadata } from "next";
import "./style.css";
export const metadata: Metadata = {
  title: "Shards MCP | Universal AI Connectivity",
  description: "One governed MCP gateway for Claude, ChatGPT, Codex, Cursor and intelligent agents.",
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
