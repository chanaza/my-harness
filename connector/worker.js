// The harness connector: a tiny MCP server. save_to_harness writes one file into the inbox;
// harness_instructions serves what a tool should do (kept current by the engine in
// connector/instructions/, so skills never need re-uploading); harness_find and harness_read
// let any tool find and read everything in the harness (index: connector/index.json).
//
// Tools that cannot write to the harness directly (claude.ai, Cowork, ...) call it from
// their harness skill. It checks the file at the door, writes it to inbox/connector/ in
// the harness repository, and starts the "harness inbox" GitHub Actions run at most every
// connector.run_every_minutes (read from harness.config.yaml); a Cron Trigger checks every 30
// minutes for files still waiting. Nothing is stored here.
//
// Standard web code (a fetch handler): runs on Cloudflare Workers, Deno Deploy, Vercel
// edge functions or any server with fetch. Settings (never in code):
//   GITHUB_TOKEN  fine-grained token for ONE repository: Contents + Actions read/write
//   REPO          owner/name of the harness repository
//   BRANCH        default "main"
//   SECRET_PATH   long random text; the connector's address is https://<host>/mcp/<SECRET_PATH>

const NAME = /^(describe-[A-Za-z0-9._-]{1,120}\.yaml|(conversation|exchange)-[A-Za-z0-9._-]{1,140}\.md)$/;
const SCHEMAS = { describe: "harness-describe/1", conversation: "harness-conversation/1", exchange: "harness-exchange/1" };
const MAX_BYTES = 1_000_000;
const WORKFLOW = "harness-inbox.yml";

const SLUG = /^[a-z0-9][a-z0-9-]{0,80}$/;

const INSTRUCTIONS_TOOL = {
  name: "harness_instructions",
  description:
    "The current instructions of the user's harness skill for this tool: when and how to save " +
    "to the harness. Call it once per conversation before saving, and follow it exactly.",
  inputSchema: {
    type: "object",
    properties: {
      tool: { type: "string", description: "The tool, as the skill names it, e.g. claude-ai" },
      profile: { type: "string", description: "The profile, as the skill names it" },
    },
    required: ["tool", "profile"],
  },
};

const READ_CHUNK = 60_000;
// Said after every saved exchange: what the user built must not wait for anyone to ask.
const BUILT_REMINDER =
  "Built mode: if in this conversation you created or changed something the user keeps (a skill, " +
  "agent, project, page, instructions, scheduled task or workflow) and have not sent it yet, send it " +
  "now in full as describe-<time>-built-<short-name>.yaml (partial: true, only that item, every file " +
  "word for word).";

const FIND_TOOL = {
  name: "harness_find",
  description:
    "Find anything in the user's harness: agents, skills, instructions, memory, projects, apps, " +
    "workflows, connections, profiles, single files, and conversations (by title, date, tool, " +
    "account, project, agent, goal or first message). Returns entries with a path to read.",
  inputSchema: {
    type: "object",
    properties: {
      query: { type: "string", description: "Words to look for (any field). Empty: list everything of a kind." },
      kind: { type: "string", description: "agent, skill, instruction, memory, project, app, workflow, connection, profile, conversation or file" },
      date: { type: "string", description: "A day or month, e.g. 2026-11-18 or 2026-11 (conversations)" },
      limit: { type: "integer", description: "At most this many results (default 30)" },
    },
  },
};

const READ_TOOL = {
  name: "harness_read",
  description:
    "Read one file of the user's harness by the path harness_find gave (a path starting with " +
    "'transcripts:' is a raw record). Long files come in parts: pass the offset it returns.",
  inputSchema: {
    type: "object",
    properties: {
      path: { type: "string", description: "The path from harness_find" },
      offset: { type: "integer", description: "Where to continue a long file (default 0)" },
    },
    required: ["path"],
  },
};

const TOOL = {
  name: "save_to_harness",
  description:
    "Save one file to the user's harness (my-harness) inbox. file_name: describe-<time>.yaml, " +
    "conversation-<started>-<title>.md or exchange-<started>-<title>-<n>.md, exactly as the harness " +
    "instructions say; content: the file. " +
    "Answers with what is wrong when the file does not match its form.",
  inputSchema: {
    type: "object",
    properties: {
      file_name: { type: "string", description: "describe-<time>.yaml, conversation-<started>-<title>.md or exchange-<started>-<title>-<n>.md" },
      content: { type: "string", description: "The whole file, as the harness skill describes it." },
    },
    required: ["file_name", "content"],
  },
};

export default {
  // Every 30 minutes (a Cron Trigger: */30 * * * *): files waiting in the inbox are
  // saved into place once connector.run_every_minutes has passed since the last run.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(startInboxRunIfWaiting(env, env.BRANCH || "main"));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (!env.SECRET_PATH || url.pathname !== `/mcp/${env.SECRET_PATH}`) {
      return new Response("Not found", { status: 404 });
    }
    if (request.method !== "POST") return new Response("Method not allowed", { status: 405 });
    let message;
    try {
      message = await request.json();
    } catch {
      return rpcError(null, -32700, "Parse error");
    }
    if (message.id === undefined) return new Response(null, { status: 202 }); // a notification
    switch (message.method) {
      case "initialize":
        return rpcResult(message.id, {
          protocolVersion: message.params?.protocolVersion || "2025-06-18",
          capabilities: { tools: {} },
          serverInfo: { name: "harness", version: "1.0.0" },
        });
      case "ping":
        return rpcResult(message.id, {});
      case "tools/list":
        return rpcResult(message.id, { tools: [TOOL, INSTRUCTIONS_TOOL, FIND_TOOL, READ_TOOL] });
      case "tools/call": {
        const args = message.params?.arguments || {};
        const handlers = {
          [INSTRUCTIONS_TOOL.name]: instructions, [FIND_TOOL.name]: find,
          [READ_TOOL.name]: read, [TOOL.name]: save,
        };
        const handler = handlers[message.params?.name];
        const result = handler ? await handler(args, env) : answer(`Unknown tool ${message.params?.name}`, true);
        return rpcResult(message.id, result);
      }
      default:
        return rpcError(message.id, -32601, `Unknown method ${message.method}`);
    }
  },
};

async function save({ file_name: name, content }, env) {
  const problem = checkAtTheDoor(name, content);
  if (problem) return answer(`Not saved: ${problem}`, true);
  const branch = env.BRANCH || "main";
  const path = `inbox/connector/${name}`;
  const existing = await github(env, "GET", `contents/${path}?ref=${branch}`);
  const body = { message: `connector: ${name}`, content: base64(content), branch };
  if (existing.ok) body.sha = (await existing.json()).sha; // the same conversation, saved again
  const written = await github(env, "PUT", `contents/${path}`, body);
  if (!written.ok) return answer(`Not saved: GitHub answered ${written.status}.`, true);
  await startInboxRun(env, branch);
  const missing = name.startsWith("exchange-") ? await missingReplies(name, content, env, branch) : [];
  const tool = (content.match(/^tool:\s*(\S+)/m) || [])[1];
  const version = tool ? await instructionsVersion(tool, env, branch) : null;
  return answer((missing.length
    ? `Saved ${name}. Replies ${missing.join(", ")} of this conversation are missing in the harness: ` +
      "send each of them now the same way (word for word, as you still see them), oldest first."
    : `Saved ${name}.`) +
    (version ? ` Current harness instructions: version ${version}; if yours are older, call ` +
      "harness_instructions again and follow the new ones from now on." : "") +
    (name.startsWith("exchange-") ? " " + BUILT_REMINDER : ""), false);
}

// The version line of the instructions the connector serves for a tool, so a conversation that
// fetched older instructions picks up the new ones without the user doing anything.
async function instructionsVersion(tool, env, branch) {
  if (!SLUG.test(tool)) return null;
  let file = await github(env, "GET", `contents/connector/instructions/${tool}.md?ref=${branch}`, null, "raw");
  if (!file.ok) return null;
  const match = (await file.text()).match(/version ([0-9][0-9.]*)/);
  return match ? match[1] : null;
}

// Which earlier replies of a conversation never arrived: neither saved (sessions/.../replies/)
// nor waiting in the inbox. Asked after every exchange, so a missed reply is sent on the next one.
async function missingReplies(name, content, env, branch) {
  const number = Number((name.match(/-(\d+)\.md$/) || [])[1]);
  const conversation = (content.match(/^conversation:\s*(\S+)/m) || [])[1];
  const profile = (content.match(/^profile:\s*(\S+)/m) || [])[1];
  if (!number || number < 2 || !conversation || !profile) return [];
  const have = new Set([number]);
  const saved = await github(env, "GET", `contents/sessions/${profile}/${conversation}/replies?ref=${branch}`);
  if (saved.ok) for (const f of await saved.json()) have.add(Number(f.name.split(".")[0]));
  const prefix = `exchange-${conversation.replace(/^conversation-/, "")}-`;
  const waiting = await github(env, "GET", `contents/inbox/connector?ref=${branch}`);
  if (waiting.ok) {
    for (const f of await waiting.json()) {
      if (f.name.startsWith(prefix)) have.add(Number(f.name.slice(prefix.length).replace(/\.md$/, "")));
    }
  }
  const missing = [];
  for (let n = 1; n < number; n++) if (!have.has(n)) missing.push(n);
  return missing;
}

async function instructions({ tool, profile }, env) {
  if (!SLUG.test(tool || "") || !SLUG.test(profile || "")) {
    return answer("tool and profile are needed, exactly as the harness skill names them.", true);
  }
  const branch = env.BRANCH || "main";
  let file = await github(env, "GET", `contents/connector/instructions/${tool}.md?ref=${branch}`, null, "raw");
  if (!file.ok) file = await github(env, "GET", `contents/connector/instructions/reader.md?ref=${branch}`, null, "raw");
  if (!file.ok) return answer("No harness instructions yet (run `harness upgrade`).", true);
  return answer((await file.text()).replaceAll("${PROFILE}", profile), false);
}

async function find({ query = "", kind, date, limit = 30 }, env) {
  const branch = env.BRANCH || "main";
  const file = await github(env, "GET", `contents/connector/index.json?ref=${branch}`, null, "raw");
  if (!file.ok) return answer("The harness has no index yet (run `harness upgrade`).", true);
  const words = String(query).toLowerCase().split(/\s+/).filter(Boolean);
  const results = (await file.json()).filter((entry) => {
    if (kind && entry.kind !== kind) return false;
    if (date && !String(entry.date || "").startsWith(date)) return false;
    const text = JSON.stringify(entry).toLowerCase();
    return words.every((word) => text.includes(word));
  });
  const shown = results.slice(0, Math.max(1, Math.min(Number(limit) || 30, 200)));
  const more = results.length > shown.length ? `\n(${results.length - shown.length} more: narrow the query)` : "";
  return answer(shown.length ? JSON.stringify(shown, null, 1) + more : "Nothing found.", false);
}

async function read({ path, offset = 0 }, env) {
  const raw = String(path || "");
  const fromTranscripts = raw.startsWith("transcripts:");
  const clean = fromTranscripts ? raw.slice("transcripts:".length) : raw;
  if (!clean || clean.startsWith("/") || clean.split("/").includes("..") || clean.startsWith(".git")) {
    return answer("path must be a path from harness_find", true);
  }
  const ref = fromTranscripts ? env.TRANSCRIPTS_BRANCH || "transcripts" : env.BRANCH || "main";
  const encoded = clean.split("/").map(encodeURIComponent).join("/");
  const file = await github(env, "GET", `contents/${encoded}?ref=${ref}`, null, "raw");
  if (!file.ok) return answer(`Not found: ${raw}`, true);
  const text = await file.text();
  const start = Math.max(0, Number(offset) || 0);
  const part = text.slice(start, start + READ_CHUNK);
  const next = start + READ_CHUNK < text.length
    ? `\n\n[part ${start}-${start + part.length} of ${text.length} characters; continue with offset ${start + READ_CHUNK}]`
    : "";
  return answer(part + next, false);
}

// The full form is checked by the engine; here only what makes a file unusable.
function checkAtTheDoor(name, content) {
  if (typeof name !== "string" || !NAME.test(name)) {
    return "file_name must be describe-<time>.yaml, conversation-<started>-<title>.md or exchange-<started>-<title>-<n>.md";
  }
  if (typeof content !== "string" || !content.trim()) return "content is empty";
  if (new TextEncoder().encode(content).length > MAX_BYTES) return "content is larger than 1 MB";
  const schema = SCHEMAS[name.split("-")[0]];
  if (!new RegExp(`^\\s*(---\\s*\\n)?schema:\\s*${schema.replace("/", "\\/")}\\s*$`, "m").test(content)) {
    return `the file must start with "schema: ${schema}" (see the harness skill)`;
  }
  for (const field of ["profile", "tool"]) {
    if (!new RegExp(`^${field}:\\s*\\S+`, "m").test(content)) return `"${field}:" is missing`;
  }
  if (/(ghp_|github_pat_|sk-ant-|xox[bp]-|AKIA)[A-Za-z0-9_-]{8,}/.test(content)) {
    return "it looks like it contains a secret (a token or key); remove it";
  }
  return null;
}

// At most one run every connector.run_every_minutes; the daily run picks up the rest.
async function startInboxRun(env, branch) {
  const minutes = await runEveryMinutes(env, branch);
  const runs = await github(env, "GET", `actions/workflows/${WORKFLOW}/runs?per_page=1`);
  if (runs.ok) {
    const latest = (await runs.json()).workflow_runs?.[0];
    if (latest && Date.now() - Date.parse(latest.created_at) < minutes * 60_000) return;
  }
  await github(env, "POST", `actions/workflows/${WORKFLOW}/dispatches`, { ref: branch });
}

async function startInboxRunIfWaiting(env, branch) {
  const listing = await github(env, "GET", `contents/inbox/connector?ref=${branch}`);
  if (!listing.ok) return; // no inbox folder: nothing waits
  const waiting = (await listing.json()).filter((f) => f.type === "file" && !f.name.startsWith("."));
  if (waiting.length) await startInboxRun(env, branch);
}

async function runEveryMinutes(env, branch) {
  const config = await github(env, "GET", `contents/harness.config.yaml?ref=${branch}`, null, "raw");
  if (config.ok) {
    const text = await config.text();
    const match = text.match(/^connector:\s*\n(?:[ \t]+.*\n)*?[ \t]+run_every_minutes:\s*(\d+)/m);
    if (match) return Math.max(5, Number(match[1]));
  }
  return 30;
}

function github(env, method, path, body = null, accept = "json") {
  return fetch(`https://api.github.com/repos/${env.REPO}/${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: accept === "raw" ? "application/vnd.github.raw" : "application/vnd.github+json",
      "User-Agent": "harness-connector",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
}

function base64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function answer(text, isError) {
  return { content: [{ type: "text", text }], isError };
}

function rpcResult(id, result) {
  return Response.json({ jsonrpc: "2.0", id, result });
}

function rpcError(id, code, message) {
  return Response.json({ jsonrpc: "2.0", id, error: { code, message } });
}
