---
name: agent-onboarding
description: Safely enrol, validate and offboard a least-privileged Shards-MCP agent through host-local admin controls.
---
# Agent Onboarding

**Trigger:** new CLI/IDE/worker principal or credential rotation. **Operator authority required.** Never enrol from a model-visible network tool.

1. **Inputs:** gateway host, approved agent name/provider, owner, necessary scopes, intended runtime, protected unused token-file path and expiry review date. Stop if owner or purpose is unknown.
2. **Prerequisites:** local access to host-only `SHARDS_DB`, `SHARDS_ADMIN_TOKEN`, directory mode 0700, current matching gateway version. Do not reveal the secret.
3. **Execute:** `shards-mcp-admin register --name NAME --provider PROVIDER --scope agent:read --token-file PATH`, replacing example with a reviewed role-specific scope set; never use `*`.
4. **Verify:** capture returned agent ID, run `shards-mcp-doctor --url GATEWAY_URL --token-file PATH --protocol both --json` with gateway URL, confirm principal and tool list. Negative-test that an unrelated admin/verify tool is denied.
5. **Handover:** give token only through target runtime secret store and restrict file permissions to 0600. Do not paste token into PR/prompt.
6. **Offboard/recover:** revoke using `shards-mcp-admin revoke AGENT_ID`; ensure old connection fails; store redacted evidence.
7. **Output:** agent ID, named owner, exact scopes, diagnostic output hash/redacted summary, denied-tool result, rotation date, status PASS/FAIL. If any negative test fails, revoke and stop.
