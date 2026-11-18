# Getting started

my-harness keeps what you build around AI tools (instructions, skills,
agents, memory, conversation summaries and transcripts) in a private Git
repository that you own, so you can move to another tool or account
without losing it.

**What setup does today: it saves. It does not load.** Once connected, your
conversations and what you build in the tool are saved to your harness
automatically, in the background. Nothing from the harness is put back into
any tool yet; loading is a separate, explicit step that comes later.

## Before you start: your harness repository

Your harness lives in a **private** GitHub repository.

- **First time:** create an empty private repository on GitHub (e.g.
  `my-harness-content`). Setup fills it.
- **Already have one:** setup connects to it.

## On your computer

### Windows

Open a terminal (Command Prompt or PowerShell; either works) and run:

```
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/chanaza/my-harness/main/scripts/install.ps1 | iex"
```

### macOS / Linux

Open a terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/chanaza/my-harness/main/scripts/install.sh | bash
```

The installer checks that Python (3.11+) and Git are installed (and tells
you where to get them if not), installs my-harness, and starts a short
guided setup that asks:

1. Where your harness repository is (its GitHub address, or a folder).
2. Which account this is (`personal`, `work`, ...). Each tool + account +
   environment is its own *profile*, e.g. `claude-code-personal-local`.
3. Where to keep full transcripts. A OneDrive or Google Drive folder keeps
   them in the cloud; they never go into the repository's main branch.

It then shows what it found (skills, agents, instructions, past
conversations) and asks before saving anything. Exclude items first if you
like, e.g. `harness config set harvest.exclude "skill:pdf"`.

That's all. Use your tool as usual.

## In Claude Code on the web (cloud sessions)

A cloud session starts on a fresh machine each time, so the connection is
made by the cloud environment itself, at the start of every session:

1. Open the environment's settings (the environment menu in the session's
   title bar, then **Edit**).
2. Under **Repositories**, add your harness repository. Cloud sessions can
   only reach private repositories that are attached this way.
3. Under **Setup script**, add (replace `my-harness-content` with your
   repository's name and `personal` with your account name):

   ```bash
   if [ -d my-harness-content ]; then
     pip install -q "git+https://github.com/chanaza/my-harness"
     python3 -m harness setup claude-code --repo "$PWD/my-harness-content" \
       --account personal --environment cloud --yes
   fi
   ```

New sessions in that environment are then saved automatically as profile
`claude-code-personal-cloud`. Their transcripts go to a `transcripts`
branch of your harness repository (a local OneDrive folder is not
reachable from the cloud). This, too, only saves: nothing is loaded into
the session.

## What you will (not) notice

Saving is designed to be invisible:

- Nothing is printed in your conversations.
- Slow work (saving the transcript, committing, pushing) runs in the
  background after each turn; you never wait for it.
- Every few messages the assistant quietly refreshes a summary of the
  conversation (one short command, no comment). Near the end of a long
  conversation it does so once more, so the latest state is never lost.
- Problems never interrupt you; they are logged.

## Checking that it works

```bash
python -m harness status
```

shows which accounts are connected on this machine, whether your harness
repository is valid, and any recent problems.

## Keeping it up to date

```bash
python -m pip install --user --upgrade "git+https://github.com/chanaza/my-harness"
python -m harness upgrade --repo <your harness folder>
```

The first command updates the engine; the second brings your harness
repository's settings and stored data up to the new version (it keeps every
value you set).

## Settings you may want to change

All settings live in `harness.config.yaml` in your harness repository, each
with an explanation. Change them with `harness config set <key> <value>`:

| Setting | Default | Meaning |
|---|---|---|
| `checkpoints.every_user_messages` | 10 | Refresh the conversation summary every N of your messages |
| `checkpoints.every_context_percent` | 20 | ...and every time the conversation grew by this much |
| `checkpoints.force_at_context_percent` | 80 | ...and once more when the conversation is nearly full |
| `harvest.exclude` | `[]` | Things not to save, e.g. `skill:pdf` |
| `git.push_every_turn` | `true` | Push after every turn |
