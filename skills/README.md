# Shards Agent Skills — discoverable, repeatable operating procedures

Shards skills implement bounded workflows for engineering, operations and MCP client integration. **They do not mint permissions, install a plugin into ChatGPT, or execute automatically.** Every skill is a directory containing a specification-compatible `SKILL.md`; selected skills provide local scripts, references and testable acceptance criteria.

Start at [AGENTS.md](../AGENTS.md), then consult the [skills map](MAP.md) or [machine-readable catalog](catalog.json). For a new session, activate [get-started](get-started/SKILL.md).

## Discover a skill, load only what you need

```sh
python scripts/skillctl.py list
python scripts/skillctl.py suggest --task "set up Cursor MCP"
python scripts/skillctl.py show client-integration
python scripts/skillctl.py validate
```

The skill router performs **read-only** local file operations. `suggest` returns lexical matches and will report ambiguity; an agent is responsible for selecting the correct skill and satisfying its prerequisites.

For an agent without local shell access: read [MAP.md](MAP.md), open the matching `<skill-name>/SKILL.md` using a trusted repository reader, then load optional references/scripts only as needed. File availability is not proof that a remote AI client automatically loaded or installed a skill.

## Safety and evidence

Only perform mutations within explicitly approved authority; never expose bootstrap tokens to a model or client configuration. Use isolated databases for examples, enforce separate task creator/worker/verifier identities, prefer reversible changes and do not retry uncertain external effects. For executable release checks use [release-readiness](release-readiness/SKILL.md); the default verdict is **NO-GO** until evidence proves otherwise.

See the [rulebook](../docs/rulebook.md), [agent identity onboarding](../docs/agent-onboarding.md) and [local getting started](../docs/getting-started.md).
