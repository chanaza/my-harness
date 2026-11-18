# claude.ai adapter (chats, projects, memory)

claude.ai keeps chats and projects in the account, not on the computer. The
complete, official way out is its data export (Settings > Privacy > Export
data), which arrives as a download link by e-mail. This adapter imports every
export it finds; nothing is read from claude.ai directly.

## What is captured, per account (by e-mail)

| From the export | Into the harness |
|---|---|
| Every conversation | `sessions/<profile>/<id>/meta.yaml` (title, real dates); the full conversation and its attachments in transcript storage |
| Projects | `core/projects/<name>/project.yaml` (instructions) + `knowledge/` files |
| Memory | `memory/` |
| The export file itself | transcript storage `<profile>/exports/` (`claude_ai.archive_exports`) |

Each account is its own profile, e.g. `claude-ai-personal-cloud`. Only
conversations that changed since the last export are rewritten.

## Settings (`claude_ai:` in harness.config.yaml)

| Setting | Default | Meaning |
|---|---|---|
| `watch_folder` | `~/Downloads` | Where downloaded exports are looked for |
| `file_pattern` | `data-*.zip` | Export file names |
| `archive_exports` | `true` | Keep each export file in transcript storage |
| `export_every_days` | `7` | How often the export skill requests a new export |

## Getting exports automatically

1. `python -m harness skill claude-ai` creates `harness-claude-ai-export.zip`
   from your settings.
2. Upload it in claude.ai: Settings > Capabilities > Skills.
3. In Cowork, create a scheduled task (e.g. weekly): "Run the
   harness-claude-ai-export skill".

Each run downloads the export requested by the previous run and requests a new
one. The computer picks the file up from the watch folder on its own
(scheduled every `capture.poll_minutes`).

Without the skill: request the export yourself and download it to the watch
folder; it is saved the same way.
