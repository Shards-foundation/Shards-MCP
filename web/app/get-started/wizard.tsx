"use client";

import { useState } from "react";
import { CLIENTS, MCP_ENDPOINT, clientPayload, clientSteps, cursorInstallUrl, type ClientId } from "@/lib/connectors";

export function ConnectionWizard() {
  const [chosen, setChosen] = useState<ClientId>("cursor-app");
  const [copied, setCopied] = useState(false);
  const client = CLIENTS.find(c => c.id === chosen)!;
  const value = clientPayload(chosen);
  const steps = clientSteps(chosen);
  function download() {
    const blob = new Blob([value + "\n"], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "shards-cursor-mcp.json";
    anchor.click();
    URL.revokeObjectURL(url);
  }
  async function copy() {
    try { await navigator.clipboard.writeText(value); setCopied(true); }
    catch { setCopied(false); }
  }
  return <section className="wizard" aria-label="Client connection wizard">
    <div className="wizard-list"><div className="eyebrow">01 / CHOOSE A CLIENT</div>
      <div className="client-choices">{CLIENTS.map(item => <button key={item.id} type="button" aria-pressed={chosen === item.id} onClick={() => { setChosen(item.id); setCopied(false); }} className={chosen === item.id ? "client-choice selected" : "client-choice"}>
        <strong>{item.name}</strong><small>{item.category}</small><span aria-hidden="true">↗</span>
      </button>)}</div>
    </div>
    <div className="wizard-main"><div className="eyebrow">02 / INSTALL AND AUTHORISE</div>
      <div className="wizard-head"><div><h2>{client.name}</h2><p>Official client configuration · HTTPS · OAuth-enabled endpoint</p></div><span className="protocol-pill">MCP / HTTP</span></div>
      <div className="endpoint-label">ENDPOINT</div><div className="endpoint-box"><code>{MCP_ENDPOINT}</code><button type="button" onClick={() => void navigator.clipboard.writeText(MCP_ENDPOINT).then(() => setCopied(true)).catch(() => setCopied(false))}>Copy URL</button></div>
      <div className="endpoint-label">{client.mode === "command" ? "TERMINAL" : client.mode === "config" ? "CONFIGURATION" : "CONNECTOR URL"}</div>
      <pre className="wizard-code"><code>{value}</code></pre>
      <div className="wizard-actions">
        {chosen === "cursor-app" && <a className="primary-cta" href={cursorInstallUrl()}>Install in Cursor</a>}
        <button className="primary-cta" type="button" onClick={() => void copy()}>{copied ? "Copied" : client.mode === "command" ? "Copy commands" : client.mode === "url" ? "Copy endpoint" : "Copy config"}</button>
        {client.mode === "config" && <button className="secondary-cta" onClick={download} type="button">Download JSON</button>}
        <a className="secondary-cta" href={client.docs} target="_blank" rel="noopener noreferrer">Official client docs</a>
      </div>
      <div className="wizard-steps"><h3>Connection sequence</h3><ol>{steps.map(step => <li key={step}>{step}</li>)}</ol></div>
      <p className="wizard-warning">Server registration, OAuth issuer metadata and scope grants must be operational before authentication succeeds. Importing the config alone is not proof of connectivity.</p>
    </div>
  </section>;
}
