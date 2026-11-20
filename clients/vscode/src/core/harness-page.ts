/**
 * The harness library page: the shell of its markup and the script that draws what the host sends. No editor in here,
 * so a test can load both into jsdom and play the host.
 *
 * Everything that came from a downloaded repository (names, descriptions, file paths, link targets) is put on the page
 * with `textContent` and never as markup: a harness is somebody else's code and its manifest is somebody else's text.
 */

import type { Page } from "./usage-page.js";

/** The page's markup before the script fills it: a form to add one, the preview slot, and the list. */
export function harnessesPage(): Page {
  return {
    title: "Harnesses",
    summary: `<span id="harness-count">Loading…</span> <span class="muted">· shared by every workspace</span>`,
    body: `<div id="harness-status" class="harness-status" role="status" aria-live="polite" hidden></div>
    <section class="panel">
      <div class="panel-head"><h2>Add a harness</h2></div>
      <form id="harness-add" class="harness-form">
        <input id="harness-source" name="source" type="text" placeholder="owner/repo, owner/repo@ref or a git address" autocomplete="off" spellcheck="false" aria-label="Where to download it from">
        <input id="harness-name" name="name" type="text" placeholder="name (optional)" autocomplete="off" spellcheck="false" aria-label="Name in the library">
        <button type="submit" class="act primary">Preview</button>
      </form>
      <p class="muted harness-hint">Nothing is imported or kept until you have read the preview and pressed Keep.</p>
    </section>
    <section id="harness-preview" class="panel" hidden></section>
    <section class="panel">
      <div class="panel-head"><h2>Library</h2><span id="harness-total" class="muted"></span></div>
      <ul id="harness-list" class="harness-list"></ul>
    </section>
    <p class="scope">The library is <code>~/.zettcode/harness/library</code>. The harness a run uses is chosen with
    <code>[harness] use</code> in the configuration or <code>/harness use</code> in the terminal; one that is in use
    cannot be removed.</p>`,
    css: HARNESS_CSS,
  };
}

/** The page's styles, appended to the shared page CSS. */
export const HARNESS_CSS = `
.harness-form { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.harness-form input, .harness-ask input { font: inherit; color: var(--ink); background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 5px 8px; min-width: 0; }
.harness-form input:focus-visible, .harness-ask input:focus-visible { outline: 1px solid var(--accent); outline-offset: 1px; }
#harness-source { flex: 2 1 260px; }
#harness-name { flex: 1 1 140px; }
.act { font: inherit; font-size: 12px; color: var(--ink); background: transparent; border: 1px solid var(--line); border-radius: 4px; padding: 4px 10px; cursor: pointer; }
.act:hover:not(:disabled) { background: color-mix(in srgb, var(--ink) 6%, transparent); }
.act:disabled { opacity: .55; cursor: progress; }
.act:focus-visible { outline: 1px solid var(--accent); outline-offset: 2px; }
.act.primary { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); }
.act.danger { color: var(--red); border-color: color-mix(in srgb, var(--red) 45%, var(--line)); }
.harness-hint { margin: 4px 0 0; font-size: 11px; }
.harness-status { padding: 8px 10px; border: 1px solid var(--line); border-radius: 4px; margin-bottom: 12px; }
.harness-status.error { color: var(--red); border-color: color-mix(in srgb, var(--red) 45%, var(--line)); }
.harness-list { list-style: none; margin: 0; padding: 0; }
.harness { padding: 9px 0; border-bottom: 1px solid var(--line); }
.harness:last-child { border-bottom: 0; }
.harness-head { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.harness-name { font-weight: 600; }
.harness .chip { margin-left: 0; }
.harness-origin, .harness-commit { color: var(--muted); font-family: var(--mono); font-size: 11px; overflow-wrap: anywhere; }
.harness-actions { margin-left: auto; display: flex; gap: 6px; flex-wrap: wrap; }
.harness-detail, .harness-ask { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; font-size: 12px; }
.harness-ask { flex-direction: row; align-items: center; flex-wrap: wrap; }
.harness-repo { border-left: 2px solid var(--line); padding-left: 10px; }
.harness-repo p { margin: 2px 0; }
.harness-tools { font-family: var(--mono); font-size: 11px; overflow-wrap: anywhere; }
.harness-files { max-height: 220px; overflow: auto; font-family: var(--mono); font-size: 11px; margin: 4px 0 0; padding-left: 18px; }
.harness .pill, .preview .pill { font-size: 11px; }
.harness-state-changed, .harness-state-missing, .harness-state-damaged { color: var(--red); }
.preview { display: flex; flex-direction: column; gap: 6px; font-size: 12px; }
.preview .caution { color: var(--red); }
.preview .banned { color: var(--red); }
.preview-title { font-size: 14px; font-weight: 600; }
.preview-actions { display: flex; gap: 8px; margin-top: 6px; }
.preview ul { margin: 2px 0; padding-left: 18px; font-family: var(--mono); font-size: 11px; overflow-wrap: anywhere; }
`;

/**
 * The script: it posts what the reader pressed and draws what the host answers. It never talks to the server, because
 * the token lives in the host; a press is disabled until the host says what came of it.
 *
 * It expects `api` (the editor's message channel) to be defined before it runs: the host puts that line in front, since
 * nothing under `core/` may name the editor's API.
 */
export const HARNESS_SCRIPT = `
const $ = (id) => document.getElementById(id);
let busy = false;

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === false || value === null || value === undefined) { continue; }
    if (key === "class") { node.className = value; } else { node.setAttribute(key, value === true ? "" : String(value)); }
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) { continue; }
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function say(text, error) {
  const status = $("harness-status");
  status.hidden = !text;
  status.textContent = text || "";
  status.className = "harness-status" + (error ? " error" : "");
}

function lock(on) {
  busy = on;
  for (const button of document.querySelectorAll("button.act, #harness-add button")) { button.disabled = on; }
}

function act(label, kind, onclick) {
  const button = h("button", { type: "button", class: "act" + (kind ? " " + kind : "") }, label);
  button.addEventListener("click", () => { if (!busy) { onclick(button); } });
  return button;
}

function send(message, working) {
  lock(true);
  say(working, false);
  api.postMessage(message);
}

function plural(count, word) { return count + " " + word + (count === 1 ? "" : word.endsWith("s") ? "es" : "s"); }

function renderList(entries) {
  $("harness-count").textContent = plural(entries.length, "harness");
  $("harness-total").textContent = String(entries.length);
  const list = $("harness-list");
  list.replaceChildren();
  if (entries.length === 0) {
    list.append(h("li", { class: "empty" }, "The library is empty. Add a harness above."));
    return;
  }
  for (const entry of entries) { list.append(row(entry)); }
}

function row(entry) {
  const item = h("li", { class: "harness", "data-name": entry.name });
  const files = entry.repositories.reduce((sum, repo) => sum + repo.file_count, 0);
  const tools = entry.repositories.reduce((sum, repo) => sum + repo.tools.length, 0);
  const actions = h("span", { class: "harness-actions" });
  actions.append(
    act("Details", "", () => { send({ type: "detail", name: entry.name }, "Reading " + entry.name + "…"); }),
    act("Update", "", () => { clearPreview(); send({ type: "preview-update", name: entry.name, force: false }, "Downloading " + entry.name + "…"); }),
    act("Fork", "", () => { askFork(item, entry.name); }),
    act("Remove", "danger", (button) => { confirmRemove(button, entry.name); }),
  );
  item.append(
    h("div", { class: "harness-head" },
      h("span", { class: "harness-name" }, entry.name),
      entry.in_use ? h("span", { class: "chip" }, "in use") : null,
      h("span", { class: "harness-origin" }, entry.origin),
      h("span", { class: "harness-commit" }, entry.commit.slice(0, 10)),
      actions),
    h("div", { class: "muted" }, plural(tools, "tool") + " · " + plural(files, "file")),
  );
  return item;
}

function askFork(item, name) {
  if (item.querySelector(".harness-ask") !== null) { return; }
  const input = h("input", { type: "text", placeholder: "new name", autocomplete: "off", spellcheck: "false", "aria-label": "Name of the copy" });
  const go = act("Fork", "primary", () => {
    if (input.value.trim() === "") { say("Give the copy a name.", true); return; }
    send({ type: "fork", name, newName: input.value.trim() }, "Copying " + name + "…");
  });
  const cancel = act("Cancel", "", () => { box.remove(); });
  const box = h("div", { class: "harness-ask" }, input, go, cancel);
  item.append(box);
  input.focus();
}

function confirmRemove(button, name) {
  // A page in a webview cannot open the browser's confirm box, so the button asks twice.
  if (button.dataset.sure !== "true") {
    button.dataset.sure = "true";
    button.textContent = "Remove " + name + "?";
    return;
  }
  send({ type: "remove", name }, "Removing " + name + "…");
}

function showDetail(entry) {
  const item = document.querySelector('.harness[data-name="' + CSS.escape(entry.name) + '"]');
  if (item === null) { say(entry.name + " is no longer in the list.", true); return; }
  item.querySelector(".harness-detail")?.remove();
  const detail = h("div", { class: "harness-detail" },
    h("div", { class: "harness-state-" + entry.state }, "state: " + entry.state),
    entry.repositories.map((repo) => h("div", { class: "harness-repo" },
      h("p", {}, h("b", {}, repo.name || "(unnamed)"), repo.version ? " " + repo.version : ""),
      repo.description ? h("p", {}, repo.description) : null,
      repo.error ? h("p", { class: "harness-state-damaged" }, repo.error) : null,
      h("p", { class: "harness-tools" }, repo.tools.length ? repo.tools.join(", ") : "no tools"),
      h("details", {}, h("summary", {}, plural(repo.file_count, "file")),
        h("ul", { class: "harness-files" }, repo.files.map((file) => h("li", {}, file)))))),
    act("Close", "", () => { detail.remove(); }));
  item.append(detail);
}

function showPreview(preview) {
  const slot = $("harness-preview");
  slot.replaceChildren();
  const links = Object.entries(preview.links || {});
  const verb = preview.action === "add" ? "Keep" : "Apply update";
  slot.append(h("div", { class: "preview" },
    h("div", { class: "preview-title" }, (preview.action === "add" ? "Preview: add " : "Preview: update ") + preview.name),
    h("div", { class: "caution" }, preview.caution),
    h("div", { class: "harness-origin" }, preview.source + " @ " + preview.commit.slice(0, 10) + " · " + preview.size + " bytes"),
    preview.version || preview.description ? h("div", {}, (preview.version ? preview.version + " " : "") + preview.description) : null,
    h("div", { class: "harness-tools" }, preview.tools.length ? "tools: " + preview.tools.join(", ") : "no tools"),
    preview.banned.length ? h("div", { class: "banned" }, "names the program does not allow: " + preview.banned.join(", ")) : null,
    preview.action === "update" ? h("div", {}, preview.up_to_date ? "Already at this commit." : "Would change:",
      preview.changes.length ? h("ul", {}, preview.changes.map((line) => h("li", {}, line))) : null) : null,
    links.length ? h("div", { class: "caution" }, "Symbolic links (they can reach files outside the harness):",
      h("ul", {}, links.map(([path, target]) => h("li", {}, path + " → " + target)))) : null,
    h("details", {}, h("summary", {}, plural(preview.files.length, "file")),
      h("ul", { class: "harness-files" }, preview.files.map((file) => h("li", {}, file)))),
    h("div", { class: "preview-actions" },
      act(verb, "primary", () => { send({ type: "confirm" }, (preview.action === "add" ? "Keeping " : "Updating ") + preview.name + "…"); }),
      act("Cancel", "", () => { clearPreview(); api.postMessage({ type: "cancel" }); }),
    ),
  ));
  slot.hidden = false;
  slot.scrollIntoView?.({ block: "nearest" });
}

function clearPreview() {
  $("harness-preview").hidden = true;
  $("harness-preview").replaceChildren();
}

$("harness-add").addEventListener("submit", (event) => {
  event.preventDefault();
  if (busy) { return; }
  const source = $("harness-source").value.trim();
  if (source === "") { say("Say where to download it from.", true); return; }
  clearPreview();
  send({ type: "preview-add", source, name: $("harness-name").value.trim() }, "Downloading " + source + "…");
});

window.addEventListener("message", (event) => {
  const message = event.data;
  if (message === null || typeof message !== "object") { return; }
  switch (message.type) {
    // The list follows a "done" and must not wipe its words.
    case "list": lock(false); renderList(message.harnesses); break;
    case "detail": lock(false); say("", false); showDetail(message.entry); break;
    case "preview": lock(false); say("", false); showPreview(message.preview); break;
    case "done":
      lock(false); clearPreview(); say(message.text, false);
      // Only a kept download empties the form; a fork or a removal must not lose a source typed but not yet previewed.
      if (message.action === "keep") { $("harness-source").value = ""; $("harness-name").value = ""; }
      break;
    case "error":
      lock(false); say(message.text, true);
      if ($("harness-count").textContent === "Loading…") { $("harness-count").textContent = "Could not read the library"; }
      if (message.retry) {
        // The server refused an update (a harness changed since it was installed): offer it again, forced, on purpose.
        $("harness-status").append(" ", act("Update anyway", "danger", () => {
          clearPreview();
          send({ type: "preview-update", name: message.retry, force: true }, "Downloading " + message.retry + "…");
        }));
      }
      break;
  }
});

api.postMessage({ type: "ready" });
`;
