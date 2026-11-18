# Claude account adapter (claude.ai, Claude Desktop, Cowork)

claude.ai chats, projects and memory, and Cowork sessions (which now run in the
cloud), live in the Claude account, not on a computer. Anthropic offers no
way to read them from outside for a single person. So the account saves itself:

1. **The `harness-account` skill**, uploaded once per account (it then works
   in claude.ai, Claude Desktop and Cowork). It writes one file per run into
   the Google Drive folder `claude_ai.drive_folder`:
   - **describe mode** (a daily Cowork scheduled task): everything the account
     has built, in a fixed form (`schemas/claude-account.schema.json`): profile,
     instructions, memory, skills, agents, plugins, connections, projects,
     workflows (scheduled tasks), apps (artifacts), native settings, and
     `cannot_see` for anything it had no view of.
   - **save mode** ("save to harness", or at the end of a meaningful
     conversation): the conversation's summary in exactly the same sections as
     Claude Code checkpoints (one definition in `harness/digest.py`).
2. **This computer** reads that folder through Google Drive for desktop
   (`claude_ai.inbox_folder`), checks each file against its form (a file that
   does not match is reported, never saved) and saves it like any other tool.
3. **A data export** (Settings > Privacy > Export data), downloaded to
   `claude_ai.watch_folder`, is imported once: the history from before the skill.

Each account (by e-mail) is its own profile, e.g. `claude-ai-personal-cloud`.

## Settings (`claude_ai:` in harness.config.yaml)

| Setting | Default | Meaning |
|---|---|---|
| `drive_folder` | `my-harness-inbox` | Google Drive folder the skill writes into |
| `inbox_folder` | `~/my-harness-inbox` | Where this computer sees that folder (synced copy) |
| `watch_folder` | `~/Downloads` | Where a downloaded export is looked for |
| `file_pattern` | `data-*.zip` | Export file names |
| `archive_exports` | `true` | Keep each export file in transcript storage |
| `skill_folder` | `~/Downloads` | Where the skill file is written for you to upload |

## Setting it up

1. `python -m harness skill claude-ai` writes one skill file per account.
2. Upload each on claude.ai, signed in as that account.
3. In Cowork (same account) type: `Set up harness-account`. It creates the
   daily scheduled task and describes the account once.
4. Install Google Drive for desktop and point `claude_ai.inbox_folder` at the
   synced `my-harness-inbox` folder.

Not verified yet: whether the skill can create files in Google Drive from
every surface, and what Claude can see from inside a scheduled task. The first
describe file tells (`cannot_see`).
