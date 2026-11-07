"""Optional OAuth JWT resource-server authentication for remote MCP clients.

The gateway IS NOT an OAuth authorisation server. It validates signed JWT
access tokens minted by a separately configured, trusted provider. The signed
issuer+subject is bound to a locally enrolled agent, then scopes are intersected.
Only a pinned, HTTPS JWKS URI is contacted; JWT header URLs are never used.
"""
from __future__ import annotations

import os
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from .core import Gateway, GatewayError, Principal, SCOPES

try:
    import jwt
    from jwt import PyJWKClient
    from jwt.exceptions import PyJWTError
except ImportError:
    jwt = None
    PyJWKClient = None
    PyJWTError = Exception


ALGORITHMS = ("RS256", "ES256")


def https_url(value: str, description: str, *, allow_path: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{description} must be a URL")
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.netloc or not parts.hostname
            or parts.username or parts.password or parts.fragment or parts.query
            or (not allow_path and parts.path not in ("", "/"))):
        raise ValueError(f"{description} must be an absolute HTTPS URL without credentials, query or fragment")
    # OAuth issuer identifiers are exact strings. Do not strip trailing '/'.
    return value


class OAuthResourceServer:
    """JWT resource-server validation with issuer, audience and agent binding."""

    def __init__(
        self, gateway: Gateway, issuer: str, resource: str, jwks_uri: str,
        key_resolver: Callable[[str], Any] | None = None,
    ):
        if jwt is None:
            raise RuntimeError("OAuth authentication requires: pip install 'shards-mcp[oauth]'")
        self.gateway = gateway
        self.issuer = https_url(issuer, "OAuth issuer")
        self.resource = https_url(resource, "MCP resource")
        if not self.resource.endswith("/mcp"):
            raise ValueError("SHARDS_PUBLIC_URL must point to the /mcp endpoint")
        self.jwks_uri = https_url(jwks_uri, "OAuth JWKS URI")
        self.metadata_url = urlunsplit((
            urlsplit(self.resource).scheme, urlsplit(self.resource).netloc,
            "/.well-known/oauth-protected-resource", "", "",
        ))
        # The provider address is supplied by the operator, never a token's jku/x5u.
        self._jwks = None if key_resolver else PyJWKClient(
            self.jwks_uri, cache_keys=True, lifespan=300, timeout=5
        )
        self._key_resolver = key_resolver

    @classmethod
    def from_environment(cls, gateway: Gateway) -> "OAuthResourceServer":
        issuer = os.environ.get("SHARDS_OAUTH_ISSUER", "")
        resource = os.environ.get("SHARDS_PUBLIC_URL", "")
        jwks = os.environ.get("SHARDS_OAUTH_JWKS_URI", "")
        return cls(gateway, issuer=issuer, resource=resource, jwks_uri=jwks)

    def metadata(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "authorization_servers": [self.issuer],
            "scopes_supported": list(SCOPES),
            "bearer_methods_supported": ["header"],
        }

    def challenge(self) -> str:
        return f'Bearer resource_metadata="{self.metadata_url}"'

    def authenticate(self, token: str) -> Principal:
        if not isinstance(token, str) or not token or len(token) > 16384:
            raise GatewayError("invalid access token", "UNAUTHENTICATED")
        try:
            headers = jwt.get_unverified_header(token)
            if not isinstance(headers, dict) or headers.get("alg") not in ALGORITHMS:
                raise GatewayError("unsupported signing algorithm", "UNAUTHENTICATED")
            kid = headers.get("kid")
            if not isinstance(kid, str) or not 1 <= len(kid) <= 256:
                raise GatewayError("missing or invalid JWT key ID", "UNAUTHENTICATED")
            key = (self._key_resolver(kid) if self._key_resolver
                   else self._jwks.get_signing_key_from_jwt(token).key)
            claims = jwt.decode(
                token, key=key, algorithms=list(ALGORITHMS),
                issuer=self.issuer, audience=self.resource,
                options={"require": ["exp", "iat", "iss", "sub", "aud"]},
                leeway=15,
            )
        except GatewayError:
            raise
        except (PyJWTError, ValueError, TypeError, OSError) as exc:
            raise GatewayError("invalid access token", "UNAUTHENTICATED") from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not 1 <= len(subject) <= 200:
            raise GatewayError("invalid OAuth subject", "UNAUTHENTICATED")
        scope_claim = claims.get("scope", "")
        if not isinstance(scope_claim, str):
            raise GatewayError("invalid OAuth scopes", "UNAUTHENTICATED")
        # Ignore any '*' claim; OAuth cannot manufacture bootstrap operator rights.
        requested = set(scope_claim.split()) & set(SCOPES)
        if not requested:
            raise GatewayError("no granted gateway scopes", "FORBIDDEN")
        return self.gateway.authenticate_oauth(subject, requested)
