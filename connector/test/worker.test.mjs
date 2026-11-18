// Run: node --test connector/test  (no network: GitHub is simulated)
import { test } from "node:test";
import assert from "node:assert/strict";
import worker from "../worker.js";

const env = { GITHUB_TOKEN: "t", REPO: "me/harness", BRANCH: "main", SECRET_PATH: "s3cret" };
const calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url, method: init.method, body: init.body && JSON.parse(init.body) });
  if (url.includes("connector/instructions/claude-ai.md")) return new Response("Profile: ${PROFILE}. Save after every reply.");
  if (url.includes("harness.config.yaml")) return new Response("connector:\n  transcript: exchange\n  run_every_minutes: 45\n");
  if (url.includes("/runs?")) return Response.json({ workflow_runs: [] });
  if (url.includes("contents/inbox/connector?")) return Response.json(globalThis.inbox || []);
  if (init.method === "GET") return new Response("{}", { status: 404 });
  return new Response("{}", { status: 201 });
};

const call = (body, path = "/mcp/s3cret") =>
  worker.fetch(new Request(`https://x${path}`, { method: "POST", body: JSON.stringify(body) }), env);
const save = (file_name, content) =>
  call({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "save_to_harness", arguments: { file_name, content } } })
    .then((r) => r.json()).then((j) => j.result);

const GOOD = "---\nschema: harness-conversation/1\nprofile: claude-ai-work-cloud\ntool: claude-ai\ntitle: x\n---\n## Goal\nx\n";

test("without the secret address there is nothing", async () => {
  assert.equal((await call({ id: 1, method: "tools/list" }, "/mcp/wrong")).status, 404);
});

test("lists one tool", async () => {
  const tools = (await (await call({ jsonrpc: "2.0", id: 1, method: "tools/list" })).json()).result.tools;
  assert.deepEqual(tools.map((t) => t.name), ["save_to_harness", "harness_instructions"]);
});

test("a good file is written to the inbox and starts a run", async () => {
  calls.length = 0;
  const result = await save("conversation-20261119-0700-plan.md", GOOD);
  assert.equal(result.isError, false, result.content[0].text);
  const put = calls.find((c) => c.method === "PUT");
  assert.match(put.url, /contents\/inbox\/connector\/conversation-20261119-0700-plan\.md$/);
  assert.ok(calls.some((c) => c.method === "POST" && c.url.endsWith("/dispatches")));
});

test("bad files are refused with the reason", async () => {
  assert.match((await save("notes.txt", GOOD)).content[0].text, /file_name must be/);
  assert.match((await save("describe-1.yaml", "free text")).content[0].text, /schema: harness-describe\/1/);
  const secret = GOOD + "token ghp_abcdefghijklmnop1234\n";
  assert.match((await save("conversation-1-x.md", secret)).content[0].text, /secret/);
});

test("the cron trigger starts a run only when files wait", async () => {
  const run = async () => {
    calls.length = 0;
    const waits = [];
    await worker.scheduled({}, env, { waitUntil: (p) => waits.push(p) });
    await Promise.all(waits);
    return calls.some((c) => c.method === "POST" && c.url.endsWith("/dispatches"));
  };
  globalThis.inbox = [];
  assert.equal(await run(), false);
  globalThis.inbox = [{ type: "file", name: "describe-1.yaml" }];
  assert.equal(await run(), true);
});

test("instructions come from the repository, for the asking profile", async () => {
  const ask = (args) => call({ jsonrpc: "2.0", id: 1, method: "tools/call",
    params: { name: "harness_instructions", arguments: args } }).then((r) => r.json()).then((j) => j.result);
  const result = await ask({ tool: "claude-ai", profile: "claude-ai-work-cloud" });
  assert.equal(result.content[0].text, "Profile: claude-ai-work-cloud. Save after every reply.");
  assert.equal((await ask({ tool: "../secrets", profile: "x" })).isError, true);
});

test("an exchange is accepted with its own form", async () => {
  const content = "---\nschema: harness-exchange/1\nprofile: claude-ai-work-cloud\ntool: claude-ai\nconversation: conversation-1-x\nnumber: 3\n---\n## User\nq\n";
  assert.equal((await save("exchange-20261119-0700-plan-3.md", content)).isError, false);
  assert.match((await save("exchange-1-x-3.md", GOOD)).content[0].text, /harness-exchange\/1/);
});
