# my-harness

**Everything you build with AI, kept safe outside any one tool.**

Your instructions, skills, projects, memory and conversations live inside the
AI tools you use. When you run out of tokens, change tool or switch account,
that work stays behind. my-harness copies it, continuously and in the
background, into a private GitHub repository that is yours, so it always
goes with you.

## Start here (5 minutes)

**You need:** a GitHub account, and an empty **private** repository in it
(on github.com: New repository, Private, nothing else). That repository will
hold your harness.

**1. On your computer, run one command.**
Open a terminal (on Windows: Command Prompt or PowerShell) and paste:

```
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/chanaza/my-harness/main/scripts/install.ps1 | iex"
```

On macOS / Linux:

```
curl -fsSL https://raw.githubusercontent.com/chanaza/my-harness/main/scripts/install.sh | bash
```

It asks a few short questions (where your repository is, a name for each of
your accounts, whether you use claude.ai) and shows what it found before
saving anything.

**2. If you use claude.ai or Cowork,** the installer puts one skill file per
account in your Downloads folder: upload it on claude.ai, then in Cowork type
`Set up harness-account`. It saves through your own small connector
([docs/connector.md](docs/connector.md), set up once).
(Can't find the file? Run `python -m harness skill claude-ai`.)

From then on, everything is saved by itself. Nothing is shown while it runs.

**Check that it works:** `python -m harness status` (and `python -m harness sources`: how each tool is captured).
**Update later:** run the same installation command again.
**More details, cloud sessions and troubleshooting:** [docs/getting-started.md](docs/getting-started.md).

### What is saved today

| Tool | What | How |
|---|---|---|
| Claude Code (computer and cloud) | Instructions, skills, agents, memory, connections, every conversation | Every turn, in the background |
| claude.ai and Cowork (your Claude account) | Instructions, memory, skills, projects, scheduled tasks, apps, conversation summaries | The account skill, through your connector: after every reply, and a daily description |
| Cowork sessions kept on this computer | Every conversation and its files | When you ask: `python -m harness harvest cowork` |

Saving only: nothing from the harness is loaded back into your tools yet.
What is finished and what is not: [ROADMAP.md](ROADMAP.md).

---

## How it works (for developers)

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

## Development

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
