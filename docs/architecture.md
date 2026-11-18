# Architecture

## Goal

Avoid lock-in. Whatever is built around a model (instructions, skills,
memory, agents, apps) must survive leaving the tool it was built in, at
any moment, including when tokens have already run out. So capture is
**continuous**, not a one-time export at the end.

## Content model

| Area | What | Who changes it |
|---|---|---|
| `core/profile` | Who the owner is | Owner |
| `core/instructions` | How to behave (prescriptive) | Owner approves every change |
| `core/skills`, `core/agents`, `core/workflows` | Reusable building blocks | Owner, via adapters |
| `core/connections.yaml` | Connections things depend on (no secrets) | Adapters |
| `memory` | What is known (descriptive) | Agents, automatically |
| `apps` | App specs and table schemas from tools like Base44, Monday | Adapters |
| `assets` | Reference files; large ones by external link | Adapters |
| `sessions/<tool>/<session-id>/` | Per-conversation meta, compactions, summary | Adapters |
| `inbox` | Raw drops from tools that cannot write to Git | Owner pastes; engine processes |

Instructions and memory are separate because they have different update
policies: an agent may record a fact on its own, but must not quietly
rewrite your rules.

## Session linking

A session id ties everything about one conversation together:
`sessions/<tool>/<id>/` in Git, and the same `<tool>/<id>/` key in
transcript and live-log storage. Tools with a native conversation id keep
it in `meta.yaml` as `native_id`; otherwise the adapter generates one
(`YYYYMMDD-HHMM-<tool>-<topic>`) and keeps reusing it during the conversation.

## Provenance and conflicts

`schemas/provenance.schema.json` is shared by every cross-session item:
`source` (tool, session, time) plus a list of `updates`. Memory entries add
`status: active | superseded | disputed`, `supersedes` and
`conflicts_with`, so a fact learned in ChatGPT and a contradicting fact
learned in Claude are both kept, linked, and surfaced for a decision.

## Language

`language.working` is the language the harness writes in. With
`language.preserve_original: true`, content defined in another language is
kept as written; translated files point to it with `original:` and declare
their own `lang:`.

## Storage

Logs do not belong in Git: they are large, append-only and should be
deletable. `harness/storage/` defines one interface (`Storage`) with
interchangeable backends selected in `harness.config.yaml`. Today:
`filesystem`, which with a Google Drive for desktop folder means Drive
storage without API keys. A database backend is a new class plus one
config line.

## Capture tiers (next phase)

| Tier | Mechanism | Tools |
|---|---|---|
| A | Real hooks on compaction / session end | Claude Code, Cursor |
| B | Model writes through a connector (MCP, Actions, API) | Claude, ChatGPT, maybe Genspark |
| C | "Save to harness" emits a structured block for the inbox; Monday also via API | Base44, Genspark, Monday |

Each tool's real capabilities are verified when its adapter is built.
