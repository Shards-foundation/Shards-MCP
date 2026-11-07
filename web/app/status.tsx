"use client";
import { useEffect, useState } from "react";

export function GatewayHealth() {
  const [state, setState] = useState("checking");
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/gateway/health", { cache: "no-store", signal: controller.signal })
      .then(async response => {
        const data: unknown = await response.json();
        if (!response.ok && response.status !== 503) throw new Error("probe_failed");
        setState(typeof data === "object" && data !== null && "state" in data &&
          typeof data.state === "string" ? data.state : "unknown");
      })
      .catch(() => { if (!controller.signal.aborted) setState("probe_failed"); });
    return () => controller.abort();
  }, []);
  return <p role="status" aria-live="polite" className="status">{state.replaceAll("_", " ")}</p>;
}
