# my-harness

**Keep your AI harness portable.** Instructions, skills, agents, workflows,
memory, app specs and conversation records live in a Git repository you own,
not inside any single AI tool. When you switch tools (or run out of tokens in
one), everything you built comes with you.

This repository is the **engine**: code, schemas and tool adapters. It holds
no personal content. Your content lives in a separate, private **content
repository** that the engine creates and maintains.

## Two repositories, on purpose

| | Engine (this repo) | Content repo (yours, private) |
|---|---|---|
| Holds | Code, schemas, templates, adapters | Your instructions, skills, memory, sessions |
| Visibility | Can be public | Private |
| Changed by | Development | Only through the engine and its adapters |

The rule that keeps this honest: **nothing is written into a content
repository by hand.** If something needs to get in, the engine needs a
command or an adapter for it.

## Three kinds of data

| Kind | Examples | Where it lives |
|---|---|---|
| Knowledge | Instructions, skills, memory, summaries, app and table schemas | Content repo (Git) |
| Logs | Full transcripts, live interaction logs | External storage (`storage:` in config) |
| App data | Rows of tables in Base44, Monday boards | Reserved: `apps/<app>/data.yaml` points to snapshots (later phase) |

## Provenance everywhere

Every item that outlives a single conversation (memory entries, skills,
agents, workflows, apps, tables, assets, connections) records a
`provenance` block: which tool and session created it, and every later
change. That is what makes it possible to detect and resolve conflicts
when two tools learned different things. Memory entries also carry
`status`, `supersedes` and `conflicts_with`.

## Quick start

```bash
pip install -e .
harness init ../my-content --owner "Your Name" --transcripts-path "~/Google Drive/My Drive/harness-storage/transcripts"
harness validate ../my-content
```

## Layout

```
harness/
  layout.py          the content-repo layout (single source of truth for paths)
  config.py          harness.config.yaml loading and typed access
  schema_loader.py   JSON Schema registry
  schemas/           one schema per content type
  storage/           storage interface + backends (filesystem today)
  validate/          checks a content repo against the schemas
  scaffold.py        `harness init`
  templates/         files a new content repo starts with
adapters/            per-tool capture and install (coming next)
docs/                design notes
tests/
```

See [docs/architecture.md](docs/architecture.md) for the design.
