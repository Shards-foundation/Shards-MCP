# Agent Onboarding — identity, connectivity and first task

**Audience:** operators enrolling Cursor/Claude Code/Codex/VS Code workers or automated agents. Enrolment is host-only and **must not** be automated by an untrusted LLM.

## Identity lifecycle

1. Select a unique agent name, owner, runtime/provider, approved capabilities, minimum required scopes, expiry/review date and recovery contact in your external registry.
2. Privileged operator runs `shards-mcp-admin register --name ... --provider ... --scope ... --token-file ...` on the gateway host, with `SHARDS_DB` and bootstrap credential available securely.
3. Capture the returned agent ID. Give the generated secret only to that exact process using its secret store; mode `0600` file for local CLI.
4. Run `shards-mcp-doctor --token-file ... --protocol both --json` and confirm `agent_identity`. Record observed gateway address, scopes, tool list and SDK/IDE version.
5. Confirm a **denial test**: a worker-only agent must not discover or invoke `task_verify` or operator `system_status`.
6. For task execution, appoint a different creator and verifier. Use a non-consequential `echo` task before enabling any real integration.
7. At offboarding, revoke by agent ID via `shards-mcp-admin revoke AGENT_ID` and remove secrets from all runtimes. Verify reauthentication fails. Review retained data/backup policy separately.

## Roles and example scopes

| Role | Intended scopes | Not permitted |
| --- | --- | --- |
| Read-only observer | `agent:read` / `task:read` only if required | Claims, execution, verification |
| Sender | `task:create`, `task:read`; optional `message:send` | Task claim, verify |
| Worker | `agent:heartbeat`, `task:read`, `task:claim`, `task:update`, `checkpoint:write` | Task creation/verification |
| Verifier | `task:verify`, `task:read` | Worker execution |
| Operator | Bootstrap token strictly **host-only** | Never passed to LLM/IDE |

Actual owner visibility is enforced per request. A scope alone never grants cross-agent task access.

## Local vs off-host

- **Local/loopback:** agent receives unique local bearer secret from host-only CLI.
- **Remote HTTPS OAuth:** gateway runs `SHARDS_AUTH_MODE=oauth`; operator enrols exact `--oauth-subject`; client must obtain signed JWT from issuer with proper resource audience, subject and scopes. Local agent tokens are refused. The admin CLI **does not mint OAuth access tokens**.
- **Console sign-in:** provider OAuth only authenticates an allowlisted console user; it does not grant any gateway scope.

## Client configuration

The [web console connection hub](../web/README.md) generates starting templates, not certification for each IDE. Follow runtime-specific secret storage requirements. Never commit bearer strings to `mcp.json`, `AGENTS.md` or workspace settings.

## Intake record (store outside source control)

Agent ID, named human owner, approved scopes, provider, enrolment UTC time, token storage location identifier **not token**, approved environment, onboarding diagnostic output (redacted), denied action test, offboarding date and external-effects policy.

See the [agent enrolment skill](../skills/agent-onboarding/SKILL.md) and [rulebook](rulebook.md).
