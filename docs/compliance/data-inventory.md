# Data Inventory and Retention Register

**Status:** initial source-driven inventory. Not an approved records-of-processing schedule. Review every release and every new hosted integration.

| Data | Purpose | Storage / controller | Retention behaviour now | Required owner decision |
| --- | --- | --- | --- | --- |
| Agent name, ID, provider, capability, scopes | Enrol and authorise agents | Self-hosted SQLite | No general expiry | Review cycle, offboarding and deletion policy |
| Token digest | Authenticate local agents | Self-hosted SQLite | Until agent revoked / records handled | Secret rotation and residual data deletion |
| External OAuth subject | Bind issuer-authenticated identities | SQLite; issuer has its own records | No automatic account linking/erasure | IdP contract, access/deletion plan |
| Messages, events and task input/output | Route delegated work | SQLite | Durable until operator action | TTL, maximum content, legal basis and prohibited classes |
| Checkpoints, verification evidence | Recover and verify work | SQLite; evidence not encrypted at application layer | Durable | Encryption, redaction, expiry, access controls |
| Audit hash-chain entries | Accountability | SQLite | App-level append-only, DB-owner not immutable | Independently anchored log, retention and legal holds |
| HTTP logs and metrics | Security and operations | Deployment logging service | Deployment-defined | Retention window, access and aggregation policy |
| Backup images | Disaster recovery | Local snapshot and operator off-host copy | Manual | Encrypt, remote retention, purge/restore rehearsal |
| Preview console session and provider claims | Authentication | NextAuth session cookies; provider | Session configuration dependent | Cookie scan, identity rights and sign-out test |

**Never put** user passwords, bearer secrets, private keys, full third-party access tokens, payment cards or unnecessary special-category data into task payloads or prompts. This is an operational rule, not a machine-enforced universal data-classification guarantee.

Prior to accepting customer data, establish data owners, lawful basis, location and residency, maximum retention/deletion process (including backups), subprocessor inventory, DSAR export, encryption posture and incident escalation. Do not claim a deletion request succeeds across SQLite, snapshots and external providers without test evidence.
