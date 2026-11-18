# Roadmap

Status of the engine. Saving comes first; loading comes after saving is complete.

## Done

- Engine: configurable, validated content repository; profiles (tool + account +
  environment); provenance and conflict handling; several machines on one harness
  (rebase + YAML merge); silent background capture; guided setup and one-line installers.
- Adapters: Claude Code (hooks); the Claude account - claude.ai, Desktop, Cowork - through the
  `harness-account` skill (Drive folder); Cowork local files on demand; monday.com (API).
- One summary language for every tool (`harness/digest.py`).

## Not finished / not verified

### Claude account skill (`harness-account`) - built, not verified in the app
Built and tested in the engine (forms, Drive inbox, the same summary sections as
Claude Code). Not yet run inside claude.ai / Cowork:
- Can the skill create a file in the Google Drive folder from claude.ai, Desktop and
  cloud Cowork? (If not: another route to the folder is needed.)
- What Claude sees inside a Cowork scheduled task (memory, projects, scheduled tasks):
  the first describe file's `cannot_see` tells.
- Whether conversations are saved reliably without a hook ("save to harness" works;
  saving on its own at the end of a conversation depends on the model).
- Google Drive for desktop must sync the folder to `claude_ai.inbox_folder`.
Fallback for history: download the data export once into the watch folder.

### Known limits
- Cloud sessions cannot reach a local synced folder; they use the git storage backend.
- Transcript retention (deleting old transcripts after N days) is not implemented.

## Next

1. Monday adapter - agents, agent jobs (workflows), workflow-builder workflows, MCP tools
   and agent runs are captured. Still open: agent memory / board learnings (the API
   answers "unauthorized"), knowledge file contents (references are kept), board
   automations and boards (structure first) as the next step, a guided `harness setup
   monday`, and a scheduled cloud capture.
2. ChatGPT, Cursor, Genspark, Base44 adapters.
3. Loading: build a "resume pack" and load the harness into a tool / account.
4. Optional: package the Claude Code adapter as a Claude Code plugin.
