# Cookies and Local Storage — deployment review draft

**Status: DRAFT.** No public hosted Shards-MCP website has been verified.

The NextAuth-based preview console uses authentication session mechanisms. Its precise cookie names, attributes, expiries and provider redirects depend on the deployed NextAuth configuration and browser; **do not publish a fixed cookie inventory without inspecting a real deployment**. OAuth identity providers may set separate cookies on their own domains under their notices.

| Category | Intended use | Verification |
| --- | --- | --- |
| Essential authentication | Session continuity, OAuth callbacks and CSRF protections | Inspect in browser after real provider sign-in |
| Operational preferences | None asserted as shipped | Verify deployed app |
| Analytics, marketing, advertising | No such scripts identified in current console source review | Confirm dependency, proxy and production scan |
| Third-party identity provider | External login/consent flows | Review provider notices and redirects |

Before launch: capture cookie name, issuer, host, lifetime, SameSite/Secure/HttpOnly setting, necessity, lawful consent or exemption assessment, and user opt-out where required. UK PECR and UK GDPR requirements apply when relevant; an essential cookie exemption should not be applied automatically to analytics. See [ICO guidance](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guide-to-pecr/cookies-and-similar-technologies/).
