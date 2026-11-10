# v2 Python tenant transaction boundary (experimental, not deployed)

The adapter in `src/shards_mcp/tenancy_v2.py` depends on the draft PostgreSQL v2 migrations. It does not alter the live Python SQLite `Gateway` or the Cloudflare Worker.

## Trust ordering

1. A separate trusted OAuth verifier **must validate the JWT cryptographic signature**, pinned issuer, exact resource audience, token age and revocation before it creates `TokenClaims`. Constructing `TokenClaims` itself does **not** verify a token.
2. An organisation UUID supplied in a request is only an **untrusted hint**. With an idle `autocommit=True` psycopg3 connection using a non-owner, `NOBYPASSRLS` role, call `TenantMembershipAuthority.bind`.
3. The adapter enters a new top-level transaction, sets transaction-local `shards.org_id`, and performs a bounded exact issuer+subject membership lookup against active organisation, active principal and nonrevoked membership.
4. It intersects verified token scopes with persisted principal scopes and role restrictions, and exposes only tenant-scoped `task_get` / `agent_directory` operations. No arbitrary SQL, writes, connector invocations or execution are available through the facade.
5. On failure, transaction rollback clears tenant context. After return, the bound scope is inactive and cannot be reused. No nested/ambient connection transactions are accepted.

## Security limits

PostgreSQL custom GUCs such as `shards.org_id` can be set by a role able to execute arbitrary SQL. RLS is therefore **defence in depth**, never authentication. Do not expose SQL endpoints, the underlying connection, or these Python dataclasses to untrusted models. This module accepts **already verified** claims and cannot be safely called directly from HTTP without a cryptographic verifier.

No portal or MCP client receives tenant access merely by providing an org UUID. Owner/admin roles are also subject to the persisted and token scopes; an auditor's write privileges are stripped regardless of incorrectly granted token/database scopes.

## Testing

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_tenancy_v2.py' -v
```

The isolated PostgreSQL workflow installs the optional `postgres` dependency, provisions two test tenants and an unprivileged role, and checks membership denial, cross-tenant task visibility, role attenuation, expiry, rollback and RLS context cleanup against PostgreSQL 17. No live database, user records, Cloudflare D1 or production credential is changed.

**Next gating PR:** trusted issuer/JWKS integration that cryptographically verifies claims, then edge-to-private-origin attestation, before exposing the v2 adapter over MCP. The legacy SQLite runtime remains unchanged.
