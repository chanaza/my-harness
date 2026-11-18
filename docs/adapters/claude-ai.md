# Claude account adapter (claude.ai, Claude Desktop, Cowork)

claude.ai chats, projects and memory, and Cowork sessions (which now run in the
cloud), live in the Claude account, not on a computer. Anthropic offers no
way to read them from outside for a single person. So the account saves itself:

1. **The `harness-account` skill**, uploaded once per account (it then works
   in claude.ai, Claude Desktop and Cowork). It sends one file per run through
   the [harness connector](../connector.md) into the repository's inbox:
   - **exchange mode** (after every reply, `connector.transcript`): that exchange,
     word for word, appended to the conversation's `log.md`.
   - **save mode** (every `connector.summary_every_replies` replies): the
     conversation's summary in exactly the same sections as Claude Code
     checkpoints (one definition in `harness/digest.py`).
   - **describe mode** (a daily Cowork scheduled task): everything the account
     has built, in a fixed form (`schemas/harness-describe.schema.json`): user
     profile, instructions, memory, skills, agents, plugins, connections,
     projects, workflows (scheduled tasks), apps (artifacts), native settings,
     and `cannot_see` for anything it had no view of.
2. **GitHub Actions** in the repository runs `harness inbox`: each file is checked
   against its form and saved like any other capture (no computer needed).
3. **A data export** (Settings > Privacy > Export data), downloaded to
   `claude_ai.watch_folder`, is imported once: the history from before the skill.

Each account (by e-mail) is its own profile, e.g. `claude-ai-personal-cloud`.

## Settings (`claude_ai:` in harness.config.yaml)

| Setting | Default | Meaning |
|---|---|---|
| `watch_folder` | `~/Downloads` | Where a downloaded export is looked for |
| `file_pattern` | `data-*.zip` | Export file names |
| `archive_exports` | `true` | Keep each export file in transcript storage |
| `skill_folder` | `~/Downloads` | Where the skill file is written for you to upload |

## Setting it up

See [the harness connector](../connector.md): a GitHub key, the connector on
Cloudflare, adding it to the account, then the skill.

Not verified yet in the app: what Claude can see inside a Cowork scheduled task
(the first describe file's `cannot_see` tells), and how reliably a model saves
after every reply without a hook.
