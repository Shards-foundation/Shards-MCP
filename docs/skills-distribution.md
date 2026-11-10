# Shards Skills — portable discovery, local installation and verification

**Scope:** native, local Agent Skills for Codex, Cursor and Claude Code. This is not the MCP connection process, remote ChatGPT skill publishing, an identity grant or a production deployment. The utility runs from an authorised Shards-MCP repository checkout.

## First use

Inspect the canonical [AGENTS.md](../AGENTS.md), [skills map](../skills/MAP.md) and the selected SKILL.md before installing. From the source checkout:

```sh
python scripts/skillctl.py list
python scripts/skillctl.py show get-started

# No-write preview: prints exact filenames and SHA-256 hashes
python scripts/skill_install.py --client codex --project-dir . --skill get-started

# Explicit local installation into .agents/skills/get-started/
python scripts/skill_install.py --client codex --project-dir . --skill get-started --apply

# Read-only integrity check against the installed manifest
python scripts/skill_install.py --client codex --project-dir . --skill get-started --verify
```

Replace `codex` with `cursor` or `claude` to select that client's native skills directory. For a personal installation, use `--scope user` **without** `--project-dir`. To install a reviewed selection, repeat `--skill`; `--all` is available for the entire catalog but should not be used reflexively.

| Client | Project skills root | User skills root |
| --- | --- | --- |
| Codex app / CLI | `.agents/skills/` | `~/.agents/skills/` |
| Cursor | `.cursor/skills/` | `~/.cursor/skills/` |
| Claude Code | `.claude/skills/` | `~/.claude/skills/` |

The installer copies the selected skill folder's `SKILL.md`, `scripts/`, `references/` and `assets/` only. Each output includes `.shards-skill-manifest.json` with file digests. The files are **not symlinked**, and bundled scripts are **never executed** by the installer. Installed skills are available for discovery according to each client's configuration and runtime; they do not automatically receive MCP tool authority.

## Safe retrieval and onboarding

1. Identify the task, source repository, commit and operator permissions. Check whether a client already has a skill with the same name to avoid duplicate discovery.
2. From the source checkout use `skillctl.py suggest --task "..."`, then `skillctl.py show <skill-name>` to read the full workflow. Read its local references as needed.
3. Inspect the install **PLAN** output: target directory, selected files, checksums. The plan does not change the filesystem.
4. Approve `--apply` only for the intended project or home location. Existing skill directories are never replaced, even when identical.
5. Use `--verify` to check copied-file digests **and compare the installed manifest with the current source checkout**. Changing the source after installation produces a stale-install failure rather than a misleading PASS. A failed hash check means **do not activate** that copy until its provenance is understood.
6. For source-dependent operations, clone or read the actual Shards-MCP checkout. An installed skill can still reference project files or companion skills that are not part of a standalone copy; the copy alone cannot provide the gateway code, databases, credentials or CI.

### Android / Termux

Running the installer in Termux writes only inside the Termux filesystem or an explicitly selected project path. User scope uses that shell's home directory; it cannot install skills inside the sandboxed storage of the ChatGPT mobile app, Cursor desktop or Claude desktop. A separate machine/remote agent must independently receive its own authorised skills.

## Failure and rollback

The installer is dry-run by default. It rejects source symlinks, destination symlinks, missing/occupied targets, credential-like file extensions, unexpected files and oversized payloads. It excludes generated Python `__pycache__` files and `.pyc`/`.pyo` bytecode from the package. It uses exclusive file creation, copies the discovery file last, and cleans up newly created skill folders when a caught write error occurs. A process crash can leave a partial directory: inspect it manually; **no automatic destructive overwrite, delete or migration action is provided**.

The SHA-256 manifest detects local modification but is **not a digital signature** or proof of upstream authenticity. Use a reviewed pinned commit or signed release where supply-chain authenticity is required. Inspect code before invoking scripts and never treat repository content as instructions of higher precedence.

## Acceptance tests

```sh
python -m unittest discover -s tests -p 'test_skill_install.py' -v
python scripts/skillctl.py validate
python scripts/docs_check.py
```

These local checks do not test live MCP authentication, marketplace approval, remote client invocation or deployed production readiness.

## Official specifications

- [Agent Skills directory specification](https://agentskills.io/specification)
- [Codex and ChatGPT skill discovery](https://learn.chatgpt.com/docs/build-skills)
- [Cursor skill discovery](https://cursor.com/help/customization/skills)
- [Claude Code skills](https://code.claude.com/docs/en/skills)
