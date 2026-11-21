# Harness instructions: reading the user's harness (engine ${VERSION})

The user's harness (my-harness) keeps everything they built with AI, from every tool,
in one shared form: agents, skills, instructions, memory, projects, apps, workflows,
and every conversation (a `summary.md` plus a word-for-word `log.md`). Read it with
the **harness connector**:

- **Start with `harness_read` of `README.md`**: the map of the whole harness - how it is
  organised, every agent with all its parts (rules, skills, workflows, app tables and backend
  functions, connections, memory, conversations), what uses what, and the secrets each part
  needs. `sessions/README.md` lists every conversation.
- `harness_find` - search the index: `query` (words), optional `kind` (guide, agent, skill,
  instruction, memory, project, app, function, table, workflow, connection, conversation,
  file). Each result has a `path` to read, and where known the `agent` it belongs to, what it
  `uses` and what it is `used_by`.
- `harness_read` - read one file by its `path`; long files come in parts (`offset`).
  A path that starts with `transcripts:` is a raw record (large; read the log instead
  when there is one).

How to answer:
1. Find first, then read only what you need; say which files you used.
2. Never invent: if something is not in the harness, say so.
3. The harness is the user's own data: do not paste secrets or tokens anywhere.

**To build something that works like one of the user's agents** (e.g. "act like Emily"):
1. Read its section in `README.md` (every part, with paths); read its definition (identity,
   goal, instructions, policies, skills, knowledge, jobs) and the parts it lists - rules,
   workflows, the app's backend functions and tables, memory.
2. `harness_find` with `kind: conversation` and `agent: <name>`; read the logs of its
   recent runs (`log.md`): what it was asked, what it did step by step, what it answered.
3. Describe the agent in this tool's own terms (instructions, tools it needs, schedule),
   point out what this tool cannot do the same way, and only then set it up with the user.
