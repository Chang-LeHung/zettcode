import "./dom-setup";
import assert from "node:assert/strict";
import { test } from "node:test";
import { apiUrl, authorization, connection, configure, normalizeBaseUrl, tokenProtocol } from "../src/api/connection";
import { socketProtocols, socketUrl } from "../src/api/events";
import { net, request } from "../src/api/http";
import { picturePath, pictureUrl } from "../src/api/pictures";
import { setLanguage, t } from "../src/i18n";
import { closeSheet, openSheet, setSheetBusy, sheets } from "../src/stores/ui";
import { makeProfile, parseStored } from "../src/lib/servers";
import {
  addServer,
  connectServer,
  disconnectServer,
  loadServers,
  removeServer,
  servers,
  testConnection,
  updateServer,
} from "../src/stores/servers";

test("an address is the gateway's origin, and a path is refused rather than silently dropped", () => {
  assert.equal(normalizeBaseUrl(" http://127.0.0.1:8765/ "), "http://127.0.0.1:8765");
  assert.equal(normalizeBaseUrl("https://gateway.example"), "https://gateway.example");
  assert.equal(normalizeBaseUrl("http://gateway.example:8765//"), "http://gateway.example:8765");
  for (const bad of [
    "gateway.example",
    "ftp://gateway.example",
    "https://gateway.example/gateway",
    "https://gateway.example?x=1",
    "https://gateway.example#token=x",
    "https://user@gateway.example",
  ]) {
    assert.throws(() => normalizeBaseUrl(bad), bad);
  }
});

test("the page calls its own address, and an app calls the server it chose", () => {
  const before = { ...connection };
  configure({ baseUrl: "", token: "" });
  assert.equal(apiUrl("/api/threads"), "/api/threads");
  configure({ baseUrl: "http://127.0.0.1:8765", token: " s3cret " });
  assert.equal(apiUrl("/api/threads"), "http://127.0.0.1:8765/api/threads");
  assert.deepEqual(authorization(), { authorization: "Bearer  s3cret " });
  configure(before);
});

test("a request carries the chosen server and the token; the page keeps its own address and cookie", async () => {
  const fetchBefore = globalThis.fetch;
  const seen: Array<{ url: string; init: RequestInit }> = [];
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    seen.push({ url: String(url), init: init ?? {} });
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
  try {
    configure({ baseUrl: "http://127.0.0.1:8765", token: "t" });
    await request("POST", "/api/threads/x/read", {});
    assert.equal(seen[0]?.url, "http://127.0.0.1:8765/api/threads/x/read");
    assert.equal(seen[0]?.init.credentials, "omit");
    assert.equal(new Headers(seen[0]?.init.headers).get("authorization"), "Bearer t");
    assert.equal(new Headers(seen[0]?.init.headers).get("content-type"), "application/json");

    configure({ baseUrl: "", token: "" });
    await request("GET", "/api/session");
    assert.equal(seen[1]?.url, "/api/session");
    assert.equal(seen[1]?.init.credentials, "same-origin");
    assert.equal(new Headers(seen[1]?.init.headers).get("authorization"), null);
  } finally {
    globalThis.fetch = fetchBefore;
    configure({ baseUrl: "", token: "" });
  }
});

test("the in-flight counter returns to zero whether a request answers, fails, or never reaches the gateway", async () => {
  const fetchBefore = globalThis.fetch;
  try {
    globalThis.fetch = (async () => new Response("{}", { status: 200 })) as typeof fetch;
    await request("GET", "/api/threads");
    assert.equal(net.active, 0);

    globalThis.fetch = (async () => new Response(JSON.stringify({ error: { message: "no" } }), { status: 500 })) as typeof fetch;
    await assert.rejects(request("GET", "/api/threads"));
    assert.equal(net.active, 0);

    globalThis.fetch = (async () => {
      throw new TypeError("offline");
    }) as typeof fetch;
    const pending = request("GET", "/api/threads");
    assert.equal(net.active, 1);
    await assert.rejects(pending);
    assert.equal(net.active, 0);
  } finally {
    globalThis.fetch = fetchBefore;
  }
});

test("a request that never answers is given up on, and a write is then marked as possibly delivered", async () => {
  const fetchBefore = globalThis.fetch;
  const timers = globalThis.setTimeout;
  try {
    globalThis.fetch = ((_url: unknown, init?: RequestInit) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      })) as typeof fetch;
    // Fire the request's own timer at once instead of waiting two minutes.
    globalThis.setTimeout = ((handler: () => void) => timers(handler, 0)) as typeof setTimeout;
    await assert.rejects(request("POST", "/api/threads/x/send", {}), (error: unknown) => {
      const failure = error as { code: string; body: { uncertain?: boolean } };
      return failure.code === "timeout" && failure.body.uncertain === true;
    });
    await assert.rejects(request("GET", "/api/threads"), (error: unknown) => (error as { body: { uncertain?: boolean } }).body.uncertain === false);
    assert.equal(net.active, 0);
  } finally {
    globalThis.fetch = fetchBefore;
    globalThis.setTimeout = timers;
  }
});

test("a sheet with an action under way is not dismissed, but answers for itself", async () => {
  const answer = openSheet<boolean>("Sure?", {} as never);
  const id = sheets[sheets.length - 1]!.id;
  setSheetBusy(id, true);
  closeSheet(id);
  assert.ok(sheets.some((entry) => entry.id === id), "a dismissal is refused while it is busy");
  closeSheet(id, true);
  assert.equal(await answer, true);
  assert.ok(!sheets.some((entry) => entry.id === id));

  const dismissed = openSheet<boolean>("Sure?", {} as never);
  closeSheet(sheets[sheets.length - 1]!.id);
  assert.equal(await dismissed, undefined);
});

test("the socket names the chosen server and offers the token as a protocol", () => {
  try {
    configure({ baseUrl: "http://127.0.0.1:8765", token: "a b" });
    assert.equal(socketUrl(), "ws://127.0.0.1:8765/api/events");
    assert.deepEqual(socketProtocols(), ["zettcode", tokenProtocol("a b")]);

    configure({ baseUrl: "https://host.example", token: "" });
    assert.equal(socketUrl(), "wss://host.example/api/events");
    assert.deepEqual(socketProtocols(), []);
  } finally {
    configure({ baseUrl: "", token: "" });
  }
});

test("a token is offered as a protocol name a browser accepts", () => {
  const protocol = tokenProtocol("a token with spaces/and+symbols");
  assert.match(protocol, /^zettcode\.token\.[A-Za-z0-9_-]+$/);
  const encoded = protocol.slice("zettcode.token.".length);
  const decoded = Buffer.from(encoded.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString();
  assert.equal(decoded, "a token with spaces/and+symbols");
});

test("a stored list keeps usable servers only, and forgets an active id it no longer holds", () => {
  const stored = parseStored(
    JSON.stringify({
      servers: [
        { id: "a", name: "one", url: "http://127.0.0.1:8765", token: "t" },
        { id: "b", name: "two", url: "not an address", token: "t" },
        { id: "a", name: "duplicate", url: "https://two.example", token: "t" },
        { id: "c", name: "three", url: "https://three.example", token: 3 },
        { id: "d", name: "four", url: "https://four.example", token: "t" },
      ],
      active: "b",
    }),
  );

  assert.deepEqual(
    stored.servers.map((server) => server.id),
    ["a", "d"],
  );
  assert.equal(stored.active, "", "the active server was dropped with its bad address");
  assert.deepEqual(parseStored("not json"), {
    servers: [],
    active: "",
    error: "unreadable",
  });
});

test("a profile is named by its host when no name was typed, and needs an address and a token", () => {
  const made = makeProfile({ name: "  ", url: "http://127.0.0.1:8765/", token: " secret " });
  assert.deepEqual({ ...made, id: "" }, { id: "", name: "127.0.0.1:8765", url: "http://127.0.0.1:8765", token: "secret" });
  assert.throws(() => makeProfile({ name: "", url: "http://127.0.0.1:8765", token: " " }), /token is required/);
  assert.throws(() => makeProfile({ name: "", url: "nope", token: "t" }));
});

test("a save that fails while switching leaves the old server and the API where they were", async () => {
  const old = { id: "old", name: "Old", url: "http://old.example", token: "old" };
  try {
    servers.mode = "app";
    servers.list = [old];
    servers.active = old;
    servers.bridge = {
      loadServers: async () => ({ servers: [], active: "" }),
      saveServers: async () => {
        throw new Error("disk");
      },
    };
    configure({ baseUrl: "http://old.example", token: "old" });

    await assert.rejects(
      connectServer({ id: "new", name: "New", url: "http://new.example", token: "new" }),
      /disk/,
    );

    assert.equal(servers.active?.id, "old");
    assert.equal(connection.baseUrl, "http://old.example");
  } finally {
    configure({ baseUrl: "", token: "" });
    servers.mode = "web";
    servers.active = null;
    servers.list = [];
    servers.bridge = null;
  }
});

test("every write that fails leaves the list and the API untouched", async () => {
  const old = { id: "old", name: "Old", url: "http://old.example", token: "old" };
  const failing = {
    loadServers: async () => ({ servers: [], active: "" }),
    saveServers: async () => {
      throw new Error("disk");
    },
  };
  const reset = (): void => {
    servers.mode = "app";
    servers.list = [old];
    servers.active = old;
    servers.bridge = failing;
    configure({ baseUrl: "http://old.example", token: "old" });
  };
  const actions: Array<[string, () => Promise<unknown>]> = [
    ["add", () => addServer({ name: "New", url: "http://new.example", token: "new" })],
    ["update", () => updateServer("old", { name: "Changed", url: "https://new.example", token: "new" })],
    ["remove", () => removeServer("old")],
    ["disconnect", () => disconnectServer()],
  ];
  try {
    for (const [name, action] of actions) {
      reset();
      await assert.rejects(action(), /disk/, name);
      assert.deepEqual(
        {
          active: servers.active?.id,
          list: servers.list.map((server) => server.id),
          base: connection.baseUrl,
          token: connection.token,
        },
        { active: "old", list: ["old"], base: "http://old.example", token: "old" },
        name,
      );
    }
  } finally {
    configure({ baseUrl: "", token: "" });
    servers.mode = "web";
    servers.active = null;
    servers.list = [];
    servers.bridge = null;
  }
});

test("a damaged store leaves the list empty but names the reason", async () => {
  window.__zettcodeNative = {
    loadServers: async () => ({ servers: [], active: "", error: "unreadable" }),
    saveServers: async () => undefined,
  };
  try {
    await loadServers();
    assert.equal(servers.problem, "The saved server list could not be read");
  } finally {
    window.__zettcodeNative = undefined;
    servers.mode = "web";
    servers.active = null;
    servers.list = [];
    servers.problem = "";
    servers.bridge = null;
  }
});

test("a validation message is translated where it is shown, not frozen in the pure module", () => {
  try {
    setLanguage("zh");
    assert.throws(() => normalizeBaseUrl("nope"), /Write the address/);
    assert.throws(
      () => makeProfile({ name: "", url: "http://127.0.0.1:8765", token: " " }),
      /The gateway's token is required/,
    );
    assert.equal(t("Write the address as http://host:port"), "地址请写成 http://host:port");
    assert.equal(t("The gateway's token is required"), "必须填写网关令牌");
    assert.equal(t("The saved server list could not be read"), "无法读取已保存的服务器列表");
    assert.equal(parseStored('{"servers":[],"active":"","error":"unreadable"}').error, "unreadable");
  } finally {
    setLanguage("en");
  }
});

test("the shell's list points the API at the active server, and saving it sends plain data", async () => {
  const saved: unknown[] = [];
  window.__zettcodeNative = {
    loadServers: async () => ({
      servers: [{ id: "a", name: "One", url: "http://127.0.0.1:8765", token: "t" }],
      active: "a",
    }),
    saveServers: async (state) => {
      // A Vue proxy cannot cross Electron's IPC: the real bridge would fail exactly here.
      saved.push(structuredClone(state));
    },
  };
  try {
    await loadServers();
    assert.equal(servers.mode, "app");
    assert.equal(servers.active?.id, "a");
    assert.equal(connection.baseUrl, "http://127.0.0.1:8765");
    assert.equal(connection.token, "t");

    await addServer({ name: "Two", url: "https://two.example", token: "x" });

    assert.equal(saved.length, 1);
    assert.deepEqual(saved[0], {
      servers: [
        { id: "a", name: "One", url: "http://127.0.0.1:8765", token: "t" },
        { id: servers.list[1]?.id, name: "Two", url: "https://two.example", token: "x" },
      ],
      active: "a",
    });
  } finally {
    window.__zettcodeNative = undefined;
    configure({ baseUrl: "", token: "" });
    servers.mode = "web";
    servers.active = null;
    servers.list = [];
    servers.problem = "";
    servers.bridge = null;
  }
});

test("a gateway that answers the session but fails the status is not reported as connected", async () => {
  const fetchBefore = globalThis.fetch;
  globalThis.fetch = (async (url: string | URL | Request) => {
    if (String(url).endsWith("/api/session")) {
      return new Response(JSON.stringify({ authenticated: true, open: false }), { status: 200 });
    }
    return new Response(JSON.stringify({ error: { message: "no status" } }), { status: 500 });
  }) as typeof fetch;
  try {
    const result = await testConnection("http://127.0.0.1:8765", "t");
    assert.equal(result.ok, false);
    assert.equal(result.message, "no status");
  } finally {
    globalThis.fetch = fetchBefore;
  }
});

test("an app reads a picture with its token and draws the blob; the page draws its own path", async () => {
  const before = { ...connection };
  const fetchBefore = globalThis.fetch;
  const calls: Array<{ url: string; init: RequestInit }> = [];
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    return new Response(new Blob(["picture"], { type: "image/png" }), { status: 200 });
  }) as typeof fetch;
  try {
    configure({ baseUrl: "http://127.0.0.1:8765", token: "t" });
    const path = picturePath("a/b", "c d");
    const blob = await pictureUrl(path);

    assert.match(blob, /^blob:/);
    assert.equal(calls[0]?.url, "http://127.0.0.1:8765/api/threads/a%2Fb/pictures/c%20d");
    assert.equal(new Headers(calls[0]?.init.headers).get("authorization"), "Bearer t");
    URL.revokeObjectURL(blob);

    configure(before);
    assert.equal(await pictureUrl(path), "/api/threads/a%2Fb/pictures/c%20d");
  } finally {
    globalThis.fetch = fetchBefore;
    configure(before);
  }
});
