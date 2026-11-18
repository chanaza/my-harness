# Cowork adapter (Claude desktop app)

Tier C+: no hooks, so capture runs on a schedule (Windows Task Scheduler, or
cron on macOS/Linux) every `capture.poll_minutes` (default 30). Nothing is
shown while it runs.

## Accounts

The desktop app keeps every signed-in account apart. Setup lists the
accounts it finds (with their conversations and skills) and asks a name for
each (`personal`, `work`, or `skip`). Each becomes its own profile, e.g.
`cowork-work-local`.

## What is captured, per account

| From Cowork | Into the harness |
|---|---|
| Skills (`skills-plugin/.../skills/<name>/`) | `core/skills/<name>/` (exclusions apply, e.g. `skill:pdf`) |
| Plugins (`rpm/<plugin>/`) | `core/plugins/<name>/` whole, plus a connection entry |
| Agent memory (`agent/memory/`) | `memory/` |
| Every conversation and persistent agent | `sessions/<profile>/<id>/meta.yaml` (dates, file list) |
| Their transcript and action log (`audit.jsonl`) | transcript storage |
| Files you uploaded and files produced (`uploads/`, `outputs/`) | transcript storage, `<profile>/<id>/files/` |

The folder a conversation was given access to on your computer (`host-cwd`)
is not copied: it is your own folder, not Cowork's.

Only what changed since the last run is copied.

## Data folder

Windows `%APPDATA%\Claude`, macOS `~/Library/Application Support/Claude`,
Linux `~/.config/Claude`. Override with `CLAUDE_APP_DATA_DIR`.

## Not covered here

Regular chats and Projects in the Claude app live in your claude.ai account,
not on this machine; they need a separate adapter.
