import assert from "node:assert/strict";
import { mock, test } from "node:test";
import { longPress, PRESS_MS, PRESS_SLOP } from "../src/lib/press";

const at = (x: number, y: number, pointerType = "touch", isPrimary = true) => ({ clientX: x, clientY: y, pointerType, isPrimary }) as PointerEvent;

test("a touch held still opens the menu once, after the delay", () => {
  mock.timers.enable({ apis: ["setTimeout", "Date"] });
  let opened = 0;
  const press = longPress(() => (opened += 1), () => Date.now());
  press.down(at(10, 10));
  mock.timers.tick(PRESS_MS - 1);
  assert.equal(opened, 0);
  mock.timers.tick(1);
  assert.equal(opened, 1);
  assert.ok(press.recent(), "the contextmenu that follows is not a second menu");
  mock.timers.tick(1500);
  assert.ok(!press.recent());
  mock.timers.reset();
});

test("a finger that moves, lifts or is cancelled opens nothing", () => {
  mock.timers.enable({ apis: ["setTimeout", "Date"] });
  let opened = 0;
  const press = longPress(() => (opened += 1), () => Date.now());
  press.down(at(0, 0));
  press.move(at(PRESS_SLOP + 1, 0));
  mock.timers.tick(PRESS_MS * 2);
  press.down(at(0, 0));
  press.move(at(3, 3));
  press.end();
  mock.timers.tick(PRESS_MS * 2);
  assert.equal(opened, 0);
  mock.timers.reset();
});

test("a mouse, a pen and a second finger are not a long press", () => {
  mock.timers.enable({ apis: ["setTimeout", "Date"] });
  let opened = 0;
  const press = longPress(() => (opened += 1), () => Date.now());
  press.down(at(0, 0, "mouse"));
  press.down(at(0, 0, "pen"));
  press.down(at(0, 0, "touch", false));
  mock.timers.tick(PRESS_MS * 2);
  assert.equal(opened, 0);
  mock.timers.reset();
});
