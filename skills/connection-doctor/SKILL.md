---
name: connection-doctor
description: Read-only Shards-MCP transport and permission diagnosis for a separately enrolled agent.
---
# Read-Only Connection Diagnostic

**Trigger:** IDE cannot discover tools, returns HTTP 401/403 or wrong protocol version. No admin credential.

1. **Input:** exact loopback HTTP or trusted HTTPS base URL, permitted scoped credential file, client/runtime version and expected scopes.
2. **Safety gate:** reject embedded URL credentials, non-loopback plaintext, redirect chains or admin identity. For remote OAuth, obtain signed issuer token through approved client flow, not local admin CLI.
3. **Execute:** `shards-mcp-doctor --url URL --token-file TOKEN_FILE --protocol both --json`.
4. **Evaluate:** both 2025-11-25 and 2026-07-28 tool subsets must return same principal/effective tool authority. A modern failure must not silently fall back. Record redacted latency and versions.
5. **Diagnose:** 401 -> credential/issuer/audience; 403 -> scopes; unreachable -> DNS/port/TLS; mismatch -> protocol metadata or client version. Do not brute-force token values.
6. **Output:** PASS/FAIL, gateway address class (not token), client version, protocol and authority checks, probable fault and smallest safe repair. Stop immediately on unexpected privileged tool discovery.
