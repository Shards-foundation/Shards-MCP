# Read-only A2A 1.0 connection doctor

shards-a2a-doctor exercises the existing constrained Shards-MCP A2A
JSON-RPC endpoint using a scoped agent credential. It is a client
diagnostic, **not** an A2A conformance certification or a transport
deployment.

## Preconditions

- A reachable Shards-MCP gateway with the A2A adapter configured.
- An enrolled target worker ID of the form agt_ followed by 24 lowercase
  hexadecimal characters.
- A separately provisioned **scoped agent token** with agent:read and
  task:read. Never use the bootstrap administrator credential.
- TLS for non-loopback endpoints. Redirects and HTTP proxy forwarding are
  disabled by the diagnostic client.

To run locally from an installed Shards-MCP package:

~~~bash
export SHARDS_GATEWAY_URL=http://127.0.0.1:8787
export SHARDS_AGENT_TOKEN="$(cat "$HOME/.config/shards/reader.token")"
shards-a2a-doctor --target-agent agt_REPLACE_WITH_ENROLLED_ID --json
~~~

The placeholder ID above must be replaced with the actual enrolled target
agent identifier. Prefer a protected file over a shell environment variable:

~~~bash
unset SHARDS_AGENT_TOKEN
shards-a2a-doctor \
  --url http://127.0.0.1:8787 \
  --target-agent agt_REPLACE_WITH_ENROLLED_ID \
  --token-file "$HOME/.config/shards/reader.token" \
  --json
~~~

File mode inherits the existing Shards doctor safeguards: no symlinks,
no unsafe group/world file permissions on POSIX and no oversized or
nonregular secret input.

## What is verified

1. Verify the caller is a **scoped agent** through the existing read-only Shards MCP initialize / agent_identity workflow; reject an operator token regardless of local administrator environment variables. Require agent:read and task:read.
2. Fetch GET /a2a/agents/ID/card using the scoped bearer token.
3. Validate that the Agent Card advertises exactly the requested
   JSONRPC v1.0 endpoint, declared nonstreaming capabilities, the bearer
   scheme and the explicit non-anonymous securityRequirements entry.
4. Send a JSON-RPC GetTask request with the A2A-Version: 1.0 header
   for a newly generated random, nonexistent task ID.
5. Require the matching JSON-RPC response ID, required string error message and the documented
   task-not-found error. A permission error, unexpected successful
   task result, wrong protocol version, malformed JSON or redirect
   is a diagnostic failure.
6. Return JSON with verified caller/target IDs, protocol version, round-trip latency
   and verified probe semantics.

The tool does not invoke SendMessage, CancelTask, worker execution,
checkpoint writes, registration, task claims or verification. The
random GetTask probe is deliberately read-only.

## Security and correctness constraints

- The CLI accepts only a validated Shards target agent ID.
- Response size, JSON nesting, duplicate JSON keys and nonfinite
  values are checked before trusting remote data.
- Credentials are not included in reports or error messages;
  reflected credentials invalidate the run.
- A missing or ambiguous required bearer-auth declaration fails closed.
- Unknown versions or endpoint mismatches fail closed without
  automatic protocol downgrades.
- The report intentionally omits the untrusted Agent Card name,
  server error body and token-bearing request headers.
- A successful run demonstrates **only** read-only Card + GetTask
  compatibility with this gateway/identity at this time.
- It does not assert multi-turn support, streaming, remote task
  creation, independent verification semantics, full A2A conformance,
  or cross-platform compatibility.

## Verification

~~~bash
python -m unittest tests.test_a2a_doctor -v
python -m unittest discover -s tests -v
~~~

The dedicated tests start the actual Shards gateway on an ephemeral
loopback port, register scoped reader/worker identities, exercise
HTTP GET and JSON-RPC POST, verify that task count is unchanged,
and test rejected scopes, revocation, malformed Agent Cards,
unsupported result envelopes, invalid origins and CLI credential safety.
