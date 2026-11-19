# Shards MCP Edge — production-source reconciliation (15 November 2026)

## Scope and origin

- **Cloudflare account:** Shards-inc (no credentials copied).
- **Worker:** `shards-mcp-edge`; origin `https://mcp.shardsinc.co.uk/mcp`.
- **Cloudflare live version:** `1417254b-dbe8-4e9b-b479-b5d474ca6726`.
- **Observed version time:** `2026-11-15T05:01:09.080047Z`.
- **Actual downloaded live worker.js SHA-256 (UTF-8 bytes):** `600c54f2fada0e15a01c96425c811b51df6f1c814746cfee481a7aa454a0883c`.
- **Exact live-source recovery commit on feature branch:** `a1485ee3983660a2f4abcbd759d1b784ee7c9709`.
- **Seven-public-tool integration commit:** `3e71f6ff22ce49de1cd4b233ac0fbf111f6200aa`.
- **Reviewed public research PR:** [#41](https://github.com/Shards-foundation/Shards-MCP/pull/41), source-only squash-merged into main at `ce10d87dfa8ab826f581da8f611c84cc4e609594`.

The recovery commit contains the **deployed Worker source**, not a fabricated reconstruction. The next commit preserves that source and adds four reviewed public research tools from #41. The original Cloudflare live version is unchanged. The entire recovered source was checked for embedded recognizable private keys, literal smcp credentials, common GitHub/OpenAI/Cloudflare API key patterns and email addresses; those checks found none, but automated regex screening is **not** a full secret audit.

## Features preserved from the actual live Worker

- Cloudflare Access operator console, owner settings, managed OAuth pilot and `/connect` identity entrypoints.
- Agent Hub audience-bound registry bridge and `agent_connection_activity` implementation.
- Existing operator collaboration workspace and agent connection wizard.
- Browser-facing skills library and related account functionality present in the live Worker.
- Existing 3 public and 9 bearer-protected MCP tools, plus four **proposed** public GitHub/skill tools.

## Cloudflare Worker binding contract (names only)

`ACCESS_AUD`, `ACCESS_TEAM`, `CONNECT_ACCESS_AUD`, `EDGE_DB`, `HUB_REGISTRY_AUD`.

Do not log, commit, display or reset binding **values**. Do not drop `HUB_REGISTRY_AUD` during migration, or overwrite the existing D1 binding. No binding migration has been applied.

## Critical outstanding work — BLOCKED for release

1. **P1 audit atomicity:** Existing live source swallows errors in `audit()`. The four protected mutating MCP operations write their effects first and audit afterwards; a failed audit can leave unlogged success. Resolve [#38](https://github.com/Shards-foundation/Shards-MCP/issues/38) with D1 transactional failure-injection evidence and concurrent/idempotent replay tests.
2. **Source parity and build reproducibility:** Confirm recovered source matches exact Cloudflare script bytes, record released artifact hash, and ensure CI tests the precise script intended for deployment. Cloudflare script version and deployment identifiers are distinct evidence.
3. **Real operator/agent integration:** Test with two distinct genuine scoped agents and an independently authenticated operator. Cover token revocation, wrong scopes and audience mix-up. No credentials in GitHub/PRs.
4. **Public tool verification:** Until this reviewed branch is deployed, **production still has only 3 public tools**. After deployment update edge-smoke workflow to require exactly the named 7 public tools and 9 private tools.
5. **Rollback:** Confirm the precise previous Cloudflare version ID, compatible D1 schema, valid bindings and operator sign-in before any rollout.

## Security and release decision

**NO-GO for production deployment and automatic merge.** This branch/PR exists to review and reconcile source, not to modify the running service or D1. Passing a source-only GitHub CI is not proof of a live authenticated rollout.
