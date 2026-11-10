---
name: marketplace-gate
description: Prepare evidence and platform-specific submissions for MCP directories and app marketplaces without implying certification or listing approval. Use for ChatGPT, Claude, GitHub, Microsoft, Google Workspace, Vercel, Oracle or third-party MCP/Discord directories.
---
# Marketplace gate — publish only supported capabilities

**Trigger:** request to list or distribute the MCP gateway through a directory/marketplace.

## Preconditions

- An independently tested HTTPS service and client-specific authentication flow exist for the chosen platform.
- Operator approval for publication, logo/trademarks, legal notices, data retention and public tool capability claims.
- Separate the **MCP server listing** from an actual commercial app, Discord bot, GitHub App or cloud integration. A GitHub repository alone is not a marketplace product.

## Inputs

Chosen target marketplace, current submission specifications, product/owner identity, live endpoint, capability inventory, OAuth/consent test, privacy and terms URLs, screenshots/assets, installation steps and support contact.

## Procedure

1. Identify submission type: MCP directory; official ChatGPT/Claude integration; GitHub App/Action; Microsoft/Workspace marketplace app; Vercel/Oracle integration; Discord bot directory.
2. Fetch current **official** marketplace policies and compatibility requirements rather than assuming one universal form. Record the consulted date and source link.
3. Verify actual functions through real client calls, permission prompts, user data boundaries, unsupported features and deletion/revocation flows; document all scopes requested. Do not use screenshots or claimed metrics as substitutes for evidence.
4. Draft manifest, clear data use and privacy description, support/troubleshooting, logo rights and installation/removal instructions. Use minimal necessary requested scopes.
5. Check licensing and hosted-service legal approval separately from the repository's open-source MIT licence.
6. Route through `release-readiness`; only submit after release GO, platform-specific approval and an authorised external submission action. Record public listing URL and review state only **after** acceptance.

## Verification

Submission checklist: endpoint reachable, auth/authorization flow, live tool call, negative scope test, user consent and revocation, documentation, data processing/legal notices, security contact and actual platform approval.

## Failure handling

Missing OAuth, PKCE, protected-resource metadata, platform entitlement, live site or legal signoff => **NO-GO**. Do not work around an unavailable platform by misclassifying the app or purchasing fake reviews.

## Output

**Output:** target platform, listing class, supported features, evidence URLs, PASS/FAIL/BLOCKED gates, approval owner, submission status and remaining blockers.
