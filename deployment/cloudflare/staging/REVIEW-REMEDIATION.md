# Final PR #47 security review reconciliation

Reviewed head: `0e3e9391cdd9725da93f49f023a26dd73b85222b`, branch
`feat/pr46-staging-acceptance`, base `main`. Primary skill: security-review;
supporting skill: client-integration. GitHub submissions, inline threads and full
conversation were retrieved. There were 13 unresolved inline threads, including
duplicates, plus CodeAnt/Qodo conversation findings. Earlier three Gitar findings
were already fixed and resolved; their existing regression coverage is retained.
The reviewed head's two applicable Actions workflows both concluded success;
that did not negate any finding below.

Links use the original review anchors on [PR #47](https://github.com/Shards-foundation/Shards-MCP/pull/47).
Every unique actionable finding is VALID. Two additional Gitar findings from the
first correction were reconciled in the second bounded cycle. No finding was dismissed because CI passed.

| ID | Reviewer / severity / original anchor | Classification | Correction | Regression evidence | Resolution |
| --- | --- | --- | --- | --- | --- |
| R1 | Codex P2 `discussion_r4591433945`; Cubic P2 `discussion_r4591496715`; CodeAnt nitpick 1; Qodo medium 1 | VALID | Shared bounded body reader maps interrupted reads to static BLOCKED codes, including module downloads; cancellation cannot replace a size verdict | `body reset and abort after headers`; `size-limit assertions survive cancellation errors` | Fixed; thread evidence/actions recorded on PR; independent re-review required |
| R2 | CodeAnt major `discussion_r4591487420`, nitpick 2; Cubic P2 `discussion_r4591496675` | VALID | Descriptor-relative no-follow traversal for fixture, builder and receipt writes; exclusive fresh output under private ignored work | `fixture and builder CLIs reject ancestor/final symlinks`; `output ancestor replacement`; `receipt files are exclusive` | Fixed; thread evidence/actions recorded on PR; independent re-review required |
| R3 | Cubic P1 `discussion_r4591496592`; CodeAnt nitpick 3 | VALID | Open once without following links; fstat and bounded read through descriptor; reject hard links and observed in-place changes | `protected reader uses validated descriptor`; `in-place read mutation`; symlink/hardlink cases | Fixed; thread evidence/actions recorded on PR; independent re-review required |
| R4 | Cubic P2 `discussion_r4591496682` | VALID | Builder refuses existing output directories, preventing mode retention and overwrite | Existing public output sentinel remains unchanged; fresh files 0600/directories 0700 | Fixed; thread evidence/actions recorded on PR; independent re-review required |
| R5 | Cubic P1 `discussion_r4591496582` | VALID | Remove public local/verifier bypasses; local exemption bound to harness-created object and in-process dispatch | `public localRuntime and verifier overrides`; real workerd/D1 matrix; independent pre/post verification | Fixed; thread evidence/actions recorded on PR; independent re-review required |
| R6 | Cubic P2 `discussion_r4591496595`; Qodo low 4 | VALID | Bounded 30–240 minute fixture lifetime, 120-minute default; require live revocable token before and after requests | `expired or nearly expired revocable fixtures`; real parallel revocation denial | Fixed; thread evidence/actions recorded on PR; independent re-review required |
| R7 | Cubic P2 `discussion_r4591496688`; Qodo low 3 | VALID | Filesystem unavailability maps to BLOCKED without raw diagnostics; deliberate policy failure stays FAIL | Missing-input verifier CLI exit 2 and exact protected receipt; injected EACCES; public-file denial | Fixed; thread evidence/actions recorded on PR; independent re-review required |
| R8 | Cubic P2 `discussion_r4591496704` | VALID | Explicit subdomain and worker shape checks before coercion/dereference | `malformed approval shapes` including null, arrays and throwing coercion | Fixed; thread evidence/actions recorded on PR; independent re-review required |
| R9 | Cubic P2 `discussion_r4591496662` | VALID | README uses python3 | Documentation command regression and actual schema/docs/skill commands | Fixed; thread evidence/actions recorded on PR; independent re-review required |
| R10 | Cubic P3 `discussion_r4591496724` | VALID | Protected exclusive receipt writer creates missing private work; CLI requires --receipt instead of unsafe shell redirection; umask documented | Receipt mode under umask 000; existing-file and symlink rejection; CLI missing-input receipt | Fixed; thread evidence/actions recorded on PR; independent re-review required |
| R11 | Cubic P2 `discussion_r4591496603` | VALID | Pin instructions hash actual git-show bytes and compare both recorded SHA-256 values | Executed documented pin command; missing pin still BLOCKED | Fixed; thread evidence/actions recorded on PR; independent re-review required |
| R12 | Qodo medium 2 `issuecomment-6929074382` | VALID | Optional exact operator-approved Access binding set in builder/verifier; default forbids extras; no configuration changes | `approved optional Access bindings remain exact`: correct, wrong, missing, extra and secret-type cases | Fixed; thread evidence/actions recorded on PR; independent re-review required |
| R13 | Gitar `discussion_r4592014589`, assessed P2 | VALID | Reserve the exclusive protected receipt descriptor before any input or network activity; complete the held descriptor once | `hosted CLIs reserve valid receipt descriptors`: missing/flag/existing/outside/symlink paths produce zero network calls; valid-path control exercises interception; pathname swap cannot redirect completion | Fixed in cycle 2; thread evidence/actions on PR; independent re-review required |
| R14 | Gitar `discussion_r4592014746`, assessed P3 | VALID | Descriptor-based --init-work creates or verifies private work before documented npm cache creation, including default umask 022 | `documented private work initialization precedes npm cache creation`: fresh root becomes 0700; repeated init succeeds; public existing root is refused | Fixed in cycle 2; thread evidence/actions on PR; independent re-review required |

CodeAnt's risk summary repeats R2. Summaries/promotional comments contain no further
remediation. Sourcery reports its free review budget exhausted; no upgrade is
requested. New automated comments must be reconciled against the exact pushed SHA.
At most three implementation/review cycles are permitted for this task.

## Verification and remaining limits

Exact commands and runtime requirements are in [README.md](README.md). Test counts
and exact-head CI are recorded in the final PR receipt after execution. Regressions
exercise synthetic data only, with ephemeral local D1 and network-disabled workerd.
Production Worker/schema and artifact source pins/digests are unchanged. No
Cloudflare requests, deployment, resource, Access, credential, production or billing
change is authorized or performed by these corrections.

Readable hosted artifact mismatch remains **FAIL** on the earlier independent
byte comparison. Existing staging URLs are disabled, old test tokens were reported
revoked, and staging Access is absent. Hosted token/revocation/Access acceptance,
shared-account quota isolation and fresh-task native Cloud acceptance remain
**BLOCKED**. No observed hash was adopted. Operator account/root and Cloudflare API
integrity remain trust anchors; before/after reads cannot atomically fence a
privileged concurrent operator. Linux/procfs is now required for protected files.

Rollback: revert this correction commit; remove only synthetic scratch directories
created under ignored work. Do not modify or tear down existing Cloudflare resources.
Keep PR draft. A fresh independent Claude review is required before a merge decision.

## Local verification receipt

Runtime: Node v22.16.0, Python 3.12.14, Miniflare 4.20260730.0,
official MCP SDK 1.32.2. Node was selected from the existing workspace runtime
cache by prepending its bin directory to PATH. No runtime or lockfile was upgraded.

```sh
node --version
# Before npm/cache creation, safely create or verify private work (no credentials).
node deployment/cloudflare/staging/protected-file.mjs --init-work
umask 077
npm ci --cache "$PWD/work/npm-cache" --prefix deployment/cloudflare/staging --ignore-scripts --audit=false --fund=false
npm test --prefix deployment/cloudflare/staging
node --test deployment/cloudflare/worker.test.mjs deployment/cloudflare/audit_atomic.test.mjs deployment/cloudflare/workspace.test.mjs deployment/cloudflare/verify_release_deployment.test.mjs deployment/cloudflare/sdk.test.mjs
.venv/bin/python -m unittest discover -s tests -v
python3 deployment/cloudflare/schema_migrations_test.py -v
.venv/bin/python -m unittest discover -s tests -p 'test_documentation.py' -v
python3 -m unittest discover -s tests -p 'test_*skills*.py' -v
python3 -m unittest discover -s tests -p 'test_skill_install.py' -v
python3 scripts/docs_check.py
python3 scripts/skillctl.py validate
.venv/bin/python -m compileall -q src tests scripts
.venv/bin/python scripts/demo_local.py
node deployment/cloudflare/staging/build.mjs --out work/pr47-final-syntax --approval deployment/cloudflare/staging/local-target.example.json
node --check work/pr47-final-syntax/main/worker.js
node --check work/pr47-final-syntax/fault/worker.js
node --check deployment/cloudflare/worker.js
git diff --check
```

Use a fresh output name when repeating the builder. Local logs are protected under
ignored work. Initial harness verification had a test-adapter failure; it was fixed.
The first clean npm install failed because the default cache was outside writable
workspace; the explicit workspace cache succeeded. A standalone system-Python doc
suite lacked the installed project; rerunning with the project virtualenv passed.
A negative public-directory fixture was accidentally private under umask 077; it
now explicitly sets the intended public mode, and the denial passes. These failed
attempts are not counted as PASS. Final counts and exact-head CI supersede them.

A separate isolated copy of the reviewed head reproduced nine underlying defects:
raw stream errors, bypassed identity checks, swapped-file contents consumed,
ENOENT/TypeError escaping, fixture output through a symlink outside work, an existing
0644 builder file remaining public, approved Access bindings rejected, and **PASS
for an expired token with no revocation at all**. Only synthetic data was used; the
copy and synthetic files were removed after recording a protected local receipt.
The committed regressions now exercise these boundaries and the three documentation
corrections. Hosted evidence and approved artifact hashes were not changed.

Cycle 2 final local results: **38/38 staging tests PASS**, including 16 new security tests
and six killed SQL predicate mutations; **47/47 Worker/SDK**, **208/208 Python**,
**6/6 schema**, **6/6 documentation-contract**, **10/10 skills** and **10/10 native
skill-install** tests PASS. The latter three are subsets of the Python suite, not
additional distinct tests. Documentation validates 67 Markdown files; skill catalog,
compile, artifact syntax and diff checks PASS. The deterministic demo passes with
no external actions, and preflight is READY_LOCAL when the virtualenv bin is on
PATH. The unverified hosted release template correctly returns NO_GO. The local
acceptance boundary table retains 11 PASS and three BLOCKED rows in each before/
after run; these rows are not hosted results. Exact-head CI is reported on the PR.

Cycle 1 exact-head CI at `43f3887cf9cff9439b4e7173fb5ab3e166c7ff59` passed all
four applicable workflows, including Python 3.11–3.15. Gitar then identified R13
and R14, both accepted and corrected in cycle 2. The receipt is now reserved before
input/network work; invalid receipt arguments cannot initiate even a Cloudflare
read. Initializing work uses only Node built-ins and precedes dependency/cache
creation, rejecting unsafe existing roots without chmod. Full local staging and
regression checks were repeated after the corrections; final-head CI and fresh
automated review are reported in the PR. This task stops after at most three cycles.
