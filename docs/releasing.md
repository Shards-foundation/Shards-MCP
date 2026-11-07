# Shards-MCP release and deployment acceptance

This document is a bounded, reproducible release contract. A successful Python release
does **not** automatically certify a public hosted gateway or ChatGPT directory listing.

## v0.1.0 supported envelope

- Python 3.11–3.15, one single-organisation gateway with persistent SQLite on one host.
- MCP tools over authenticated local loopback HTTP, local stdio bridge, and scoped bearer credentials.
- Remote Streamable HTTP is an **optional operator-managed** deployment with TLS termination,
  an external issuer of signed OAuth JWT access tokens, and strict enrolment by issuer subject.
- Durable messaging, task queues, leases, checkpoints, manual reconciliation and verified results.
- Constrained A2A v1.0 text task adapter, interval scheduler and read-only diagnostics.

**Not covered:** multi-tenant SaaS isolation, multi-host HA, exactly-once external effects,
unrestricted shell or wallet execution, automatic running-task cancellation, full A2A/MCP
extension conformance, hosted ChatGPT OAuth flows, or public plugin-directory approval.

## Pre-publication controls (must be performed by an organisation owner)

1. Complete a secrets/history/dependency review and approve public distribution.
   The GitHub repository is currently private; a GitHub Release in a private repository
   remains private. Publishing to PyPI distributes the source and wheel **publicly** even
   if GitHub stays private. Only change repository visibility after reviewing its history.
2. Protect `main` and release tags matching `v*`; require CI and independent review
   before merges. Create a GitHub environment called `pypi` with required reviewers
   and deployment restrictions permitting approved version tags only.
3. In the PyPI project settings, register a **Trusted Publisher** for
   owner `Shards-foundation`, repository `Shards-MCP`, workflow
   `publish.yml`, environment `pypi`. For a first release, create a
   pending trusted publisher under the `shards-mcp` project name. Confirm the
   name is available and assigned to the correct maintainer. No API token is needed.
4. Verify the intended release commit on `main` has successful 3.11–3.15 CI,
   official MCP SDK client integration, security regression, wheel/sdist installation,
   and Docker/Compose syntax checks. Review any CI skips or failures.
5. Update `pyproject.toml` version, `src/shards_mcp/__init__.py` version
   and version-specific tests in a reviewed PR. For the initial release these
   should all equal `0.1.0`. Never reuse a published package version.

## Publish (owner-triggered only)

Create tag `v0.1.0` at the verified commit on `main` and push the tag using trusted Git CLI. **Do not use the GitHub Releases UI to publish a release at this stage**: it can create a release before PyPI approval and make the workflow's final `gh release create` fail. A maintainer using a trusted cloud terminal can perform this operation without a local computer:

```bash
git fetch origin main --tags
git switch main
git pull --ff-only origin main
git tag -a v0.1.0 -m "Shards-MCP v0.1.0"
git push origin v0.1.0
```

`.github/workflows/publish.yml` then:

1. Checks exact tag/package version equality and runs unit, HTTP, MCP/A2A E2E,
   and pinned SDK tests on Python 3.11–3.15.
2. Builds a fresh sdist and wheel, checks metadata and artifact names, prints
   SHA-256 hashes, then smoke-tests an isolated wheel installation.
3. Publishes through PyPI OIDC Trusted Publishing **only after the environment
   reviewer approves**. The PyPI publishing action generates attestations.
4. Creates a GitHub Release with the same artifacts only after PyPI succeeds.

The workflow does not deploy the web console or gateway. Check both registry
pages and the workflow logs before claiming publication. If the PyPI upload
succeeds but GitHub Release creation fails, rerun only the failed release job
rather than attempting to upload the same package version again. Do not delete
or re-tag a previously published immutable release.

## Public remote deployment — separate GO/NO-GO

Do **not** announce the hosted gateway as production-ready until all of these
have supporting evidence recorded for the deployed version and endpoint:

| Gate | Acceptance |
| --- | --- |
| Network | DNS, real TLS certificate, HTTPS-only ingress, known Origin policy, bounded ingress and upstream timeouts |
| Auth | Real external OAuth code/PKCE login, issuer/audience/scope rejection tests, expired/revoked subject denial, admin token never exposed |
| MCP | Live SDK and target IDE/ChatGPT handshake, identity scope, allowed read and denied write tests |
| Durability | Restart/state retention, concurrent claim isolation, crashed worker lease quarantine, manual reconciliation |
| Recovery | Verified encrypted off-host backup, independent restore rehearsal with recorded recovery time |
| Observability | Metrics and access logs visible to operators, rate limits, alerts and an actionable incident contact |
| Security | No secrets in client bundles, scoped host credentials, patch and dependency review, tested proxy boundaries |
| UX | Real sign-in/sign-out on mobile and desktop, no misleading placeholder actions, real provider callback testing |
| Service | Public privacy policy, support channel, usage limits, retention policy and documented operational owner |

Each gate is binary. A failing critical security or recovery gate is **NO-GO**
for production exposure, independent of passing CI. Local users can still
install and use the documented narrow package envelope.

## ChatGPT plugin-directory submission — separate approval path

A Python package or a remote MCP URL is **not** automatically a published
ChatGPT plugin. For public directory review, verify the appropriate OpenAI
organisation or business, deploy a working authenticated remote endpoint,
document privacy and support policies, test in ChatGPT with safe scoped tools,
supply reviewer instructions and metadata, and submit through the official
plugin submission portal. Publication is contingent on review and approval.

Official references:
- https://docs.pypi.org/trusted-publishers/using-a-publisher/
- https://docs.pypi.org/attestations/producing-attestations/
- https://developers.openai.com/plugins/deploy/app-review
