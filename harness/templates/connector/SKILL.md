---
name: harness-account
description: ${NOT_HERE_SHORT}Keeps ${SCOPE} saved in the user's harness (my-harness) through the harness connector. Use after every reply you give (it sends that exchange), when a scheduled task says to run harness-account, and when the user says "save to harness" / "שמור להרנס".
---

# Save ${SCOPE} to the harness

${NOT_HERE_LONG}

1. At the start of a conversation, call the **harness connector**'s `harness_instructions`
   tool with `tool: ${TOOL}` and `profile: ${PROFILE}`. Once per conversation is enough:
   keep following them for the rest of the conversation.
2. Follow the instructions it returns exactly. They are kept up to date in the user's
   harness, so this skill never needs to change.

If the harness connector is not available here, say so in one sentence once per
conversation and continue normally.
