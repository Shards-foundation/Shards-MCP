"use client";

import { useCallback, useEffect, useState } from "react";

type Agent = {
  id: string;
  name: string;
  provider: string;
  scopes: string[];
  revoked: boolean;
  heartbeat_state: "recent" | "stale" | "unobserved" | "revoked";
  last_seen: string | null;
};

const explanations: Record<string, string> = {
  unconfigured: "Set SHARDS_GATEWAY_INTERNAL_URL and SHARDS_CONSOLE_READ_TOKEN on the console server.",
  configuration_error: "The server-side gateway configuration is invalid or its credential is not a local scoped agent token.",
  permission_denied: "The configured token must identify one active gateway agent with exactly agent:read permission.",
  gateway_unavailable: "The configured gateway did not respond successfully. Check its internal address and network health.",
  invalid_gateway_response: "The gateway returned an invalid or excessively large inventory response.",
  authentication_required: "Your console session has expired. Sign in again.",
  unexpected_response: "The console returned an unexpected response.",
};

function localTime(value: string | null): string {
  if (!value) return "Never recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Invalid timestamp";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Europe/London",
  }).format(date) + " UK";
}

function isAgent(value: unknown): value is Agent {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<Agent>;
  return typeof item.id === "string" && typeof item.name === "string" &&
    typeof item.provider === "string" && typeof item.revoked === "boolean" &&
    Array.isArray(item.scopes) &&
    item.scopes.every((scope: unknown) => typeof scope === "string") &&
    ["recent", "stale", "unobserved", "revoked"].includes(String(item.heartbeat_state)) &&
    (item.last_seen === null || typeof item.last_seen === "string");
}

export function AgentInventory() {
  const [state, setState] = useState("checking");
  const [agents, setAgents] = useState<Agent[]>([]);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setState("checking");
    try {
      const response = await fetch("/api/gateway/agents", { cache: "no-store", signal });
      const data: unknown = await response.json();
      if (signal?.aborted) return;
      if (typeof data !== "object" || data === null || !("state" in data) ||
          typeof data.state !== "string") {
        setState(response.status === 401 ? "authentication_required" : "unexpected_response");
        setAgents([]);
        return;
      }
      if (response.ok && data.state === "connected" && "agents" in data &&
          Array.isArray(data.agents) && data.agents.every(isAgent)) {
        setAgents(data.agents);
        setState("connected");
      } else {
        setAgents([]);
        setState(response.status === 401 ? "authentication_required" : data.state);
      }
    } catch {
      if (!signal?.aborted) {
        setAgents([]);
        setState("gateway_unavailable");
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  const active = agents.filter(agent => !agent.revoked);
  const recent = active.filter(agent => agent.heartbeat_state === "recent");

  return <section className="panel" aria-label="Live agent registry">
    <div className="registry-heading">
      <div><div className="eyebrow">LIVE GATEWAY DATA</div><h2>Registered identities</h2>
        <p className="muted">Read-only inventory. Heartbeat state is based on the gateway’s recorded observations, not a live process guarantee.</p>
      </div>
      <button className="action" type="button" onClick={() => void refresh()} disabled={state === "checking"}>Refresh</button>
    </div>
    {state === "checking" ? <p role="status">Reading gateway inventory…</p> : null}
    {state !== "checking" && state !== "connected" ?
      <p role="alert">Inventory unavailable: {explanations[state] ?? explanations.unexpected_response}</p> : null}
    {state === "connected" ? <>
      <p role="status"><strong>{active.length} active</strong> · {recent.length} recent heartbeat · {agents.length - active.length} revoked · {agents.length} registered</p>
      {agents.length === 0 ? <p>No agents have been registered with this gateway.</p> :
        <div className="registry-scroll">
          <table className="registry-table">
            <thead><tr><th scope="col">Identity</th><th scope="col">Heartbeat</th><th scope="col">Granted scopes</th><th scope="col">Last observed</th></tr></thead>
            <tbody>{agents.map(agent => <tr key={agent.id}>
              <td><strong>{agent.name}</strong><small>{agent.provider} · {agent.id}</small></td>
              <td>{agent.heartbeat_state.replaceAll("_", " ")}</td>
              <td>{agent.scopes.length ? agent.scopes.join(", ") : "None"}</td>
              <td>{localTime(agent.last_seen)}</td>
            </tr>)}</tbody>
          </table>
        </div>}
    </> : null}
  </section>;
}
