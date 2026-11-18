// @ts-nocheck
import { afterEach, test } from "node:test";
import assert from "node:assert";
import { AgentFlowClient, ApiError } from "../src/index.js";

const Q = String.fromCharCode(34);
const NL = String.fromCharCode(10);
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

function setFetch(handler: (url: any, init: any) => Response): void {
  (globalThis as any).fetch = handler;
}

test("auth header is sent", async () => {
  let captured: string | undefined;
  setFetch((url, init) => {
    captured = init.headers["X-API-Key"];
    return new Response(JSON.stringify({ code: 0, message: "ok", data: { id:1 } }), {
      status: 200,
      headers: { "content-type": "application/json" }
    });
  });
  const client = new AgentFlowClient("http://test", { apiKey: "af_demo" });
  const data = await client.workflows.list();
  assert.deepStrictEqual(data, { id: 1 });
  assert.strictEqual(captured, "af_demo");
});

test("api error raised on nonzero code", async () => {
  setFetch(() =>
    new Response(JSON.stringify({ code: 4010, message: "bad", data: null }), { status: 200 })
  );
  const client = new AgentFlowClient("http://test", { apiKey: "af_demo" });
  await assert.rejects(() => client.workflows.list(), ApiError);
});

test("run returns aggregated result", async () => {
  const runResult = {
    runId: "abc",
    status: "SUCCESS",
    outputs: { text: "hi" },
    nodeStatus: [],
    elapsedMs: 12,
    errorMessage: null
  };
  setFetch((url, init) => {
    const u = new URL(url);
    assert.strictEqual(u.pathname, "/api/workflows/5/run");
    assert.strictEqual(init.method, "POST");
    return new Response(JSON.stringify({ code: 0, message: "ok", data: runResult }), {
      status: 200
    });
  });
  const client = new AgentFlowClient("http://test", { apiKey: "af_demo" });
  const result = await client.workflows.run(5, { topic: "x" });
  assert.strictEqual(result.status, "SUCCESS");
  assert.deepStrictEqual(result.outputs, { text: "hi" });
});

test("executeStream parses sse", async () => {
  const sse = [
    "event: run_started",
    "data: {" + Q + "runId" + Q + ":" + Q + "r1" + Q + "}",
    "",
    "event: run_finished",
    "data: {" + Q + "status" + Q + ":" + Q + "SUCCESS" + Q + "}",
    "",
    ""
  ].join(NL);
  setFetch(() =>
    new Response(sse, { status: 200, headers: { "content-type": "text/event-stream" } })
  );
  const client = new AgentFlowClient("http://test", { apiKey: "af_demo" });
  const events: [string, any][] = [];
  for await (const ev of client.workflows.executeStream(5, {})) {
    events.push(ev);
  }
  assert.strictEqual(events.length, 2);
  assert.strictEqual(events[0][0], "run_started");
  assert.strictEqual(events[1][0], "run_finished");
  assert.strictEqual(events[1][1].status, "SUCCESS");
});

async function collectEvents(body: string): Promise<[string, any][]> {
  setFetch(() => new Response(body));
  const client = new AgentFlowClient("http://test", { apiKey: "af_demo" });
  const events: [string, any][] = [];
  for await (const event of client.workflows.executeStream(5)) events.push(event);
  return events;
}

for (const newline of ["\n", "\r\n", "\r"]) {
  test("executeStream handles multiline JSON and default event with " + JSON.stringify(newline), async () => {
    const body = ["\ufeff: heartbeat", "", 'data: {"text":', 'data: "你好"}', "", ""].join(newline);
    assert.deepStrictEqual(await collectEvents(body), [["message", { text: "你好" }]]);
  });
}

for (const suffix of ["", "\n", "\r\n"]) {
  test("executeStream keeps final event with suffix " + JSON.stringify(suffix), async () => {
    const body = 'event: run_finished\ndata: {"status":"SUCCESS"}' + suffix;
    assert.deepStrictEqual(await collectEvents(body), [["run_finished", { status: "SUCCESS" }]]);
  });
}

test("executeStream decodes UTF-8 and CRLF split across chunks", async () => {
  const bytes = new TextEncoder().encode('event: node_token\r\ndata: {"delta":"你好"}\r\n\r\n');
  setFetch(() => new Response(new ReadableStream({
    start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      controller.close();
    }
  })));
  const events = [];
  for await (const event of new AgentFlowClient("http://test").workflows.executeStream(5)) events.push(event);
  assert.deepStrictEqual(events, [["node_token", { delta: "你好" }]]);
});

test("executeStream cancels response body on early exit", async () => {
  let canceled = false;
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('event: run_started\ndata: {}\n\n'));
    },
    cancel() { canceled = true; }
  });
  setFetch(() => new Response(stream));
  for await (const event of new AgentFlowClient("http://test").workflows.executeStream(5)) {
    assert.strictEqual(event[0], "run_started");
    break;
  }
  assert.strictEqual(canceled, true);
  assert.strictEqual(stream.locked, false);
});

test("requests and execution streams honor configured timeout", async () => {
  setFetch((url, init) => new Promise((resolve, reject) => {
    assert.ok(init.signal instanceof AbortSignal);
    init.signal.addEventListener("abort", () => reject(init.signal.reason), { once: true });
  }));
  const client = new AgentFlowClient("http://test", { timeout: 10 });
  // AbortSignal.timeout uses an unref'ed timer, so keep the test process alive.
  const keepAlive = setInterval(() => {}, 1000);
  try {
    await assert.rejects(() => client.workflows.list(), { name: "TimeoutError" });
    await assert.rejects(() => client.workflows.executeStream(5).next(), { name: "TimeoutError" });
  } finally {
    clearInterval(keepAlive);
  }
});

test("executeStream surfaces HTTP errors", async () => {
  setFetch(() => new Response("bad key", { status: 401 }));
  await assert.rejects(() => new AgentFlowClient("http://test").workflows.executeStream(5).next(),
    (error) => error instanceof ApiError && error.code === 401 && error.message.includes("bad key"));
});
