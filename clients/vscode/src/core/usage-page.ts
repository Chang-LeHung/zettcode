/** The HTML of the usage, model-check and plugin pages. No editor in here, so the tests can read it as a document. */

import type {
  ModelCheck,
  PluginEntry,
  PluginReport,
  SessionTotals,
  Totals,
  WorkspaceUsage,
} from "../../../typescript/src/types.js";
import { calendar, dayKey, dayTitle, rootScale, share, streaks } from "./usage.js";
import { escapeHtml, formatTokens, sessionLabel } from "./format.js";

/** How many weeks the calendar draws: a year, as GitHub's contribution graph does. */
export const CALENDAR_WEEKS = 53;

/** Columns at each end where a day's box opens inward instead of centred, so it stays inside the calendar. */
const TIP_EDGE = 8;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export interface Page {
  title: string;
  /** The body of the page, after the header. */
  body: string;
  /** The one line under the title. */
  summary: string;
  /** Whether the numbers are those of one workspace, which the page then says before anything else. */
  scoped?: boolean;
  /** The page's own script, for a page with a control on it; the panel runs it under a nonce. */
  script?: string;
}

/**
 * The sentence that tells the reader whose numbers these are. The usage ledger is kept for each workspace, so a window
 * opened on another folder shows a different page, and nothing on the page used to say so.
 */
export function scopeNote(path: string): string {
  const where = path ? ` <code>${escapeHtml(path)}</code>` : "";
  return `<p class="scope">Only this workspace:${where}. It counts the sessions stored for this folder; other folders keep their own usage.</p>`;
}

const percent = (fraction: number): string => `${Math.max(0, Math.min(100, fraction * 100)).toFixed(1)}%`;

/** The line the terminal puts under its tabs: what the whole workspace has spent. */
function summary(usage: WorkspaceUsage): string {
  const total = usage.total;
  return `<span class="sum-name">All models</span>
    <b>${formatTokens(total.total_tokens)}</b> tokens
    <span class="sum-in" title="Input tokens">↑ ${formatTokens(total.input_tokens)}</span>
    <span class="sum-out" title="Output tokens">↓ ${formatTokens(total.output_tokens)}</span>
    <span class="muted">cached ${share(total.cache_share)} · ${total.requests.toLocaleString("en-US")} requests · ${
      usage.sessions.length
    } session${usage.sessions.length === 1 ? "" : "s"}</span>`;
}

function bar(
  value: number,
  maximum: number,
  tone: string,
  scale: "linear" | "root" = "linear",
  dim = 0,
): string {
  const fill = scale === "root" ? rootScale(value, maximum) : maximum > 0 ? Math.min(1, value / maximum) : 0;
  const width = value > 0 ? Math.max(1.5, fill * 100) : 0;
  // `dim` is the part of the value that is a different kind of the same thing: input served from the cache, or
  // output spent thinking. It is drawn first, toned down, so the bar says how much of it was that.
  const share = value > 0 ? Math.max(0, Math.min(1, dim / value)) * 100 : 0;
  const inner = share > 0 ? `<i class="dim" style="width:${share.toFixed(1)}%"></i>` : "";
  return `<span class="bar"><span class="fill ${tone}" style="width:${width.toFixed(1)}%">${inner}</span></span>`;
}

function modelsTab(usage: WorkspaceUsage): string {
  if (usage.models.length === 0) {
    return `<div class="empty">No model replies have been recorded in this workspace yet.</div>`;
  }
  const ranked = usage.models.slice().sort((left, right) => right.tokens.total_tokens - left.tokens.total_tokens);
  const mostIn = Math.max(...ranked.map((model) => model.tokens.input_tokens), 1);
  const mostOut = Math.max(...ranked.map((model) => model.tokens.output_tokens), 1);
  const rows = ranked
    .map(
      ({ model, tokens }) => `<div class="model">
        <div class="model-head"><strong class="model-name">${escapeHtml(model)}</strong>
          <span class="muted">${formatTokens(tokens.total_tokens)} tokens · ${tokens.requests.toLocaleString("en-US")} requests</span></div>
        <div class="line"><span class="kind in">input</span>${bar(tokens.input_tokens, mostIn, "in", "linear", tokens.cache_read_tokens)}
          <b>${formatTokens(tokens.input_tokens)}</b><span class="muted">${share(tokens.cache_share)} cached</span></div>
        <div class="line"><span class="kind out">output</span>${bar(tokens.output_tokens, mostOut, "out", "linear", tokens.reasoning_tokens)}
          <b>${formatTokens(tokens.output_tokens)}</b><span class="muted">${formatTokens(tokens.reasoning_tokens)} reasoning</span></div>
      </div>`,
    )
    .join("");
  const key = `<span class="key"><i class="swatch in"></i>input <i class="swatch in dim"></i>of it cached
    <i class="swatch out"></i>output <i class="swatch out dim"></i>of it reasoning</span>`;
  return `<p class="note">Bars compare each model with the largest one, input and output on their own scales.</p>
    <p class="note">${key}</p>${rows}`;
}

/** `Oct 18 11:00`, in the reader's own clock. */
function stamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  return `${MONTHS[date.getMonth()]} ${date.getDate()} ${hours}:${minutes}`;
}

function sessionRow(session: SessionTotals, mostIn: number, mostOut: number): string {
  const tokens = session.tokens;
  const cached = tokens.cache_share ?? 0;
  return `<div class="srow">
    <span class="when">${escapeHtml(stamp(session.started))}</span>
    <span class="when">${escapeHtml(stamp(session.updated))}</span>
    <span class="title" title="${escapeHtml(session.models.join(", ") || "unknown model")}">${escapeHtml(
      sessionLabel(session.title),
    )}</span>
    <span class="cell">${bar(tokens.input_tokens, mostIn, "in", "root")}<b>${formatTokens(tokens.input_tokens)}</b></span>
    <span class="cell">${bar(tokens.output_tokens, mostOut, "out", "root")}<b>${formatTokens(tokens.output_tokens)}</b></span>
    <span class="cell">${bar(cached, 1, "cache")}<b>${tokens.cache_share === null ? "—" : percent(cached)}</b></span>
  </div>`;
}

function sessionsTab(usage: WorkspaceUsage): string {
  if (usage.sessions.length === 0) {
    return `<div class="empty">This workspace has no sessions yet.</div>`;
  }
  const ordered = usage.sessions.slice().sort((left, right) => right.updated.localeCompare(left.updated));
  const mostIn = Math.max(...ordered.map((session) => session.tokens.input_tokens), 1);
  const mostOut = Math.max(...ordered.map((session) => session.tokens.output_tokens), 1);
  return `<p class="note">Token bars: square-root scale against the busiest session. Cached bar: 0–100%, full is all of it.</p>
    <div class="srow shead"><span>Began</span><span>Updated</span><span>Title</span><span>Input</span><span>Output</span><span>Cached</span></div>
    ${ordered.map((session) => sessionRow(session, mostIn, mostOut)).join("")}`;
}

function tokensOf(totals: Totals): string {
  return `${formatTokens(totals.total_tokens)} tokens · ↑ ${formatTokens(totals.input_tokens)} · ↓ ${formatTokens(
    totals.output_tokens,
  )} · ${totals.requests.toLocaleString("en-US")} requests`;
}

function calendarTab(usage: WorkspaceUsage, today: string): string {
  const grid = calendar(usage.days, today, CALENDAR_WEEKS);
  const labels = grid.months.map((month) => `<span style="grid-column:${month.column + 1}">${month.name}</span>`).join("");
  const weekdays = ["", "Mon", "", "Wed", "", "Fri", ""]
    .map((name) => `<span class="weekday">${name}</span>`)
    .join("");
  const cells = grid.columns
    .map((week, column) =>
      week
        .map((cell, row) => {
          if (cell.future) {
            return `<i class="cell-day future"></i>`;
          }
          const lines =
            cell.tokens > 0
              ? [
                  dayTitle(cell.day),
                  `${formatTokens(cell.tokens)} tokens · ↑ ${formatTokens(cell.input)} · ↓ ${formatTokens(cell.output)}`,
                  `${cell.requests.toLocaleString("en-US")} request${cell.requests === 1 ? "" : "s"}${
                    cell.input > 0 ? ` · ${share(cell.cached / cell.input)} cached` : ""
                  }`,
                ]
              : [dayTitle(cell.day), "Nothing spent"];
          // The box opens away from the nearest edge, so a cell at the corner never has it cut off by the calendar.
          const across = column < TIP_EDGE ? "tip-start" : column >= CALENDAR_WEEKS - TIP_EDGE ? "tip-end" : "tip-mid";
          const down = row < 4 ? "tip-below" : "tip-above";
          return `<i class="cell-day heat${cell.level} ${across} ${down}" data-tip="${escapeHtml(
            lines.join("\n"),
          )}" aria-label="${escapeHtml(lines.join(", "))}"></i>`;
        })
        .join(""),
    )
    .join("");
  const used = usage.days.filter((entry) => entry.tokens.total_tokens > 0);
  const run = streaks(usage.days, today);
  const busiest = used.reduce<(typeof used)[number] | null>(
    (best, entry) => (best === null || entry.tokens.total_tokens > best.tokens.total_tokens ? entry : best),
    null,
  );
  const facts =
    used.length === 0
      ? `<p class="muted">Nothing has been spent yet.</p>`
      : `<p class="today"><strong>Today</strong> ${escapeHtml(
          tokensOf(usage.days.find((entry) => entry.day === today)?.tokens ?? emptyTotals()),
        )}</p>
        <p class="muted">${used.length} active day${used.length === 1 ? "" : "s"} · longest streak ${
          run.longest
        } · current streak ${run.current}${
          busiest === null ? "" : ` · busiest ${escapeHtml(busiest.day)} (${formatTokens(busiest.tokens.total_tokens)})`
        }</p>`;
  return `<div class="calendar">
      <div class="months" style="--weeks:${CALENDAR_WEEKS}">${labels}</div>
      <div class="cal-body"><div class="weekdays">${weekdays}</div>
        <div class="days" style="--weeks:${CALENDAR_WEEKS}">${cells}</div></div>
      <div class="legend"><span class="muted">Less</span>${[0, 1, 2, 3, 4]
        .map((level) => `<i class="cell-day heat${level}"></i>`)
        .join("")}<span class="muted">More</span></div>
    </div>
    ${facts}`;
}

function emptyTotals(): Totals {
  return {
    requests: 0,
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    reasoning_tokens: 0,
    total_tokens: 0,
    cache_share: null,
  };
}

/** The usage page: the terminal's three tabs, switched by radio buttons so the page needs no script. */
export function usagePage(usage: WorkspaceUsage | null, now = new Date()): Page {
  if (usage === null) {
    return {
      title: "Usage",
      scoped: true,
      summary: `<span class="muted">Nothing has been measured yet.</span>`,
      body: `<div class="empty">The usage ledger is not available; add a model first and try again.</div>`,
    };
  }
  const tabs = [
    { id: "models", label: "Models", body: modelsTab(usage) },
    { id: "sessions", label: "Sessions", body: sessionsTab(usage) },
    { id: "calendar", label: "Calendar", body: calendarTab(usage, dayKey(now)) },
  ];
  const body = `<div class="tabbed">
    ${tabs
      .map(
        (tab, index) =>
          `<input class="tab-radio" type="radio" name="tab" id="tab-${tab.id}"${index === 0 ? " checked" : ""}>`,
      )
      .join("")}
    <div class="tabs" role="tablist">${tabs
      .map((tab) => `<label for="tab-${tab.id}" role="tab">${tab.label}</label>`)
      .join("")}</div>
    ${tabs.map((tab) => `<section class="tab-body" id="body-${tab.id}">${tab.body}</section>`).join("")}
  </div>`;
  return { title: "Usage", summary: summary(usage), body, scoped: true };
}

/** The model check: one card for each model, with its answer or its error. */
export function doctorPage(checks: ModelCheck[]): Page {
  const passed = checks.filter((check) => check.ok).length;
  const cards = checks
    .map(
      (check) => `<article class="check-card">
        <div class="check-head">
          <span class="pill ${check.ok ? "ok" : "bad"}">${check.ok ? "pass" : "fail"}</span>
          <strong>${escapeHtml(check.model)}</strong>
          <span class="check-time">${check.seconds.toFixed(1)}s</span>
        </div>
        <div class="check-id">${escapeHtml(check.model_id)}</div>
        <p class="check-detail">${escapeHtml(check.detail || "No detail returned.")}</p>
        <div class="check-tokens">${check.input_tokens === null ? "—" : formatTokens(check.input_tokens)} input · ${
          check.output_tokens === null ? "—" : formatTokens(check.output_tokens)
        } output</div>
      </article>`,
    )
    .join("");
  return {
    title: "Model check",
    summary: `<b>${passed}</b> of ${checks.length} models answered <span class="muted">· one short question to each</span>`,
    body: checks.length === 0 ? `<div class="empty">No model is configured yet.</div>` : `<div class="check-grid">${cards}</div>`,
  };
}

/**
 * The plugins: the ones compiled into the program, the ones installed beside it, and the ones that did not load.
 *
 * Every row says what it is called, where it came from, and — for an installed one — whether the next start loads it,
 * as a switch. A builtin has no switch because it cannot be left out: it is the program itself. The page is why a
 * plugin's switch is a promise about the next start and not about this one, so it says so under the list.
 */
export function pluginsPage(plugins: PluginReport): Page {
  const entries = plugins.entries.length > 0 ? plugins.entries : legacyEntries(plugins);
  const builtin = entries.filter((entry) => entry.builtin);
  const installed = entries.filter((entry) => !entry.builtin);
  const off = installed.filter((entry) => !entry.enabled).length;
  const failed = entries.filter((entry) => entry.failure !== "").length;
  return {
    title: "Plugins",
    summary: `<b>${plugins.loaded.length}</b> loaded <span class="muted">· ${off} off at the next start · ${failed} failed</span>`,
    body: `<section class="columns">
      ${group("Built in", builtin, "No plugin is compiled into the program.")}
      ${group("Installed", installed, "No plugin is installed beside the program.")}
    </section>
    <p class="scope">A switch is written down now and honoured by the next start: this one keeps the plugins it
    loaded. <strong>ZettCode: Restart Server</strong> starts one that reads it.</p>`,
  };
}

/** One group of rows, under a heading with how many it has. */
function group(title: string, entries: PluginEntry[], empty: string): string {
  const rows =
    entries.length === 0
      ? `<div class="empty">${empty}</div>`
      : `<ul class="plugin-list">${entries.map((entry) => row(entry)).join("")}</ul>`;
  return `<div class="panel"><div class="panel-head"><h2>${title}</h2><span class="muted">${entries.length}</span></div>${rows}</div>`;
}

/** One plugin: its dot, its name, where it came from, why it failed, and the switch an installed one has. */
function row(entry: PluginEntry): string {
  const failed = entry.failure !== "";
  const dot = failed ? "failed" : entry.enabled ? "on" : "off";
  const origin = entry.origin === entry.name ? "" : `<span class="plugin-origin">${escapeHtml(entry.origin)}</span>`;
  const failure = failed ? `<span class="plugin-failure">${escapeHtml(entry.failure)}</span>` : "";
  const control = entry.builtin
    ? `<span class="chip">built in</span>`
    : `<button class="switch" role="switch" data-name="${escapeHtml(entry.origin)}" data-enabled="${entry.enabled}"
         aria-pressed="${entry.enabled}" aria-checked="${entry.enabled}" title="${
           entry.enabled ? "On from the next start" : "Off from the next start"
         }"><span class="knob"></span><span class="switch-word">${entry.enabled ? "on" : "off"}</span></button>`;
  return `<li class="plugin ${dot}" data-name="${escapeHtml(entry.origin)}"><i class="dot"></i><span class="plugin-name">${escapeHtml(
    entry.name,
  )}</span>${origin}${failure}${control}</li>`;
}

/** A report from a server too old to send entries: the names alone, which is all there was to show. */
function legacyEntries(plugins: PluginReport): PluginEntry[] {
  return [
    ...plugins.loaded.map((name) => ({ name, origin: name, builtin: false, enabled: true, failure: "" })),
    ...plugins.failures.map((failure) => ({
      name: failure.split(":")[0] ?? failure,
      origin: failure.split(":")[0] ?? failure,
      builtin: false,
      enabled: true,
      failure,
    })),
  ];
}

/** The page's styles, using the editor's colours so it follows the theme. */
export const PAGE_CSS = `
:root {
  color-scheme: light dark;
  --ink: var(--vscode-foreground);
  --muted: var(--vscode-descriptionForeground);
  --line: var(--vscode-widget-border, rgba(128,128,128,.24));
  --card: var(--vscode-editorWidget-background, rgba(128,128,128,.06));
  --bg: var(--vscode-editor-background);
  --accent: #5fca94;
  --in: #6aa9ff;
  --out: #f6cf78;
  --red: var(--vscode-errorForeground, #f48771);
  --mono: var(--vscode-editor-font-family, monospace);
}
* { box-sizing: border-box; }
body { margin: 0; padding: 26px 30px 56px; color: var(--ink); background: var(--bg);
  font-family: var(--vscode-font-family); font-size: 13px; line-height: 1.5; -webkit-font-smoothing: antialiased; }
.page { max-width: 1040px; margin: 0 auto; }
.brand { display: flex; align-items: center; gap: 9px; margin-bottom: 18px; color: var(--muted); font-size: 11px; }
.brand img { width: 24px; height: 24px; }
.brand strong { color: var(--ink); font-weight: 600; }
h1 { margin: 0 0 6px; font-size: 22px; font-weight: 650; letter-spacing: -.02em; }
.summary { margin-bottom: 18px; font-variant-numeric: tabular-nums; }
.scope { margin: 0 0 12px; color: var(--muted); font-size: 12px; line-height: 1.5; }
.scope code { padding: 1px 5px; border-radius: 4px; background: color-mix(in srgb, var(--ink) 9%, transparent); font-family: var(--vscode-editor-font-family, monospace); font-size: 11.5px; overflow-wrap: anywhere; }
.summary b { font-weight: 650; }
.sum-name { font-weight: 600; margin-right: 8px; }
.sum-in { color: var(--in); margin-left: 8px; }
.sum-out { color: var(--out); margin: 0 8px; }
.muted { color: var(--muted); }
.tab-radio { position: absolute; opacity: 0; pointer-events: none; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); margin-bottom: 16px; }
.tabs label { padding: 7px 14px; border-radius: 8px 8px 0 0; color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }
.tabs label:hover { color: var(--ink); }
.tab-body { display: none; }
#tab-models:checked ~ .tabs label[for="tab-models"],
#tab-sessions:checked ~ .tabs label[for="tab-sessions"],
#tab-calendar:checked ~ .tabs label[for="tab-calendar"] { color: var(--ink); border-bottom-color: var(--accent); font-weight: 600; }
#tab-models:focus-visible ~ .tabs label[for="tab-models"],
#tab-sessions:focus-visible ~ .tabs label[for="tab-sessions"],
#tab-calendar:focus-visible ~ .tabs label[for="tab-calendar"] { outline: 1px solid var(--vscode-focusBorder, var(--accent)); }
#tab-models:checked ~ #body-models,
#tab-sessions:checked ~ #body-sessions,
#tab-calendar:checked ~ #body-calendar { display: block; }
.note { margin: 0 0 10px; color: var(--muted); font-size: 11.5px; }
.key { display: inline-flex; align-items: center; flex-wrap: wrap; gap: 4px 8px; }
.swatch { display: inline-block; width: 18px; height: 8px; border-radius: 999px; }
.swatch.in, .fill.in { background: var(--in); }
.swatch.out, .fill.out { background: var(--out); }
.swatch.dim { background-image: linear-gradient(color-mix(in srgb, var(--bg) 55%, transparent), color-mix(in srgb, var(--bg) 55%, transparent)); }
.empty { border: 1px dashed var(--line); border-radius: 12px; padding: 22px; color: var(--muted); background: var(--card); }
.model { padding: 12px 0; border-bottom: 1px solid var(--line); }
.model:last-child { border-bottom: 0; }
.model-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 7px; }
.model-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.line { display: grid; grid-template-columns: 64px minmax(80px, 1fr) 56px 124px; gap: 12px; align-items: center; margin: 6px 0; font-variant-numeric: tabular-nums; }
.line .kind { display: flex; align-items: center; gap: 7px; color: var(--muted); }
.line .kind::before { content: ""; width: 8px; height: 8px; border-radius: 2px; background: currentColor; flex-shrink: 0; }
.line .kind.in { color: var(--in); }
.line .kind.out { color: var(--out); }
.line b { text-align: right; font-weight: 600; }
.bar { position: relative; display: block; height: 10px; border-radius: 999px; background: color-mix(in srgb, var(--ink) 11%, transparent); overflow: hidden; }
.fill { position: absolute; left: 0; top: 0; bottom: 0; display: block; margin: 0; border-radius: 999px; overflow: hidden; }
.fill i.dim { position: absolute; left: 0; top: 0; bottom: 0; background: color-mix(in srgb, var(--bg) 55%, transparent); }
.fill.cache { background: var(--accent); }
.srow { display: grid; grid-template-columns: 96px 96px minmax(120px, 1.4fr) repeat(3, minmax(110px, 1fr)); gap: 12px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--line); font-variant-numeric: tabular-nums; }
.srow.shead { color: var(--muted); font-size: 11.5px; padding-top: 0; }
.srow .when { color: var(--muted); font-size: 11.5px; white-space: nowrap; }
.srow .title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 550; }
.srow .cell { display: grid; grid-template-columns: minmax(40px, 1fr) 54px; gap: 8px; align-items: center; }
.srow .cell b { text-align: right; font-weight: 600; }
.calendar { overflow-x: auto; padding-bottom: 6px; direction: rtl; }
/* Right to left only so a narrow view starts at the latest day; when it all fits it sits at the left like the rest. */
.calendar > * { direction: ltr; width: max-content; margin: 0 auto 0 0; }
.months, .days { display: grid; grid-template-columns: repeat(var(--weeks), 14px); gap: 3px; }
.months { margin-left: 36px; height: 16px; color: var(--muted); font-size: 11px; }
.months span { white-space: nowrap; }
.cal-body { display: flex; gap: 6px; }
.weekdays { display: grid; grid-template-rows: repeat(7, 14px); gap: 3px; width: 30px; color: var(--muted); font-size: 10.5px; line-height: 14px; }
.days { grid-auto-flow: column; grid-template-rows: repeat(7, 14px); }
.cell-day { position: relative; display: block; width: 14px; height: 14px; border-radius: 3px; background: var(--line); }
.cell-day.future { background: transparent; }
.cell-day.heat0 { background: color-mix(in srgb, var(--ink) 9%, transparent); }
.cell-day.heat1 { background: color-mix(in srgb, var(--accent) 32%, var(--bg)); }
.cell-day.heat2 { background: color-mix(in srgb, var(--accent) 54%, var(--bg)); }
.cell-day.heat3 { background: color-mix(in srgb, var(--accent) 78%, var(--bg)); }
.cell-day.heat4 { background: var(--accent); }
/* The day under the pointer: ringed, with its figures in a box that opens at once (no wait, unlike a title). */
.cell-day[data-tip]:hover { outline: 1.5px solid var(--ink); outline-offset: 1px; z-index: 5; }
.cell-day[data-tip]:hover::after {
  content: attr(data-tip);
  position: absolute; z-index: 10; pointer-events: none;
  white-space: pre; text-align: left; font-size: 11.5px; line-height: 1.5; font-weight: 400; font-style: normal;
  padding: 6px 10px; border-radius: 8px;
  color: var(--vscode-editorHoverWidget-foreground, var(--ink));
  background: var(--vscode-editorHoverWidget-background, var(--card));
  border: 1px solid var(--vscode-editorHoverWidget-border, var(--line));
  box-shadow: 0 6px 18px rgba(0, 0, 0, .35);
}
.cell-day.tip-below:hover::after { top: calc(100% + 8px); }
.cell-day.tip-above:hover::after { bottom: calc(100% + 8px); }
.cell-day.tip-mid:hover::after { left: 50%; transform: translateX(-50%); }
.cell-day.tip-start:hover::after { left: -4px; }
.cell-day.tip-end:hover::after { right: -4px; }
.legend { display: flex; align-items: center; gap: 4px; margin: 12px 0 0 36px; font-size: 11px; }
.legend .cell-day { width: 12px; height: 12px; }
.today { margin: 16px 0 4px; }
.panel { border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px; background: color-mix(in srgb, var(--card) 55%, transparent); }
.panel-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }
.panel-head h2 { margin: 0; font-size: 13px; }
.columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }
.plugin-list { list-style: none; margin: 0; padding: 0; }
.plugin-list li { display: flex; gap: 8px; align-items: baseline; padding: 7px 0; border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }
.plugin-list li:last-child { border-bottom: 0; }
.dot { width: 8px; height: 8px; margin-top: 6px; border-radius: 50%; background: var(--accent); flex-shrink: 0; }
.plugin .dot { align-self: flex-start; }
.plugin.off .dot { background: var(--muted); }
.plugin.failed { color: var(--red); }
.plugin.failed .dot { background: var(--red); }
.plugin-name { font-weight: 600; }
.plugin-origin { color: var(--muted); font-family: var(--mono); font-size: 11px; }
.plugin-failure { color: var(--red); font-size: 11px; flex: 1 1 auto; }
.plugin .chip, .plugin .switch { margin-left: auto; flex-shrink: 0; }
.chip { border: 1px solid var(--line); border-radius: 999px; padding: 1px 8px; color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: .06em; }
.switch { display: inline-flex; align-items: center; gap: 6px; font: inherit; font-size: 11px; color: var(--muted);
  background: transparent; border: 1px solid var(--line); border-radius: 999px; padding: 2px 8px 2px 3px; cursor: pointer; }
.switch .knob { width: 12px; height: 12px; border-radius: 50%; background: var(--muted); transition: transform .12s ease; }
.switch[data-enabled="true"] { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); }
.switch[data-enabled="true"] .knob { background: var(--accent); }
.switch:disabled { opacity: .55; cursor: progress; }
.switch:hover:not(:disabled) { background: color-mix(in srgb, var(--ink) 6%, transparent); }
.switch:focus-visible { outline: 1px solid var(--accent); outline-offset: 2px; }
.check-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 12px; }
.check-card { border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px; background: var(--card); }
.check-head { display: flex; align-items: center; gap: 8px; }
.pill { border-radius: 999px; padding: 2px 8px; font-size: 10px; text-transform: uppercase; letter-spacing: .06em; font-weight: 600; }
.pill.ok { color: var(--accent); background: color-mix(in srgb, var(--accent) 16%, transparent); }
.pill.bad { color: var(--red); background: color-mix(in srgb, var(--red) 14%, transparent); }
.check-time { margin-left: auto; color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.check-id { color: var(--muted); font-family: var(--mono); font-size: 11px; margin: 5px 0 8px; }
.check-detail { color: var(--muted); margin: 0; overflow-wrap: anywhere; }
.check-tokens { color: var(--muted); font-size: 11px; margin-top: 10px; font-variant-numeric: tabular-nums; }
@media (max-width: 760px) {
  body { padding: 18px 14px 40px; }
  .srow { grid-template-columns: minmax(100px, 1fr) repeat(3, minmax(90px, 1fr)); }
  .srow .when { display: none; }
  .line { grid-template-columns: 50px minmax(60px, 1fr) 54px; }
  .line .muted { grid-column: 2 / -1; }
}
`;
