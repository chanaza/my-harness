---
name: harness-account
description: Keep this Claude account (claude.ai, Claude Desktop, Cowork) saved in the user's harness (my-harness). Modes - "describe" writes everything the account has built (instructions, memory, skills, projects, scheduled tasks...) in a fixed form; "save" writes a summary of the current conversation; "setup" creates the daily scheduled task. Use when a scheduled task says to run harness-account, when the user says "save to harness" / "שמור להרנס" / "שמור", or at the end of a meaningful conversation (a decision, a result, or a wrap-up).
---

# Save this Claude account to the harness

The user's harness saves everything they build with AI outside any single tool,
in one shared form, so it can move between tools. You write ONE file per run
into the Google Drive folder **${DRIVE_FOLDER}** (create it if missing); the
harness picks it up from there. Never write anywhere else, never include
passwords, API keys or tokens. Work quietly; afterwards say in one sentence what
was saved.

If you have no way to create a file in that Google Drive folder, do not pretend:
tell the user in one sentence that this skill needs a Google Drive connection
that can create files, and stop.

Account: ${ACCOUNT}. File names use the current UTC time, e.g. 20261119-0600.

**Which mode:** a scheduled task names it. "set up" = setup mode. "save" or a
wrap-up of a conversation = save mode. Otherwise ask nothing: use save mode.

## Setup mode (once per account)

Create one Cowork scheduled task: name "Harness - describe account", every day,
prompt: "Run the harness-account skill in describe mode." Then run describe mode
once now.

## Describe mode

Write `describe-<time>.yaml` with EXACTLY this structure. Fill every field from
what you can actually see (your instructions, memory, available skills, tools
and connectors, projects, scheduled tasks). Copy texts word for word; do not
summarise them. Use an empty list for nothing, and put every kind you could not
see at all into `cannot_see` instead of guessing. Add no other fields.

```yaml
schema: claude-account/1
account: ${ACCOUNT}
captured_at: 2026-11-19T06:00:00Z     # now, UTC
surface: cowork                        # cowork | claude-ai | desktop
profile:                               # what Claude knows about the user (name, role, work)
  text: "..."
instructions:                          # always-on instructions
  - {name: personal-preferences, text: "..."}
  - {name: "style: <style name>", text: "..."}
memory:
  - {text: "..."}
skills:                                # every skill available here
  - {name: ..., description: ..., origin: mine}        # mine | anthropic | plugin
agents:                                # sub-agents (e.g. from plugins)
  - {name: ..., description: ..., plugin: ...}
plugins:
  - {name: ..., description: ..., origin: mine}        # mine | marketplace
connections:                           # connectors and MCP servers, names only
  - {name: ..., kind: connector, purpose: ...}         # connector | mcp
projects:
  - {name: ..., description: ..., instructions: "...", files: [file name]}
workflows:                             # scheduled tasks
  - {name: ..., schedule: ..., prompt: "..."}
apps:                                  # artifacts the user built (pages, apps)
  - {name: ..., description: ..., link: ...}
native:                                # settings with no equivalent elsewhere (model, features on)
  - {name: ..., value: ...}
cannot_see: []                         # kinds above you had no view of, e.g. [projects, apps]
```

## Save mode

Write `conversation-<time>-<short-title>.md`:

```
---
schema: claude-conversation/1
account: ${ACCOUNT}
surface: claude-ai            # cowork | claude-ai | desktop
title: <the conversation's title>
project: <the project's name, or empty>
saved_at: <now, UTC>
---
```

followed by the summary, written exactly as follows:

${SUMMARY_REQUEST}
