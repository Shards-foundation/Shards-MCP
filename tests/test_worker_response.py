"""Fail-closed reference worker HTTP response envelope regressions."""
import io
import json
import unittest

from shards_mcp.worker import AgentClient


class FakeResponse:
    def __init__(self, body):
        self.body = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.body.read(size)


class FakeOpener:
    def __init__(self, body):
        self.body = body

    def open(self, request, timeout):
        assert timeout == 15
        return FakeResponse(self.body)


class WorkerResponseTests(unittest.TestCase):
    def setUp(self):
        self.client = AgentClient("http://127.0.0.1:8787", "a" * 48)

    def test_valid_response(self):
        self.client.opener = FakeOpener(b'{"ok":true,"result":{"claimed":false}}')
        self.assertEqual(self.client.call("task_claim_next", {}), {"claimed": False})

    def test_reject_malformed_envelopes(self):
        bodies = [
            b"[]", b"null", b'"hello"', b'{"ok":1,"result":{}}',
            b'{"ok":true}', b'{"ok":false,"result":{}}',
            b'{"ok":true,"result":', b'\xff',
        ]
        for body in bodies:
            with self.subTest(body=repr(body)):
                self.client.opener = FakeOpener(body)
                with self.assertRaises(RuntimeError):
                    self.client.call("task_claim_next", {})

    def test_reject_oversized_response_before_parsing(self):
        self.client.opener = FakeOpener(b" " * 262145)
        with self.assertRaisesRegex(RuntimeError, "size limit"):
            self.client.call("task_claim_next", {})

    def test_accept_exact_size_limit(self):
        body = b'{"ok":true,"result":null}'
        self.client.opener = FakeOpener(body + b" " * (262144 - len(body)))
        self.assertIsNone(self.client.call("task_claim_next", {}))


if __name__ == "__main__":
    unittest.main()
