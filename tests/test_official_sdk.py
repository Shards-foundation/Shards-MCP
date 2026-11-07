import secrets
"""Official MCP Python SDK v2 interoperability smoke test.

Runtime intentionally stays stdlib-only; CI installs the official SDK to prove
an independent MCP client can negotiate, discover and invoke tools over HTTP.
"""
import asyncio
from http.server import ThreadingHTTPServer
import os
import tempfile
import threading
import unittest

try:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False

from shards_mcp.core import Gateway
from shards_mcp.server import make_handler


@unittest.skipUnless(SDK_AVAILABLE, "official MCP SDK integration extra not installed")
class OfficialSdkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = secrets.token_urlsafe(48)
        self.gateway = Gateway(os.path.join(self.tmp.name, "db.sqlite"), self.token)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.gateway, set()))
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)
        self.tmp.cleanup()

    def test_official_client_handshake_tools_and_call(self):
        async def run():
            url = "http://127.0.0.1:%s/mcp" % self.server.server_port
            async with httpx2.AsyncClient(headers={
                "Authorization": "Bearer " + self.token
            }, timeout=httpx2.Timeout(10, read=20)) as http_client:
                transport = streamable_http_client(url, http_client=http_client)
                async with Client(transport) as client:
                    names = {tool.name for tool in (await client.list_tools()).tools}
                    self.assertIn("system_status", names)
                    result = await client.call_tool("system_status", {})
                    self.assertFalse(result.is_error)
                    self.assertEqual(result.structured_content["agents"], 0)
        asyncio.run(run())

    def test_official_modern_client_discovers_and_invokes_tools(self):
        """2026-07-28 SDK protocol auto-selection, no legacy initialize."""
        async def run():
            url = "http://127.0.0.1:%s/mcp" % self.server.server_port
            async with httpx2.AsyncClient(headers={
                "Authorization": "Bearer " + self.token,
            }, timeout=httpx2.Timeout(10, read=20)) as http_client:
                transport = streamable_http_client(url, http_client=http_client)
                async with Client(transport, mode="auto") as client:
                    self.assertEqual(client.protocol_version, "2026-07-28")
                    self.assertEqual(client.server_info.name, "shards-mcp")
                    names = {tool.name for tool in (await client.list_tools()).tools}
                    self.assertIn("system_status", names)
                    response = await client.call_tool("system_status", {})
                    self.assertFalse(response.is_error)
                    self.assertEqual(response.structured_content["agents"], 0)
        asyncio.run(run())

    def test_official_modern_client_enforces_scoped_agent_visibility(self):
        """SDK-negotiated modern tool calls enforce registered scope boundaries."""
        root = self.gateway.authenticate(self.token)
        enrolled = self.gateway.register(
            root, "modern-scoped", "sdk-test", [], ["agent:read"],
        )

        async def run():
            url = "http://127.0.0.1:%s/mcp" % self.server.server_port
            async with httpx2.AsyncClient(headers={
                "Authorization": "Bearer " + enrolled["token"],
            }, timeout=httpx2.Timeout(10, read=20)) as http_client:
                transport = streamable_http_client(url, http_client=http_client)
                async with Client(transport, mode="auto") as client:
                    self.assertEqual(client.protocol_version, "2026-07-28")
                    tools = {tool.name for tool in (await client.list_tools()).tools}
                    self.assertIn("agent_identity", tools)
                    self.assertIn("agent_list", tools)
                    self.assertNotIn("system_status", tools)
                    self.assertNotIn("task_create", tools)
                    identity = await client.call_tool("agent_identity", {})
                    self.assertFalse(identity.is_error)
                    self.assertEqual(identity.structured_content["agent_id"],
                                     enrolled["agent_id"])
                    self.assertEqual(identity.structured_content["scopes"], ["agent:read"])
                    self.assertNotIn(enrolled["token"],
                                     str(identity.structured_content))
                    blocked = await client.call_tool("system_status", {})
                    self.assertTrue(blocked.is_error)
        asyncio.run(run())

    def test_official_client_with_signed_oauth_jwt_least_privilege(self):
        """Real SDK over HTTP + RSA JWT resource-server authentication together.

        This uses a locally generated key and an injected test key resolver;
        it does not pretend to test an external provider's login/PKCE flow.
        """
        from datetime import datetime, timedelta, timezone
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        from shards_mcp.oauth import OAuthResourceServer

        issuer = "https://issuer.example.test"
        resource = "https://shards.example.test/mcp"
        subject = "official-sdk-oauth-subject"
        admin = self.gateway.authenticate(self.token)
        enrolled = self.gateway.register(
            admin, "sdk-oauth-agent", "tests", ["read-only"],
            ["agent:read"], oauth_subject=subject,
        )
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = private.public_key()
        oauth = OAuthResourceServer(
            self.gateway, issuer, resource, issuer + "/jwks.json",
            key_resolver=lambda kid: public if kid == "sdk-interop-key" else None,
        )
        now = datetime.now(timezone.utc)
        token = jwt.encode({
            "iss": issuer,
            "sub": subject,
            "aud": resource,
            "iat": now,
            "exp": now + timedelta(minutes=10),
            # Attempted excessive JWT scope is deliberately intersected with
            # the agent's actual enrolment, never granting task creation or *.
            "scope": "agent:read task:create *",
        }, private, algorithm="RS256", headers={"kid": "sdk-interop-key"})
        protected = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(self.gateway, set(), oauth=oauth),
        )
        protected_thread = threading.Thread(
            target=protected.serve_forever, daemon=True
        )
        protected_thread.start()
        try:
            async def run():
                url = "http://127.0.0.1:%s/mcp" % protected.server_port
                async with httpx2.AsyncClient(
                    headers={"Authorization": "Bearer " + token},
                    timeout=httpx2.Timeout(10, read=20),
                ) as http_client:
                    transport = streamable_http_client(url, http_client=http_client)
                    async with Client(transport) as client:
                        names = {tool.name for tool in (await client.list_tools()).tools}
                        self.assertIn("agent_identity", names)
                        self.assertIn("agent_list", names)
                        self.assertNotIn("system_status", names)
                        self.assertNotIn("task_create", names)
                        report = await client.call_tool("agent_identity", {})
                        self.assertFalse(report.is_error)
                        identity = report.structured_content
                        self.assertEqual(identity["agent_id"], enrolled["agent_id"])
                        self.assertEqual(identity["role"], "agent")
                        self.assertEqual(identity["scopes"], ["agent:read"])
                        self.assertNotIn(token, str(identity))
                        denied = await client.call_tool("system_status", {})
                        self.assertTrue(denied.is_error)
            asyncio.run(run())
        finally:
            protected.shutdown()
            protected.server_close()
            protected_thread.join(timeout=5)
            self.assertFalse(protected_thread.is_alive())


if __name__ == "__main__":
    unittest.main()
