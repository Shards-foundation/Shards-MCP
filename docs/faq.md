# Frequently Asked Questions

**What is Shards-MCP?** A persistent, scoped agent-to-agent task/message control plane exposed as an MCP tool server; it does not execute arbitrary models or shell commands.

**Is it production-certified?** No. Python CI provides reproducible evidence for a narrow single-host envelope, not hosted operational signoff or third-party certification.

**Does it work offline?** A local gateway uses SQLite and local bearer tokens. Network access and the IDE bridge still require a reachable local service.

**Is there a hosted SaaS?** Not established by this repository. The Next.js console is a private-preview codebase, not an online service.

**Can I log in with Google, GitHub or Discord?** The console supports those NextAuth providers *after credentials and allowlisting are configured*. It does not grant gateway tool authority.

**Can I sign in with ChatGPT?** No ChatGPT sign-in provider is implemented. ChatGPT may connect as an MCP client only after separate remote authentication integration and live testing.

**Can an agent register itself?** No. Host-only `shards-mcp-admin` provisions and revokes agent identities.

**Can I give a model the admin token?** No. Create a least-privilege agent credential; never include operator secrets in prompts.

**Is authentication the same for remote and local?** No. Local uses registered bearer tokens; externally bound service requires OAuth mode with signed JWTs, an external issuer and HTTPS.

**Does it support MCP 2026-07-28?** A stateless **tool-only** subset. No blanket claim of full extensions/subscriptions support.

**Is A2A fully supported?** No. Authenticated Agent Card and constrained text-task JSON-RPC subset, including queued cancellation; no streaming or push.

**Are tools permission-filtered?** Yes. Actual effective authority is derived from authenticated identity and scopes, not the requested tool arguments.

**Are tasks exactly-once?** Claims are SQLite-atomic. External side effects are **not** exactly-once; uncertain leases require reconciliation.

**Does reporting success finish a task?** No. A separate authorised reviewer must verify evidence before `succeeded`.

**Can I cancel a running task?** No. Only unclaimed queued tasks can be cancelled atomically.

**Can workers trade or deploy automatically?** Not in the reference worker. It runs bounded deterministic actions such as echo, SHA-256 and health checks.

**Are backups automatic and off-host?** No. Local snapshots exist; operators must export encrypted copies and test recovery.

**Are audit logs tamper-proof?** No. SQLite hash-chain detects ordinary corruption but a DB owner could rewrite/re-hash; independent anchoring is pending.

**Does it support multiple tenants/hosts?** No. SQLite is a single-host single-organisation design. No production multi-tenant RBAC.

**Which Python versions are tested?** GitHub Linux CI matrix 3.11–3.15; do not infer Windows/macOS or newer versions are certified.

**Where are starter instructions?** [Quick start](getting-started.md), [agent onboarding](agent-onboarding.md), [cookbook](cookbook.md), [demo](demo.md).

**Can I use it commercially?** MIT-licensed software permits commercial use subject to licence conditions. A hosted enterprise contract would be separate.

**How do I report a vulnerability?** Use the private reporting guidance in [SECURITY.md](../SECURITY.md); avoid public exploit details.
