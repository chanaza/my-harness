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
| Transcripts | Full conversation transcripts | Transcript storage (`storage:` in config) |
| App data | Rows of tables in Base44, Monday boards | Reserved: `apps/<app>/data.yaml` points to snapshots (later phase) |

## Provenance everywhere

Every item that outlives a single conversation (memory entries, skills,
agents, workflows, apps, tables, assets, connections) records a
`provenance` block: which **profile** (a tool + an account, registered in
`core/profiles.yaml`) and session created it, and every later change. That is what makes it possible to detect and resolve conflicts
when two tools learned different things. Memory entries also carry
`status`, `supersedes` and `conflicts_with`.

## Getting started

**[docs/getting-started.md](docs/getting-started.md)**: one command on
Windows, macOS or Linux, and a setup script for cloud sessions. Setup saves
only; loading into a tool is a separate step.

For developers:

```bash
pip install -e ".[dev]"
python -m pytest
harness --help
```

## Code map

The engine is a small set of classes, each with one job. Extension points
are marked with ★.

| Class | Module | Job |
|---|---|---|
| `RepoLayout` | `harness/layout.py` | Where everything lives in a content repo |
| `ContentRepo` | `harness/repo.py` | Entry point: a content repo with its layout, config and storage |
| `ConfigFile`, `HarnessConfig` | `harness/config.py` | Read / change / upgrade harness.config.yaml (validated) |
| `SchemaRegistry` | `harness/schemas/registry.py` | All JSON Schemas, cross-references resolved |
| `Profile`, `ProfileRegistry` | `harness/profiles.py` | Tool + account + environment (local/cloud) identities; rename |
| `Origin`, `Provenance` | `harness/provenance.py` | Who created and changed each item |
| `SessionRecord` | `harness/sessions.py` | One conversation: meta, rolling summary, compactions |
| `CheckpointPolicy`, `CheckpointRecorder` | `harness/checkpoints.py` | When a summary is due; recording it |
| `SummaryDigest` | `harness/digest.py` | Structured summary sections -> instructions, memory, connections |
| `WorkspaceScanner` | `harness/workspace.py` | Repositories, branches and commits a session works in |
| `MemoryStore` | `harness/memory.py` | Memory entries with conflict tracking |
| `Captured`, `HarvestSync`, `ItemWriter` ★ | `harness/harvest/` | Turning what a tool holds into harness content |
| `Adapter` ★, `AdapterRegistry` | `harness/adapters/` | One class per tool: harvest, hooks, install |
| `ClaudeCodeAdapter` | `harness/adapters/claude_code/` | Claude Code ([docs](docs/adapters/claude-code.md)) |
| `CoworkAdapter` | `harness/adapters/cowork/` | Cowork in the Claude desktop app ([docs](docs/adapters/cowork.md)) |
| `ClaudeAiAdapter` | `harness/adapters/claude_ai/` | claude.ai chats, projects, memory via its export ([docs](docs/adapters/claude-ai.md)) |
| `AccountBoundAdapter` | `harness/adapters/base.py` | Shared base for tools with several accounts, captured on a schedule |
| `StructuredMerge` | `harness/merge.py` | Merges the harness's YAML files by content across machines |
| `Scheduler` | `harness/scheduler.py` | Periodic capture for tools without hooks (Task Scheduler / cron) |
| `Storage` ★, `BackendRegistry` | `harness/storage/` | Transcript storage (per profile) |
| `Migration` ★ | `harness/migrations.py` | Bring existing content to the current engine (`harness upgrade`) |
| `FilesystemStorage`, `GitStorage` | `harness/storage/` | A (synced) folder, or a branch of a Git repository |
| `GitSync` | `harness/git_sync.py` | Commit / push after captures |
| `LocalHome` | `harness/local.py` | Per-machine settings and state (`~/.my-harness`) |
| `RepoValidator`, `Check` ★, `FileReader` ★ | `harness/validation/` | Configurable checks over a content repo |
| `Scaffolder` | `harness/scaffold.py` | `harness init` and `harness upgrade` |
| `HarnessCLI`, `Command` ★ | `harness/cli/` | The `harness` program; one class per command |

Adding things:

- **A tool**: subclass `Adapter`, decorate with `@adapters.register`, import it in `harness/adapters/__init__.py`.
- **A storage backend**: subclass `Storage`, decorate with `@backends.register`, add its name to `config.schema.json`.
- **A content type**: add a schema to `harness/schemas/`, an `ItemWriter` if tools produce it, and a `SchemaCheck`.
- **A command**: subclass `Command` and add it to `DEFAULT_COMMANDS`.

```
docs/       design notes and per-tool adapter docs
tests/      one test file per component
```

See [docs/architecture.md](docs/architecture.md) for the design.
