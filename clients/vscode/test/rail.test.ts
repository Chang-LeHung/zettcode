import assert from "node:assert/strict";
import test from "node:test";

import { announcement, createTurn, type Turn } from "../src/core/state.js";
import { open } from "./harness.js";

const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

function said(id: string, prompt: string): Turn {
  const turn = createTurn(prompt, [], 1, id);
  turn.status = "done";
  turn.finishedAt = 2;
  return turn;
}

type Ui = Awaited<ReturnType<typeof open>>;

/** jsdom has no layout, so give the rail and the messages a fixed one: ticks 10px apart from y=100. */
function layout(ui: Ui, tops: Record<string, number>): { scrolled: { id: string | undefined; options: unknown }[] } {
  const scrolled: { id: string | undefined; options: unknown }[] = [];
  const proto = ui.window.HTMLElement.prototype as unknown as Record<string, unknown>;
  const rect = (top: number, height = 0) => ({ top, bottom: top + height, left: 0, right: 0, width: 0, height, x: 0, y: top });
  proto.getBoundingClientRect = function (this: HTMLElement) {
    if (this.classList.contains("rail-tick")) {
      const index = Array.from(this.parentElement?.querySelectorAll(".rail-tick") ?? []).indexOf(this);
      return rect(100 + index * 10, 2);
    }
    if (this.classList.contains("rail-nav")) {
      return rect(90, 200);
    }
    const id = this.dataset?.id;
    return id !== undefined && id in tops ? rect(tops[id]!) : rect(0);
  };
  proto.scrollIntoView = function (this: HTMLElement, options: unknown) {
    scrolled.push({ id: this.dataset?.id, options });
  };
  return { scrolled };
}

const four = (): Turn[] => [
  said("turn-a", "Explain this codebase"),
  said("turn-b", "Fix the failing tests"),
  said("turn-c", "Add a retry with backoff"),
  said("turn-d", "Thanks"),
];

async function move(ui: Ui, y: number): Promise<void> {
  const rail = ui.one(".rail-nav");
  assert.ok(rail);
  rail.dispatchEvent(new ui.window.MouseEvent("pointermove", { clientY: y, bubbles: true }));
  await wait(0);
}

test("a tick for each message you sent, and none for what you did not", async () => {
  const side = said("turn-side", "/btw what is this");
  side.aside = true;
  const empty = said("turn-resumed", "");
  const ui = await open([
    said("turn-a", "first"),
    announcement("Model changed from a to b.", 3, "turn-announce-1"),
    side,
    empty,
    said("turn-b", "second"),
  ]);
  assert.equal(ui.all(".rail-nav .rail-tick").length, 2);
  assert.equal(ui.one(".rail-nav")?.getAttribute("aria-label"), "Jump to one of your messages");
});

test("with a single message there is nothing to jump between, so there is no rail", async () => {
  assert.equal((await open([said("turn-a", "only one")])).one(".rail-nav"), null);
  assert.equal((await open([])).one(".rail-nav"), null);
});

test("ticks swell toward the pointer like a dock, and the nearest shows its message", async () => {
  const ui = await open(four());
  layout(ui, {});
  await move(ui, 120);

  const k = ui.all<HTMLElement>(".rail-nav .rail-tick").map((tick) => Number(tick.style.getPropertyValue("--k")));
  assert.equal(k.length, 4);
  assert.ok(k[2]! > 0.99, "the nearest swells fully");
  // From the pointer at y=120 the ticks (centred at 101, 111, 121, 131) are 19, 9, 1 and 11 away: nearer swells more.
  assert.ok(k[2]! > k[1]! && k[1]! > k[3]! && k[3]! > k[0]!, `neighbours swell less the farther they are: ${k.join(", ")}`);
  assert.ok(ui.one(".rail-nav .rail-tick.hover") === ui.all(".rail-nav .rail-tick")[2]);

  const tip = ui.one(".rail-tip");
  assert.ok(tip, "a preview opens");
  assert.equal(tip.querySelector(".rail-tip-count")?.textContent, "3 / 4");
  assert.equal(tip.querySelector(".rail-tip-text")?.textContent, "Add a retry with backoff");

  await move(ui, 99);
  assert.equal(ui.one(".rail-tip .rail-tip-text")?.textContent, "Explain this codebase");
});

test("leaving the rail puts the ticks back and closes the preview", async () => {
  const ui = await open(four());
  layout(ui, {});
  await move(ui, 120);
  ui.one(".rail-nav")!.dispatchEvent(new ui.window.MouseEvent("pointerleave", { bubbles: true }));
  await wait(0);
  assert.equal(ui.one(".rail-tip"), null);
  assert.equal(ui.one(".rail-nav .rail-tick.hover"), null);
  for (const tick of ui.all<HTMLElement>(".rail-nav .rail-tick")) {
    assert.equal(Number(tick.style.getPropertyValue("--k") || 0), 0);
  }
});

test("clicking a tick scrolls to that message and makes it flash once", async () => {
  const ui = await open(four());
  const { scrolled } = layout(ui, {});
  await move(ui, 131);
  ui.one(".rail-nav")!.dispatchEvent(new ui.window.MouseEvent("click", { clientY: 131, bubbles: true }));
  await wait(40);

  assert.equal(scrolled.length, 1);
  assert.equal(scrolled[0]?.id, "turn-d");
  assert.equal((scrolled[0]?.options as { block: string }).block, "start");
  assert.equal((scrolled[0]?.options as { behavior: string }).behavior, "smooth");
  assert.ok(ui.one('[data-id="turn-d"] .user-bubble.flash'), "the message it landed on flashes");
  assert.equal(ui.all(".user-bubble.flash").length, 1);
  assert.ok(ui.one(".rail-nav .rail-tick.active") === ui.all(".rail-nav .rail-tick")[3]);
});

test("the tick for the message you are at is marked, and follows the scrolling", async () => {
  const ui = await open(four());
  layout(ui, { "turn-a": -900, "turn-b": -400, "turn-c": -20, "turn-d": 500 });
  ui.one("#transcript")!.dispatchEvent(new ui.window.Event("scroll"));
  await wait(60);
  const active = () => ui.all(".rail-nav .rail-tick").findIndex((tick) => tick.classList.contains("active"));
  assert.equal(active(), 2, "the last message that has reached the top of the view");

  layout(ui, { "turn-a": -20, "turn-b": 300, "turn-c": 600, "turn-d": 900 });
  ui.one("#transcript")!.dispatchEvent(new ui.window.Event("scroll"));
  await wait(60);
  assert.equal(active(), 0);
});

test("the arrow keys step between messages, and Home and End go to the ends", async () => {
  const ui = await open(four());
  const { scrolled } = layout(ui, { "turn-a": -900, "turn-b": -400, "turn-c": -20, "turn-d": 500 });
  const rail = ui.one(".rail-nav")!;
  ui.one("#transcript")!.dispatchEvent(new ui.window.Event("scroll"));
  await wait(60);

  const key = async (name: string) => {
    rail.dispatchEvent(new ui.window.KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true }));
    await wait(40);
  };
  await key("ArrowUp");
  await key("ArrowUp");
  await key("ArrowUp");
  await key("ArrowDown");
  await key("End");
  await key("Home");
  assert.deepEqual(
    scrolled.map((item) => item.id),
    ["turn-b", "turn-a", "turn-a", "turn-b", "turn-d", "turn-a"],
    "up from the third, clamped at the first, then down, then the ends",
  );
});

test("a side question, a command's row or an announcement is not something the rail leads to", async () => {
  const ui = await open([said("turn-a", "first"), announcement("Reasoning effort changed from low to high.", 3, "turn-announce-1"), said("turn-b", "second")]);
  const { scrolled } = layout(ui, {});
  assert.equal(ui.all(".rail-nav .rail-tick").length, 2);
  await move(ui, 111);
  ui.one(".rail-nav")!.dispatchEvent(new ui.window.MouseEvent("click", { clientY: 111, bubbles: true }));
  await wait(40);
  assert.equal(scrolled[0]?.id, "turn-b");
});
