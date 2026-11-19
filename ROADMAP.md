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

### Harness connector + account skill - built, not verified in the app
Built and tested (connector with simulated GitHub, inbox processing, forms, the same
summary sections as Claude Code). Not yet run for real:
- Deploying the connector (Cloudflare) and adding it to claude.ai as a custom connector.
- What Claude sees inside a Cowork scheduled task (the first describe's `cannot_see`).
- How reliably a model saves after every reply without a hook.
- GitHub Actions run in the content repository (started by the connector, daily sweep).
Fallback for history: the data export, downloaded once into the watch folder.
- Full content in descriptions (skills, plugins, agents, projects' knowledge, apps):
  whether Claude can read every file (`not_readable` / `cannot_see` in the first runs).
### Genspark - built, not verified in Genspark
Saves through the connector with the engine's shared instructions (`ConnectorAdapter`).
Not yet tried: adding the MCP server in Genspark, following the instruction after every reply.

### Reading from other tools - built, not verified in a tool
`harness_find` / `harness_read` on the connector, an engine index of every file, and
reading instructions served to any tool. Not yet tried in Genspark (adding an MCP server
there, following the served instructions).
Next: OAuth sign-in for the connector; writing back into tools (loading proper).

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
