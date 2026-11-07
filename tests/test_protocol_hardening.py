"""Transport hardening for MCP 2025-11-25 over real HTTP sockets."""
from __future__ import annotations

import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest

from shards_mcp.core import Gateway
from shards_mcp.server import MCP_PROTOCOL_VERSION, make_handler


class ProtocolHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = secrets.token_urlsafe(48)
        self.gateway = Gateway(str(Path(self.tmp.name) / "gateway.sqlite"), self.token)
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(self.gateway, {"https://trusted.example"})
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def raw(self, body, extra_headers=()):
        if isinstance(body, str):
            body = body.encode("utf-8")
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            c.putrequest("POST", "/mcp")
            c.putheader("Authorization", "Bearer " + self.token)
            c.putheader("Content-Type", "application/json")
            if not any(k.lower() == "content-length" for k, _ in extra_headers):
                c.putheader("Content-Length", str(len(body)))
            for name, value in extra_headers:
                c.putheader(name, value)
            c.endheaders(body)
            response = c.getresponse()
            raw_body = response.read()
            return response.status, json.loads(raw_body) if raw_body else None
        finally:
            c.close()

    @staticmethod
    def ping(identifier=1):
        return json.dumps({"jsonrpc": "2.0", "id": identifier,
                           "method": "ping", "params": {}})

    def test_explicit_protocol_version_must_be_supported(self):
        self.assertEqual(MCP_PROTOCOL_VERSION, "2025-11-25")
        valid = self.raw(self.ping(), [("MCP-Protocol-Version", MCP_PROTOCOL_VERSION)])
        self.assertEqual(valid[0], 200, valid)
        self.assertEqual(valid[1]["result"], {})
        # Missing header remains accepted for compatibility with legacy clients.
        self.assertEqual(self.raw(self.ping())[0], 200)
        for version in ("2026-07-28", "2024-11-05", "invalid",
                        "2025-11-25,2026-07-28", ""):
            with self.subTest(version=version):
                status, payload = self.raw(
                    self.ping(), [("MCP-Protocol-Version", version)]
                )
                self.assertEqual(status, 400, payload)
                self.assertIn("unsupported", payload["error"])

    def test_get_mcp_probe_validates_origin_and_version_before_405(self):
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            c.request("GET", "/mcp", headers={
                "MCP-Protocol-Version": "2026-07-28",
                "Origin": "https://trusted.example",
            })
            response = c.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
        finally:
            c.close()
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            c.request("GET", "/mcp", headers={
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                "Origin": "https://untrusted.example",
            })
            response = c.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
        finally:
            c.close()
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            c.request("GET", "/mcp", headers={
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                "Origin": "https://trusted.example",
            })
            response = c.getresponse()
            self.assertEqual(response.status, 405)
            response.read()
        finally:
            c.close()

    def test_ambiguous_protocol_content_length_and_auth_headers_rejected(self):
        # The second version header must never be silently ignored.
        status, _ = self.raw(self.ping(), [
            ("MCP-Protocol-Version", MCP_PROTOCOL_VERSION),
            ("MCP-Protocol-Version", "2026-07-28"),
        ])
        self.assertEqual(status, 400)
        data = self.ping()
        # Two equal lengths are ambiguous even if this specific pair agrees.
        status, _ = self.raw(data, [
            ("Content-Length", str(len(data))),
            ("Content-Length", str(len(data))),
        ])
        self.assertEqual(status, 400)
        status, _ = self.raw(
            self.ping(), [("Authorization", "Bearer " + self.token)]
        )
        self.assertEqual(status, 400)

    def test_duplicate_json_properties_rejected_including_nested_input(self):
        for body in (
            '{"jsonrpc":"2.0","id":1,"method":"ping","method":"tools/list"}',
            '{"jsonrpc":"2.0","id":1,"method":"ping","params":{"a":1,"a":2}}',
        ):
            with self.subTest(body=body):
                status, payload = self.raw(body)
                self.assertEqual(status, 400)
                self.assertEqual(payload["error"]["code"], -32700)

    def test_exponent_overflow_is_rejected_during_json_decode(self):
        # json.loads normally converts 1e999 to float('inf') even with
        # parse_constant rejecting the literal Infinity token. That value
        # must not reach canonical response serialization or tool execution.
        for raw in (
            '{"jsonrpc":"2.0","id":1e999,"method":"ping"}',
            '{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":-1e999}}',
            '{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":1e999}}',
        ):
            with self.subTest(raw=raw):
                code, response = self.raw(raw)
                self.assertEqual(code, 400)
                self.assertEqual(response["error"]["code"], -32700)
                self.assertIsNone(response["id"])
        self.assertEqual(self.raw(self.ping(1.125))[0], 200)

    def test_http_rejects_deep_json_before_decoder_version_dependent_recursion(self):
        depth = 180
        payload = ('{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":'
                   + "[" * depth + "0" + "]" * depth + '}}')
        code, result = self.raw(payload)
        self.assertEqual(code, 400)
        self.assertEqual(result["error"]["code"], -32700)
        # Delimiters inside a JSON string are data, not nesting.
        valid = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping",
                            "params": {"x": "[" * 800}})
        self.assertEqual(self.raw(valid)[0], 200)

    def test_mcp_rejects_utf16_and_utf32_json_body_encoding(self):
        # json.loads(bytes) auto-detects UTF-16/32 and could disagree with a
        # byte-wise structural scan. MCP requires UTF-8 JSON on the wire.
        sample = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping",
                             "params": {"text": "\u2200", "items": [[1]]}},
                            ensure_ascii=False)
        for encoding in ("utf-16", "utf-16-le", "utf-16-be",
                         "utf-32", "utf-32-le", "utf-32-be"):
            with self.subTest(encoding=encoding):
                status, data = self.raw(sample.encode(encoding))
                self.assertEqual(status, 400, data)
                self.assertEqual(data["error"]["code"], -32700)
        self.assertEqual(self.raw(sample)[0], 200)

    def test_jsonrpc_ids_must_be_scalar_and_not_boolean(self):
        for bad_id in (True, False, None, [], {"nested": "id"}):
            with self.subTest(identifier=bad_id):
                status, payload = self.raw(self.ping(bad_id))
                self.assertEqual(status, 200)
                self.assertEqual(payload["error"]["code"], -32600)
                self.assertIsNone(payload["id"])
        for valid_id in (0, -1, "req-1", 1.5):
            with self.subTest(identifier=valid_id):
                status, payload = self.raw(self.ping(valid_id))
                self.assertEqual(status, 200)
                self.assertEqual(payload["id"], valid_id)
                self.assertEqual(payload["result"], {})

    def test_initialized_notification_cannot_have_request_id(self):
        packet = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self.assertEqual(self.raw(json.dumps(packet)), (202, None))
        status, payload = self.raw(json.dumps({**packet, "id": "incorrect"}))
        self.assertEqual(status, 200)
        self.assertEqual(payload["error"]["code"], -32600)

    def test_ambiguous_origin_is_not_accepted_even_with_allowlisted_first(self):
        status, body = self.raw(self.ping(), [
            ("Origin", "https://trusted.example"),
            ("Origin", "https://evil.example"),
        ])
        self.assertEqual(status, 403, body)
        status, body = self.raw(self.ping(), [("Origin", "https://trusted.example")])
        self.assertEqual(status, 200, body)


if __name__ == "__main__":
    unittest.main()
