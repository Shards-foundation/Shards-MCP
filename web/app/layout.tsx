import type { Metadata } from "next";
import "./style.css";

export const metadata: Metadata = {
  title: "Shards MCP | Agent Control Plane",
  description: "Authenticated operations console for the Shards MCP gateway",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
