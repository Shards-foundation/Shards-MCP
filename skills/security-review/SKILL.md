---
name: security-review
description: Bounded adversarial review of Shards-MCP trust boundaries and CI evidence; never assert certification without deployment tests.
---
# Security Review

**Trigger:** auth/OAuth, task-state, protocol parser, database, releases, token or console changes.

1. **Inputs:** exact commit SHA/PR, changed paths, threat assumptions, affected scopes and test environment. Require redacted test credentials.
2. **Inspect:** `SECURITY.md`, `docs/threat-model.md`, `src/shards_mcp/server.py` permission map, `src/shards_mcp/core.py` ownership constraints and relevant tests.
3. **Exercise:** denial of absent/revoked credentials, malformed JSON, wrong OAuth issuer/audience, cross-agent ownership, concurrent claim/cancel, worker double-completion and audit mutation. Use only isolated test DB.
4. **Assess:** severity (P0 exploit/bypass, P1 serious isolation or integrity, P2 hardening, P3 documentation). Every finding needs reproduction, affected SHA and recommended fix.
5. **Verify remediation:** add targeted regression; run full CI matrix as appropriate; independent reviewer threads must be addressed before merge.
6. **Output:** evidence links, pass/fail per invariant, untested boundaries, critical blockers and binary deployment GO/NO-GO. Never claim no vulnerabilities based solely on green tests.
