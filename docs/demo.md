# Demonstration — provable rather than theatrical

This repository includes a **safe local end-to-end demo** that creates temporary SQLite state, three distinct agent identities, a task, a deterministic result and independent verification. It never executes shell commands from task input, connects to production services or prints tokens.

## Run the demonstration

```bash
python -m pip install -e .
python scripts/demo_local.py
```

Expected: JSON with `ok:true`, `task_state:"succeeded"`, distinct creator/worker/verifier IDs, `audit_valid:true`, and `temporary_database:true`. A failure exits nonzero. The script uses the actual `Gateway` implementation and no live cloud credentials.

For a **network** integration demo instead, use [getting started](getting-started.md) to start local HTTP, enrol a scoped token with host-only admin CLI, and run:

```bash
shards-mcp-doctor --protocol both --token-file "$HOME/.config/shards/doctor.token" --json
```

The diagnostic is read-only and does not simulate external OAuth or live ChatGPT login. To exercise stdio, worker and restart over HTTP with isolated clients, CI runs:

```bash
python -m unittest discover -s tests -p 'test_gateway_e2e.py' -v
```

## Demo storyboard (for video)

0–10s: architecture and scoped identities. 10–25s: show command output for agent enrolment with tokens redacted. 25–45s: send safe `echo` task. 45–60s: worker claims + checkpoints, result marked reported. 60–75s: independent reviewer attests result; task succeeded. 75–90s: verify audit chain, repeat an idempotent request, demonstrate a denied operator-only call. End card: limits (single-host, no external effect rollback, live hosting not claimed).

**Production claim gate:** live HTTPS/OAuth, tenancy if applicable, backup recovery, independent security review and external client tests must have evidence before a demo is advertised as production use.
