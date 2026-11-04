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


if __name__ == "__main__":
    unittest.main()
