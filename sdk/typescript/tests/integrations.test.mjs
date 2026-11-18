import { afterEach, test } from "node:test";
import assert from "node:assert/strict";
import { AgentFlowClient, ApiError } from "../dist-test/src/index.js";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const ok = (data) => new Response(JSON.stringify({ code: 0, data }));

test("MCP wrappers use platform auth and preserve explicit settings", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    assert.equal(init.headers["X-API-Key"], "af_platform");
    assert.equal(init.headers.Authorization, undefined);
    calls.push([init.method, new URL(url).pathname, init.body ? JSON.parse(init.body) : undefined]);
    return ok({ id: 7, ok: true, tools: [] });
  };
  const client = new AgentFlowClient("http://test", { apiKey: "af_platform" });
  await client.mcp.list();
  await client.mcp.create("中文服务", "https://tools.example/mcp", { headers: { Authorization: "Bearer REMOTE" }, enabled: false });
  await client.mcp.discover(7);
  await client.mcp.update(7, { name: "中文服务", url: "https://tools.example/mcp", allowedTools: ["echo"], timeoutMs: 1000, enabled: false });
  await client.mcp.tools(7);
  await client.mcp.delete(7);
  assert.deepEqual(calls.map(([method, path]) => [method, path]), [
    ["GET", "/api/mcp-servers"], ["POST", "/api/mcp-servers"], ["POST", "/api/mcp-servers/7/discover"],
    ["PUT", "/api/mcp-servers/7"], ["GET", "/api/mcp-servers/7/tools"], ["DELETE", "/api/mcp-servers/7"],
  ]);
  assert.deepEqual(calls[1][2].allowedTools, []);
  assert.equal(calls[1][2].enabled, false);
  assert.equal(calls[1][2].headers.Authorization, "Bearer REMOTE");
  assert.deepEqual(calls[3][2], { name: "中文服务", url: "https://tools.example/mcp", allowedTools: ["echo"], timeoutMs: 1000, enabled: false, clearHeaders: false });
});

test("MCP full updates strip response metadata and only clear secrets explicitly", async () => {
  const calls = [];
  globalThis.fetch = async (_url, init) => { calls.push(JSON.parse(init.body)); return ok({}); };
  const client = new AgentFlowClient("http://test");
  const settings = { id: 7, hasCredentials: true, tools: [], name: "server", url: "https://tools.example/mcp", allowedTools: ["echo"], timeoutMs: 15000, enabled: false };
  await client.mcp.update(7, settings);
  await client.mcp.update(7, { ...settings, clearHeaders: true });
  assert.equal("id" in calls[0], false);
  assert.equal("hasCredentials" in calls[0], false);
  assert.equal("tools" in calls[0], false);
  assert.equal("headers" in calls[0], false);
  assert.equal(calls[1].clearHeaders, true);
  assert.deepEqual(settings.allowedTools, ["echo"]);
});

for (const [method, path, invoke] of [
  ["GET", "/api/skills", (resource) => resource.list()],
  ["GET", "/api/skills/report-helper", (resource) => resource.get("report-helper")],
  ["PUT", "/api/skills/report-helper", (resource) => resource.save("report-helper", "中文\n资料")],
  ["DELETE", "/api/skills/report-helper", (resource) => resource.delete("report-helper")],
  ["POST", "/api/skills/reload", (resource) => resource.reload()],
  ["GET", "/api/skills/report-helper/references/guide.v1.md", (resource) => resource.reference("report-helper", "guide.v1.md")],
]) {
  test(`Skills ${method} ${path}`, async () => {
    globalThis.fetch = async (url, init) => {
      assert.equal(new URL(url).pathname, path);
      assert.equal(init.method, method);
      assert.equal(init.headers.Authorization, "Bearer JWT");
      if (method === "PUT") assert.deepEqual(JSON.parse(init.body), { content: "中文\n资料" });
      return ok({ content: "内容" });
    };
    assert.deepEqual(await invoke(new AgentFlowClient("http://test", { token: "JWT" }).skills), { content: "内容" });
  });
}

test("invalid identifiers never reach fetch", () => {
  globalThis.fetch = async () => { assert.fail("invalid identifier reached network"); };
  const client = new AgentFlowClient("http://test");
  for (const id of [0, -1, NaN, Infinity, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => client.mcp.tools(id), RangeError);
  }
  for (const name of ["../secret", "a/b", "UPPER", ""]) assert.throws(() => client.skills.get(name), RangeError);
  assert.throws(() => client.skills.reference("report-helper", "../guide.md"), RangeError);
});

test("invalid tool lists cannot be expanded into accidental permissions", () => {
  globalThis.fetch = async () => { assert.fail("invalid tool list reached network"); };
  const client = new AgentFlowClient("http://test");
  for (const allowedTools of ["echo", [1], [""]]) {
    assert.throws(() => client.mcp.update(7, {
      name: "server", url: "https://tools.example/mcp", allowedTools, timeoutMs: 15000, enabled: true,
    }), TypeError);
  }
});

test("permission failures stay ApiError and failed probes remain inspectable", async () => {
  const client = new AgentFlowClient("http://test");
  globalThis.fetch = async () => new Response(JSON.stringify({ message: "forbidden" }), { status: 403 });
  await assert.rejects(() => client.skills.save("report-helper", "content"), error => error instanceof ApiError && error.code === 403);
  globalThis.fetch = async () => ok({ ok: false, tools: [], message: "cannot connect" });
  assert.equal((await client.mcp.discover(7)).ok, false);
});
