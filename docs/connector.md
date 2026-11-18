# The harness connector

Tools that cannot write to your harness themselves (claude.ai, Claude Desktop,
Cowork, and later any tool that supports connectors) save through **one small
connector of your own**. It can do exactly two things: put a file into the
`inbox/connector/` folder of your harness repository, and hand a tool's skill its
current instructions (`connector/instructions/<tool>.md`, written by the engine). It
cannot read, change or delete anything else, and nothing is stored on it.

**Skills update themselves:** the skill you upload is a few lines that ask the
connector for its instructions. When the engine improves, `harness inbox` (GitHub
Actions) and `harness upgrade` rewrite the instructions in your repository, and every
account follows them from its next conversation. No new upload.

```
your skill in claude.ai / Cowork  ->  harness connector  ->  inbox/connector/ in your repository
                                                        ->  GitHub Actions saves it into place
```

- **At the door** the connector refuses files that are not in the harness form
  (and anything that looks like a password or key), and tells Claude why.
- **In the repository** GitHub Actions runs the engine (`harness inbox`): every
  file is checked against its full form and saved like any other capture. A file
  that does not match goes to `inbox/rejected/` with the reason next to it.
- **How often:** at most every `connector.run_every_minutes` (default 30). Files that
  arrive meanwhile wait; the connector checks every 30 minutes and starts the next run
  as soon as it is allowed (a file waits about an hour at most).

## Set it up (once, about 15 minutes)

### 1. A GitHub key for your harness repository only

On github.com: your picture > **Settings** > **Developer settings** >
**Personal access tokens** > **Fine-grained tokens** > **Generate new token**.

- Name: `harness connector`. Expiration: the longest offered (write the date down).
- Repository access: **Only select repositories** > your harness repository.
- Permissions: **Contents: Read and write**, **Actions: Read and write**.
- **Generate**, and copy the key (it is shown once).

### 2. The connector on Cloudflare (free)

1. Sign up at dash.cloudflare.com.
2. **Workers & Pages** > **Create** > **Create Worker**. Name: `harness-connector` > **Deploy**.
3. **Edit code**: delete everything, paste the whole of
   [connector/worker.js](../connector/worker.js), **Deploy**.
4. **Settings** > **Variables and Secrets** > add:
   - `REPO` (Text): `your-github-name/your-harness-repository`
   - `GITHUB_TOKEN` (Secret): the key from step 1
   - `SECRET_PATH` (Secret): a long random text, e.g. 40 letters and digits
     typed at random. It is part of the connector's address: keep it private.
5. **Settings** > **Triggers** > **Cron Triggers** > **Add**: `*/30 * * * *` (every 30
   minutes it checks whether files wait in the inbox; free).
6. The connector's address is `https://harness-connector.<your-name>.workers.dev/mcp/<SECRET_PATH>`
   (the first part is shown on the Worker's page).

### 3. Add it to your Claude account

claude.ai > **Settings** > **Connectors** > **Add custom connector**: name
`harness`, address from step 2. It is then available in claude.ai, Claude
Desktop and Cowork of that account. Repeat for each account.

### 4. The skill

`python -m harness skill claude-ai` makes one skill file per account; upload
it on claude.ai (signed in as that account), then in Cowork type
`Set up harness-account`.

## Settings (`connector:` in harness.config.yaml)

| Setting | Default | Meaning |
|---|---|---|
| `save_every` | `reply` | When the skill saves the conversation: `reply` (after every reply), `meaningful` (decisions, results, wrap-ups) or `request` (only when you ask). After a change: `python -m harness skill claude-ai` and upload the new file. |
| `run_every_minutes` | `30` | How often, at most, the inbox is saved into place |

## Not locked in

- **Another host:** `connector/worker.js` is standard web code. It runs as it is
  on Deno Deploy, Vercel or any server: create a project there, paste the same
  code, set the same three settings, and replace the address in claude.ai.
- **No GitHub Actions:** `python -m harness inbox` on any computer saves the inbox
  the same way (also on a schedule).
- **Free limits:** Cloudflare's free plan allows 100,000 requests a day (a save
  is one request). GitHub's free plan includes a monthly amount of Actions
  minutes for private repositories; a run takes about a minute. If either runs
  out, files wait safely in the inbox: nothing is lost.

## Protection

The address contains a secret: whoever has it can put files into your inbox
(only files that pass the form check). Never paste it into a conversation. A
proper sign-in (OAuth) comes together with reading from the harness.
