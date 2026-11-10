"""Tenant-bound PostgreSQL v2 transaction facade. NOT wired to the v1 gateway.

TokenClaims must originate ONLY from an independent cryptographic JWT/OAuth
verifier. This module validates claims' shape, binding and lifetime but DOES
NOT perform signature verification or grant permission from an org hint.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from time import time
from typing import Any, Iterator
from uuid import UUID

from .core import SCOPES


class TenantBoundaryError(Exception):
    """Denial hides whether another tenant or principal exists."""
    code = "FORBIDDEN"


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """A trusted issuer-verifier output carrier; NOT a verification mechanism."""
    issuer: str
    subject: str
    audience: str
    scopes: tuple[str, ...]
    issued_at: int
    expires_at: int


READ_SCOPES = frozenset({
    "agent:read", "message:read", "task:read", "audit:read", "event:read",
})
MEMBER_SCOPES = READ_SCOPES | frozenset({"task:create", "event:write", "message:send"})
ROLE_SCOPES = {
    "owner": frozenset(SCOPES), "admin": frozenset(SCOPES),
    "member": MEMBER_SCOPES, "auditor": READ_SCOPES,
    "agent": frozenset(SCOPES),
}

# Only static parameterised SQL; never expose raw SQL to MCP/tool callers.
_MEMBERSHIP = """
SELECT p.principal_id, p.scopes, m.role, p.kind
FROM shards_v2.principals AS p
JOIN shards_v2.memberships AS m
  ON m.org_id = p.org_id AND m.principal_id = p.principal_id
JOIN shards_v2.organizations AS o ON o.org_id = p.org_id
WHERE p.org_id = %s::uuid AND p.external_issuer = %s
  AND p.external_subject = %s AND p.state = 'active'
  AND m.revoked_at IS NULL AND o.lifecycle = 'active'
LIMIT 2
"""
_TASK_READ = """
SELECT task_id, state, creator_id, worker_id, input_json, result_json
FROM shards_v2.tasks
WHERE org_id = %s::uuid AND task_id = %s
  AND (creator_id = %s OR worker_id = %s)
LIMIT 1
"""
_AGENT_READ = """
SELECT principal_id, name, kind, state FROM shards_v2.principals
WHERE org_id = %s::uuid AND kind = 'agent' AND state = 'active'
ORDER BY principal_id LIMIT %s
"""


class TenantScope:
    """Internal-only tenant read facade. No arbitrary SQL execution method."""

    def __init__(self, conn: Any, org_id: str, principal_id: str,
                 role: str, scopes: tuple[str, ...]):
        self._conn = conn
        self._active = True
        self.org_id = org_id
        self.principal_id = principal_id
        self.role = role
        self.scopes = scopes

    def require(self, scope: str) -> None:
        if not self._active:
            raise TenantBoundaryError("tenant transaction has ended")
        if scope not in self.scopes:
            raise TenantBoundaryError("tenant access denied")

    def task_get(self, task_id: str) -> dict[str, Any] | None:
        self.require("task:read")
        if not isinstance(task_id, str) or not 1 <= len(task_id) <= 200:
            raise TenantBoundaryError("tenant access denied")
        row = self._conn.execute(
            _TASK_READ, (self.org_id, task_id, self.principal_id, self.principal_id)
        ).fetchone()
        if row is None:
            return None
        return {
            "task_id": row[0], "state": row[1], "creator_id": row[2],
            "worker_id": row[3], "input": row[4], "result": row[5],
        }

    def agent_directory(self, limit: int = 50) -> list[dict[str, str]]:
        self.require("agent:read")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise TenantBoundaryError("tenant access denied")
        rows = self._conn.execute(_AGENT_READ, (self.org_id, limit)).fetchall()
        return [{"principal_id": r[0], "name": r[1], "kind": r[2],
                 "state": r[3]} for r in rows]


class TenantMembershipAuthority:
    """Validate membership in an RLS-bound transaction before task access."""

    def __init__(self, *, issuer: str, resource: str):
        if (not isinstance(issuer, str) or not issuer.startswith("https://")
                or not isinstance(resource, str) or not resource.startswith("https://")
                or not resource.endswith("/mcp")):
            raise ValueError("expected HTTPS issuer and MCP resource")
        self.issuer = issuer
        self.resource = resource

    def _validate_claims(self, claims: TokenClaims) -> None:
        if not isinstance(claims, TokenClaims):
            raise TenantBoundaryError("tenant access denied")
        if claims.issuer != self.issuer or claims.audience != self.resource:
            raise TenantBoundaryError("tenant access denied")
        if (not isinstance(claims.subject, str)
                or not 1 <= len(claims.subject) <= 200
                or type(claims.issued_at) is not int
                or type(claims.expires_at) is not int
                or not isinstance(claims.scopes, tuple)
                or not claims.scopes
                or any(not isinstance(s, str) or s not in SCOPES for s in claims.scopes)):
            raise TenantBoundaryError("tenant access denied")
        stamp = int(time())
        if (claims.issued_at > stamp + 30
                or claims.expires_at <= stamp
                or claims.expires_at <= claims.issued_at
                or claims.expires_at - claims.issued_at > 300):
            raise TenantBoundaryError("tenant access denied")

    @contextmanager
    def bind(self, conn: Any, claims: TokenClaims, requested_org_id: str,
             required_scope: str | None = None) -> Iterator[TenantScope]:
        self._validate_claims(claims)
        try:
            org_id = str(UUID(requested_org_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise TenantBoundaryError("tenant access denied") from exc
        if requested_org_id != org_id:
            raise TenantBoundaryError("tenant access denied")
        if required_scope is not None and required_scope not in SCOPES:
            raise TenantBoundaryError("tenant access denied")
        # SET LOCAL must never leak into an ambient/nested pooled transaction.
        # psycopg3 TransactionStatus.IDLE is integer 0.
        if (getattr(conn, "autocommit", None) is not True
                or int(getattr(getattr(conn, "info", None),
                               "transaction_status", -1)) != 0):
            raise TenantBoundaryError("dedicated idle autocommit connection required")
        with conn.transaction():
            # Selection hint is NOT permission. Only a matching ACTIVE membership
            # and tenant-scoped principal grant permit the caller to proceed.
            conn.execute("SELECT set_config('shards.org_id', %s, true)", (org_id,))
            row = conn.execute(_MEMBERSHIP, (org_id, claims.issuer, claims.subject)).fetchone()
            if row is None:
                raise TenantBoundaryError("tenant access denied")
            principal_id, granted, role, kind = row
            if (not isinstance(principal_id, str)
                    or role not in ROLE_SCOPES
                    or kind not in ("user", "agent", "service")
                    or not isinstance(granted, list)
                    or any(not isinstance(s, str) for s in granted)
                    or (role == "agent" and kind != "agent")):
                raise TenantBoundaryError("tenant access denied")
            effective = tuple(sorted(
                set(claims.scopes) & set(granted) & ROLE_SCOPES[role]
            ))
            if not effective or (required_scope is not None
                                 and required_scope not in effective):
                raise TenantBoundaryError("tenant access denied")
            scope = TenantScope(conn, org_id, principal_id, role, effective)
            try:
                yield scope
            finally:
                scope._active = False
