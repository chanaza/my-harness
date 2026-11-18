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
pip install -e ".[dev]"
harness init ../my-content --owner "Your Name" --transcripts-path "C:\Users\you\OneDrive\Sessions\transcripts"
harness config set capture.live_log_threshold_percent 80 --repo ../my-content
harness validate --repo ../my-content
```

Every change to a content repository goes through a command like these;
settings are validated before they are written, and comments are kept.

## Code map

The engine is a small set of classes, each with one job. Extension points
are marked with ★.

| Class | Module | Job |
|---|---|---|
| `RepoLayout` | `harness/layout.py` | Where everything lives in a content repo |
| `ContentRepo` | `harness/repo.py` | Entry point: a content repo with its layout, config and storage |
| `ConfigFile`, `HarnessConfig` | `harness/config.py` | Change / read harness.config.yaml (validated) |
| `SchemaRegistry` | `harness/schemas/registry.py` | All JSON Schemas, cross-references resolved |
| `Storage` ★, `BackendRegistry` | `harness/storage/` | Interface + registry for transcript / log storage |
| `FilesystemStorage` | `harness/storage/filesystem.py` | Folder storage (OneDrive / Drive synced folders) |
| `RepoValidator`, `Check` ★, `FileReader` ★ | `harness/validation/` | Configurable checks over a content repo |
| `Scaffolder` | `harness/scaffold.py` | `harness init` |
| `HarnessCLI`, `Command` ★ | `harness/cli/` | The `harness` program; one class per command |
| `YamlDocument` | `harness/yaml_io.py` | Comment-preserving YAML edits (the only YAML dependency) |

Adding things:

- **A storage backend**: subclass `Storage`, decorate with `@backends.register`, add its name to `config.schema.json`.
- **A content type**: add a schema to `harness/schemas/` and a `SchemaCheck` in `RepoValidator.default`.
- **A command**: subclass `Command` and add it to `DEFAULT_COMMANDS`.

```
adapters/   per-tool capture and install (coming next)
docs/       design notes
tests/      one test file per component
```

See [docs/architecture.md](docs/architecture.md) for the design.
