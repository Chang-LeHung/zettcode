/** The client against a real HTTP server: the JSON endpoints, the SSE stream, and the answers posted into a run. */

import { strict as assert } from "node:assert";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import { after, describe, test } from "node:test";

import {
  RunCancelledError,
  RunFailedError,
  ZettCodeClient,
  ZettCodeError,
  parseBlock,
  sseFrames,
  totalTokens,
  wireOptions,
} from "../src/index.js";
import type { RunEvent, RunResult, StreamFrame } from "../src/index.js";

interface Request {
  method: string;
  url: string;
  headers: IncomingMessage["headers"];
  body: string;
}

type Handler = (request: Request, response: ServerResponse) => void | Promise<void>;

interface Server {
  url: string;
  requests: Request[];
  close(): Promise<void>;
}

async function serve(handler: Handler): Promise<Server> {
  const requests: Request[] = [];
  const server = createServer(async (incoming, response) => {
    const chunks: Buffer[] = [];
    for await (const chunk of incoming) {
      chunks.push(chunk as Buffer);
    }
    const request: Request = {
      method: incoming.method ?? "",
      url: incoming.url ?? "",
      headers: incoming.headers,
      body: Buffer.concat(chunks).toString("utf-8"),
    };
    requests.push(request);
    await handler(request, response);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${address.port}`,
    requests,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

function json(response: ServerResponse, body: unknown, status = 200): void {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

function frame(event: string, payload: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
}

function stream(response: ServerResponse): void {
  response.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
}

const usage = {
  input_tokens: 10,
  output_tokens: 2,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  reasoning_tokens: 0,
  seconds: 0.5,
  requests: 1,
  context_tokens: 12,
};

const result: RunResult = {
  text: "done",
  session_id: "session-1",
  usage,
  tools: [],
  stop: null,
  stop_message: null,
  questions: [],
};

const servers: Server[] = [];
after(async () => {
  await Promise.all(servers.map((server) => server.close()));
});

async function start(handler: Handler): Promise<Server> {
  const server = await serve(handler);
  servers.push(server);
  return server;
}

/** Type one event payload of a frame, for the assertions. */
function eventOf(item: StreamFrame): RunEvent | null {
  return item.event === "event" ? (item.data as RunEvent) : null;
}

describe("the JSON API", () => {
  test("health needs no token in the request and is sent with one when configured", async () => {
    const server = await start((request, response) => {
      assert.equal(request.url, "/health");
      json(response, { status: "ok", version: "0.1.0", workspace: "/w", session: "s1", busy: false });
    });
    const client = new ZettCodeClient({ baseUrl: server.url, token: "s3cret" });

    assert.equal((await client.health()).session, "s1");
    assert.equal(server.requests[0]?.headers.authorization, "Bearer s3cret");
  });

  test("models, settings and plugins are read, and a settings change is a PATCH", async () => {
    const model = {
      name: "fast",
      model: "gpt-5-mini",
      context_window: 200_000,
      multimodal: false,
      efforts: ["low", "medium"],
      active: true,
      compact_percent: 80,
    };
    const settings = {
      model,
      effort: "medium",
      efforts: ["low", "medium"],
      permission: "deny",
      permissions: ["deny", "ask", "safe", "auto"],
    };
    const server = await start((request, response) => {
      if (request.url === "/models") return json(response, { models: [model], current: "fast" });
      if (request.url === "/settings" && request.method === "PATCH") {
        const sent = JSON.parse(request.body);
        if (sent.compact_percent !== undefined) {
          assert.deepEqual(sent, { compact_percent: 55 });
          return json(response, { ...settings, model: { ...model, compact_percent: 55 } });
        }
        assert.deepEqual(sent, { permission: "safe" });
        return json(response, { ...settings, permission: "safe" });
      }
      if (request.url === "/settings") return json(response, settings);
      if (request.url === "/plugins") return json(response, { loaded: ["shell"], failures: [] });
      json(response, { error: "not_found", message: request.url }, 404);
    });
    const client = new ZettCodeClient({ baseUrl: server.url });

    assert.equal((await client.models()).current, "fast");
    assert.equal((await client.settings()).effort, "medium");
    assert.equal((await client.updateSettings({ permission: "safe" })).permission, "safe");
    assert.equal((await client.updateSettings({ compact_percent: 55 })).model.compact_percent, 55);
    assert.deepEqual((await client.plugins()).loaded, ["shell"]);
  });

  test("sessions are listed, opened and renamed, with the id escaped in the path", async () => {
    const session = { id: "a/b", title: "T", created_at: null, updated_at: null, current: true };
    const server = await start((request, response) => {
      if (request.url === "/sessions?limit=5") return json(response, { sessions: [session] });
      if (request.url === "/sessions/a%2Fb/open") {
        return json(response, { id: "a/b", title: "T", locked: false, usage });
      }
      if (request.url === "/sessions/current/rename") {
        assert.deepEqual(JSON.parse(request.body), { title: "New" });
        return json(response, { ...session, title: "New" });
      }
      json(response, { error: "not_found", message: request.url }, 404);
    });
    const client = new ZettCodeClient({ baseUrl: server.url });

    assert.deepEqual(await client.listSessions(5), [session]);
    assert.equal((await client.openSession("a/b")).id, "a/b");
    assert.equal((await client.renameSession("New")).title, "New");
  });

  test("the rest of the conversation endpoints answer what the server says", async () => {
    const server = await start((request, response) => {
      if (request.url === "/sessions/current/name") return json(response, { id: "s", title: "Named", current: true });
      if (request.url === "/sessions/current/fork") return json(response, { id: "f", title: null, locked: false, usage });
      if (request.url === "/sessions/current/compact") {
        return json(response, { applied: true, summary: "s", compressed: 10, kept: 2 });
      }
      if (request.url === "/sessions/current/context") return json(response, null);
      if (request.url === "/sessions/current/history") return json(response, { messages: [] });
      if (request.url === "/sessions/current/history?full=true") {
        return json(response, { messages: [{ role: "summary", text: "s" }] });
      }
      if (request.url === "/sessions/current/ask") {
        assert.deepEqual(JSON.parse(request.body), { question: "why?", timeout: 5 });
        return json(response, { answer: "because" });
      }
      if (request.url === "/usage") return json(response, usage);
      if (request.url === "/runs/resumable") return json(response, { resumable: false, kind: null, description: null });
      json(response, { error: "not_found", message: request.url }, 404);
    });
    const client = new ZettCodeClient({ baseUrl: server.url });

    assert.equal((await client.nameSession()).title, "Named");
    assert.equal((await client.forkSession()).id, "f");
    assert.equal((await client.compactSession()).compressed, 10);
    assert.equal(await client.context(), null);
    assert.deepEqual(await client.history(), []);
    assert.equal((await client.history({ full: true }))[0]?.role, "summary");
    assert.equal(await client.ask("why?", 5), "because");
    assert.equal((await client.usage()).input_tokens, 10);
    assert.deepEqual(await client.resumable(), { resumable: false, kind: null, description: null });
  });

  test("an error body becomes a ZettCodeError with its code and status", async () => {
    const server = await start((_request, response) =>
      json(response, { error: "busy", message: "A run is already in progress" }, 409),
    );
    const client = new ZettCodeClient({ baseUrl: server.url });

    await assert.rejects(client.createSession(), (error: unknown) => {
      assert.ok(error instanceof ZettCodeError);
      assert.equal(error.code, "busy");
      assert.equal(error.status, 409);
      assert.match(error.message, /already in progress/);
      return true;
    });
  });

  test("a model update can carry chat, a temperature, and a null that removes a key", async () => {
    const model = { name: "Fast", model: "gpt-5", context_window: 128000, multimodal: false, efforts: ["low"], active: true, compact_percent: 80 };
    let sent: unknown = null;
    const server = await start((request, response) => {
      if (request.url === "/models/Fast" && request.method === "PATCH") {
        sent = JSON.parse(request.body);
        return json(response, { models: [model], current: "Fast" });
      }
      if (request.url === "/models" && request.method === "POST") {
        sent = JSON.parse(request.body);
        return json(response, { models: [model], current: "Fast" }, 201);
      }
      json(response, { error: "not_found", message: request.url }, 404);
    });
    const client = new ZettCodeClient({ baseUrl: server.url });

    await client.addModel({ model: "llama3", chat: true, temperature: 0, base_url: "http://localhost:11434/v1" });
    assert.deepEqual(sent, { model: "llama3", chat: true, temperature: 0, base_url: "http://localhost:11434/v1" });

    await client.updateModel("Fast", { temperature: null, anthropic: null, chat: true });
    assert.deepEqual(sent, { temperature: null, anthropic: null, chat: true }, "null reaches the server as null");
  });

  test("models can be added, changed and removed, and health says whether one exists", async () => {
    const model = { name: "Fast", model: "gpt-5", context_window: 128000, multimodal: false, efforts: ["low"], active: true, compact_percent: 80 };
    const server = await start((request, response) => {
      if (request.url === "/models" && request.method === "POST") {
        assert.deepEqual(JSON.parse(request.body), { model: "gpt-5", token: "sk-1", display_model: "Fast" });
        return json(response, { models: [model], current: "Fast" }, 201);
      }
      if (request.url === "/models/Fast" && request.method === "PATCH") {
        assert.deepEqual(JSON.parse(request.body), { context_window: 200000 });
        return json(response, { models: [{ ...model, context_window: 200000 }], current: "Fast" });
      }
      if (request.url === "/models/Fast" && request.method === "DELETE") {
        return json(response, { error: "invalid", message: "that is the only model; add another before removing it" }, 400);
      }
      if (request.url === "/health") {
        return json(response, { status: "ok", version: "0.1.0", workspace: "/w", ready: true, session: "s", models: 1, busy: false });
      }
      json(response, { error: "not_found", message: request.url }, 404);
    });
    const client = new ZettCodeClient({ baseUrl: server.url });

    const added = await client.addModel({ model: "gpt-5", token: "sk-1", display_model: "Fast" });
    assert.equal(added.current, "Fast");
    assert.equal((await client.updateModel("Fast", { context_window: 200000 })).models[0]?.context_window, 200000);
    await assert.rejects(client.removeModel("Fast"), (error: unknown) => {
      assert.ok(error instanceof ZettCodeError);
      assert.equal(error.code, "invalid");
      return true;
    });
    const health = await client.health();
    assert.equal(health.ready, true);
    assert.equal(health.session, "s");
    assert.equal(health.models, 1);
  });

  test("mentions, the usage ledger, session stats, self-compaction and doctor are all reachable", async () => {
    const server = await start((request, response) => {
      if (request.url === "/mentions?query=cli&limit=5") {
        return json(response, { mentions: [{ token: "@src/cli.py", kind: "file", name: "src/cli.py", description: "4 KB" }] });
      }
      if (request.url === "/usage/ledger") {
        return json(response, {
          sessions: [],
          models: [],
          days: [],
          total: { requests: 1, input_tokens: 10, output_tokens: 2, cache_read_tokens: 0, reasoning_tokens: 0, total_tokens: 12, cache_share: 0 },
        });
      }
      if (request.url === "/sessions/stats?ids=a%2Cb") {
        return json(response, { stats: [{ id: "a", entries: 4, requests: 2, input_tokens: 10, output_tokens: 2, cache_read_tokens: 0, reasoning_tokens: 0, total_tokens: 12, cache_share: 0 }] });
      }
      if (request.url === "/sessions/current/stats") {
        return json(response, { id: "a", entries: 1, requests: 1, input_tokens: 5, output_tokens: 1, cache_read_tokens: 0, reasoning_tokens: 0, total_tokens: 6, cache_share: null });
      }
      if (request.url === "/sessions/current/self-compaction") {
        if (request.method === "PUT") {
          assert.deepEqual(JSON.parse(request.body), { choice: true });
          return json(response, { choice: true, effective: true });
        }
        return json(response, { choice: null, effective: false });
      }
      if (request.url === "/doctor") {
        assert.deepEqual(JSON.parse(request.body), { timeout: 7 });
        return json(response, { checks: [{ model: "m", model_id: "m", ok: true, seconds: 0.4, detail: "ok", input_tokens: 1, output_tokens: 1 }] });
      }
      json(response, { error: "not_found", message: request.url }, 404);
    });
    const client = new ZettCodeClient({ baseUrl: server.url });

    assert.equal((await client.mentions("cli", 5))[0]?.name, "src/cli.py");
    assert.equal((await client.usageLedger()).total.total_tokens, 12);
    assert.deepEqual((await client.sessionStats(["a", "b"])).map((item) => item.id), ["a"]);
    assert.equal((await client.sessionStats())[0]?.id, "a");
    assert.deepEqual(await client.sessionStats([]), []);
    assert.deepEqual(await client.selfCompaction(), { choice: null, effective: false });
    assert.deepEqual(await client.setSelfCompaction(true), { choice: true, effective: true });
    assert.equal((await client.doctor(7))[0]?.ok, true);
  });

  test("an HTML answer is returned as text, not parsed as JSON", async () => {
    const server = await start((_request, response) => {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end("<html>the conversation</html>");
    });

    assert.match(await new ZettCodeClient({ baseUrl: server.url }).exportSession(), /the conversation/);
  });
});

describe("a prompt", () => {
  test("streams its frames, answers an approval from the handler, and resolves the result", async () => {
    let open: ServerResponse | undefined;
    let body: unknown;
    const server = await start((request, response) => {
      if (request.url === "/prompts") {
        body = JSON.parse(request.body);
        open = response;
        stream(response);
        response.write(frame("event", { type: "text_delta", text: "Hello" }));
        response.write(
          frame("event", { type: "approval_requested", call_id: "call-1", command: "pytest -q", approved: null }),
        );
        return;
      }
      if (request.url === "/runs/approvals") {
        assert.deepEqual(JSON.parse(request.body), { call_id: "call-1", approve: true, remember: false });
        json(response, { resolved: true });
        open?.write(frame("event", { type: "text_delta", text: " again" }));
        open?.end(frame("result", result));
        return;
      }
      json(response, { error: "not_found", message: request.url }, 404);
    });
    const client = new ZettCodeClient({ baseUrl: server.url });
    const text: string[] = [];
    let asked: { command: string } | undefined;

    const run = client.prompt("fix it", {
      approvals: { mode: "ask", commands: [] },
      questions: "ask",
      answerTimeout: 12,
      onApproval: (request) => {
        asked = request;
        return true;
      },
    });
    const finished = await run.result;
    for await (const item of run) {
      const event = eventOf(item);
      if (event?.type === "text_delta") {
        text.push(event.text);
      }
    }

    assert.equal(finished.text, "done");
    assert.deepEqual(text, ["Hello", " again"]);
    assert.equal(asked?.command, "pytest -q");
    assert.deepEqual(body, {
      text: "fix it",
      approvals: { mode: "ask", commands: [] },
      questions: "ask",
      answer_timeout: 12,
    });
  });

  test("posts the answers to questions from the handler", async () => {
    let open: ServerResponse | undefined;
    const server = await start((request, response) => {
      if (request.url === "/prompts") {
        open = response;
        stream(response);
        response.write(
          frame("event", {
            type: "question_asked",
            call_id: "q1",
            question: "Which database?",
            options: ["sqlite", "postgres"],
            allow_multiple: false,
            answered: false,
          }),
        );
        return;
      }
      if (request.url === "/runs/questions") {
        assert.deepEqual(JSON.parse(request.body), { call_id: "q1", answer: "sqlite" });
        json(response, { resolved: true });
        open?.end(frame("result", result));
        return;
      }
      json(response, { error: "not_found", message: request.url }, 404);
    });
    const client = new ZettCodeClient({ baseUrl: server.url });
    let seen: string | undefined;

    const run = client.prompt("build it", {
      questions: "ask",
      onQuestion: (request) => {
        seen = request.question;
        return "sqlite";
      },
    });

    assert.equal((await run.result).text, "done");
    assert.equal(seen, "Which database?");
  });

  test("a question answered with null declines it", async () => {
    let open: ServerResponse | undefined;
    const server = await start((request, response) => {
      if (request.url === "/prompts") {
        open = response;
        stream(response);
        response.write(
          frame("event", { type: "question_asked", call_id: "q2", question: "Sure?", options: [], allow_multiple: false, answered: false }),
        );
        return;
      }
      if (request.url === "/runs/questions") {
        assert.deepEqual(JSON.parse(request.body), { call_id: "q2", answer: null });
        json(response, { resolved: true });
        open?.end(frame("cancelled", { type: "cancelled" }));
        return;
      }
      json(response, { error: "not_found", message: request.url }, 404);
    });
    const run = new ZettCodeClient({ baseUrl: server.url }).prompt("go", { questions: "ask", onQuestion: () => null });

    await assert.rejects(run.result, RunCancelledError);
  });

  test("a side question streams its answer from the ask endpoint and sends the question", async () => {
    let seen: { url?: string; body?: unknown } = {};
    const server = await start((request, response) => {
      seen = { url: request.url, body: JSON.parse(request.body) };
      stream(response);
      response.write(frame("event", { type: "text_delta", text: "about " }));
      setTimeout(() => {
        response.write(frame("event", { type: "text_delta", text: "pagers" }));
        response.end(frame("result", { ...result, text: "about pagers" }));
      }, 5);
    });
    const run = new ZettCodeClient({ baseUrl: server.url }).askStream("pagers", 60);
    const pieces: string[] = [];
    for await (const item of run) {
      const event = eventOf(item);
      if (event?.type === "text_delta") {
        pieces.push(event.text);
      }
    }

    assert.deepEqual(pieces, ["about ", "pagers"], "the answer arrives in pieces");
    assert.equal((await run.result).text, "about pagers");
    assert.equal(seen.url, "/sessions/current/ask/stream");
    assert.deepEqual(seen.body, { question: "pagers", timeout: 60 });
  });

  test("parses frames split across chunks and resolves the result", async () => {
    const server = await start((_request, response) => {
      stream(response);
      const body =
        frame("event", { type: "text_delta", text: "one" }) +
        frame("event", { type: "text_delta", text: "two" }) +
        frame("result", result);
      response.write(body.slice(0, 7));
      setTimeout(() => {
        response.write(body.slice(7, 41));
        setTimeout(() => {
          response.write(body.slice(41));
          response.end();
        }, 5);
      }, 5);
    });
    const client = new ZettCodeClient({ baseUrl: server.url });

    const seen: string[] = [];
    const run = client.prompt("go");
    for await (const item of run) {
      const event = eventOf(item);
      if (event?.type === "text_delta") {
        seen.push(event.text);
      }
    }

    assert.deepEqual(seen, ["one", "two"]);
    assert.equal((await run.result).text, "done");
  });

  test("an error frame rejects the result with RunFailedError", async () => {
    const server = await start((_request, response) => {
      stream(response);
      response.write(frame("error", { error: "run", message: "the provider went away" }));
      response.end();
    });
    const run = new ZettCodeClient({ baseUrl: server.url }).prompt("go");

    await assert.rejects(run.result, (error: unknown) => {
      assert.ok(error instanceof RunFailedError);
      assert.equal(error.code, "run");
      assert.match(error.message, /provider went away/);
      return true;
    });
  });

  test("an HTTP failure before the stream rejects with the code the server gave", async () => {
    const server = await start((_request, response) =>
      json(response, { error: "busy", message: "A run is already in progress" }, 409),
    );
    const run = new ZettCodeClient({ baseUrl: server.url }).prompt("second");

    await assert.rejects(run.result, (error: unknown) => {
      assert.ok(error instanceof ZettCodeError);
      assert.equal(error.code, "busy");
      assert.equal(error.status, 409);
      return true;
    });
  });

  test("cancel posts to the run and the stream ends as cancelled", async () => {
    let open: ServerResponse | undefined;
    const server = await start((request, response) => {
      if (request.url === "/prompts") {
        open = response;
        stream(response);
        response.write(frame("event", { type: "text_delta", text: "working" }));
        return;
      }
      if (request.url === "/runs/cancel") {
        json(response, { cancelled: true });
        open?.end(frame("cancelled", { type: "cancelled" }));
        return;
      }
      json(response, { error: "not_found", message: request.url }, 404);
    });
    const run = new ZettCodeClient({ baseUrl: server.url }).prompt("long");
    await new Promise((resolve) => setTimeout(resolve, 50));

    assert.equal(await run.cancel(), true);
    await assert.rejects(run.result, RunCancelledError);
  });

  test("aborting the signal closes the connection", async () => {
    const controller = new AbortController();
    const server = await start((_request, response) => {
      stream(response);
      response.write(frame("event", { type: "text_delta", text: "working" }));
    });
    const run = new ZettCodeClient({ baseUrl: server.url }).prompt("long", { signal: controller.signal });
    await new Promise((resolve) => setTimeout(resolve, 50));

    controller.abort();

    await assert.rejects(run.result);
  });

  test("steering and answering go to the run endpoints", async () => {
    const server = await start((request, response) => {
      if (request.url === "/runs/steer") {
        assert.deepEqual(JSON.parse(request.body), { text: "also the docs" });
        return json(response, { steered: true });
      }
      if (request.url === "/runs/approvals") {
        assert.deepEqual(JSON.parse(request.body), { call_id: "c", approve: false, remember: true });
        return json(response, { resolved: false });
      }
      if (request.url === "/runs/questions") {
        assert.deepEqual(JSON.parse(request.body), { call_id: "q", answer: null });
        return json(response, { resolved: true });
      }
      if (request.url === "/runs/current") return json(response, { running: false, pending: null });
      if (request.url === "/runs/resume") {
        stream(response);
        response.end(frame("result", result));
        return;
      }
      json(response, { error: "not_found", message: request.url }, 404);
    });
    const client = new ZettCodeClient({ baseUrl: server.url });

    assert.equal(await client.steer("also the docs"), true);
    assert.equal(await client.approve("c", false, true), false);
    assert.equal(await client.answer("q", null), true);
    assert.deepEqual(await client.runState(), { running: false, pending: null });
    assert.equal((await client.resume().result).text, "done");
  });
});

describe("helpers", () => {
  test("run options are translated to the wire names and the unset ones are left out", () => {
    assert.deepEqual(
      wireOptions({
        approvals: { mode: "commands", commands: ["pytest"] },
        questions: "ask",
        timeout: 30,
        answerTimeout: 5,
        keepEvents: true,
        onEvent: () => undefined,
      }),
      {
        approvals: { mode: "commands", commands: ["pytest"] },
        questions: "ask",
        timeout: 30,
        answer_timeout: 5,
        keep_events: true,
      },
    );
    assert.deepEqual(wireOptions({ approvals: {} }), { approvals: { mode: "deny" } });
    assert.deepEqual(wireOptions({}), {});
  });

  test("a frame is parsed by its fields, with comments ignored and data joined", () => {
    assert.deepEqual(parseBlock(': keepalive\nevent: event\ndata: {"a":\ndata: 1}'), {
      event: "event",
      data: '{"a":\n1}',
    });
    assert.equal(parseBlock(": only a comment"), null);
    assert.deepEqual(parseBlock("data: hello"), { event: "message", data: "hello" });
  });

  test("the SSE reader ends on the last frame without a trailing blank line", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('event: event\ndata: {"type":"notice","text":"hi"}'));
        controller.close();
      },
    });
    const frames: StreamFrame[] = [];
    for await (const item of sseFrames(body)) {
      frames.push(item);
    }
    assert.deepEqual(frames, [{ event: "event", data: { type: "notice", text: "hi" } }]);
  });

  test("a usage total is input plus output", () => {
    assert.equal(totalTokens(usage), 12);
  });
});
