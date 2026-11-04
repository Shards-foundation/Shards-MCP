# ChatGPT and other AI client integration

## Implemented transport

MCP JSON-RPC POST endpoint at /mcp, with bearer authentication. Tools may be called by clients that can send custom MCP HTTP requests. Generic HTTP clients can also call GET /v1/tools and POST /v1/tools/{name}, passing the same JSON arguments as an MCP tool call, with a bearer credential. This is a Shards-specific REST adapter, not an A2A protocol implementation. Agent-to-agent communication occurs through persisted message and task APIs; direct A2A protocol interoperability is planned but not yet implemented.

## OAuth and ChatGPT remote integration status

RFC 9728 protected-resource discovery and signed JWT verification are implemented in optional OAuth mode. Configure an external OAuth issuer and register the signed `sub` as a Shards agent through the **host-only operator CLI**. Remote token scopes can never exceed enrolled agent scopes. ChatGPT still requires a hosted HTTPS endpoint, supported workspace permissions, compatible authorisation-server discovery, and a real client login/tool-call test. There is no deployed hosted service or App Directory approval.

## ChatGPT platform

ChatGPT supports remote custom MCP server connections subject to plan/workspace permissions. An optional OAuth JWT resource-server implementation now provides protected-resource metadata and signed access-token validation, but needs an external configured issuer and verified deployment. Do not claim that it is ready for directory submission, published, or approved.

Release checklist:
1. Add externally accessible HTTPS plus fully compliant OAuth protected-resource discovery and token audience/scope validation.
2. Connect from the supported ChatGPT web interface using an agent-specific principal, never the admin token.
3. Perform handshake, tool-discovery and read-only tool smoke tests with ChatGPT.
4. Test allowed and disallowed mutations, privacy requirements and platform submission checks.
5. Publish compatibility evidence and a privacy policy appropriate to the actual hosted service.

References:
- https://modelcontextprotocol.io/specification/2025-11-25
- https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt

## Other AI agents

Claude, Grok, Gemini, Manus, Hermes and custom agents may connect **when their specific runtime supports custom MCP HTTP connections and compatible authentication**. Some product UIs do not. For those, build and test an explicit adapter; do not assume universal native support. Tool actions must remain scoped per authenticated agent.

## Operator provisioning

Register agents only from a trusted gateway-host process using `shards-mcp-admin register`, storing each issued credential in a protected local file. Credential issuance and revocation are not network MCP/REST tools. Clients should receive only their own agent token via their runtime secrets mechanism; never use the bootstrap operator token.


## A2A v1.0 task adapter (constrained)

The gateway can expose authenticated Agent Cards at `GET /a2a/agents/<agent_id>/card` and text-only JSON-RPC delegation at `POST /a2a/agents/<agent_id>` when `SHARDS_A2A_BASE_URL` is configured. In remote OAuth mode, the base is derived from `SHARDS_PUBLIC_URL`. A2A requests must send `A2A-Version: 1.0` and the same authenticated bearer credential used for MCP/REST.

Implemented methods: `SendMessage` (creates a durable worker task using A2A `messageId` for idempotency) and `GetTask` (polls creator/worker-owned tasks). The gateway does not run models or automatically execute queued work. The task's stored A2A payload is an input for independently connected agent runtimes. Verified task results become artifacts only after the separate Shards verification gate.

A2A v1.0 streaming, push notifications, cancellation, task listing, multi-turn continuation, public default Agent Cards and full conformance are not implemented. Unsupported methods return a JSON-RPC method error. Direct card URL configuration is required. See https://a2a-protocol.org/v1.0.0/specification/.

