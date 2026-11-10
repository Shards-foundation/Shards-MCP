# Contributing to Shards-MCP

Thanks for contributing. The project optimises for verifiable, least-privilege working software rather than implementation volume or speculative feature coverage.

## Before starting

Read [README](README.md), [AGENTS.md](AGENTS.md), [security policy](SECURITY.md), [technical specification](docs/specification.md), [rulebook](docs/rulebook.md) and [governance](GOVERNANCE.md). For larger features, open an issue defining user value, failure modes, bounded scope, acceptance tests and alternatives. Do not put secrets or customer data in the issue.

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[oauth]'
python -m pip install 'mcp==2.0.0'
python -m compileall -q src tests scripts
python -m unittest discover -s tests -v
python scripts/docs_check.py
python scripts/demo_local.py
```

Relevant focused checks:

```bash
python -m unittest discover -s tests -p 'test_protocol_hardening.py' -v
python -m unittest discover -s tests -p 'test_gateway_e2e.py' -v
python -m unittest discover -s tests -p 'test_official_sdk.py' -v
```

Full CI tests Linux Python **3.11–3.15** including an isolated official MCP SDK 2.3.0 environment, wheel/sdist build and representative container configuration. Never claim Windows/macOS/platform support from this Linux matrix.

### Web console

```bash
cd web
npm ci --no-audit --no-fund
npm run typecheck
npm run build
```

No OAuth provider secrets should enter test fixtures or PRs. Hosted provider callback tests require separately approved test accounts and a real environment.

## PR quality checklist

- **Scope:** one bounded problem, risk and acceptance criterion; avoid unrelated refactors.
- **Tests:** reproducer for a bug, adversarial negative tests for scopes/JSON/OAuth/recovery, documented expected state transitions.
- **Docs:** update README/spec/architecture/FAQ/examples if public behaviour changes; refresh privacy inventory for new personal data, security model for new trust boundaries.
- **Security:** no bootstrap token in clients; no plaintext secrets; no financial/external-effect executor without separate safety and approval design.
- **Validation:** attach exact SHA, test command, results, skip rationale, known limitations and rollback procedure.
- **Review:** address independent inline review threads; do not dismiss confirmed release-blocking findings to force a green badge.
- **Dependencies:** explain why added, pin where appropriate, verify their licence and supply-chain risks.

Use Conventional Commit style where practical (`feat:`, `fix:`, `docs:`, `test:`, `ci:`). PR body should identify affected public APIs, security/data changes, tests executed and remaining rollout controls.

## Supported scope vs aspirational work

No automatic shell execution, distributed exactly-once side effects, cross-host HA, multi-tenant RBAC or full A2A/ChatGPT conformity exists today. Contributors proposing them must supply a threat model and E2E acceptance plan rather than silently changing product claims.

## Maintainer and legal policy

The canonical [MIT licence](LICENSE) governs covered project code. Only contribute content you have rights to share and preserve third-party attribution. Security issues must use private disclosure, not a public pull request with working exploit details. Changes to external legal terms or compliance statements require named human approvers before publication.
