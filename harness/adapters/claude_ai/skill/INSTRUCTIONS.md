# Harness instructions: Claude account (instructions version ${VERSION})

The user's harness saves everything they build with AI outside any single tool, in
one shared form, so it can move between tools. You send ONE file per run with the
**harness connector**'s `save_to_harness` tool (arguments: `file_name`, `content`).
It checks the file against its form: if it answers with a problem, fix the file and
send it again. Never include passwords, API keys or tokens. Work quietly: do not
mention the saving in your answer unless it failed.

**Not in Claude Code:** Claude Code is saved by the harness itself (completely, with
its own hooks). If you are running as Claude Code (a coding agent in a terminal, IDE
or Claude Code on the web), do nothing with this skill.

If the harness connector is not available here, say so in one sentence once per
conversation and continue normally.

Profile: ${PROFILE} (tool: ${TOOL}). File names use the current UTC time, e.g. 20261119-0600.

**What to send in a conversation:** ${AFTER_EVERY_REPLY}. Also send a summary when the
user says "save to harness" and when the conversation wraps up. Together they let the
user continue the conversation anywhere: the latest summary plus every exchange after it.
Number your replies in the conversation 1, 2, 3...; the conversation's file names use
when it started (`<started>` = UTC time of its first message, e.g. 20261119-0700) and a
short title, and stay the same for the whole conversation.

**Which mode:** a scheduled task names it. "set up" = setup mode. "save the project" =
project mode. Otherwise save mode; and in a conversation inside a project, also run
project mode once per conversation (projects can only be read from inside them).

## Setup mode (once per account)

Create one Cowork scheduled task: name "Harness - describe account", every day,
prompt: "Run the harness-account skill in describe mode." Then run describe mode
once now.

## Describe mode

Send `describe-<time>.yaml` with EXACTLY this structure. Fill every field from what
you can actually see. Copy texts and files word for word; never summarise or invent.
Use an empty list for nothing; put every kind you had no view of at all into
`cannot_see`. Add no other fields.

**Full content for everything the user built** (origin `mine`): every file of each
skill (read them where skills are kept for you, e.g. /mnt/skills/user/<skill>/), every
file of each plugin and agent, each project's instructions and knowledge files, each
app's code (read each app's source with the artifact tools when you have them, and copy
it exactly). If you cannot read an item's content, keep the item with
`not_readable: <why>` instead of `files`: never send an empty or made-up copy.
Others' items (Anthropic's skills, marketplace plugins): name and description only.

**Large:** if the file would be over 800 KB, split it into parts named
`describe-<time>-1of3.yaml`, `-2of3`, ... Every part starts with the same `schema`,
`profile`, `tool`, `captured_at`, plus `part: 1/3` (2/3, ...), and carries some of the
lists; a list may continue in the next part. Send every part.

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
memory:                                # name = the topic (e.g. the memory file's name)
  - {name: ai-governance-presentation, text: "..."}
skills:                                # every skill available here
  - name: ...
    description: ...
    origin: mine                       # mine | anthropic | plugin | marketplace
    files:                             # mine: every file, in full
      - {path: SKILL.md, content: "..."}
      - {path: references/x.md, content: "..."}
  - {name: ..., description: ..., origin: anthropic}
agents:                                # sub-agents (e.g. from plugins)
  - {name: ..., description: ..., files: [{path: agent.md, content: "..."}]}
plugins:
  - {name: ..., description: ..., origin: mine, files: [{path: ..., content: "..."}]}   # mine | anthropic | marketplace
connections:                           # connectors and MCP servers, names only
  - {name: ..., kind: connector, purpose: ...}         # connector | mcp
projects:
  - name: ...
    description: ...
    instructions: "..."
    knowledge: [{path: file name, content: "..."}]
workflows:                             # scheduled tasks
  - {name: ..., schedule: ..., prompt: "..."}
apps:                                  # artifacts the user built (pages, apps)
  - {name: ..., description: ..., link: ..., files: [{path: index.html, content: "..."}]}
native:                                # settings with no equivalent elsewhere (model, features on)
  - {name: ..., value: ...}
cannot_see: []                         # kinds you had no view of at all, e.g. [apps]
```

## Project mode (inside a project)

Send `describe-<time>-project-<short-name>.yaml` with ONLY this project, in full:

```yaml
schema: harness-describe/1
profile: ${PROFILE}
tool: ${TOOL}
captured_at: 2026-11-19T06:00:00Z
surface: claude-ai
partial: true                          # only this project; nothing else is touched
projects:
  - name: <the project's name>
    description: ...
    instructions: "<the project's instructions, word for word>"
    knowledge: [{path: <file name>, content: "<the file, word for word>"}]
```

Every knowledge file in full; a file you cannot read: leave it out and add
`not_readable: <which files, why>` to the project.

## Exchange mode (after a reply)

Send `exchange-<started>-<short-title>-<n>.md`, where n is the number of the reply you
just gave:

```
---
schema: harness-exchange/1
profile: ${PROFILE}
tool: ${TOOL}
conversation: conversation-<started>-<short-title>
number: <n>
at: <now, UTC>
title: <the conversation's title>
surface: claude-ai            # cowork | claude-ai | desktop
---
## User

<the user's message, word for word>

## Assistant

<your reply, word for word>
```

Copy both word for word, nothing shortened. Files attached to the message: list their
names only.

## Save mode

Send `conversation-<started>-<short-title>.md` (the same name at every save of the
conversation; the newest replaces the earlier one):

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
