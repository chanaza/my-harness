---
name: harness-account
description: Keep this Claude account (claude.ai, Claude Desktop, Cowork) saved in the user's harness (my-harness) through the harness connector. Modes - "save" sends a summary of the current conversation (${SAVE_WHEN}); "describe" sends everything the account has built (instructions, memory, skills, projects, scheduled tasks...) in a fixed form; "setup" creates the daily scheduled task. Use when a scheduled task says to run harness-account, when the user says "save to harness" / "שמור להרנס", and ${SAVE_WHEN}.
---

# Save this Claude account to the harness

The user's harness saves everything they build with AI outside any single tool, in
one shared form, so it can move between tools. You send ONE file per run with the
**harness connector**'s `save_to_harness` tool (arguments: `file_name`, `content`).
It checks the file against its form: if it answers with a problem, fix the file and
send it again. Never include passwords, API keys or tokens. Work quietly: do not
mention the saving in your answer unless it failed.

If the harness connector is not available here, say so in one sentence once per
conversation and continue normally.

Profile: ${PROFILE} (tool: ${TOOL}). File names use the current UTC time, e.g. 20261119-0600.

**When to save the conversation:** ${SAVE_WHEN}. Each save sends the summary of
the WHOLE conversation so far (the newest file replaces the earlier ones).

**Which mode:** a scheduled task names it. "set up" = setup mode. Otherwise save mode.

## Setup mode (once per account)

Create one Cowork scheduled task: name "Harness - describe account", every day,
prompt: "Run the harness-account skill in describe mode." Then run describe mode
once now.

## Describe mode

Send `describe-<time>.yaml` with EXACTLY this structure. Fill every field from
what you can actually see (your instructions, memory, available skills, tools
and connectors, projects, scheduled tasks). Copy texts word for word; do not
summarise them. Use an empty list for nothing, and put every kind you could not
see at all into `cannot_see` instead of guessing. Add no other fields.

```yaml
schema: harness-describe/1
profile: ${PROFILE}
tool: ${TOOL}
captured_at: 2026-11-19T06:00:00Z     # now, UTC
surface: cowork                        # cowork | claude-ai | desktop
user_profile:                          # what Claude knows about the user (name, role, work)
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

Send `conversation-<started>-<short-title>.md`, where <started> is when the
conversation started (so every save of the same conversation has the same name):

```
---
schema: harness-conversation/1
profile: ${PROFILE}
tool: ${TOOL}
surface: claude-ai            # cowork | claude-ai | desktop
title: <the conversation's title>
project: <the project's name, or empty>
saved_at: <now, UTC>
---
```

followed by the summary, written exactly as follows:

${SUMMARY_REQUEST}
