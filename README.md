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

It asks a few short questions (where your repository is, a short name for this
computer such as `office` or `home`, a name for each of your accounts, whether
you use claude.ai) and shows what it found before saving anything. On a second
computer run the same command and give it another name.

**2. If you use claude.ai or Cowork,** set up your own small **harness
connector** once (about 15 minutes, free, no command line:
[docs/connector.md](docs/connector.md)) and add it to each Claude account. Then
upload the skill file the installer put in your Downloads folder (one per
account) and, in Cowork, type `Set up harness-account`. The skill updates
itself: improvements arrive without uploading it again.
(Can't find the file? Run `python -m harness skill claude-ai`.)

From then on, everything is saved by itself. Nothing is shown while it runs.

**Check that it works:** `python -m harness status` (and `python -m harness sources`: how each tool is captured).
**Update later:** run the same installation command again.
**More details, cloud sessions and troubleshooting:** [docs/getting-started.md](docs/getting-started.md).

### What is saved today

| Tool | What | How |
|---|---|---|
| Claude Code (computer and cloud) | Instructions, skills, agents, memory, connections; every conversation in full (raw transcript + readable log) and its summary | Every turn, in the background |
| claude.ai and Cowork (your Claude account) | Profile, instructions, memory, your skills and plugins with their files, projects (from inside each project), scheduled tasks, apps (artifacts, new or changed versions), connections | The account skill: a full description every day; a project when you work in it |
| — conversations there | Every exchange word for word, and a summary every 10 replies | The account skill, after every reply |
| — history from before | Every chat with its attachments | Once, from claude.ai's data export (Settings > Privacy > Export data) |
| Cowork sessions kept on a computer | Every conversation and its files | When you ask: `python -m harness harvest cowork` |
| monday.com | Your AI agents (with skills, knowledge, jobs), workflows, recent agent runs | When you ask: `python -m harness harvest monday` |

How each tool is captured is one setting per tool (`capture_modes` in your
harness settings); `python -m harness sources` shows it.

### Continue anywhere

Every conversation, from any tool, ends up in the same form in
`sessions/<profile>/<conversation>/`: **`summary.md`** (goal, decisions, current
state, open thread, standing instructions, preferences, connections) and
**`log.md`** (word for word, reply by reply). If you run out of tokens, give a
new tool the latest summary and the log after it, and continue from exactly
where you stopped.

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
| Conversations | `summary.md` + readable `log.md` per conversation | Content repo, `sessions/` |
| Transcripts | Raw transcripts, exactly as the tool keeps them | Transcript storage (`storage:` in config) |
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
node --test connector/test/worker.test.mjs
harness --help
```

Every change keeps this README, `docs/` and `ROADMAP.md` up to date. Nothing is
pushed unless every test passes.

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
| `SummaryDigest`, `summary_request` | `harness/digest.py` | The one summary language for every tool; its sections -> instructions, memory, connections |
| `ConversationLog`, `Reply` | `harness/conversation_log.py` | The one readable `log.md` per conversation, for every tool |
| `InboxProcessor` | `harness/inbox.py` | Saves what the harness connector dropped into `inbox/connector/` (`harness inbox`) |
| `WorkspaceScanner` | `harness/workspace.py` | Repositories, branches and commits a session works in |
| `MemoryStore` | `harness/memory.py` | Memory entries with conflict tracking |
| `Captured`, `HarvestSync`, `ItemWriter` ★ | `harness/harvest/` | Turning what a tool holds into harness content |
| `Adapter` ★, `AdapterRegistry` | `harness/adapters/` | One class per tool: harvest, hooks, install |
| `ClaudeCodeAdapter` | `harness/adapters/claude_code/` | Claude Code ([docs](docs/adapters/claude-code.md)) |
| `CoworkAdapter` | `harness/adapters/cowork/` | Cowork in the Claude desktop app ([docs](docs/adapters/cowork.md)) |
| `ClaudeAiAdapter` | `harness/adapters/claude_ai/` | The Claude account (claude.ai, Desktop, Cowork): the self-updating skill, and one-off exports ([docs](docs/adapters/claude-ai.md)) |
| `MondayAdapter` | `harness/adapters/monday/` | monday.com agents, workflows and runs through its API |
| harness connector | `connector/worker.js` | Your own tiny MCP server: tools without direct access save into the inbox ([docs](docs/connector.md)) |
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

Adding things. The rule: **the engine holds every piece of logic once; an adapter only
translates its tool's own format** (e.g. Claude Code's transcript into `Reply` objects).

- **A tool**: subclass `Adapter`, decorate with `@adapters.register`, import it in `harness/adapters/__init__.py`.
- **A storage backend**: subclass `Storage`, decorate with `@backends.register`, add its name to `config.schema.json`.
- **A content type**: add a schema to `harness/schemas/`, an `ItemWriter` if tools produce it, and a `SchemaCheck`.
- **A command**: subclass `Command` and add it to `DEFAULT_COMMANDS`.

```
docs/       design notes and per-tool adapter docs
tests/      one test file per component
```

See [docs/architecture.md](docs/architecture.md) for the design.
