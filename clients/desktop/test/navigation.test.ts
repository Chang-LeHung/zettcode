import assert from "node:assert/strict";
import { test } from "node:test";
import { decide, opensExternally } from "../src/navigation";

const LIST = "app://-/index.html";

test("the list may open any web server, and nothing that is not one", () => {
  assert.equal(decide(LIST, "http://127.0.0.1:8765/"), "allow");
  assert.equal(decide(LIST, "https://gw.example/"), "allow");
  assert.equal(decide(LIST, "file:///etc/passwd"), "deny");
  assert.equal(decide(LIST, "javascript:alert(1)"), "deny");
  assert.equal(decide(LIST, "not a url"), "deny");
});

test("a server's page stays on its origin and sends other links to the system browser", () => {
  assert.equal(decide("http://127.0.0.1:8765/", "http://127.0.0.1:8765/other"), "allow");
  assert.equal(decide("http://127.0.0.1:8765/", "http://127.0.0.1:9999/"), "external");
  assert.equal(decide("https://gw.example/", "https://evil.example/"), "external");
  assert.equal(decide("https://gw.example/", "file:///etc/passwd"), "deny");
});

test("a page can always go back to the list", () => {
  assert.equal(decide("https://gw.example/", "app://-/index.html#choose"), "allow");
});

test("only web addresses open outside the window", () => {
  assert.equal(opensExternally("https://example.com"), true);
  assert.equal(opensExternally("http://localhost:1"), true);
  assert.equal(opensExternally("file:///x"), false);
  assert.equal(opensExternally("mailto:a@b.c"), false);
});
