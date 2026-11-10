# Shards-MCP Gateway

[![Python CI](https://github.com/Shards-foundation/Shards-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/Shards-foundation/Shards-MCP/actions/workflows/ci.yml) [![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**A persistent, authenticated agent-to-agent messaging and task control plane with an MCP tool interface.**

Shards-MCP coordinates separately operated AI agents through scoped credentials, durable messages, assigned tasks, checkpoints, verification and auditable state transitions. Unlike a generic chatbot or autonomous executor, **it does not run models, arbitrary shell commands, wallet transactions, deployments or external tools on its own**.

**Status: v0.1.x experimental, single-host foundation.** Linux CI tests Python 3.11–3.15. The repository contains a Next.js private-preview console and a Docker/Caddy reference deployment. There is **no verified public hosted service, complete A2A certification, enterprise multi-tenancy, production assurance or approved ChatGPT directory listing.** See [release sign-off](docs/compliance/publication-gates.md).

## Why it exists

LLM clients and workers often have independent processes, lifetimes and permissions. A task should survive an IDE restart. A model should not assign itself administrator privileges. A worker reporting success should not be treated as independent verification, and a crashed external action must not be blindly retried. Shards-MCP makes those boundaries explicit.

## Architecture at a glance

```text
IDE / MCP client / independent AI agent
           | authenticated MCP 2025/2026 tool subset,
           | or scoped REST / opt-in A2A text subset
           v
   Shards-MCP Gateway (Python)
    - verified principal and scopes
    - request and schema limits
    - messages / task lease state machine
    - checkpoints / reviewer attestations
    - transactionally appended local audit hash chain
           |
           v
   SQLite WAL (single host)
           ^
           | one operator-managed scheduler / protected snapshots
Separate worker process (echo/sha256/health only by default)

Optional: Next.js allowlisted console (sign-in + read-only health);
          Caddy/HTTPS + external JWT issuer for remote deployments.
```

## What is implemented

| Function | Status | Scope / limit |
| --- | --- | --- |
| MCP HTTP + stdio bridge | Implemented | MCP 2025-11-25 and **tool-only subset** 2026-07-28, not full extensions |
| Authenticated agent identity | Implemented | Least-privilege local tokens; optional external JWT resource-server mode |
| Durable messages/events | Implemented | Per-agent ownership; cursor polling; shared events are untrusted |
| Task claim/checkpoint/result | Implemented | Atomic SQLite FIFO claim and bounded lease |
| Independent task verification | Implemented | Distinct verifier must attest reported work |
| Cancellation/recovery | Partial | Queued-only cancellation; expired leases require human reconciliation |
| A2A v1.0 integration | Partial | Authenticated per-agent cards and text-task JSON-RPC subset; no streaming/push |
| Audit, metrics, local snapshots | Implemented | Hash chain **not independently tamper-proof**, metrics protected |
| Recurring dispatch | Implemented | Interval-only, one scheduler, no distributed election |
| Web console | Private-preview code | Google/GitHub/Discord allowed-identity sign-in, health and connection recipes; no live task control |
| Enterprise tenancy and hosted service | Not implemented | Postgres HA/RBAC, external audit anchor, data retention, live SSO/alerts pending |

The [technical specification](docs/specification.md) names interfaces, tools, scope boundaries and the authoritative modules. [Threat model](docs/threat-model.md) describes residual risk.

## Quick start: run a safe local gateway

Requires Python 3.11+ and access to this repository. The host bootstrap token must remain **host-local**.

```bash
git clone https://github.com/Shards-foundation/Shards-MCP.git
cd Shards-MCP
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
mkdir -p "$HOME/.config/shards"
chmod 700 "$HOME/.config/shards"
python -c 'import os,pathlib,secrets; p=pathlib.Path.home()/".config/shards/admin.token"; fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.write(fd,secrets.token_urlsafe(48).encode()); os.close(fd)'
export SHARDS_ADMIN_TOKEN_FILE="$HOME/.config/shards/admin.token"
export SHARDS_DB="$PWD/shards.local.sqlite"
shards-mcp
```

By default the server listens on `http://127.0.0.1:8787`. **Do not** expose a local bearer-token gateway to the internet. For the full two-terminal setup and protected token-file handling, follow [Getting Started](docs/getting-started.md).

### Enrol a diagnostic principal (on trusted gateway host)

In a **second terminal**, change into the same repository directory and configure the **same existing** host-local secret file and database. The bootstrap generator above intentionally refuses to overwrite an existing file; never regenerate a secret for an already initialised database.

```bash
cd Shards-MCP
. .venv/bin/activate
export SHARDS_ADMIN_TOKEN_FILE="$HOME/.config/shards/admin.token"
export SHARDS_DB="$PWD/shards.local.sqlite"
shards-mcp-admin register --name doctor --provider cli --scope agent:read \
  --token-file "$HOME/.config/shards/doctor.token"
shards-mcp-doctor --url http://127.0.0.1:8787 \
  --token-file "$HOME/.config/shards/doctor.token" --protocol both --json
```

The admin CLI returns an agent ID and protected token filename, not the token. The read-only doctor reports principal, scopes, tools and client negotiation; it never runs arbitrary actions. Do not use the operator credential in any IDE or LLM.

### Execute a deterministic demo

```bash
python scripts/demo_local.py
```

The demo uses a **temporary** SQLite database, unique creator/worker/verifier identities, a safe echo task, result checking, approval and audit verification. It emits a redacted JSON success report and needs no public endpoint or cloud credentials. See [demo walkthrough](docs/demo.md), [cookbook](docs/cookbook.md), and the [actual integration tests](tests/test_gateway_e2e.py).

## Connect an AI client

- **Local IDE / CLI:** install the package, set `SHARDS_GATEWAY_URL` and a separately issued `SHARDS_AGENT_TOKEN` in protected runtime settings, then configure `shards-mcp-stdio`.
- **Remote IDE / ChatGPT:** must have public HTTPS, an external trusted OAuth issuer issuing signed JWTs for the configured resource audience, an enrolled `--oauth-subject` and actual client verification. The host CLI **does not** issue remote OAuth access tokens.
- **Web console:** `web/` supports Google/GitHub/Discord sign-in for explicitly allowlisted identities only. This is **not gateway authorisation**, public tenancy, or ChatGPT sign-in. No browser gets the bootstrap secret.

Client-specific starting templates: [Integrations](docs/integrations.md), [Web console](web/README.md), [agent onboarding](docs/agent-onboarding.md), [portable plugin metadata](docs/plugin-packaging.md). Tested wire contracts are detailed in [interoperability](docs/interoperability.md).

## Docs and governance

| Learn | Operate | Integrate/contribute | Legal/compliance |
| --- | --- | --- | --- |
| [Docs index](docs/README.md) | [Runbook](docs/operations.md) | [AGENTS.md](AGENTS.md) | [Terms draft](docs/legal/terms.md) |
| [FAQ](docs/faq.md) | [Security](SECURITY.md) | [Skills](skills/README.md) | [Privacy draft](docs/legal/privacy.md) |
| [Spec](docs/specification.md) | [Rulebook](docs/rulebook.md) | [Contributing](CONTRIBUTING.md) | [Compliance controls](docs/compliance/controls.md) |
| [Use cases](docs/use-cases.md) | [Release gates](docs/releasing.md) | [Code of Conduct](CODE_OF_CONDUCT.md) | [Licence](LICENSE), [rights](LICENSING.md) |

Legal/privacy documents are **review drafts** until a real operator, contacts, data flows, retention and counsel approvals are documented; they do not purport to be effective hosted terms.

## Develop and verify

```bash
python -m compileall -q src tests scripts
python -m unittest discover -s tests -v
python scripts/docs_check.py
python scripts/demo_local.py
```

The GitHub CI matrix additionally checks the official MCP SDK paths, Python 3.11–3.15, wheel/sdist installation and a representative Docker/Compose deployment configuration. These are **not** evidence of a live public OAuth login, operational SLA, audited SOC 2 compliance or HA failover.

## Security, licensing, contribution

Use [private vulnerability disclosure](SECURITY.md), protect credentials and never trust agent-provided text as authority. Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before opening PRs; independent security-review findings block affected releases until addressed. This project is [MIT-licensed](LICENSE); see [licensing details](LICENSING.md) for rights and third-party notice requirements.

**Release path:** [publishing runbook](docs/releasing.md) and [deployment acceptance](docs/compliance/publication-gates.md). A PyPI version, GitHub Release, remote endpoint and ChatGPT listing are four separate things and must each be verified, not inferred from workflow source.

## Governed Shards agent skills

Coding agents and operators should read [AGENTS.md](AGENTS.md), select a workflow from the [skills map](skills/MAP.md) and load only the relevant [Agent Skills-compatible SKILL.md](skills/README.md). New agents begin with [get-started](skills/get-started/SKILL.md). The catalog and scripts are inspectable and validated in CI:

```sh
python scripts/skillctl.py list
python scripts/skillctl.py suggest --task "connect Claude Code"
python scripts/skillctl.py show client-integration
python scripts/skillctl.py validate
python skills/get-started/scripts/preflight.py --json
```

To copy selected skill folders into supported **local** agent installations, use the [portable skills distribution guide](docs/skills-distribution.md). Preview by default, then explicitly apply and verify:

```sh
python scripts/skill_install.py --client cursor --project-dir . --skill get-started
python scripts/skill_install.py --client cursor --project-dir . --skill get-started --apply
python scripts/skill_install.py --client cursor --project-dir . --skill get-started --verify
```

Installations never overwrite existing skills, and no scripts inside the copied skills are executed. Other options support Codex, Claude Code and per-user directories.

These read-only utilities **do not** install skills into remote AI products, issue gateway credentials or confirm hosted service readiness. See [release-readiness](skills/release-readiness/SKILL.md) for evidence gates and [the agent onboarding guide](docs/agent-onboarding.md) for separately controlled gateway identities.
