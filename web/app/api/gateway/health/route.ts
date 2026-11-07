import { getServerSession } from "next-auth";
import { NextResponse } from "next/server";
import { authOptions } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function GET() {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "authentication_required" }, { status: 401 });
  }
  const configured = process.env.SHARDS_GATEWAY_INTERNAL_URL;
  if (!configured) {
    return NextResponse.json({ state: "unconfigured" }, { headers: { "Cache-Control": "no-store" } });
  }
  let url: URL;
  try {
    url = new URL(configured);
    const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if ((url.protocol !== "https:" && !(url.protocol === "http:" && loopback)) ||
        url.username || url.password || url.search || url.hash || (url.pathname !== "/" && url.pathname !== "")) {
      throw new Error("invalid gateway URL");
    }
  } catch {
    return NextResponse.json({ state: "configuration_error" }, { status: 503 });
  }
  try {
    // Fixed, server-configured endpoint; no user-controlled URL or credential forwarding.
    const response = await fetch(new URL("/health/live", url), {
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(3000),
    });
    return NextResponse.json(
      { state: response.status === 200 ? "reachable" : "unhealthy" },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return NextResponse.json({ state: "unreachable" }, { headers: { "Cache-Control": "no-store" } });
  }
}
