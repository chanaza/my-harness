---
name: harness-account
description: Not for Claude Code (it saves itself). Keeps this Claude account (claude.ai, Claude Desktop, Cowork) saved in the user's harness (my-harness) through the harness connector. Use after every reply you give (to check whether a save is due), when a scheduled task says to run harness-account, and when the user says "save to harness" / "שמור להרנס".
---

# Save this Claude account to the harness

Not in Claude Code (a coding agent in a terminal, IDE or Claude Code on the web):
there, do nothing with this skill.

1. Call the **harness connector**'s `harness_instructions` tool with
   `tool: ${TOOL}` and `profile: ${PROFILE}` (once per conversation is enough).
2. Follow the instructions it returns exactly. They are kept up to date in the
   user's harness, so this skill never needs to change.

If the harness connector is not available here, say so in one sentence once per
conversation and continue normally.
