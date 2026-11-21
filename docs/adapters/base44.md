# Base44 adapter (Superagents)

Base44 Superagents are pulled through Base44's API, like monday.com: nothing has to be sent
by the agent itself. Every item carries the Base44 profile as its source.

| In Base44 | In the harness |
|---|---|
| Identity and soul (`.agents/.memory/IDENTITY.md`, `SOUL.md`), model, skills, connections | `core/agents/<superagent>.yaml` |
| Rules (`.agents/rules/*.md`, always on) | `core/instructions/` |
| Skills (`.agents/skills/`, with scripts) | `core/skills/` |
| MCP servers it runs (`.agents/mcps/<name>/`) | `core/plugins/<superagent>-mcp-<name>/` and `core/connections.yaml` |
| Structured memory, `USER.md`, `memory.md`, `notes/` | `memory/` |
| Data model (entities, `base44/`) | `apps/<superagent>/` (the table data stays in Base44) |
| Conversations | `sessions/<profile>/conversation-<id>/` with `log.md`; files made in a conversation next to it |

Never saved: `.agents/.env`, anything that looks like a secret (reported by name), MCP
environment and header values (names only), Base44's own docs (`.agents/platform-docs/`).

**Limit:** Base44 returns the last 200 messages of a conversation. Every pull keeps what it
saw (by message id), so from the first pull on nothing is lost; earlier messages of long
conversations are noted as not available.

**Access:** a Base44 personal access token with full access (created in a Superagent's
settings > Developer; it is account-wide). Reading the Superagent's definition and skills is
refused for a read-only token. In a cloud session the token is a network secret for
`app.base44.com`; on a computer, the password store (`HARNESS_BASE44_TOKEN` or keyring
name `base44`).

Pull: `python -m harness harvest base44`.
