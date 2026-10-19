import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";

/**
 * The view's styles are global: a `<style>` block in a component is not scoped, so a bare `.name` rule reaches every
 * element with that class anywhere in the view. A short, common word therefore leaks: `.live` was the status row's
 * (`display: flex`), and the thought step marking itself live was laid out beside its own label instead of under it.
 * `.tick` was the message rail's bar, and it flattened the check marks in the model menu.
 *
 * The classes below are shared on purpose: they are small primitives one component draws and another places.
 */
const SHARED = new Set([
  "step",
  "step-dot",
  "option",
  "option-copy",
  "option-desc",
  "option-list",
  "option-name",
  "dropdown-empty",
  "out",
  "out-head",
  "out-title",
  "plus",
  "minus",
  "swatch",
]);

interface Component {
  file: string;
  template: string;
  style: string;
}

async function components(): Promise<Component[]> {
  const folder = "src/webview/components";
  const names = (await readdir(folder)).filter((name) => name.endsWith(".vue"));
  const out: Component[] = [];
  for (const name of [...names.map((entry) => `${folder}/${entry}`), "src/webview/App.vue"]) {
    const text = await readFile(name, "utf8");
    const template = /<template>([\s\S]*?)<\/template>/.exec(text)?.[1] ?? "";
    const style = /<style>([\s\S]*?)<\/style>/.exec(text)?.[1] ?? "";
    out.push({ file: name, template, style });
  }
  return out;
}

/** The classes a component's template puts on an element: `class="a b"` and the keys of `:class="{ a: cond }"`. */
function used(template: string): Set<string> {
  const names = new Set<string>();
  for (const match of template.matchAll(/(?<!:)class="([^"]*)"/g)) {
    for (const name of (match[1] ?? "").split(/\s+/)) {
      if (name) {
        names.add(name);
      }
    }
  }
  for (const match of template.matchAll(/:class="\{([^}]*)\}"/g)) {
    for (const key of (match[1] ?? "").matchAll(/([a-zA-Z][\w-]*)\s*:/g)) {
      names.add(key[1] ?? "");
    }
  }
  return names;
}

/** The bare, single-class selectors a component's style defines: `.name {`, which is the ones that can leak. */
function defined(style: string): Set<string> {
  const names = new Set<string>();
  for (const match of style.matchAll(/^\.([a-zA-Z][\w-]*)\s*\{/gm)) {
    names.add(match[1] ?? "");
  }
  return names;
}

test("a class a component lays out is its own, unless it is one of the shared primitives", async () => {
  const all = await components();
  const leaks: string[] = [];
  for (const owner of all) {
    for (const name of defined(owner.style)) {
      if (SHARED.has(name)) {
        continue;
      }
      const others = all.filter((other) => other.file !== owner.file && used(other.template).has(name));
      if (others.length) {
        leaks.push(`.${name} is laid out in ${owner.file} and used by ${others.map((other) => other.file).join(", ")}`);
      }
    }
  }
  assert.deepEqual(leaks, [], leaks.join("\n"));
});

test("the status row and the message rail keep their own class names", async () => {
  const all = await components();
  const byName = (file: string): Component => {
    const found = all.find((entry) => entry.file.endsWith(file));
    assert.ok(found, file);
    return found;
  };
  assert.deepEqual([...defined(byName("LiveStatus.vue").style)].filter((name) => name === "live"), []);
  assert.deepEqual([...defined(byName("MessageRail.vue").style)].filter((name) => name === "tick"), []);
});
