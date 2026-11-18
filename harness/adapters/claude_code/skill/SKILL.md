---
name: harness-save
description: Save the current conversation to the user's harness (my-harness) on request - a summary of the whole conversation and any lasting facts, decisions or preferences as memory. Use when the user says "save to harness", "שמור לי", "save this", or asks to remember something across tools.
---

# Save to harness

The user keeps a portable harness outside any AI tool. The commands below
write to it (they validate, commit and push). They apply to the current
conversation automatically.

## 1. Refresh the conversation summary

Summarize the WHOLE conversation so far, not only the last part: goals,
decisions and their reasons, current state, open items, and what you learned
about the user's preferences. Stay under 400 words unless the harness asked
for a different limit, in the harness working language.

```bash
"${PYTHON}" -m harness session checkpoint --profile ${PROFILE} --reason "manual save" <<'HARNESS_EOF'
<summary>
HARNESS_EOF
```

## 2. Save lasting memory (optional)

One command per fact, decision or preference that should outlive this
conversation. `--kind` is one of fact, decision, preference, project-state.

```bash
"${PYTHON}" -m harness memory add --profile ${PROFILE} --id <short-slug> --kind fact --subject "<what it is about>" <<'HARNESS_EOF'
<the memory, self-contained>
HARNESS_EOF
```

If a command reports a conflict, another account or tool recorded something
different. Tell the user: both versions are kept for them to decide.
