# Getting Started — local first-run

**Supported envelope:** Python 3.11–3.15 on the tested Linux CI matrix; self-hosted single-user/single-organisation SQLite. A remote deployment requires a separate OAuth issuer and HTTPS.

## 1. Install

```bash
git clone https://github.com/Shards-foundation/Shards-MCP.git
cd Shards-MCP
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
shards-mcp --help
```

A private repository requires GitHub access; the command does not imply anonymous cloning. For a verified public PyPI release, use the published package version; confirm registry availability before recommending a version pin.

## 2. Start local gateway (terminal one)

```bash
export SHARDS_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export SHARDS_DB="$PWD/shards.local.sqlite"
shards-mcp
```

The gateway listens on `127.0.0.1:8787` by default. Do not expose the bootstrap credential to another process or model. The terminal retains the secret; use protected secret files outside demonstrations.

## 3. Enrol a diagnostic agent (terminal two)

Use the **same** `SHARDS_ADMIN_TOKEN` and `SHARDS_DB` as terminal one, supplied securely by the operator. Do not generate a new admin secret for the existing database.

```bash
mkdir -p "$HOME/.config/shards"
chmod 700 "$HOME/.config/shards"
shards-mcp-admin register --name local-diagnostic --provider cli \
  --scope agent:read \
  --token-file "$HOME/.config/shards/diagnostic.token"
```

The command returns an agent ID and token-file path, not the raw token in the console. Retain the agent ID for later revocation.

## 4. Check read-only connection

```bash
export SHARDS_GATEWAY_URL=http://127.0.0.1:8787
shards-mcp-doctor --token-file "$HOME/.config/shards/diagnostic.token" --protocol both --json
```

Expect `ok: true` with an enrolled agent identity and scoped tools. The probe performs **no mutations**. If it fails, check the gateway address, token-file permissions and whether the agent is revoked. See [connection skill](../skills/connection-doctor/SKILL.md).

## 5. Try the safe reference worker

Enrol a separate worker with `agent:heartbeat`, `task:read`, `task:claim`, `task:update` and `checkpoint:write`; create a different creator principal with `task:create`. Follow the [task lifecycle cookbook](cookbook.md) or run [the local demo](demo.md). No arbitrary shell or LLM execution is included.

## 6. Remote deployment is separate

Never simply set `SHARDS_BIND=0.0.0.0` with a local bearer credential. Use the [deployment runbook](../deploy/README.md) with a real HTTPS host, trusted issuer, audience/subject scopes, external monitoring and backups. Web console sign-in is a separate identity boundary.
