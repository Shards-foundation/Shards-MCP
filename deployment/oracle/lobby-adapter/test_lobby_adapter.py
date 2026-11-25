"""Local tests for the loopback Lobby adapter.

Every HTTP request in this file targets 127.0.0.1 and a fake upstream created
by the test. No live gateway, host service or external provider is called.
"""
from __future__ import annotations

import contextlib
import http.client
import io
import json
import os
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lobby_adapter as adapter  # noqa: E402
import lobby_client  # noqa: E402


def write_private(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.write_bytes(data)
    path.chmod(mode)


def raw_request(port: int, request: bytes, timeout: float = 5.0) -> tuple[int, bytes, bytes]:
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.sendall(request)
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    data = b"".join(chunks)
    head, _, body = data.partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n", 1)[0].split(b" ")[1])
    return status, head, body


def write_in_parts(sock: socket.socket, parts: tuple[bytes, ...], delay: float) -> None:
    """Emit a finite fixture over a single test-local connection."""
    try:
        for index, part in enumerate(parts):
            if index:
                time.sleep(delay)
            sock.sendall(part)
    except (BrokenPipeError, ConnectionResetError):
        pass


class FakeUpstreamServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _FakeUpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        return None

    def do_POST(self) -> None:
        server = self.server
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        with server.lock:
            server.calls += 1
            server.last_path = self.path
            server.last_headers = {key: value for key, value in self.headers.items()}
            server.last_body = body
        if server.delay:
            time.sleep(server.delay)
        if server.mode == "error":
            self._send(500, b'{"error":"UPSTREAM-INTERNAL-VALUE"}')
        elif server.mode == "redirect":
            self._send(
                302,
                b"",
                {"Location": f"http://127.0.0.1:{server.redirect_port}/v1/chat/completions"},
            )
        elif server.mode == "badjson":
            self._send(200, b"not-json")
        elif server.mode == "huge":
            self._send(200, b"x" * (server.max_response + 1))
        elif server.mode == "empty":
            self._send(200, b'{"choices":[]}')
        else:
            payload = json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": server.reply}}]}
            ).encode()
            headers = (
                b"HTTP/1.1 200 OK\r\nConnection: close\r\n"
                + f"Content-Length: {len(payload)}\r\n\r\n".encode()
            )
            if server.mode == "slow_headers":
                write_in_parts(self.connection, (headers[:20], headers[20:43], headers[43:] + payload), 0.2)
            elif server.mode == "slow_body":
                write_in_parts(self.connection, (headers + payload[:1], payload[1:2], payload[2:]), 0.2)
            elif server.mode == "truncated":
                self._send(200, payload, {"Connection": "close"}, length=len(payload) + 1)
                self.close_connection = True
            elif server.mode == "chunked":
                self.connection.sendall(
                    b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
                    + f"{len(payload):x}\r\n".encode() + payload + b"\r\n0\r\n\r\n"
                )
                self.close_connection = True
            else:
                self._send(200, payload)

    def _send(self, status: int, body: bytes, headers=None, length=None) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body) if length is None else length))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass


class FakeUpstream:
    def __init__(
        self,
        mode: str = "ok",
        delay: float = 0.0,
        reply: str = "fake upstream reply",
        max_response: int = 1024,
        redirect_port: int = 1,
    ):
        self.server = FakeUpstreamServer(("127.0.0.1", 0), _FakeUpstreamHandler)
        self.server.mode = mode
        self.server.delay = delay
        self.server.reply = reply
        self.server.max_response = max_response
        self.server.redirect_port = redirect_port
        self.server.lock = threading.Lock()
        self.server.calls = 0
        self.server.last_path = None
        self.server.last_headers = None
        self.server.last_body = None
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    @property
    def calls(self) -> int:
        with self.server.lock:
            return self.server.calls

    @property
    def last_headers(self):
        with self.server.lock:
            return self.server.last_headers

    @property
    def last_body(self):
        with self.server.lock:
            return self.server.last_body

    @property
    def last_path(self):
        with self.server.lock:
            return self.server.last_path

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class Harness:
    def __init__(
        self,
        upstream_mode: str = "ok",
        upstream_delay: float = 0.0,
        upstream_timeout: float = 2.0,
        request_timeout: float = adapter.REQUEST_TIMEOUT,
        max_request_bytes: int = adapter.MAX_REQUEST_BYTES,
        max_message_chars: int = adapter.MAX_MESSAGE_CHARS,
        max_message_bytes: int = adapter.MAX_MESSAGE_BYTES,
        max_response_bytes: int = adapter.MAX_RESPONSE_BYTES,
        redirect_port: int = 1,
        reply: str = "fake upstream reply",
        state_dir: Path | None = None,
    ):
        self.secret = b"test-adapter-secret-" + secrets.token_urlsafe(32).encode()
        self.gateway_token = "test-gateway-token-" + secrets.token_urlsafe(24)
        self.upstream = FakeUpstream(
            mode=upstream_mode,
            delay=upstream_delay,
            reply=reply,
            max_response=max_response_bytes,
            redirect_port=redirect_port,
        )
        self.config = adapter.AdapterConfig(
            adapter_secret=self.secret,
            gateway_token=self.gateway_token,
            bind_port=0,
            upstream_port=self.upstream.port,
            request_timeout=request_timeout,
            upstream_timeout=upstream_timeout,
            max_request_bytes=max_request_bytes,
            max_message_chars=max_message_chars,
            max_message_bytes=max_message_bytes,
            max_response_bytes=max_response_bytes,
            state_dir=state_dir,
        )
        self.server = adapter.LobbyHTTPServer(
            self.config, adapter.make_handler(self.config)
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.thread.start()
        self.port = self.server.server_address[1]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.upstream.close()

    def request(
        self,
        method: str,
        path: str,
        body=None,
        token: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 5.0,
    ):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        request_headers = dict(headers or {})
        if token is not None:
            request_headers["Authorization"] = "Bearer " + token
        if body is not None and not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        elif body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            raw = response.read()
            status = response.status
            response_headers = dict(response.getheaders())
        finally:
            connection.close()
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = None
        return status, parsed, raw, response_headers

    def token(self) -> str:
        return self.secret.decode("ascii")


class SecretAndConfigTests(unittest.TestCase):
    def test_loads_0600_secret_and_strips_one_newline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            value = b"a" * 64
            write_private(path, value + b"\n")
            self.assertEqual(adapter.load_adapter_secret(path), value)

    def test_rejects_secret_with_group_or_other_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            write_private(path, b"b" * 64, mode=0o644)
            with self.assertRaises(adapter.ConfigError) as caught:
                adapter.load_adapter_secret(path)
            self.assertNotIn("b" * 64, str(caught.exception))

    def test_rejects_symlinked_or_short_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            write_private(target, b"c" * 64)
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaises(adapter.ConfigError):
                adapter.load_adapter_secret(link)
            short = root / "short"
            write_private(short, b"too-short")
            with self.assertRaises(adapter.ConfigError):
                adapter.load_adapter_secret(short)

    def test_create_secret_is_random_mode_0600_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "one"
            second = root / "two"
            adapter.create_secret(first)
            adapter.create_secret(second)
            self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)
            self.assertGreaterEqual(len(adapter.load_adapter_secret(first)), 32)
            self.assertNotEqual(first.read_bytes(), second.read_bytes())
            with self.assertRaises(adapter.ConfigError):
                adapter.create_secret(first)

    def test_cli_init_secret_does_not_print_the_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "lobby_adapter.py"),
                    "init-secret",
                    "--secret-file",
                    str(path),
                ],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            value = path.read_text(encoding="ascii").strip()
            self.assertGreaterEqual(len(value), 32)
            self.assertNotIn(value, completed.stdout)
            self.assertNotIn(value, completed.stderr)

    def test_gateway_token_paths_and_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token = "gateway-token-" + secrets.token_urlsafe(24)
            for document in (
                {"gateway": {"auth": {"token": token}}},
                {"gateway": {"token": token}},
                {
                    "gateway": {
                        "auth": {"token": token},
                        "token": token,
                    }
                },
            ):
                path = root / "config.json"
                write_private(path, json.dumps(document).encode())
                self.assertEqual(adapter.load_gateway_token(path), token)
            conflict = root / "conflict.json"
            write_private(
                conflict,
                json.dumps(
                    {
                        "gateway": {
                            "auth": {"token": token},
                            "token": token + "-different",
                        }
                    }
                ).encode(),
            )
            with self.assertRaises(adapter.ConfigError):
                adapter.load_gateway_token(conflict)
            missing = root / "missing.json"
            write_private(missing, b'{"gateway":{}}')
            with self.assertRaises(adapter.ConfigError):
                adapter.load_gateway_token(missing)

    def test_openclaw_config_rejects_duplicate_keys_and_non_ascii_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = root / "duplicate.json"
            write_private(
                duplicate,
                b'{"gateway":{"token":"first"},"gateway":{"token":"second"}}',
            )
            with self.assertRaises(adapter.ConfigError):
                adapter.load_gateway_token(duplicate)
            non_ascii = root / "non-ascii.json"
            write_private(
                non_ascii,
                json.dumps(
                    {"gateway": {"token": "gateway-token-" + "\u00e9" * 20}}
                ).encode(),
            )
            with self.assertRaises(adapter.ConfigError):
                adapter.load_gateway_token(non_ascii)

    def test_cli_startup_error_does_not_print_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = b"S" * 64
            secret_path = root / "secret"
            write_private(secret_path, secret, mode=0o644)
            token = "gateway-token-" + secrets.token_urlsafe(24)
            config_path = root / "config.json"
            write_private(
                config_path,
                json.dumps({"gateway": {"auth": {"token": token}}}).encode(),
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "lobby_adapter.py"),
                    "serve",
                    "--secret-file",
                    str(secret_path),
                    "--openclaw-config",
                    str(config_path),
                ],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            combined = completed.stdout + completed.stderr
            self.assertNotIn(secret.decode(), combined)
            self.assertNotIn(token, combined)

    def test_openclaw_config_must_be_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            token = "gateway-token-" + secrets.token_urlsafe(24)
            write_private(
                path,
                json.dumps({"gateway": {"auth": {"token": token}}}).encode(),
                mode=0o644,
            )
            with self.assertRaises(adapter.ConfigError):
                adapter.load_gateway_token(path)

    def test_config_refuses_public_bind_or_arbitrary_upstream(self):
        base = dict(
            adapter_secret=b"a" * 64,
            gateway_token="gateway-token-" + "x" * 24,
        )
        with self.assertRaises(ValueError):
            adapter.AdapterConfig(bind_host="0.0.0.0", **base)
        with self.assertRaises(ValueError):
            adapter.AdapterConfig(upstream_host="example.com", **base)
        with self.assertRaises(ValueError):
            adapter.AdapterConfig(upstream_path="/v1/other", **base)

    def test_private_file_loader_rejects_fifo_without_waiting_for_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-a-regular-file"
            os.mkfifo(path, 0o600)
            completed = subprocess.run(
                [sys.executable, str(HERE / "lobby_adapter.py"), "serve", "--secret-file", str(path)],
                capture_output=True, text=True, timeout=3,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("must be a regular file", completed.stderr)

    def test_config_credentials_are_distinct_and_absent_from_repr(self):
        secret = secrets.token_urlsafe(48)
        gateway = secrets.token_urlsafe(32)
        config = adapter.AdapterConfig(adapter_secret=secret.encode(), gateway_token=gateway)
        self.assertNotIn(secret, repr(config))
        self.assertNotIn(gateway, repr(config))
        with self.assertRaises(ValueError):
            adapter.AdapterConfig(adapter_secret=secret.encode(), gateway_token=secret)


class AdapterHttpTests(unittest.TestCase):
    def setUp(self):
        self.harness = Harness()

    def tearDown(self):
        self.harness.close()

    def _body(self, message: str = "hello", conversation_id: str | None = None):
        return {
            "conversation_id": conversation_id or str(uuid.uuid4()),
            "message": message,
        }

    def test_health_requires_auth_and_does_not_call_upstream(self):
        status, _, raw, _ = self.harness.request("GET", "/health")
        self.assertEqual(status, 401)
        status, _, _, _ = self.harness.request(
            "GET", "/health", token="wrong-" + "x" * 40
        )
        self.assertEqual(status, 401)
        status, body, raw, _ = self.harness.request(
            "GET", "/health", token=self.harness.token()
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "ok", "model": adapter.MODEL})
        self.assertEqual(self.harness.upstream.calls, 0)
        self.assertNotIn(self.harness.secret, raw)
        self.assertNotIn(self.harness.gateway_token.encode(), raw)

    def test_positive_chat_uses_fixed_shape_and_derived_namespace(self):
        conversation_id = str(uuid.uuid4())
        status, body, raw, headers = self.harness.request(
            "POST",
            "/chat",
            self._body("hello adapter", conversation_id),
            token=self.harness.token(),
        )
        self.assertEqual(status, 200, raw)
        self.assertEqual(body["conversation_id"], conversation_id)
        self.assertEqual(body["reply"], "fake upstream reply")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(self.harness.upstream.calls, 1)
        self.assertEqual(self.harness.upstream.last_path, "/v1/chat/completions")
        upstream_body = json.loads(self.harness.upstream.last_body)
        self.assertEqual(upstream_body["model"], "openclaw/shards")
        self.assertEqual(
            upstream_body["messages"],
            [{"role": "user", "content": "hello adapter"}],
        )
        self.assertFalse(upstream_body["stream"])
        self.assertEqual(
            upstream_body["user"],
            adapter.conversation_namespace(conversation_id),
        )
        self.assertNotIn(conversation_id, upstream_body["user"])
        self.assertEqual(
            self.harness.upstream.last_headers["Authorization"],
            "Bearer " + self.harness.gateway_token,
        )
        for forbidden in (
            "X-Forwarded-For",
            "X-Real-IP",
            "Cookie",
            "Origin",
            "X-Session-Key",
            "X-User-Id",
        ):
            self.assertNotIn(forbidden, self.harness.upstream.last_headers)
        self.assertNotIn(self.harness.secret, raw)
        self.assertNotIn(self.harness.gateway_token.encode(), raw)

    def test_proxy_environment_is_not_used(self):
        proxy = "http://127.0.0.1:1"
        with mock.patch.dict(
            os.environ,
            {
                "HTTP_PROXY": proxy,
                "http_proxy": proxy,
                "HTTPS_PROXY": proxy,
                "https_proxy": proxy,
                "ALL_PROXY": proxy,
                "all_proxy": proxy,
            },
            clear=False,
        ):
            status, body, raw, _ = self.harness.request(
                "POST", "/chat", self._body(), token=self.harness.token()
            )
        self.assertEqual(status, 200, raw)
        self.assertEqual(body["reply"], "fake upstream reply")
        self.assertEqual(self.harness.upstream.calls, 1)

    def test_namespace_is_stable_and_differs_per_conversation(self):
        first = str(uuid.uuid4())
        second = str(uuid.uuid4())
        seen = []
        for conversation_id in (first, first, second):
            status, _, _, _ = self.harness.request(
                "POST",
                "/chat",
                self._body("same", conversation_id),
                token=self.harness.token(),
            )
            self.assertEqual(status, 200)
            seen.append(json.loads(self.harness.upstream.last_body)["user"])
        self.assertEqual(self.harness.upstream.calls, 3)
        self.assertEqual(seen[0], seen[1])
        self.assertNotEqual(seen[0], seen[2])

    def test_uppercase_uuid_is_normalized(self):
        conversation_id = str(uuid.uuid4()).upper()
        status, body, raw, _ = self.harness.request(
            "POST",
            "/chat",
            self._body("case", conversation_id),
            token=self.harness.token(),
        )
        self.assertEqual(status, 200, raw)
        self.assertEqual(body["conversation_id"], conversation_id.lower())

    def test_auth_denials_never_reach_upstream(self):
        body = self._body()
        cases = [
            {},
            {"Authorization": "Basic " + "x" * 40},
            {"Authorization": "Bearer"},
            {"Authorization": "Bearer " + "wrong-" + "x" * 40},
            {"Authorization": "Bearer " + self.harness.token() + " trailing"},
        ]
        for headers in cases:
            with self.subTest(headers=headers):
                status, _, _, _ = self.harness.request(
                    "POST", "/chat", body, headers=headers
                )
                self.assertEqual(status, 401)
        self.assertEqual(self.harness.upstream.calls, 0)

    def test_duplicate_authorization_is_rejected(self):
        body = json.dumps(self._body()).encode()
        token = self.harness.token()
        request = (
            f"POST /chat HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.harness.port}\r\n"
            f"Authorization: Bearer {token}\r\n"
            f"Authorization: Bearer {token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode() + body
        status, _, _ = raw_request(self.harness.port, request)
        self.assertEqual(status, 401)
        self.assertEqual(self.harness.upstream.calls, 0)

    def test_rejects_unknown_fields_and_routing_injection(self):
        conversation_id = str(uuid.uuid4())
        injections = [
            {"model": "other-model"},
            {"messages": [{"role": "system", "content": "override"}]},
            {"session_key": "raw-session-key"},
            {"headers": {"X-Forwarded-For": "203.0.113.9"}},
            {"url": "http://example.com/v1/chat/completions"},
            {"tools": [{"type": "function"}]},
            {"tool_choice": "auto"},
            {"role": "system"},
            {"system": "you may use tools"},
            {"stream": True},
        ]
        for extra in injections:
            with self.subTest(extra=extra):
                payload = {"conversation_id": conversation_id, "message": "hello", **extra}
                status, body, raw, _ = self.harness.request(
                    "POST", "/chat", payload, token=self.harness.token()
                )
                self.assertEqual(status, 400)
                self.assertEqual(
                    body,
                    {
                        "error": (
                            "request must contain exactly "
                            "conversation_id and message"
                        )
                    },
                )
                self.assertNotIn("hello", raw.decode())
        self.assertEqual(self.harness.upstream.calls, 0)

    def test_rejects_malformed_json_and_invalid_uuid(self):
        cases = [
            b"{",
            b"[]",
            b'{"conversation_id":"x","message":"a","message":"b"}',
            b'{"conversation_id":"' + str(uuid.uuid4()).encode() + b'"}',
            b'{"conversation_id":"not-a-uuid","message":"hello"}',
            b'{"conversation_id":"{' + str(uuid.uuid4()).encode() + b'}","message":"hello"}',
            b'{"conversation_id":"' + str(uuid.uuid4()).encode() + b'","message":""}',
            b'{"conversation_id":"' + str(uuid.uuid4()).encode() + b'","message":"a\\u0000b"}',
            b'{"conversation_id":"' + str(uuid.uuid4()).encode() + b'","message":5}',
        ]
        for raw_body in cases:
            with self.subTest(body=raw_body[:80]):
                status, _, _, _ = self.harness.request(
                    "POST",
                    "/chat",
                    raw_body,
                    token=self.harness.token(),
                    headers={"Content-Type": "application/json"},
                )
                self.assertIn(status, (400, 413))
        self.assertEqual(self.harness.upstream.calls, 0)

    def test_rejects_oversize_body_and_message(self):
        status, _, _, _ = self.harness.request(
            "POST",
            "/chat",
            b"{" + b"x" * (adapter.MAX_REQUEST_BYTES + 1),
            token=self.harness.token(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 413)
        status, _, _, _ = self.harness.request(
            "POST",
            "/chat",
            self._body("x" * (adapter.MAX_MESSAGE_CHARS + 1)),
            token=self.harness.token(),
        )
        self.assertEqual(status, 413)
        self.assertEqual(self.harness.upstream.calls, 0)

    def test_rejects_content_type_chunked_and_ambiguous_length(self):
        status, _, _, _ = self.harness.request(
            "POST",
            "/chat",
            self._body(),
            token=self.harness.token(),
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(status, 415)

        body = json.dumps(self._body()).encode()
        token = self.harness.token()
        chunked = (
            f"POST /chat HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.harness.port}\r\n"
            f"Authorization: Bearer {token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Transfer-Encoding: chunked\r\n"
            f"Connection: close\r\n\r\n"
            f"{len(body):x}\r\n"
        ).encode() + body + b"\r\n0\r\n\r\n"
        self.assertEqual(raw_request(self.harness.port, chunked)[0], 411)

        missing_length = (
            f"POST /chat HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.harness.port}\r\n"
            f"Authorization: Bearer {token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Connection: close\r\n\r\n"
        ).encode() + body
        self.assertEqual(raw_request(self.harness.port, missing_length)[0], 411)

        duplicate_length = (
            f"POST /chat HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.harness.port}\r\n"
            f"Authorization: Bearer {token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode() + body
        self.assertEqual(raw_request(self.harness.port, duplicate_length)[0], 411)
        self.assertEqual(self.harness.upstream.calls, 0)

    def test_host_and_origin_guards(self):
        body = self._body()
        token = self.harness.token()
        status, _, _, _ = self.harness.request(
            "POST", "/chat", body, token=token, headers={"Host": "evil.example"}
        )
        self.assertEqual(status, 403)
        status, _, _, _ = self.harness.request(
            "POST",
            "/chat",
            body,
            token=token,
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(status, 403)
        request = (
            f"POST /chat HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.harness.port}\r\n"
            f"Host: evil.example\r\n"
            f"Authorization: Bearer {token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(json.dumps(body))}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode() + json.dumps(body).encode()
        self.assertEqual(raw_request(self.harness.port, request)[0], 403)
        self.assertEqual(self.harness.upstream.calls, 0)

    def test_only_chat_post_and_health_get_are_routed(self):
        token = self.harness.token()
        cases = [
            ("GET", "/chat", 405),
            ("POST", "/health", 405),
            ("POST", "/v1/chat/completions", 404),
            ("GET", "/health?probe=1", 404),
            ("POST", "/chat?probe=1", 404),
            ("POST", "//chat", 404),
            ("POST", "/chat/../health", 404),
            ("GET", "/", 404),
        ]
        for method, path, expected in cases:
            with self.subTest(method=method, path=path):
                body = self._body() if method == "POST" else None
                status, _, _, _ = self.harness.request(
                    method, path, body, token=token
                )
                self.assertEqual(status, expected)
        self.assertEqual(self.harness.upstream.calls, 0)

    def test_upstream_error_is_sanitized_and_not_retried(self):
        self.harness.close()
        self.harness = Harness(upstream_mode="error")
        status, body, raw, _ = self.harness.request(
            "POST", "/chat", self._body(), token=self.harness.token()
        )
        self.assertEqual(status, 502)
        self.assertEqual(body, {"error": "upstream rejected request", "outcome": "unknown"})
        self.assertNotIn(b"UPSTREAM-INTERNAL-VALUE", raw)
        self.assertNotIn(self.harness.gateway_token.encode(), raw)
        self.assertNotIn(self.harness.secret, raw)
        self.assertEqual(self.harness.upstream.calls, 1)

    def test_upstream_redirect_is_not_followed(self):
        target = FakeUpstream()
        try:
            self.harness.close()
            self.harness = Harness(
                upstream_mode="redirect", redirect_port=target.port
            )
            status, body, _, _ = self.harness.request(
                "POST", "/chat", self._body(), token=self.harness.token()
            )
            self.assertEqual(status, 502)
            self.assertEqual(body["outcome"], "unknown")
            self.assertEqual(self.harness.upstream.calls, 1)
            self.assertEqual(target.calls, 0)
        finally:
            target.close()

    def test_upstream_invalid_or_oversize_response_is_rejected(self):
        for mode in ("badjson", "huge", "empty"):
            with self.subTest(mode=mode):
                self.harness.close()
                self.harness = Harness(
                    upstream_mode=mode, max_response_bytes=128
                )
                status, body, raw, _ = self.harness.request(
                    "POST", "/chat", self._body(), token=self.harness.token()
                )
                self.assertEqual(status, 502)
                expected = (
                    "upstream response too large"
                    if mode == "huge"
                    else "invalid upstream response"
                )
                self.assertEqual(body["error"], expected)
                self.assertEqual(self.harness.upstream.calls, 1)

    def test_upstream_timeout_returns_504_without_retry(self):
        self.harness.close()
        self.harness = Harness(upstream_delay=0.5, upstream_timeout=0.1)
        status, body, raw, _ = self.harness.request(
            "POST", "/chat", self._body(), token=self.harness.token()
        )
        self.assertEqual(status, 504)
        self.assertEqual(body, {"error": "upstream timeout", "outcome": "unknown"})
        self.assertEqual(self.harness.upstream.calls, 1)
        self.assertNotIn(self.harness.gateway_token.encode(), raw)
        self.assertNotIn(self.harness.secret, raw)

    def test_slow_request_body_times_out(self):
        self.harness.close()
        self.harness = Harness(request_timeout=0.2)
        request = (
            f"POST /chat HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.harness.port}\r\n"
            f"Authorization: Bearer {self.harness.token()}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: 10\r\n"
            f"Connection: close\r\n\r\n"
        ).encode() + b"{"
        with socket.create_connection(
            ("127.0.0.1", self.harness.port), timeout=2.0
        ) as sock:
            sock.sendall(request)
            time.sleep(0.5)
            response = sock.recv(65536)
        self.assertIn(b" 408 ", response.split(b"\r\n", 1)[0])
        self.assertEqual(self.harness.upstream.calls, 0)

    def test_busy_adapter_returns_503(self):
        self.harness.close()
        self.harness = Harness(upstream_delay=0.5)
        result: list[tuple[int, dict | None, bytes, dict]] = []
        chat = self._body()

        def first_request() -> None:
            result.append(
                self.harness.request(
                    "POST", "/chat", chat, token=self.harness.token()
                )
            )

        worker = threading.Thread(target=first_request, daemon=True)
        worker.start()
        deadline = time.monotonic() + 2.0
        while self.harness.upstream.calls == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.harness.upstream.calls, 1)
        status, body, _, _ = self.harness.request(
            "POST", "/chat", chat, token=self.harness.token()
        )
        self.assertEqual(status, 503)
        self.assertEqual(body, {"error": "busy"})
        worker.join(timeout=5)
        self.assertEqual(result[0][0], 200)
        self.assertEqual(self.harness.upstream.calls, 1)

    def test_request_body_and_credentials_are_not_logged(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output), contextlib.redirect_stdout(output):
            status, _, _, _ = self.harness.request(
                "POST",
                "/chat",
                self._body("CANARY-REQUEST-BODY"),
                token=self.harness.token(),
            )
        self.assertEqual(status, 200)
        logged = output.getvalue()
        self.assertNotIn("CANARY-REQUEST-BODY", logged)
        self.assertNotIn(self.harness.token(), logged)
        self.assertNotIn(self.harness.gateway_token, logged)

    def test_successful_upstream_reply_cannot_echo_either_credential(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output), contextlib.redirect_stdout(output):
            for credential in (self.harness.token(), self.harness.gateway_token):
                self.harness.upstream.server.reply = f"prefix {credential} suffix"
                status, body, raw, headers = self.harness.request(
                    "POST", "/chat", self._body(), token=self.harness.token()
                )
                self.assertEqual(status, 502)
                self.assertEqual(body, {"error": "invalid upstream response", "outcome": "unknown"})
                self.assertNotIn(credential.encode(), raw)
                self.assertNotIn(credential, repr(headers))
        self.assertEqual(self.harness.upstream.calls, 2)
        self.assertNotIn(self.harness.token(), output.getvalue())
        self.assertNotIn(self.harness.gateway_token, output.getvalue())

    def test_unexpected_post_dispatch_exception_is_sanitized_and_ambiguous(self):
        output = io.StringIO()
        failure = RuntimeError(self.harness.token() + self.harness.gateway_token)
        with (
            mock.patch.object(adapter, "_extract_reply", side_effect=failure),
            contextlib.redirect_stderr(output),
        ):
            status, body, raw, _ = self.harness.request(
                "POST", "/chat", self._body(), token=self.harness.token()
            )
        self.assertEqual(status, 502)
        self.assertEqual(body, {"error": "upstream unavailable", "outcome": "unknown"})
        self.assertEqual(self.harness.upstream.calls, 1)
        self.assertNotIn(self.harness.token(), output.getvalue() + raw.decode())
        self.assertNotIn(self.harness.gateway_token, output.getvalue() + raw.decode())

    def test_failed_upstream_connect_is_known_not_dispatched(self):
        body = json.dumps(self._body()).encode()
        request = (
            f"POST /chat HTTP/1.1\r\nHost: 127.0.0.1:{self.harness.port}\r\n"
            f"Authorization: Bearer {self.harness.token()}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
        ).encode() + body
        with mock.patch.object(http.client.HTTPConnection, "connect", side_effect=ConnectionRefusedError):
            status, _, raw = raw_request(self.harness.port, request)
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(raw), {"error": "upstream unavailable", "outcome": "not_dispatched"})
        self.assertEqual(self.harness.upstream.calls, 0)

    def test_parser_errors_reject_without_reflecting_request_fields(self):
        host = f"Host: 127.0.0.1:{self.harness.port}\r\n"
        auth = f"Authorization: Bearer {self.harness.token()}\r\n"
        cases = (
            (f"{self.harness.token()} /health HTTP/1.1\r\n{host}\r\n", 501),
            (f"GET /health HTTP/1.1\r\n{host}{auth}broken header\r\n\r\n", 400),
            (f"GET /health HTTP/1.1\r\n{host}{auth}X-Local: one\r\n two\r\n\r\n", 400),
            (f"GET /health HTTP/1.1\r\n{host}{auth}X@Local: one\r\n\r\n", 400),
            (f"POST /chat HTTP/1.1\r\n{host}Expect: 100-continue\r\n\r\n", 417),
        )
        for request, expected in cases:
            status, _, body = raw_request(self.harness.port, request.encode())
            self.assertEqual(status, expected)
            self.assertNotIn(self.harness.secret, body)
        self.assertEqual(self.harness.upstream.calls, 0)

    def test_slow_request_line_and_headers_are_closed_at_the_deadline(self):
        self.harness.close()
        self.harness = Harness(request_timeout=0.32)
        host = f"Host: 127.0.0.1:{self.harness.port}\r\n".encode()
        auth = f"Authorization: Bearer {self.harness.token()}\r\n\r\n".encode()
        for parts in (
            (b"GET ", b"/health ", b"HTTP/1.1\r\n" + host + auth),
            (b"GET /health HTTP/1.1\r\n", host, auth),
        ):
            with socket.create_connection(("127.0.0.1", self.harness.port), timeout=2) as sock:
                writer = threading.Thread(target=write_in_parts, args=(sock, parts, 0.2))
                writer.start()
                try:
                    self.assertEqual(sock.recv(4096), b"")
                finally:
                    writer.join()

    def test_request_body_deadline_includes_time_spent_on_headers(self):
        self.harness.close()
        self.harness = Harness(request_timeout=0.32)
        body = json.dumps(self._body()).encode()
        headers = (
            f"POST /chat HTTP/1.1\r\nHost: 127.0.0.1:{self.harness.port}\r\n"
            f"Authorization: Bearer {self.harness.token()}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
        ).encode()
        for parts in (
            (headers, b"\r\n" + body[:1], body[1:]),
            (headers + b"\r\n" + body[:1], body[1:2], body[2:]),
        ):
            with socket.create_connection(("127.0.0.1", self.harness.port), timeout=2) as sock:
                writer = threading.Thread(target=write_in_parts, args=(sock, parts, 0.2))
                writer.start()
                try:
                    self.assertIn(b" 408 ", sock.recv(4096).split(b"\r\n", 1)[0])
                finally:
                    writer.join()
        self.assertEqual(self.harness.upstream.calls, 0)

    def test_connection_limit_is_enforced_before_authentication(self):
        self.harness.close()
        with mock.patch.object(adapter, "MAX_CONNECTIONS", 2):
            self.harness = Harness(request_timeout=2)
        with contextlib.ExitStack() as connections:
            def connect():
                return connections.enter_context(
                    socket.create_connection(("127.0.0.1", self.harness.port), timeout=0.8)
                )

            for _ in range(2):
                connect().sendall(b"GET /health HTTP/1.1\r\n")
            self.assertEqual(connect().recv(1), b"")
        self.assertEqual(self.harness.upstream.calls, 0)

    def test_upstream_deadline_bounds_streamed_headers_and_body(self):
        for mode in ("slow_headers", "slow_body"):
            with self.subTest(mode=mode):
                self.harness.close()
                self.harness = Harness(upstream_mode=mode, upstream_timeout=0.32)
                status, body, _, _ = self.harness.request(
                    "POST", "/chat", self._body(), token=self.harness.token()
                )
                self.assertEqual(status, 504)
                self.assertEqual(body, {"error": "upstream timeout", "outcome": "unknown"})
                self.assertEqual(self.harness.upstream.calls, 1)

    def test_upstream_accepts_chunked_response_and_rejects_truncated_length(self):
        for mode, expected in (("chunked", 200), ("truncated", 502)):
            with self.subTest(mode=mode):
                self.harness.close()
                self.harness = Harness(upstream_mode=mode)
                status, body, _, _ = self.harness.request(
                    "POST", "/chat", self._body(), token=self.harness.token()
                )
                self.assertEqual(status, expected)
                if expected == 502:
                    self.assertEqual(body["outcome"], "unknown")
                self.assertEqual(self.harness.upstream.calls, 1)

    def test_local_client_reads_only_the_private_adapter_secret(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            write_private(path, self.harness.secret)
            with (
                mock.patch.object(adapter, "BIND_PORT", self.harness.port),
                mock.patch("sys.stdin", io.TextIOWrapper(io.BytesIO(b"local message"))),
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(output),
            ):
                self.assertEqual(lobby_client.main(["health", "--secret-file", str(path)]), 0)
                self.assertEqual(lobby_client.main(["chat", "--secret-file", str(path)]), 0)
        health, chat = map(json.loads, output.getvalue().splitlines())
        self.assertEqual(health["status"], "ok")
        self.assertEqual(chat["reply"], "fake upstream reply")
        self.assertEqual(self.harness.upstream.calls, 1)
        self.assertNotIn(self.harness.token(), output.getvalue())
        self.assertNotIn(self.harness.gateway_token, output.getvalue())


class PendingDispatchGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.directory.name) / "state"
        self.harness: Harness | None = None

    def tearDown(self):
        if self.harness is not None:
            self.harness.close()
        self.directory.cleanup()

    def _start(self, **kwargs) -> Harness:
        self.harness = Harness(state_dir=self.state_dir, **kwargs)
        return self.harness

    def _body(self, message: str = "hello", conversation_id: str | None = None):
        return {
            "conversation_id": conversation_id or str(uuid.uuid4()),
            "message": message,
        }

    def _marker(self) -> Path:
        return self.state_dir / adapter.PENDING_MARKER_NAME

    def _raw_chat(self, harness: Harness, body: dict) -> bytes:
        raw = json.dumps(body).encode()
        return (
            f"POST /chat HTTP/1.1\r\nHost: 127.0.0.1:{harness.port}\r\n"
            f"Authorization: Bearer {harness.token()}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(raw)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode() + raw

    def _await(self, predicate, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return predicate()

    def test_config_defaults_to_the_owner_only_state_directory(self):
        config = adapter.AdapterConfig(
            adapter_secret=b"a" * 64,
            gateway_token="gateway-token-" + "x" * 24,
        )
        self.assertEqual(config.state_dir, adapter.default_state_dir())
        self.assertIsNotNone(config.state_dir)

    def test_success_clears_marker_and_health_stays_ok(self):
        harness = self._start()
        status, body, raw, _ = harness.request(
            "POST", "/chat", self._body("hello gate"), token=harness.token()
        )
        self.assertEqual(status, 200, raw)
        self.assertEqual(body["reply"], "fake upstream reply")
        self.assertFalse(self._marker().exists())
        status, body, raw, _ = harness.request(
            "GET", "/health", token=harness.token()
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "ok", "model": adapter.MODEL})

    def test_first_dispatch_syncs_new_directory_entries_and_marker(self):
        root = self.state_dir.parent
        self.state_dir = root / "new-parent" / "state"
        synced = set()
        fsync = os.fsync
        observed = []

        def record_sync(fd):
            info = os.fstat(fd)
            fsync(fd)
            synced.add((info.st_dev, info.st_ino))

        def inspect_dispatch(*args):
            paths = (root, self.state_dir.parent, self.state_dir, self._marker())
            for path in paths:
                info = path.stat()
                if (info.st_dev, info.st_ino) in synced:
                    observed.append(path)
            return "completed"

        with (
            mock.patch.object(os, "fsync", side_effect=record_sync),
            mock.patch.object(adapter, "call_upstream", side_effect=inspect_dispatch),
        ):
            harness = self._start()
            status, _, _, _ = harness.request(
                "POST", "/chat", self._body(), token=harness.token()
            )
        self.assertEqual(status, 200)
        self.assertEqual(observed, [root, self.state_dir.parent, self.state_dir, self._marker()])

    def test_failed_clear_sync_keeps_running_adapter_closed(self):
        harness = self._start()
        fsync = os.fsync

        def fail_clear_sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode) and not self._marker().exists():
                raise OSError("synthetic filesystem failure after marker removal")
            fsync(fd)

        with mock.patch.object(os, "fsync", side_effect=fail_clear_sync):
            status, body, _, _ = harness.request(
                "POST", "/chat", self._body(), token=harness.token()
            )
        self.assertEqual(status, 503)
        self.assertEqual(body, {"error": "dispatch state unavailable"})
        self.assertEqual(harness.upstream.calls, 1)
        self.assertEqual(harness.request("GET", "/health", token=harness.token())[0], 503)
        status, body, _, _ = harness.request(
            "POST", "/chat", self._body(), token=harness.token()
        )
        self.assertEqual(status, 503)
        self.assertEqual(body, {"error": "reconciliation required"})
        self.assertEqual(harness.upstream.calls, 1)

    def test_failed_marker_sync_prevents_dispatch(self):
        harness = self._start()
        fsync = os.fsync

        def fail_directory_sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("synthetic directory sync failure")
            fsync(fd)

        with mock.patch.object(os, "fsync", side_effect=fail_directory_sync):
            status, body, _, _ = harness.request(
                "POST", "/chat", self._body(), token=harness.token()
            )
        self.assertEqual(status, 503)
        self.assertEqual(body, {"error": "dispatch state unavailable"})
        self.assertTrue(self._marker().exists())
        self.assertEqual(harness.upstream.calls, 0)

    def test_unknown_timeout_retains_marker_and_blocks_all_conversations(self):
        harness = self._start(upstream_delay=0.5, upstream_timeout=0.1)
        conversation_id = str(uuid.uuid4())
        status, body, raw, _ = harness.request(
            "POST",
            "/chat",
            self._body("CANARY-PROMPT-TEXT", conversation_id),
            token=harness.token(),
        )
        self.assertEqual(status, 504)
        self.assertEqual(body, {"error": "upstream timeout", "outcome": "unknown"})
        marker = self._marker()
        self.assertTrue(marker.exists())
        self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
        marker_raw = marker.read_bytes()
        self.assertNotIn(b"CANARY-PROMPT-TEXT", marker_raw)
        self.assertNotIn(conversation_id.encode(), marker_raw)
        self.assertNotIn(harness.secret, marker_raw)
        self.assertNotIn(harness.gateway_token.encode(), marker_raw)
        self.assertIn(b"pending_dispatch", marker_raw)

        status, health, health_raw, _ = harness.request(
            "GET", "/health", token=harness.token()
        )
        self.assertEqual(status, 503)
        self.assertEqual(health["status"], "blocked")
        self.assertEqual(health["model"], adapter.MODEL)
        self.assertIn("reason", health)
        for forbidden in (
            conversation_id.encode(),
            harness.secret,
            harness.gateway_token.encode(),
        ):
            self.assertNotIn(forbidden, health_raw)

        status, body, raw, _ = harness.request(
            "POST",
            "/chat",
            self._body("different conversation", str(uuid.uuid4())),
            token=harness.token(),
        )
        self.assertEqual(status, 503)
        self.assertEqual(body, {"error": "reconciliation required"})
        self.assertEqual(harness.upstream.calls, 1)

    def test_upstream_error_retains_marker(self):
        harness = self._start(upstream_mode="error")
        status, body, raw, _ = harness.request(
            "POST", "/chat", self._body(), token=harness.token()
        )
        self.assertEqual(status, 502)
        self.assertEqual(
            body, {"error": "upstream rejected request", "outcome": "unknown"}
        )
        self.assertNotIn(b"UPSTREAM-INTERNAL-VALUE", raw)
        self.assertTrue(self._marker().exists())
        self.assertEqual(harness.upstream.calls, 1)

    def test_blocked_chat_still_requires_authentication(self):
        harness = self._start(upstream_delay=0.5, upstream_timeout=0.1)
        harness.request("POST", "/chat", self._body(), token=harness.token())
        self.assertTrue(self._marker().exists())
        status, body, _, _ = harness.request("POST", "/chat", self._body())
        self.assertEqual(status, 401)
        self.assertEqual(harness.upstream.calls, 1)

    def test_validation_error_writes_no_marker(self):
        harness = self._start()
        status, _, _, _ = harness.request(
            "POST",
            "/chat",
            {"conversation_id": "not-a-uuid", "message": "x"},
            token=harness.token(),
        )
        self.assertEqual(status, 400)
        self.assertFalse(self._marker().exists())
        self.assertEqual(harness.upstream.calls, 0)

    def test_not_dispatched_clears_marker_and_allows_next_chat(self):
        harness = self._start()
        with mock.patch.object(
            http.client.HTTPConnection,
            "connect",
            side_effect=ConnectionRefusedError,
        ):
            status, _, raw = raw_request(
                harness.port, self._raw_chat(harness, self._body())
            )
        self.assertEqual(status, 502)
        self.assertEqual(
            json.loads(raw),
            {"error": "upstream unavailable", "outcome": "not_dispatched"},
        )
        self.assertFalse(self._marker().exists())
        status, body, raw, _ = harness.request(
            "POST", "/chat", self._body("after"), token=harness.token()
        )
        self.assertEqual(status, 200, raw)
        self.assertFalse(self._marker().exists())

    def test_concurrent_second_request_is_busy_not_blocked(self):
        harness = self._start(upstream_delay=0.4)
        result: list[tuple[int, dict | None, bytes, dict]] = []

        def first_request() -> None:
            result.append(
                harness.request("POST", "/chat", self._body(), token=harness.token())
            )

        worker = threading.Thread(target=first_request, daemon=True)
        worker.start()
        self.assertTrue(
            self._await(lambda: harness.upstream.calls == 1),
            "first request never reached the fake upstream",
        )
        self.assertTrue(self._marker().exists())
        status, health, _, _ = harness.request(
            "GET", "/health", token=harness.token()
        )
        self.assertEqual(status, 200)
        self.assertEqual(health, {"status": "ok", "model": adapter.MODEL})
        status, body, _, _ = harness.request(
            "POST",
            "/chat",
            self._body("overlap", str(uuid.uuid4())),
            token=harness.token(),
        )
        self.assertEqual(status, 503)
        self.assertEqual(body, {"error": "busy"})
        worker.join(timeout=5)
        self.assertEqual(result[0][0], 200)
        self.assertFalse(self._marker().exists())
        self.assertEqual(harness.upstream.calls, 1)

    def test_crash_marker_blocks_a_new_adapter_until_reconcile(self):
        completed = subprocess.run(
            [
                sys.executable, "-c",
                "import os, sys, uuid; from pathlib import Path; import lobby_adapter as adapter\n"
                "store = adapter.StateStore(Path(sys.argv[1]))\n"
                "store.prepare()\n"
                "store.acquire_process_lock()\n"
                "store.begin(adapter.conversation_namespace(str(uuid.uuid4())))\n"
                "os._exit(0)\n",
                str(self.state_dir),
            ],
            cwd=HERE, capture_output=True, text=True, timeout=3,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(self._marker().exists())

        harness = self._start()
        status, body, _, _ = harness.request(
            "GET", "/health", token=harness.token()
        )
        self.assertEqual(status, 503)
        self.assertEqual(body["status"], "blocked")
        status, body, _, _ = harness.request(
            "POST", "/chat", self._body(), token=harness.token()
        )
        self.assertEqual(status, 503)
        self.assertEqual(body, {"error": "reconciliation required"})
        self.assertEqual(harness.upstream.calls, 0)

    def test_restart_retains_marker_and_reconcile_is_explicit(self):
        harness = self._start(upstream_delay=0.5, upstream_timeout=0.1)
        harness.request("POST", "/chat", self._body(), token=harness.token())
        self.assertTrue(self._marker().exists())
        harness.close()
        self.harness = None

        output = io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(output),
        ):
            code = adapter.main(["reconcile", "--state-dir", str(self.state_dir)])
        self.assertEqual(code, 2)
        self.assertTrue(self._marker().exists())
        self.assertIn("confirm-upstream-inspected", output.getvalue())

        harness = self._start()
        status, body, _, _ = harness.request(
            "POST", "/chat", self._body(), token=harness.token()
        )
        self.assertEqual(status, 503)
        self.assertEqual(body, {"error": "reconciliation required"})
        self.assertEqual(harness.upstream.calls, 0)
        harness.close()
        self.harness = None

        with (
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(output),
        ):
            code = adapter.main(
                [
                    "reconcile",
                    "--state-dir",
                    str(self.state_dir),
                    "--confirm-upstream-inspected",
                ]
            )
        self.assertEqual(code, 0)
        self.assertFalse(self._marker().exists())

        harness = self._start()
        status, body, raw, _ = harness.request(
            "POST", "/chat", self._body("resumed"), token=harness.token()
        )
        self.assertEqual(status, 200, raw)
        self.assertFalse(self._marker().exists())

    def test_reconcile_refuses_while_adapter_holds_the_lock(self):
        harness = self._start(upstream_delay=0.5, upstream_timeout=0.1)
        harness.request("POST", "/chat", self._body(), token=harness.token())
        self.assertTrue(self._marker().exists())
        output = io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(output),
        ):
            code = adapter.main(
                [
                    "reconcile",
                    "--state-dir",
                    str(self.state_dir),
                    "--confirm-upstream-inspected",
                ]
            )
        self.assertEqual(code, 2)
        self.assertTrue(self._marker().exists())
        self.assertIn("another adapter", output.getvalue())

    def test_reconcile_and_second_adapter_are_blocked_while_shutdown_drains(self):
        harness = self._start()
        dispatched = threading.Event()
        finish_dispatch = threading.Event()
        close_started = threading.Event()
        result = []

        def upstream(*args):
            dispatched.set()
            finish_dispatch.wait(5)
            raise adapter.UpstreamFailure(504, "upstream timeout")

        def chat():
            result.append(harness.request("POST", "/chat", self._body(), token=harness.token()))

        def close():
            close_started.set()
            harness.server.server_close()

        with mock.patch.object(adapter, "call_upstream", side_effect=upstream):
            client = threading.Thread(target=chat)
            client.start()
            closer = threading.Thread(target=close)
            try:
                self.assertTrue(dispatched.wait(3))
                harness.server.shutdown()
                closer.start()
                self.assertTrue(close_started.wait(3))
                self.assertTrue(self._await(lambda: harness.server.socket.fileno() == -1))
                completed = subprocess.run(
                    [sys.executable, str(HERE / "lobby_adapter.py"), "reconcile",
                     "--state-dir", str(self.state_dir), "--confirm-upstream-inspected"],
                    capture_output=True, text=True, timeout=3,
                )
                self.assertEqual(completed.returncode, 2)
                self.assertIn("another adapter", completed.stderr)
                with self.assertRaises(adapter.StateError):
                    adapter.LobbyHTTPServer(harness.config, adapter.make_handler(harness.config))
                self.assertTrue(self._marker().exists())
            finally:
                finish_dispatch.set()
                client.join(5)
                if closer.ident is not None:
                    closer.join(5)
        self.assertFalse(closer.is_alive())
        self.assertEqual(result[0][0], 504)
        self.assertTrue(self._marker().exists())

    def test_malformed_marker_blocks_chats_and_does_not_echo_its_fields(self):
        store = adapter.StateStore(self.state_dir)
        store.prepare()
        canary = secrets.token_hex(16)
        write_private(self._marker(), json.dumps({"dispatch_id": canary}).encode())
        harness = self._start()
        self.assertEqual(harness.request("GET", "/health", token=harness.token())[0], 503)
        self.assertEqual(harness.request("POST", "/chat", self._body(), token=harness.token())[0], 503)
        self.assertEqual(harness.request("POST", "/reconcile", token=harness.token())[0], 404)
        self.assertEqual(harness.upstream.calls, 0)
        harness.close()
        self.harness = None
        completed = subprocess.run(
            [sys.executable, str(HERE / "lobby_adapter.py"), "reconcile",
             "--state-dir", str(self.state_dir)],
            capture_output=True, text=True, timeout=3,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertTrue(self._marker().exists())
        self.assertNotIn(canary, completed.stdout + completed.stderr)
        self.assertIn("unreadable", completed.stdout)

    def test_competing_adapter_same_state_dir_is_refused(self):
        harness = self._start()
        with self.assertRaises(adapter.StateError):
            adapter.LobbyHTTPServer(
                harness.config, adapter.make_handler(harness.config)
            )
        status, _, _, _ = harness.request(
            "GET", "/health", token=harness.token()
        )
        self.assertEqual(status, 200)

    def test_state_directory_with_group_access_is_rejected(self):
        self.state_dir.mkdir(parents=True)
        self.state_dir.chmod(0o755)
        store = adapter.StateStore(self.state_dir)
        with self.assertRaises(adapter.ConfigError):
            store.prepare()

    def test_client_disconnect_after_dispatch_clears_on_known_completion(self):
        harness = self._start(upstream_delay=0.2)
        request = self._raw_chat(harness, self._body("disconnect"))
        with socket.create_connection(
            ("127.0.0.1", harness.port), timeout=2
        ) as sock:
            sock.sendall(request)
            # Close before reading the reply: the upstream run still completes.
        self.assertTrue(
            self._await(
                lambda: harness.upstream.calls == 1 and not self._marker().exists()
            ),
            "known completion did not clear the marker",
        )
        self.assertFalse(self._marker().exists())


if __name__ == "__main__":
    unittest.main()
