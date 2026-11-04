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
