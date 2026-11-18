# Roadmap

Status of the engine. Saving comes first; loading comes after saving is complete.

## Done

- Engine: configurable, validated content repository; profiles (tool + account +
  environment); provenance and conflict handling; several machines on one harness
  (rebase + YAML merge); silent background capture; guided setup and one-line installers.
- Adapters: Claude Code (hooks), Cowork (scheduled), claude.ai (data export).

## Not finished / not verified

### claude.ai export automation - built, not verified end to end
The export skill (`harness-export`) and its two Cowork scheduled tasks are built and
tested in isolation, but the in-app part has not been run successfully yet:
- Cowork's "Set up my harness export" (setup mode creating the two scheduled tasks).
- Browser control in Cowork for requesting / downloading the export (the built-in
  browser connection could not be established in the first trial).
- Fallback that always works: download the export yourself (claude.ai Settings >
  Privacy > Export data) into the watch folder; it is imported automatically.
Next: run setup mode once per account, confirm the tasks exist, confirm one export
arrives and is imported; document any differences in the skill.

### Known limits
- Cloud sessions cannot reach a local synced folder; they use the git storage backend.
- Transcript retention (deleting old transcripts after N days) is not implemented.

## Next

1. Monday adapter (boards, columns, docs, files, automations, agents).
2. ChatGPT, Cursor, Genspark, Base44 adapters.
3. Loading: build a "resume pack" and load the harness into a tool / account.
4. Optional: package the Claude Code adapter as a Claude Code plugin.
