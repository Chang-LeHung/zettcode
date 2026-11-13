import "./dom-setup";
import assert from "node:assert/strict";
import { test } from "node:test";
import { markMentions } from "../src/lib/mentions";

const md = (html: string): HTMLElement => {
  const el = document.createElement("div");
  el.innerHTML = html;
  return el;
};

test("a member's handle becomes a mention, anywhere in the text, and what is around it is kept", () => {
  const root = md("<p>hi @Reviewer, and (@测试员) please; also @planner-2!</p>");
  assert.equal(markMentions(root, ["reviewer", "测试员", "planner-2"]), 3);
  assert.deepEqual([...root.querySelectorAll(".mention")].map((e) => e.textContent), ["@Reviewer", "@测试员", "@planner-2"]);
  assert.equal(root.textContent, "hi @Reviewer, and (@测试员) please; also @planner-2!");
});

test("a mention after any punctuation counts, in any script", () => {
  const root = md("<p>好的，@planner。@reviewer：请看；@tester！「@docs」 and e-mail bob@docs.dev</p>");
  assert.equal(markMentions(root, ["planner", "reviewer", "tester", "docs"]), 4);
  assert.equal(root.textContent, "好的，@planner。@reviewer：请看；@tester！「@docs」 and e-mail bob@docs.dev");
});

test("only a handle from the list counts, and a word that merely follows an @ is text", () => {
  const root = md("<p>mail bob@reviewer.dev or @stranger or @reviewerx</p>");
  assert.equal(markMentions(root, ["reviewer"]), 0);
  assert.equal(root.querySelector(".mention"), null);
});

test("code and links are left alone, and marking twice changes nothing", () => {
  const root = md('<p><code>@reviewer</code> <a href="#">@reviewer</a> @reviewer</p>');
  assert.equal(markMentions(root, ["reviewer"]), 1);
  assert.equal(markMentions(root, ["reviewer"]), 0);
  assert.equal(root.querySelectorAll(".mention").length, 1);
});

test("the reader's own handle is marked as theirs", () => {
  const root = md("<p>@alice and @bob</p>");
  markMentions(root, ["alice", "bob"], "Bob");
  assert.deepEqual([...root.querySelectorAll(".mention")].map((e) => e.className), ["mention", "mention me"]);
});

test("nothing to match means nothing is touched", () => {
  const root = md("<p>@alice</p>");
  assert.equal(markMentions(root, []), 0);
  assert.equal(root.innerHTML, "<p>@alice</p>");
});
