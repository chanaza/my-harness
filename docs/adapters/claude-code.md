# Claude Code adapter

Tier A: real hooks. Everything is captured automatically.

## What is captured

| From Claude Code | Into the harness |
|---|---|
| `CLAUDE.md` (global, project, `.claude/`, `CLAUDE.local.md`) | `core/instructions/<profile>/` |
| `skills/**/SKILL.md` (whole folder, incl. synced skills) | `core/skills/<name>/` |
| `commands/*.md` | `core/skills/<name>/` |
| `agents/*.md` | `core/agents/<name>.yaml` |
| `projects/*/memory/**/*.md` | `memory/` |
| MCP servers (`~/.claude.json`, `.mcp.json`) | `core/connections.yaml`: type + host or executable only |
| Plugins | `core/connections.yaml` (`kind: plugin`) |
| `settings.json` (secrets removed), `output-styles/` | `native/<profile>/` |

Skip items with `harvest.exclude` in `harness.config.yaml`, e.g.
`harness config set harvest.exclude "skill:pdf" "skill:docx"`.

## Hooks

| Event | Action |
|---|---|
| SessionStart | Register the session and harvest (background); after a compaction, a checkpoint is due |
| UserPromptSubmit | Count the message; when a checkpoint is due, pass the request to the model as hidden context |
| Stop | Decide whether a checkpoint is due; in the background: harvest, workspace state, transcript, commit, push |
| PreCompact | Save the transcript |
| SessionEnd | Save the transcript; commit and push |

A checkpoint asks the model, in the same conversation and without comment,
to refresh `sessions/<profile>/<id>/summary.md` through `harness session
checkpoint`. The request travels as hidden context with the user's next
message; only the forced one (context nearly full, when there may be no next
message) is made at the end of a turn, once. When checkpoints are due is set
under `checkpoints:` in `harness.config.yaml`.

Hooks are silent: they print nothing, hand slow work to a background process
(`capture.background`), and log problems to `~/.my-harness/logs/harness.log`
(`harness status` shows them).

## Setup

See [getting-started.md](../getting-started.md). Under the hood, `harness
setup` calls this adapter's installer, which:

- registers the profile (tool + account + environment) in `core/profiles.yaml`,
- binds this Claude Code installation (its config folder) to that profile in `~/.my-harness/`,
- adds the five hooks above to `settings.json` (each runs `python -m harness hook claude-code`),
- adds the `harness-save` skill (save on request).

It does not write anything from the harness into Claude Code (no
instructions, skills or memory are loaded).

Several accounts on one machine: run each with its own `CLAUDE_CONFIG_DIR`
and run setup once per account. The hook detects which account is running.

To import sessions from before the harness was installed (session records
with their real dates, plus transcripts; safe to re-run):

```bash
python -m harness backfill claude-code --dry-run
python -m harness backfill claude-code            # or --since-days 30
```

To capture without hooks (e.g. a temporary cloud session):

```bash
python -m harness install claude-code --profile claude-code-personal-cloud --environment cloud --repo <folder> --no-hooks
python -m harness harvest claude-code
```
