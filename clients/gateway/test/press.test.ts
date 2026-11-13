import assert from "node:assert/strict";
import { mock, test } from "node:test";
import { longPress, PRESS_MS, PRESS_SLOP } from "../src/lib/press";

const at = (x: number, y: number, pointerType = "touch", isPrimary = true) => ({ clientX: x, clientY: y, pointerType, isPrimary }) as PointerEvent;

test("a touch held still opens the menu once, after the delay, and the contextmenu after it is known to be a duplicate", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  let opened = 0;
  const press = longPress(() => (opened += 1));
  press.down(at(10, 10));
  mock.timers.tick(PRESS_MS - 1);
  assert.equal(opened, 0);
  mock.timers.tick(1);
  assert.equal(opened, 1);
  assert.ok(press.recent());
  mock.timers.tick(60_000);
  assert.ok(press.recent(), "a contextmenu that arrives long after is still the same press");
  press.end();
  assert.ok(press.recent(), "lifting the finger does not make the late contextmenu a new request");
  press.down(at(0, 0, "mouse"));
  assert.ok(!press.recent(), "the next pointer, a right click included, starts afresh");
  mock.timers.reset();
});

test("a finger that moves, lifts or is cancelled opens nothing", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  let opened = 0;
  const press = longPress(() => (opened += 1));
  press.down(at(0, 0));
  press.move(at(PRESS_SLOP + 1, 0));
  mock.timers.tick(PRESS_MS * 2);
  press.down(at(0, 0));
  press.move(at(3, 3));
  press.end();
  mock.timers.tick(PRESS_MS * 2);
  assert.equal(opened, 0);
  assert.ok(!press.recent());
  mock.timers.reset();
});

test("a mouse, a pen and a second finger are not a long press", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  let opened = 0;
  const press = longPress(() => (opened += 1));
  press.down(at(0, 0, "mouse"));
  press.down(at(0, 0, "pen"));
  press.down(at(0, 0, "touch", false));
  mock.timers.tick(PRESS_MS * 2);
  assert.equal(opened, 0);
  mock.timers.reset();
});

test("the system starting a text selection under the finger cancels the press", async () => {
  const { JSDOM } = await import("jsdom");
  const dom = new JSDOM("", { url: "http://localhost/" });
  Object.assign(globalThis, { document: dom.window.document });
  try {
    mock.timers.enable({ apis: ["setTimeout"] });
    let opened = 0;
    const press = longPress(() => (opened += 1));
    press.down(at(5, 5));
    mock.timers.tick(PRESS_MS / 2);
    dom.window.document.dispatchEvent(new dom.window.Event("selectionchange"));
    mock.timers.tick(PRESS_MS);
    assert.equal(opened, 0);
    assert.ok(!press.recent());
    mock.timers.reset();
  } finally {
    delete (globalThis as { document?: unknown }).document;
  }
});
