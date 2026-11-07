"""OAuth protected-resource verification using a locally generated RSA test key.

Never trusts token-supplied JWKS URLs; issuer, audience, and subject are pinned.
No external identity provider or network is contacted by this test.
"""
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
import http.client
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from shards_mcp.core import Gateway, GatewayError, SCOPES
from shards_mcp.oauth import OAuthResourceServer
from shards_mcp.server import make_handler


class OAuthTests(unittest.TestCase):
    ISSUER = "https://issuer.example.test"
    RESOURCE = "https://shards.example.test/mcp"
    JWKS = "https://issuer.example.test/keys.json"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.admin_secret = secrets.token_urlsafe(48)
        self.gateway = Gateway(str(Path(self.temp.name) / "state.sqlite"), self.admin_secret)
        self.admin = self.gateway.authenticate(self.admin_secret)
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public = self.key.public_key()
        self.external_sub = "oauth-test-identity-123"
        registered = self.gateway.register(
            self.admin, "chatgpt-oauth", "tests", ["read-only"],
            ["agent:read", "message:read"], oauth_subject=self.external_sub,
        )
        self.agent_id = registered["agent_id"]
        self.local_agent_token = registered["token"]
        self.oauth = OAuthResourceServer(
            self.gateway, self.ISSUER, self.RESOURCE, self.JWKS,
            key_resolver=lambda kid: self.public if kid == "trusted-key-1" else None,
        )
        self.http = ThreadingHTTPServer(("127.0.0.1", 0),
                                        make_handler(self.gateway, set(), oauth=self.oauth))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def jwt_token(self, **overrides):
        claims = {
            "iss": self.ISSUER, "sub": self.external_sub, "aud": self.RESOURCE,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            "scope": "agent:read message:read",
        }
        claims.update(overrides)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "trusted-key-1"})

    def request(self, method, path, token=None, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.http.server_port, timeout=5)
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = "Bearer " + token
        data = json.dumps(payload) if payload is not None else None
        conn.request(method, path, data, headers=h)
        response = conn.getresponse()
        headers = {k.lower(): v for k, v in response.getheaders()}
        body = response.read()
        code = response.status
        conn.close()
        return code, json.loads(body) if body else None, headers

    def test_rfc9728_metadata_and_auth_challenge(self):
        code, metadata, _ = self.request("GET", "/.well-known/oauth-protected-resource")
        self.assertEqual(code, 200)
        self.assertEqual(metadata["resource"], self.RESOURCE)
        self.assertEqual(metadata["authorization_servers"], [self.ISSUER])
        self.assertEqual(set(metadata["scopes_supported"]), set(SCOPES))
        code, _, _ = self.request("GET", "/.well-known/oauth-protected-resource/mcp")
        self.assertEqual(code, 200)
        code, _, headers = self.request("POST", "/mcp",
                                        payload={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(code, 401)
        self.assertIn("resource_metadata=", headers["www-authenticate"])
        self.assertIn("/.well-known/oauth-protected-resource", headers["www-authenticate"])

    def test_valid_jwt_is_bound_to_registered_scopes_and_identity(self):
        code, data, _ = self.request("POST", "/mcp", self.jwt_token(),
                                    {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(code, 200)
        names = {t["name"] for t in data["result"]["tools"]}
        self.assertIn("agent_list", names)
        self.assertIn("message_poll", names)
        self.assertIn("agent_identity", names)
        _, identity, _ = self.request("POST", "/mcp", self.jwt_token(),
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "agent_identity", "arguments": {}}})
        self.assertEqual(identity["result"]["structuredContent"]["agent_id"], self.agent_id)
        self.assertNotIn("token", identity["result"]["structuredContent"])
        self.assertNotIn("task_create", names)
        self.assertNotIn("system_status", names)
        result = self.oauth.authenticate(self.jwt_token())
        self.assertEqual(result.agent_id, self.agent_id)
        self.assertEqual(set(result.scopes), {"agent:read", "message:read"})

    def test_forged_or_unrelated_tokens_are_rejected(self):
        unauthorized = (
            self.admin_secret, self.local_agent_token,
            self.jwt_token(aud="https://other.example.test"),
            self.jwt_token(iss="https://other-issuer.example.test"),
            self.jwt_token(sub="unknown-identity"),
            self.jwt_token(exp=datetime.now(timezone.utc) - timedelta(minutes=10)),
            self.jwt_token(scope="task:create"),
        )
        for credential in unauthorized:
            with self.subTest(length=len(credential)):
                code, _, _ = self.request("GET", "/v1/tools", credential)
                self.assertEqual(code, 401)
        foreign_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode({
            "iss": self.ISSUER, "sub": self.external_sub, "aud": self.RESOURCE,
            "iat": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            "scope": "agent:read",
        }, foreign_key, algorithm="RS256", headers={"kid": "trusted-key-1"})
        self.assertEqual(self.request("GET", "/v1/tools", forged)[0], 401)

    def test_restricted_scopes_and_revocation(self):
        # OAuth claims cannot grant a scope that the enrolled agent lacks.
        result = self.oauth.authenticate(self.jwt_token(scope="agent:read task:create *"))
        self.assertEqual(result.scopes, ("agent:read",))
        self.gateway.revoke(self.admin, self.agent_id)
        self.assertEqual(self.request("GET", "/v1/tools", self.jwt_token())[0], 401)

    def test_untrusted_configuration_fails_closed(self):
        for issuer, resource, jwks in [
            ("http://issuer.test", self.RESOURCE, self.JWKS),
            (self.ISSUER, "http://shards.test/mcp", self.JWKS),
            (self.ISSUER, self.RESOURCE, "http://issuer.test/keys.json"),
            (self.ISSUER, "https://shards.test/other-path", self.JWKS),
            ("https://user:password@issuer.example.test", self.RESOURCE, self.JWKS),
        ]:
            with self.subTest(issuer=issuer, resource=resource, jwks=jwks):
                with self.assertRaises(ValueError):
                    OAuthResourceServer(self.gateway, issuer, resource, jwks,
                                        key_resolver=lambda _: self.public)

    def test_oauth_issuer_uri_is_compared_exactly_including_trailing_slash(self):
        issuer = self.ISSUER + "/"
        oauth = OAuthResourceServer(self.gateway, issuer, self.RESOURCE, self.JWKS,
                                    key_resolver=lambda _: self.public)
        self.assertEqual(oauth.issuer, issuer)
        token = self.jwt_token(iss=issuer)
        self.assertEqual(oauth.authenticate(token).agent_id, self.agent_id)
        with self.assertRaises(GatewayError):
            oauth.authenticate(self.jwt_token(iss=self.ISSUER))

    def test_duplicate_oauth_subject_is_rejected(self):
        with self.assertRaises(GatewayError) as raised:
            self.gateway.register(self.admin, "other-agent", "test", [], ["agent:read"],
                                  oauth_subject=self.external_sub)
        self.assertEqual(raised.exception.code, "CONFLICT")


if __name__ == "__main__":
    unittest.main()
