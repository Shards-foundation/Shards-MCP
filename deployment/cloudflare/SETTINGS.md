# Shards MCP — Operator Account Settings

**Scope:** The existing single-operator Cloudflare Access application at https://mcp.shardsinc.co.uk/manage. This is not a public multi-user identity product.

## Available features

| Section | What actually works |
| --- | --- |
| Profile | Editable full name, provider-supplied identity email (read-only), local avatar upload |
| Avatar | Mobile resize to 96×96 PNG/JPEG/WebP, magic-header validation, max 24 KB decoded, D1 persistence |
| Appearance | System, dark, light and high-contrast modes persisted per account |
| Password / login methods | Cloudflare Access provider-managed; no fictitious password reset or social linking |
| 2FA | Managed by the IdP, **not confirmed/enrolled by Shards** |
| API/CLI credentials | 256-bit independent keys, single-use plaintext reveal, SHA-256 hash storage, read-only account scope, 30/90-day expiry and revocation |
| Connections | Actual owner-issued agent credentials and last API token use; no invented online status |
| SSH keys | Ed25519 public-key upload, fingerprint, list and removal; **does not grant host SSH login** |
| Delete account | Typed confirmation; local profile/SSH deletion, owned key revocation, issued agent disabling and tombstone, preserving audit/history and external Cloudflare identity |

## Routes

Every account settings API is protected by the **operator** Cloudflare Access JWT audience, signature, issuer, subject and expiry. The Connect-app audience cannot be substituted. Mutations enforce same-origin JSON and bounded bodies.

- **GET /manage/api/account** — profile, provider-owned security descriptions, owned keys/SSH records and agent credentials; no bearer plaintext.
- **PUT /manage/api/account/profile** — full_name, theme and small validated avatar_data URI or null; email cannot be overwritten.
- **POST /manage/api/account/keys** — kind api/cli, label and expires_days 30/90. Plaintext issued once only; fixed account:read scope.
- **DELETE /manage/api/account/keys/{id}** — revoke one owned key.
- **POST /manage/api/account/ssh** — label and OpenSSH Ed25519 public key; no private key material accepted.
- **DELETE /manage/api/account/ssh/{id}** — remove one owned public key.
- **DELETE /manage/api/account** — confirmation text DELETE MY SHARDS ACCOUNT; transactional local deletion and owned-key/agent revocation.
- **GET /v1/account/whoami** — bearer smcp_api_ or smcp_cli_ 256-bit key, read-only identity response, updates last-used timestamp, refuses expired/revoked keys.

Agent tool credentials are separate. Account keys **cannot** enrol agents, send messages, execute agent tools or obtain shell access.

## Deployment / acceptance gates

1. Review the exact PR head, tests and independent security reviews. Retain the old deployed Worker version for rollback.
2. Back up the current EU D1 database and confirm recovery.
3. Apply additive **migrations/0002_operator_settings.sql** to the existing Shards MCP D1. This creates three new tables; it does not edit existing messages/tasks/agents.
4. Verify tables and current separate operator/Connect audience bindings.
5. Upload the exact reviewed Cloudflare Worker version with strict inheritance of EDGE_DB, ACCESS_TEAM, ACCESS_AUD and CONNECT_ACCESS_AUD.
6. Test that anonymous account APIs deny access, a real signed session can save profile/theme, issue and use a real read-only key, revoke it and observe denial. Also check /mcp, /signin, /lab and /api/status.
7. Do not delete a real account during a smoke test. Roll back the Worker to the pinned version if a regression occurs. Keep new D1 tables to avoid destroying user data.

## Explicit product boundaries

The operator Access application currently has a one-hour session. Password updates, MFA enrolment, and Google/GitHub/Apple/Microsoft/Meta/Discord/OpenAI/Claude account linking require real IdP configuration and consent; they cannot be safely simulated by switches in the website. Email OTP alone is not proof of two-factor authentication. The current settings do not provide a public tenant signup system, active SSH login, server credentials management for external providers, browser device/session revocation, or complete third-party integrations.

**Account deletion removes Shards-owned local records and revokes owned Shards credentials, but does not remove an external Cloudflare identity or historical organisation audit/messages.** The local account tombstone prevents subsequent Shards operator-management API access.
