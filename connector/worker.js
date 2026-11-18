// The harness connector: a tiny MCP server with ONE tool, save_to_harness.
//
// Tools that cannot write to the harness directly (claude.ai, Cowork, ...) call it from
// their harness skill. It checks the file at the door, writes it to inbox/connector/ in
// the harness repository, and starts the "harness inbox" GitHub Actions run at most every
// connector.run_every_minutes (read from harness.config.yaml). Nothing is stored here.
//
// Standard web code (a fetch handler): runs on Cloudflare Workers, Deno Deploy, Vercel
// edge functions or any server with fetch. Settings (never in code):
//   GITHUB_TOKEN  fine-grained token for ONE repository: Contents + Actions read/write
//   REPO          owner/name of the harness repository
//   BRANCH        default "main"
//   SECRET_PATH   long random text; the connector's address is https://<host>/mcp/<SECRET_PATH>

const NAME = /^(describe|conversation)-[A-Za-z0-9._-]{1,120}\.(yaml|md)$/;
const MAX_BYTES = 1_000_000;
const WORKFLOW = "harness-inbox.yml";

const TOOL = {
  name: "save_to_harness",
  description:
    "Save one file to the user's harness (my-harness) inbox. file_name: describe-<time>.yaml " +
    "or conversation-<started>-<title>.md, exactly as the harness skill says; content: the file. " +
    "Answers with what is wrong when the file does not match its form.",
  inputSchema: {
    type: "object",
    properties: {
      file_name: { type: "string", description: "describe-<time>.yaml or conversation-<started>-<title>.md" },
      content: { type: "string", description: "The whole file, as the harness skill describes it." },
    },
    required: ["file_name", "content"],
  },
};

export default {
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
        return rpcResult(message.id, { tools: [TOOL] });
      case "tools/call":
        return rpcResult(message.id, await save(message.params?.arguments || {}, env));
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
  return answer(`Saved ${name}.`, false);
}

// The full form is checked by the engine; here only what makes a file unusable.
function checkAtTheDoor(name, content) {
  if (typeof name !== "string" || !NAME.test(name)) {
    return "file_name must be describe-<time>.yaml or conversation-<started>-<title>.md";
  }
  if (typeof content !== "string" || !content.trim()) return "content is empty";
  if (new TextEncoder().encode(content).length > MAX_BYTES) return "content is larger than 1 MB";
  const schema = name.startsWith("describe-") ? "harness-describe/1" : "harness-conversation/1";
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
