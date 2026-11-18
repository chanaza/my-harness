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
| SessionStart | Register the session, harvest; after a compaction, the next Stop requests a checkpoint |
| UserPromptSubmit | Count the message toward the next checkpoint |
| Stop | Harvest; workspace state; save the transcript; commit; request a structured checkpoint when due |
| PreCompact | Save the transcript |
| SessionEnd | Save the transcript; commit and push |

A checkpoint asks the model, in the same conversation, to refresh
`sessions/<profile>/<id>/summary.md` through `harness session checkpoint`.
When it is due is set under `checkpoints:` in `harness.config.yaml`.

Hooks never interrupt Claude Code: failures go to `~/.my-harness/logs/harness.log`.

## Setup (Windows, macOS, Linux)

Requires Python 3.11+ and Git.

```bash
pip install git+https://github.com/chanaza/my-harness
git clone https://github.com/<you>/<your-content-repo> <folder>
python -m harness install claude-code --profile claude-code-personal-local --environment local --repo <folder>
```

Several accounts on one machine: run each with its own `CLAUDE_CONFIG_DIR`
and install once per account, with a different `--profile`. The hook detects
which account is running from that folder.

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
