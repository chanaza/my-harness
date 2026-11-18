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
| `export_every_days` | `7` | How often a new export is requested |
| `download_after_hours` | `3` | How long after the request the download task runs |

## Getting exports automatically

1. `python -m harness skill claude-ai` creates `harness-claude-ai-export.zip`
   from your settings.
2. Upload it in claude.ai: Settings > Capabilities > Skills.
3. In Cowork, create two scheduled tasks (the command prints them, from your
   settings):
   - every `export_every_days`: "Run the harness-claude-ai-export skill in request mode."
   - `download_after_hours` later: "Run the harness-claude-ai-export skill in download mode."

The first asks claude.ai for an export; the second saves it once the e-mail has
arrived. The computer picks the file up from the watch folder on its own
(scheduled every `capture.poll_minutes`).

Without the skill: request the export yourself and download it to the watch
folder; it is saved the same way.
