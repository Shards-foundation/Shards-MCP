import { getServerSession } from "next-auth";
import { NextResponse } from "next/server";
import { authOptions } from "@/lib/auth";
import {
  gatewayOrigin, InventoryError, invokeReadTool, isLocalAgentToken,
  requireReadOnlyIdentity, sanitiseInventory,
} from "@/lib/gateway-readonly";

export const dynamic = "force-dynamic";

export async function GET() {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "authentication_required" }, {
      status: 401, headers: { "Cache-Control": "no-store" },
    });
  }
  const rawUrl = process.env.SHARDS_GATEWAY_INTERNAL_URL;
  const token = process.env.SHARDS_CONSOLE_READ_TOKEN;
  if (!rawUrl || !token) {
    return NextResponse.json({ state: "unconfigured" }, {
      status: 503, headers: { "Cache-Control": "no-store" },
    });
  }
  if (!isLocalAgentToken(token)) {
    return NextResponse.json({ state: "configuration_error" }, {
      status: 503, headers: { "Cache-Control": "no-store" },
    });
  }
  try {
    const origin = gatewayOrigin(rawUrl);
    // Before reading the directory, prove this is a dedicated, read-only
    // gateway identity. Never use the root operator token in this console.
    const identity = await invokeReadTool(origin, token, "agent_identity");
    requireReadOnlyIdentity(identity);
    const agents = sanitiseInventory(await invokeReadTool(origin, token, "agent_list"));
    // Names are operator-supplied data: never reflect the credential by mistake.
    if (JSON.stringify(agents).includes(token)) {
      throw new InventoryError("invalid_gateway_response");
    }
    return NextResponse.json({ state: "connected", agents }, {
      headers: { "Cache-Control": "private, no-store" },
    });
  } catch (error) {
    const state = error instanceof InventoryError ? error.state : "gateway_unavailable";
    return NextResponse.json({ state }, {
      status: 503, headers: { "Cache-Control": "no-store" },
    });
  }
}
