const MAX_RESPONSE_BYTES = 262_144;
const MAX_AGENTS = 500;
// The local agent issuer creates shards_ + token_urlsafe(36). Reject operator
// secrets and OAuth tokens rather than accidentally accepting a broad credential.
const LOCAL_AGENT_TOKEN = /^shards_[A-Za-z0-9_-]{48}$/;

type InventoryState =
  | "configuration_error"
  | "unconfigured"
  | "permission_denied"
  | "gateway_unavailable"
  | "invalid_gateway_response";

export class InventoryError extends Error {
  constructor(readonly state: InventoryState) {
    super(state);
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function gatewayOrigin(value: string): URL {
  // URL() normalises newlines and whitespace: reject the original input first.
  if (!value || /[\s\u0000-\u001f\u007f\\?#]/u.test(value) ||
      !/^https?:\/\/[^/?#]+\/?$/i.test(value)) {
    throw new InventoryError("configuration_error");
  }
  try {
    const url = new URL(value);
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if ((url.protocol !== "https:" && !(url.protocol === "http:" && local)) ||
        url.username || url.password || url.port === "0" ||
        url.pathname !== "/" || url.search || url.hash) {
      throw new InventoryError("configuration_error");
    }
    return url;
  } catch {
    throw new InventoryError("configuration_error");
  }
}

export async function readBoundedJson(response: Response): Promise<unknown> {
  if (!(response.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json")) {
    throw new InventoryError("invalid_gateway_response");
  }
  const stream = response.body?.getReader();
  if (!stream) throw new InventoryError("invalid_gateway_response");
  const parts: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await stream.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_RESPONSE_BYTES) throw new InventoryError("invalid_gateway_response");
      parts.push(value);
    }
  } finally {
    stream.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) {
    bytes.set(part, offset);
    offset += part.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown;
  } catch {
    throw new InventoryError("invalid_gateway_response");
  }
}

export async function invokeReadTool(origin: URL, token: string, name: "agent_identity" | "agent_list"): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(new URL("/v1/tools/" + name, origin), {
      method: "POST",
      headers: {
        Authorization: "Bearer " + token,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: "{}",
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(3000),
    });
  } catch {
    throw new InventoryError("gateway_unavailable");
  }
  if (response.status === 401 || response.status === 403) {
    throw new InventoryError("permission_denied");
  }
  if (response.status !== 200) {
    throw new InventoryError("gateway_unavailable");
  }
  const value = await readBoundedJson(response);
  if (!isRecord(value) || value.ok !== true || !("result" in value)) {
    throw new InventoryError("invalid_gateway_response");
  }
  return value.result;
}

export type AgentRow = {
  id: string;
  name: string;
  provider: string;
  scopes: string[];
  revoked: boolean;
  heartbeat_state: "recent" | "stale" | "unobserved" | "revoked";
  last_seen: string | null;
};

export function sanitiseInventory(input: unknown): AgentRow[] {
  if (!Array.isArray(input) || input.length > MAX_AGENTS) {
    throw new InventoryError("invalid_gateway_response");
  }
  return input.map((item: unknown) => {
    if (!isRecord(item) ||
        typeof item.id !== "string" || !/^agt_[0-9a-f]{24}$/.test(item.id) ||
        typeof item.name !== "string" || item.name.length > 200 ||
        typeof item.provider !== "string" || item.provider.length > 200 ||
        !Array.isArray(item.scopes) || item.scopes.length > 32 ||
        !item.scopes.every((scope: unknown) => typeof scope === "string" && scope.length <= 64) ||
        typeof item.revoked !== "boolean" ||
        !["recent", "stale", "unobserved", "revoked"].includes(String(item.heartbeat_state)) ||
        !(item.last_seen === null || (typeof item.last_seen === "string" && item.last_seen.length <= 64))) {
      throw new InventoryError("invalid_gateway_response");
    }
    return {
      id: item.id,
      name: item.name,
      provider: item.provider,
      scopes: item.scopes as string[],
      revoked: item.revoked,
      heartbeat_state: item.heartbeat_state as AgentRow["heartbeat_state"],
      last_seen: item.last_seen as string | null,
    };
  }).sort((a: AgentRow, b: AgentRow) => a.name.localeCompare(b.name));
}

export function isLocalAgentToken(token: string): boolean {
  return LOCAL_AGENT_TOKEN.test(token);
}

export function requireReadOnlyIdentity(identity: unknown): void {
  if (!isRecord(identity) || identity.role !== "agent" ||
      typeof identity.agent_id !== "string" ||
      !/^agt_[0-9a-f]{24}$/.test(identity.agent_id) ||
      !Array.isArray(identity.scopes) || identity.scopes.length !== 1 ||
      identity.scopes[0] !== "agent:read") {
    throw new InventoryError("permission_denied");
  }
}
