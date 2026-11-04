
## Review-identified residual risks

- `agent_register` returns a newly generated bearer token. If called via an LLM holding the bootstrap token, that secret enters its tool transcript. Provision agents out of band and never connect the bootstrap administrator credential to a model.
- `event:read` and `audit:read` remain global organisational scopes. Event topics lack access-control lists. Do not include secrets in events or assume event contents are trustworthy.
- Verification evidence is persisted in plaintext SQLite. Add encryption, retention and access policy before accepting sensitive evidence.
- Audit UPDATE/DELETE triggers stop ordinary modifications, but a database owner can remove them and rehash the ledger. External immutable anchoring remains a production prerequisite.
- Socket timeouts and a 64-connection bound do not replace reverse proxy rate limiting, quotas and network protections.
- A length/diversity check is not proof of entropy: generate bootstrap secrets using a cryptographically secure source.

# Security policy and threat model

**v0.1.0 is experimental, single-organisation software.** Do not expose to the public internet or attach production wallets, financial accounts, secrets, or infrastructure write privileges.

- All MCP requests require a bearer credential. Administrator token is configured via SHARDS_ADMIN_TOKEN (>=32 characters, >=12 distinct characters; generate randomly). Agents receive unique randomly generated bearer tokens stored as SHA-256 digests.
- Agent authority derives from the authenticated credential, not arbitrary input. Agents cannot register or elevate their own privileges.
- Agent registration returns a credential once. Keep it in a secret manager, not a ChatGPT conversation. Revoke exposed credentials promptly.
- Localhost binding is the default; non-loopback requires SHARDS_ALLOW_REMOTE=1. Remote usage additionally requires a secure reverse proxy, TLS, rate limiting, network restrictions and proper OAuth 2.1 integration.
- Origin headers are denied unless explicitly allowlisted via SHARDS_ALLOWED_ORIGINS.
- Audit entries are committed with state mutations. The hash chain catches accidental edits, but a privileged database attacker can rewrite and rehash it; independent immutable audit anchoring is not yet implemented.
- The HTTP endpoint does not provide OAuth protected-resource metadata, JWT audience validation, credential expiry, SSE, multi-tenant isolation or rate limiting. **Do not claim broad ChatGPT plugin authentication compliance.**
- Prompt injection, untrusted task payloads, malicious agents, secret exfiltration, storage compromise, and external side-effect uncertainty remain risks.
- Use test credentials and non-consequential operations only. Backup and restore the SQLite file using the SQLite backup API, with encrypted off-host storage.

Report vulnerabilities using private GitHub reporting when enabled. Never post real credentials or exploit details in public issues.


## Event-topic and audit isolation (review follow-up)

- Non-admin principals can publish and read only their own \`agent.<authenticated_agent_id>.<topic>\` event namespaces and the organisation-wide \`shared.<topic>\` broadcast namespace.
- \`system.*\` event topics are administrator-only. Any shared event is untrusted, not an authoritative system instruction.
- Agent-scoped audit readers see only the audit rows they authored. Operators with bootstrap credentials may inspect all rows.
- This is **single-organisation** topic separation, not a multi-tenant security model. No per-topic subscriptions or topic permission grants beyond these namespaces are implemented.
