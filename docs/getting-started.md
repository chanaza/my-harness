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

Setup connects every supported tool it finds on the computer (today:
Claude Code, and Cowork in the Claude desktop app). If a tool has several
signed-in accounts (e.g. personal and work), it lists them and asks a name
for each. It then shows what it found (skills, plugins, instructions,
memory, past conversations) and asks before saving anything. Exclude items first if you
like, e.g. `harness config set harvest.exclude "skill:pdf"`.

That's all. Use your tool as usual.

## Your Claude account (claude.ai, Claude Desktop, Cowork)

Chats, projects, memory and Cowork sessions live in your Claude account, not on
the computer, so the account saves itself, through your own small
[harness connector](connector.md) (set up once, about 15 minutes). The installer
asks for your account e-mail(s) and puts one `harness-account-<e-mail>.zip` per
account in your Downloads folder:

1. Set up the connector and add it to each account ([connector.md](connector.md)).
2. Upload the skill file on claude.ai, signed in as that account.
3. In Cowork (same account), type: `Set up harness-account`.

After every reply the exchange is saved word for word, and every 10 replies a
summary (settings `connector.transcript`, `connector.summary_every_replies`), and
every day the account describes itself (instructions, memory, skills, projects,
scheduled tasks...). Details:
[adapters/claude-ai.md](adapters/claude-ai.md).

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

Run the same installation command again (or `python -m harness update`).
On a computer that is already connected it asks nothing: it installs the
latest engine, brings your harness repository's
settings and stored data up to the new version (keeping every value you
set), refreshes the connection of every tool on this machine, and saves once.

## Several computers

Every computer (and cloud environment) saves to the same harness repository.
Before pushing, each one first brings in what the others pushed, so they
never overwrite each other.

Each computer has a short name (setup asks for it once, e.g. `office` or
`home`), and its profiles end with it: `claude-code-work-office`,
`claude-code-work-home`, `claude-code-personal-cloud`.

**A second computer:** run the same installation command there and give it
a different name. **A computer installed before names existed:** run
`python -m harness machine name office` once.

## How each tool is captured

One line per kind of tool in `harness.config.yaml`, for every account and computer:

```yaml
capture_modes:
  claude-code: {mode: push}                        # every turn, by the tool itself
  cowork: {mode: scheduled, every_minutes: 30}
  claude-ai: {mode: scheduled, every_minutes: 30}
  monday: {mode: on_demand}                        # `harness harvest monday`
```

`push` = the tool sends; `scheduled` = this computer checks every N minutes;
`on_demand` = only when you run `harness harvest <tool>`. After a change run
`python -m harness update`. `python -m harness sources` shows each tool's mode,
why, which accounts are connected here and when it was last captured.

## If something goes wrong

**"Repository not found" when downloading your harness repository.** Your
repository is private, and GitHub answers "not found" when Git is signed in
as an account that cannot see it. Remove the saved login, then download it
once yourself, naming your account, and sign in when asked:

```
cmdkey /delete:git:https://github.com
git clone https://<your-github-name>@github.com/<your-github-name>/<repository>
```

(The first line is for Windows.) Then run the installer again and give it
the downloaded folder.

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
