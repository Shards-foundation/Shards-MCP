#!/usr/bin/env python3
"""Bounded local Lobby HTTP adapter for Agent Hub v0.2 (stdlib only).

The adapter is a loopback-only translation boundary between a local Lobby
client and the existing OpenClaw gateway. It does not install, deploy, tunnel,
or widen any gateway approval. It never forwards caller headers and never
returns either credential.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import io
import json
import math
import os
import re
import secrets
import socket
import stat
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

BIND_HOST = "127.0.0.1"
BIND_PORT = 18790
UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = 18789
UPSTREAM_PATH = "/v1/chat/completions"
MODEL = "openclaw/shards"

MAX_REQUEST_BYTES = 16 * 1024
MAX_MESSAGE_CHARS = 8_000
MAX_MESSAGE_BYTES = 12 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_JSON_DEPTH = 8
MAX_CONCURRENCY = 1
MAX_CONNECTIONS = 8
REQUEST_TIMEOUT = 10.0
UPSTREAM_TIMEOUT = 30.0
MAX_SECRET_BYTES = 512
MAX_CONFIG_BYTES = 64 * 1024

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)
_BEARER_RE = re.compile(r"Bearer ([!-~]+)\Z", re.IGNORECASE)
_CONTENT_TYPE_RE = re.compile(r"application/json(?:\s*;.*)?\Z", re.IGNORECASE)
_CONTENT_LENGTH_RE = re.compile(r"[0-9]{1,10}\Z")
_HTTP_TOKEN_RE = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_GATEWAY_TOKEN_PATHS = (("gateway", "auth", "token"), ("gateway", "token"))


class ConfigError(RuntimeError):
    """Startup failure whose message never includes a credential value."""


class RequestRejected(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class UpstreamFailure(Exception):
    def __init__(self, status: int, message: str, outcome: str = "unknown"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.outcome = outcome


def default_secret_file() -> Path:
    return Path.home() / ".openclaw" / "lobby-adapter.secret"


def default_openclaw_config() -> Path:
    return Path.home() / ".openclaw" / "openclaw.json"


def _read_private_file(path: Path, *, max_bytes: int, label: str) -> bytes:
    """Read a regular owner-only file without following symlinks."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        raise ConfigError(f"{label} is missing") from None
    except OSError:
        raise ConfigError(f"{label} is unreadable or is a symlink") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ConfigError(f"{label} must be a regular file")
        if info.st_uid != os.geteuid():
            raise ConfigError(f"{label} must be owned by the current user")
        if info.st_mode & 0o077:
            raise ConfigError(
                f"{label} must not be accessible by group or others (chmod 600)"
            )
        if info.st_size <= 0 or info.st_size > max_bytes:
            raise ConfigError(f"{label} has an invalid size")
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            chunk = os.read(fd, min(8192, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) > max_bytes:
        raise ConfigError(f"{label} has an invalid size")
    return data


def load_adapter_secret(path: Path | str) -> bytes:
    data = _read_private_file(
        Path(path), max_bytes=MAX_SECRET_BYTES, label="adapter secret file"
    )
    if data.endswith(b"\n"):
        data = data[:-1]
    if data.endswith(b"\r"):
        data = data[:-1]
    if len(data) < 32:
        raise ConfigError("adapter secret must be at least 32 bytes")
    if any(byte < 0x21 or byte > 0x7E for byte in data):
        raise ConfigError("adapter secret must be printable ASCII without whitespace")
    return data


def create_secret(path: Path | str) -> Path:
    path = Path(path)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        raise ConfigError("cannot create the secret directory") from None
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise ConfigError(
            "secret file already exists; remove it explicitly to rotate"
        ) from None
    except OSError:
        raise ConfigError("cannot create the secret file") from None
    try:
        os.fchmod(fd, 0o600)
        payload = secrets.token_urlsafe(48).encode("ascii") + b"\n"
        written = 0
        while written < len(payload):
            written += os.write(fd, payload[written:])
        os.fsync(fd)
    except OSError:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise ConfigError("cannot write the secret file") from None
    finally:
        os.close(fd)
    return path


def load_gateway_token(path: Path | str) -> str:
    data = _read_private_file(
        Path(path), max_bytes=MAX_CONFIG_BYTES, label="OpenClaw config"
    )
    try:
        document = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ConfigError("OpenClaw config is not valid UTF-8 JSON") from None
    if not isinstance(document, dict):
        raise ConfigError("OpenClaw config must be a JSON object")
    found: list[str] = []
    for keys in _GATEWAY_TOKEN_PATHS:
        current: Any = document
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                break
            current = current[key]
        else:
            if not isinstance(current, str) or not current:
                raise ConfigError("OpenClaw gateway token is not a non-empty string")
            found.append(current)
    if not found:
        raise ConfigError(
            "OpenClaw gateway token not found at gateway.auth.token or gateway.token"
        )
    if len(set(found)) != 1:
        raise ConfigError("OpenClaw config contains conflicting gateway tokens")
    token = found[0]
    if (
        len(token) < 16
        or len(token) > 4096
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in token)
    ):
        raise ConfigError("OpenClaw gateway token has an invalid format")
    return token


@dataclass(frozen=True)
class AdapterConfig:
    adapter_secret: bytes = field(repr=False)
    gateway_token: str = field(repr=False)
    bind_host: str = BIND_HOST
    bind_port: int = BIND_PORT
    upstream_host: str = UPSTREAM_HOST
    upstream_port: int = UPSTREAM_PORT
    upstream_path: str = UPSTREAM_PATH
    request_timeout: float = REQUEST_TIMEOUT
    upstream_timeout: float = UPSTREAM_TIMEOUT
    max_request_bytes: int = MAX_REQUEST_BYTES
    max_message_chars: int = MAX_MESSAGE_CHARS
    max_message_bytes: int = MAX_MESSAGE_BYTES
    max_response_bytes: int = MAX_RESPONSE_BYTES
    max_concurrency: int = MAX_CONCURRENCY

    def __post_init__(self) -> None:
        if self.bind_host != BIND_HOST:
            raise ValueError("bind host is fixed to 127.0.0.1")
        if self.upstream_host != UPSTREAM_HOST:
            raise ValueError("upstream host is fixed to 127.0.0.1")
        if self.upstream_path != UPSTREAM_PATH:
            raise ValueError("upstream path is fixed")
        if not 0 <= self.bind_port <= 65535:
            raise ValueError("bind port is invalid")
        if not 1 <= self.upstream_port <= 65535:
            raise ValueError("upstream port is invalid")
        if (
            not isinstance(self.adapter_secret, bytes)
            or len(self.adapter_secret) < 32
            or any(byte < 0x21 or byte > 0x7E for byte in self.adapter_secret)
        ):
            raise ValueError("adapter secret must be at least 32 printable ASCII bytes")
        if (
            not isinstance(self.gateway_token, str)
            or len(self.gateway_token) < 16
            or any(
                ord(character) < 0x21 or ord(character) > 0x7E
                for character in self.gateway_token
            )
        ):
            raise ValueError("gateway token has an invalid format")
        if _constant_time_equal(self.adapter_secret, self.gateway_token.encode("ascii")):
            raise ValueError("adapter secret and gateway token must differ")
        for name in (
            "request_timeout",
            "upstream_timeout",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be finite and positive")
        for name in (
            "max_request_bytes",
            "max_message_chars",
            "max_message_bytes",
            "max_response_bytes",
            "max_concurrency",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


def _constant_time_equal(left: bytes, right: bytes) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(left).digest(), hashlib.sha256(right).digest()
    )


def _time_left(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining


class _DeadlineReader(io.RawIOBase):
    """Apply an absolute deadline to each socket read behind HTTP buffering."""

    def __init__(self, sock: socket.socket, deadline: float):
        super().__init__()
        self.sock = sock
        self.deadline = deadline
        # Keep the descriptor alive for responses with Connection: close.
        self.stream = sock.makefile("rb", buffering=0)

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        self.sock.settimeout(_time_left(self.deadline))
        return self.stream.readinto(buffer)

    def close(self) -> None:
        self.stream.close()
        super().close()


class _ResponseSocket:
    """Supply the deadline-aware file that stdlib HTTPResponse reads."""

    def __init__(self, sock: socket.socket, deadline: float):
        self.sock = sock
        self.deadline = deadline

    def makefile(self, mode: str) -> io.BufferedReader:
        return io.BufferedReader(_DeadlineReader(self.sock, self.deadline))


class _DeadlineHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, deadline: float):
        self.deadline = deadline
        super().__init__(host, port, timeout=_time_left(deadline))

    def send(self, data) -> None:
        if self.sock is not None:
            self.sock.settimeout(_time_left(self.deadline))
        super().send(data)

    def response_class(self, sock, *args, **kwargs):
        return http.client.HTTPResponse(
            _ResponseSocket(sock, self.deadline), *args, **kwargs
        )


def _valid_headers(headers: http.client.HTTPMessage) -> bool:
    return not headers.defects and all(
        _HTTP_TOKEN_RE.fullmatch(name)
        and isinstance(value, str)
        and all(character == "\t" or 0x20 <= ord(character) < 0x7F for character in value)
        for name, value in headers.items()
    )


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_: str) -> Any:
    raise ValueError("non-finite number")


def _json_depth_ok(value: Any, limit: int = MAX_JSON_DEPTH) -> bool:
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > limit:
            return False
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
    return True


def parse_strict_json(raw: bytes) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise RequestRejected(400, "invalid JSON") from None
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (ValueError, RecursionError):
        raise RequestRejected(400, "invalid JSON") from None
    if not _json_depth_ok(value):
        raise RequestRejected(400, "JSON nesting too deep")
    return value


def _validate_text(value: Any, max_chars: int, max_bytes: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RequestRejected(400, "message must be non-empty text")
    if len(value) > max_chars:
        raise RequestRejected(413, "message too large")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise RequestRejected(400, "message must be valid Unicode text") from None
    if len(encoded) > max_bytes:
        raise RequestRejected(413, "message too large")
    if any(
        (ord(character) < 0x20 and character not in "\n\r\t")
        or ord(character) == 0x7F
        for character in value
    ):
        raise RequestRejected(400, "message contains control characters")
    return value


def validate_chat_payload(payload: Any, config: AdapterConfig) -> tuple[str, str]:
    if not isinstance(payload, dict):
        raise RequestRejected(400, "request must be a JSON object")
    if set(payload) != {"conversation_id", "message"}:
        raise RequestRejected(
            400, "request must contain exactly conversation_id and message"
        )
    raw_id = payload["conversation_id"]
    if not isinstance(raw_id, str) or not _UUID_RE.fullmatch(raw_id):
        raise RequestRejected(400, "conversation_id must be a UUID")
    try:
        parsed = uuid.UUID(raw_id)
    except ValueError:
        raise RequestRejected(400, "conversation_id must be a UUID") from None
    if str(parsed) != raw_id.lower():
        raise RequestRejected(400, "conversation_id must be canonical UUID text")
    message = _validate_text(
        payload["message"], config.max_message_chars, config.max_message_bytes
    )
    return str(parsed), message


def conversation_namespace(conversation_id: str) -> str:
    digest = hashlib.sha256(
        b"shards-lobby-user-v1\x00" + conversation_id.encode("ascii")
    ).hexdigest()
    return "lobby-" + digest[:32]


def _upstream_body(namespace: str, message: str) -> bytes:
    # No tools or tool_choice fields are sent. A prompt-only "no tools" request
    # would not enforce a policy; tool authority remains with the gateway.
    return json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": message}],
            "user": namespace,
            "stream": False,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _extract_reply(payload: Any, max_chars: int, max_bytes: int) -> str:
    if not isinstance(payload, dict):
        raise UpstreamFailure(502, "invalid upstream response")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise UpstreamFailure(502, "invalid upstream response")
    first = choices[0]
    if not isinstance(first, dict):
        raise UpstreamFailure(502, "invalid upstream response")
    message = first.get("message")
    if not isinstance(message, dict):
        raise UpstreamFailure(502, "invalid upstream response")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise UpstreamFailure(502, "invalid upstream response")
    if len(content) > max_chars:
        raise UpstreamFailure(502, "invalid upstream response")
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError:
        raise UpstreamFailure(502, "invalid upstream response") from None
    if len(encoded) > max_bytes:
        raise UpstreamFailure(502, "invalid upstream response")
    if any(
        (ord(character) < 0x20 and character not in "\n\r\t")
        or ord(character) == 0x7F
        for character in content
    ):
        raise UpstreamFailure(502, "invalid upstream response")
    return content


def call_upstream(config: AdapterConfig, namespace: str, message: str) -> str:
    """Make exactly one bounded upstream call. Ambiguous outcomes are not retried."""
    body = _upstream_body(namespace, message)
    deadline = time.monotonic() + config.upstream_timeout
    connection = _DeadlineHTTPConnection(
        config.upstream_host, config.upstream_port, deadline
    )
    try:
        try:
            connection.connect()
        except TimeoutError:
            raise UpstreamFailure(504, "upstream timeout", "not_dispatched") from None
        except OSError:
            raise UpstreamFailure(502, "upstream unavailable", "not_dispatched") from None
        try:
            connection.request(
                "POST",
                config.upstream_path,
                body=body,
                headers={
                    "Authorization": "Bearer " + config.gateway_token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Host": f"{config.upstream_host}:{config.upstream_port}",
                    "Connection": "close",
                },
            )
            with connection.getresponse() as response:
                if response.status != 200:
                    raise UpstreamFailure(502, "upstream rejected request")
                lengths = response.headers.get_all("Content-Length", [])
                encodings = response.headers.get_all("Transfer-Encoding", [])
                if (
                    not _valid_headers(response.headers)
                    or len(lengths) > 1
                    or (lengths and not _CONTENT_LENGTH_RE.fullmatch(lengths[0]))
                    or (encodings and (lengths or [value.lower() for value in encodings] != ["chunked"]))
                ):
                    raise UpstreamFailure(502, "invalid upstream response")
                raw = response.read(config.max_response_bytes + 1)
                if len(raw) > config.max_response_bytes:
                    raise UpstreamFailure(502, "upstream response too large")
                if response.length not in (None, 0):
                    raise UpstreamFailure(502, "invalid upstream response")
                _time_left(deadline)
        except TimeoutError:
            raise UpstreamFailure(504, "upstream timeout") from None
        except (http.client.HTTPException, OSError):
            raise UpstreamFailure(502, "upstream unavailable") from None
    finally:
        connection.close()
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise UpstreamFailure(502, "invalid upstream response") from None
    if not _json_depth_ok(payload):
        raise UpstreamFailure(502, "invalid upstream response")
    return _extract_reply(payload, config.max_message_chars, config.max_message_bytes)


def make_handler(config: AdapterConfig):
    known_credentials = config.adapter_secret.decode("ascii"), config.gateway_token

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "LobbyAdapter/0.2"
        sys_version = ""

        def setup(self) -> None:
            super().setup()
            self._request_deadline = time.monotonic() + config.request_timeout
            self.rfile.close()
            self.rfile = io.BufferedReader(
                _DeadlineReader(self.connection, self._request_deadline)
            )
            self._responded = False

        def log_message(self, format: str, *args: Any) -> None:
            return None

        def parse_request(self) -> bool:
            if not super().parse_request():
                return False
            _time_left(self._request_deadline)
            parts = self.requestline.split(" ")
            if (
                self.request_version not in ("HTTP/1.0", "HTTP/1.1")
                or not self.raw_requestline.endswith(b"\r\n")
                or len(parts) != 3
                or parts != self.requestline.split()
                or not _HTTP_TOKEN_RE.fullmatch(self.command)
                or not _valid_headers(self.headers)
            ):
                self.send_error(400)
                return False
            if "Expect" in self.headers:
                return self.handle_expect_100()
            return True

        def handle_expect_100(self) -> bool:
            self._error(417, "expectation not supported")
            return False

        def send_error(self, code: int, message=None, explain=None) -> None:
            if self.request_version not in ("HTTP/1.0", "HTTP/1.1"):
                self.request_version = "HTTP/1.0"
            self._error(code, "invalid HTTP request")

        def _host_ok(self) -> bool:
            values = self.headers.get_all("Host", [])
            if len(values) != 1:
                return False
            port = self.server.server_address[1]
            return values[0] in (
                f"127.0.0.1:{port}",
                f"localhost:{port}",
            )

        def _origin_ok(self) -> bool:
            return not self.headers.get_all("Origin", [])

        def _target_ok(self) -> bool:
            # BaseHTTPRequestHandler collapses a leading "//" into "/", which
            # would otherwise turn an absolute-form or doubled-slash target
            # into the legitimate route. Compare the raw request target too.
            parts = self.requestline.split()
            if len(parts) != 3 or parts[1] != self.path:
                return False
            return "?" not in parts[1] and "#" not in parts[1]

        def _authorized(self) -> bool:
            values = self.headers.get_all("Authorization", [])
            if len(values) != 1:
                return False
            match = _BEARER_RE.fullmatch(values[0])
            if match is None:
                return False
            return _constant_time_equal(
                match.group(1).encode("utf-8"), config.adapter_secret
            )

        def _respond(
            self,
            status: int,
            payload: dict[str, Any],
            headers: dict[str, str] | None = None,
        ) -> None:
            raw = json.dumps(
                payload, ensure_ascii=True, separators=(",", ":")
            ).encode("utf-8")
            self._responded = True
            try:
                deadline = time.monotonic() + config.request_timeout
                self.connection.settimeout(_time_left(deadline))
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.connection.settimeout(_time_left(deadline))
                self.wfile.write(raw)
            except OSError:
                pass
            finally:
                self.close_connection = True

        def _error(
            self,
            status: int,
            message: str,
            headers: dict[str, str] | None = None,
            outcome: str | None = None,
        ) -> None:
            payload: dict[str, Any] = {"error": message}
            if outcome is not None:
                payload["outcome"] = outcome
            self._respond(status, payload, headers)

        def _reject(self, status: int, message: str, allow: str = "POST") -> None:
            headers = None
            if status == 401:
                headers = {"WWW-Authenticate": 'Bearer realm="lobby-adapter"'}
            elif status == 405:
                headers = {"Allow": allow}
            elif status == 503:
                headers = {"Retry-After": "1"}
            self._error(status, message, headers)

        def do_GET(self) -> None:
            if not self._target_ok():
                return self._reject(404, "not found")
            if not self._host_ok() or not self._origin_ok():
                return self._reject(403, "forbidden")
            if self.path == "/health":
                if not self._authorized():
                    return self._reject(401, "unauthorized")
                return self._respond(200, {"status": "ok", "model": MODEL})
            if self.path == "/chat":
                return self._reject(405, "method not allowed")
            return self._reject(404, "not found")

        def do_POST(self) -> None:
            if not self._target_ok():
                return self._reject(404, "not found")
            if not self._host_ok() or not self._origin_ok():
                return self._reject(403, "forbidden")
            if self.path != "/chat":
                if self.path == "/health":
                    return self._reject(405, "method not allowed", allow="GET")
                return self._reject(404, "not found")
            if not self._authorized():
                return self._reject(401, "unauthorized")
            try:
                self._handle_chat()
            except RequestRejected as exc:
                self._reject(exc.status, exc.message)
            except UpstreamFailure as exc:
                self._error(exc.status, exc.message, outcome=exc.outcome)
            except Exception:
                if not self._responded:
                    self._error(500, "internal error")

        def _read_body(self, length: int) -> bytes:
            try:
                body = self.rfile.read(length)
                _time_left(self._request_deadline)
            except TimeoutError:
                raise RequestRejected(408, "request body timed out") from None
            except OSError:
                raise RequestRejected(400, "invalid request body") from None
            if len(body) != length:
                raise RequestRejected(400, "invalid request body")
            return body

        def _handle_chat(self) -> None:
            if "Transfer-Encoding" in self.headers:
                raise RequestRejected(411, "Content-Length required")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not _CONTENT_LENGTH_RE.fullmatch(lengths[0]):
                raise RequestRejected(411, "valid Content-Length required")
            length = int(lengths[0])
            if length <= 0:
                raise RequestRejected(400, "request body required")
            if length > config.max_request_bytes:
                raise RequestRejected(413, "request body too large")
            content_types = self.headers.get_all("Content-Type", [])
            if (
                len(content_types) != 1
                or not _CONTENT_TYPE_RE.fullmatch(content_types[0].strip())
            ):
                raise RequestRejected(415, "application/json required")
            if "Content-Encoding" in self.headers:
                raise RequestRejected(415, "content encoding not supported")
            raw = self._read_body(length)
            payload = parse_strict_json(raw)
            conversation_id, message = validate_chat_payload(payload, config)
            namespace = conversation_namespace(conversation_id)
            if not self.server.slots.acquire(blocking=False):
                raise RequestRejected(503, "busy")
            try:
                reply = call_upstream(config, namespace, message)
            except UpstreamFailure:
                raise
            except Exception:
                raise UpstreamFailure(502, "upstream unavailable") from None
            finally:
                self.server.slots.release()
            if any(
                credential in reply or credential in conversation_id
                for credential in known_credentials
            ):
                raise UpstreamFailure(502, "invalid upstream response")
            self._respond(
                200, {"conversation_id": conversation_id, "reply": reply}
            )

    return Handler


class LobbyHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 8

    def __init__(self, config: AdapterConfig, handler_class):
        self.config = config
        self.slots = threading.BoundedSemaphore(config.max_concurrency)
        self.connection_slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__((config.bind_host, config.bind_port), handler_class)

    def process_request(self, request, client_address) -> None:
        if not self.connection_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connection_slots.release()

    def handle_error(self, request, client_address) -> None:
        # The default traceback can include parser or peer data.
        return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lobby-adapter",
        description="Bounded loopback Lobby adapter for the local OpenClaw gateway.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="run the loopback adapter")
    serve.add_argument(
        "--secret-file", type=Path, default=default_secret_file()
    )
    serve.add_argument(
        "--openclaw-config", type=Path, default=default_openclaw_config()
    )
    init_secret = subparsers.add_parser(
        "init-secret", help="create a new mode-0600 adapter secret"
    )
    init_secret.add_argument(
        "--secret-file", type=Path, default=default_secret_file()
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "init-secret":
        try:
            path = create_secret(args.secret_file)
        except ConfigError as exc:
            print(f"lobby-adapter: {exc}", file=sys.stderr)
            return 2
        print(f"created {path} with mode 0600; secret value not printed")
        return 0
    try:
        config = AdapterConfig(
            adapter_secret=load_adapter_secret(args.secret_file),
            gateway_token=load_gateway_token(args.openclaw_config),
        )
        server = LobbyHTTPServer(config, make_handler(config))
    except (ConfigError, ValueError, OSError) as exc:
        print(f"lobby-adapter: {exc}", file=sys.stderr)
        return 2
    host, port = server.server_address[:2]
    print(
        f"lobby-adapter listening on http://{host}:{port}; "
        f"upstream http://{UPSTREAM_HOST}:{UPSTREAM_PORT}{UPSTREAM_PATH}; "
        f"model {MODEL}",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
