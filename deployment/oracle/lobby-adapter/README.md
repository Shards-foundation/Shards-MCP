# Lobby local adapter for Agent Hub v0.2

**Status:** source-only local adapter. It is not installed, deployed, tunneled, exposed publicly, or accepted against a live service by this repository change. The test suite uses a fake upstream and real loopback HTTP only.

This is a small, stdlib-only Python process that lets a local Lobby client call the existing OpenClaw gateway through a narrow, authenticated, loopback-only HTTP contract. It is a translation and validation boundary, not a policy engine, sandbox, approval layer, or audit store.

## Fixed boundary

| Item | Value |
| --- | --- |
| Listener | `127.0.0.1:18790` only |
| Routes | `POST /chat`; authenticated `GET /health` |
| Upstream | `http://127.0.0.1:18789/v1/chat/completions` only |
| Model | `openclaw/shards` only |
| Adapter credential | Separate random secret in a mode-0600 file |
| Gateway credential | Read locally from `~/.openclaw/openclaw.json` |
| Forwarded caller headers | None |
| Proxies and redirects | Not used; any non-200 upstream response is rejected |
| Automatic retries | None |

The command-line interface has no bind-host, bind-port, upstream-host, upstream-path, or model override. `AdapterConfig` rejects a non-loopback bind or upstream host and any upstream path other than the fixed one.

## Request contract

`POST /chat` accepts exactly one JSON object with exactly two keys:

```json
{"conversation_id":"<canonical-uuid>","message":"text"}
```

Validation is strict and bounded:

- `conversation_id` must be canonical UUID text. Uppercase input is normalised to lowercase. Braces, URNs, and arbitrary session keys are rejected.
- `message` must be non-empty text, at most 8,000 characters and 12 KiB of UTF-8, with no C0 control characters other than newline, carriage return, and tab.
- Unknown keys are rejected. This includes `model`, `messages`, `role`, `system`, `session_key`, `tools`, `tool_choice`, `headers`, `url`, and `stream`.
- The body is at most 16 KiB. `Content-Type: application/json` and one valid `Content-Length` are required. Chunked transfer, content encoding, duplicate `Content-Length`, duplicate `Authorization`, duplicate `Host`, and duplicate `Content-Type` are rejected.
- The `Host` header must be `127.0.0.1:18790` or `localhost:18790`. Any `Origin` header is rejected, so browser-originated calls are not supported.
- The raw request target must equal the parsed path. This rejects absolute-form and doubled-slash routing attempts.

A successful response is:

```json
{"conversation_id":"<canonical-uuid>","reply":"text"}
```

Errors are sanitised:

```json
{"error":"fixed message"}
{"error":"upstream timeout","outcome":"unknown"}
```

No upstream response body, request body, adapter secret, or gateway token is returned to the caller or written to a log. Per-request `BaseHTTPRequestHandler` logging is disabled.

## Conversation namespace

The client never supplies a session key. For each valid conversation UUID the adapter derives:

```text
user = "lobby-" + sha256("shards-lobby-user-v1\0" + uuid).hexdigest()[:32]
```

The value is stable for the same UUID, opaque to the client, and different for a different UUID. It is sent as the OpenAI-compatible `user` field. This implementation assumes the gateway treats that field as the per-conversation namespace; verify that assumption on the target OpenClaw revision before relying on conversation continuity.

## Security model

- The adapter secret is generated with `secrets.token_urlsafe(48)` (384 bits of randomness), written with mode `0600` and `O_EXCL`, and compared in constant time through SHA-256 and `hmac.compare_digest`. The value is never printed by the CLI.
- The gateway token is read only from `gateway.auth.token` or `gateway.token` in the local OpenClaw config. Missing, conflicting, non-string, non-ASCII, or malformed tokens fail closed. The config and secret files must be regular, owner-owned, and not accessible by group or others.
- The gateway token is placed only in the fixed upstream `Authorization` header. It is not forwarded from the caller, logged, returned, or used for the downstream adapter credential.
- `http.client.HTTPConnection` connects directly to the fixed loopback address. It does not read proxy environment variables, and the adapter does not follow redirects.
- Active chat handling is capped at four concurrent requests; excess valid requests receive `503 busy`. Request-body reads have a 10-second total deadline, upstream calls have a 30-second timeout, request bodies are capped at 16 KiB, and upstream responses are capped at 256 KiB.
- A timeout or connection failure after dispatch is reported as `outcome: unknown`. The adapter makes exactly one upstream attempt and never retries an ambiguous inference outcome automatically.

## Prompt-only "no tools" does not enforce policy

This adapter sends no `tools` or `tool_choice` fields and does not add a system prompt. It therefore does **not** enforce a "no tools" policy, and a prompt that says "do not use tools" is not an enforcement control. Tool availability remains whatever the existing OpenClaw gateway already grants. The adapter does not widen, create, or change gateway approvals, tool permissions, identity, or policy. It also does not record an audit trail of its own; use the gateway's existing controls for that.

## Preconditions

1. The existing OpenClaw 2026.11.8 revision `2d4ab29` is already running as the unprivileged `openclaw` user, with the gateway on `127.0.0.1:18789`, native `/v1/chat/completions` enabled, and model `openclaw/shards` authenticated. This change does not install, configure, restart, or modify OpenClaw.
2. Run the adapter as the same unprivileged `openclaw` user so `HOME` resolves to that user's home and the credential files have the expected owner.
3. `~/.openclaw/openclaw.json` must be owned by that user and mode `0600` because it contains the gateway token. If it is not, record the original mode, then `chmod 600 ~/.openclaw/openclaw.json`. This is reversible and does not change the token.
4. No package installation, new runtime, systemd unit, firewall rule, tunnel, Cloudflare Access change, DNS change, public listener, or production deployment is part of this adapter.

## Local setup and smoke test

From the repository root, as the `openclaw` user:

```sh
python3 deployment/oracle/lobby-adapter/lobby_adapter.py init-secret
```

This creates `~/.openclaw/lobby-adapter.secret` with mode `0600`, refuses to overwrite an existing file, and prints only the path. The secret value is never printed. Read it locally into a client configuration; do not commit it, paste it into a ticket, or send it to a log.

Start the adapter:

```sh
python3 deployment/oracle/lobby-adapter/lobby_adapter.py serve
```

The startup line reports the fixed listener, upstream URL, and model, and contains no credential. If the bind fails or a credential file fails validation, the process exits with status `2` and a sanitised message.

Optional local smoke test, with the gateway already running:

```sh
read -r LOBBY_TOKEN < ~/.openclaw/lobby-adapter.secret
curl -sS -H "Authorization: Bearer $LOBBY_TOKEN" http://127.0.0.1:18790/health
CONV=$(python3 -c 'import uuid; print(uuid.uuid4())')
curl -sS -H "Authorization: Bearer $LOBBY_TOKEN" \
  -H 'Content-Type: application/json' \
  --data "{\"conversation_id\":\"$CONV\",\"message\":\"Reply with one short sentence.\"}" \
  http://127.0.0.1:18790/chat
```

The second command performs real local inference if the gateway is live. It is an operator action, not part of the automated tests. Do not paste the token into shell history, CI logs, screenshots, or tickets.

### Reversible cleanup

- Stop the process with `Ctrl-C`. No service manager, boot hook, or scheduled task is installed.
- Remove the adapter credential with `rm ~/.openclaw/lobby-adapter.secret`. Existing clients then receive `401`.
- If you changed the OpenClaw config mode, restore the recorded original mode.
- No repository file, gateway configuration, tunnel, Access policy, DNS record, or production state is changed by setup or cleanup.

## Tests

Run the local suite:

```sh
python3 -m unittest discover -s deployment/oracle/lobby-adapter -p 'test_*.py' -v
```

The suite starts a fake upstream and a real loopback adapter, then covers:

- positive request and fixed upstream shape;
- missing, wrong, malformed, and duplicate authentication;
- malformed JSON, duplicate keys, invalid UUIDs, control characters, oversize bodies, and oversize messages;
- arbitrary routing attempts, unknown fields, wrong `Host`, and browser `Origin`;
- busy/concurrency rejection and slow request-body timeout;
- upstream error, timeout, redirect, invalid JSON, empty choices, and oversize response;
- proxy environment variables being ignored;
- secret/config file permissions, symlinks, conflicts, and CLI output redaction;
- request bodies and credentials not appearing in logs or responses.

No test contacts the live gateway, a host service, Cloudflare, or an external provider. A green local suite is evidence for this adapter's code paths only; it is not hosted acceptance, OpenClaw compatibility certification, or a production claim.

## Limitations

- Source-only and local-only. Nothing is installed, deployed, tunneled, or publicly exposed.
- The gateway revision, `/v1/chat/completions` behaviour, `user` namespace semantics, and model availability are assumed from the stated environment; the automated tests do not prove them.
- Single-turn transport: the adapter sends one user message per request. Conversation continuity depends on the gateway's handling of the derived `user` value; the adapter stores no history.
- Text only, no streaming, no files, images, audio, tools, or tool approval changes.
- No automatic retry. `outcome: unknown` means the caller must reconcile or retry deliberately.
- Concurrency is capped for active chat requests; this is not a general-purpose rate limiter or denial-of-service defence for the loopback host.
- Browser clients are rejected by the `Origin` rule; use a local CLI or desktop client.
- The adapter refuses group/other-accessible credential files. It does not repair host permissions.
- No hot reload: restart the adapter after rotating the adapter secret or gateway token.
- Not supported on Windows because it uses `os.geteuid` and `O_NOFOLLOW`.
- This adapter does not replace Cloudflare Access, a tunnel, the Hub, or the Edge gateway, and it does not expand their authority.

See [AGENTS.md](../../../AGENTS.md), [SECURITY.md](../../../SECURITY.md), and the [Agent Hub release boundary](../../cloudflare/agent-hub/README.md) for the surrounding repository rules.
