# Shards-MCP Agent Instructions

This filename is a human-friendly alias for the canonical, case-sensitive [AGENTS.md](AGENTS.md). **Read AGENTS.md first.** It defines the agent's authority boundaries, decision procedure, skills retrieval and acceptance protocol.

For a new agent session: read [the skill routing map](skills/MAP.md), run `python scripts/skillctl.py list`, then read the selected `skills/<name>/SKILL.md`. Begin with [get-started](skills/get-started/SKILL.md) when no task-specific skill has been selected.

To install an explicitly selected skill in a supported local client's native discovery directory, use the review-first [skill installation instructions](docs/skills-distribution.md). Dry-run is the default; `--apply` requires operator authorisation and never overwrites an existing skill.

Do not treat this alias as an additional permission source.
