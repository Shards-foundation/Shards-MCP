# ChatGPT and other AI client integration

## Implemented transport

MCP JSON-RPC POST endpoint at /mcp, with bearer authentication. Tools may be called by clients that can send custom MCP HTTP requests. Agent-to-agent communication occurs through persisted message and task APIs; direct A2A protocol interoperability is planned but not yet implemented.

## ChatGPT platform

ChatGPT supports remote custom MCP server connections subject to plan/workspace permissions. This version does not yet implement the OAuth 2.1 resource metadata and token validation expected for broad secure deployment. Do not claim that it is ready for directory submission, published, or approved.

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
