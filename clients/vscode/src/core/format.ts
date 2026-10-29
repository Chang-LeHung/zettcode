/** Describing a tool call, and formatting tokens and time, without a browser or an editor. */

import { escapeHtml } from "./escape.js";

export { escapeHtml };

/** The name, target and syntax a tool row shows before its output. */
export interface ToolDisplay {
  verb: string;
  target: string;
  /** The path the target names, when the row can link to a file or a directory. */
  path?: string;
  /** A language for the detail block, when it is code rather than JSON. */
  language?: string;
}

/** Terminal colour and cursor codes mean nothing in a transcript; drop them and normalise line endings. */
export function cleanOutput(output: string): string {
  return output
    .replace(/\u001b\[[0-9;?]*[ -/]*[@-~]/g, "")
    .replace(/\u001b\][^\u0007]*(?:\u0007|\u001b\\)/g, "")
    .replace(/\r\n?/g, "\n")
    .replace(/\s+$/, "");
}

/** The first lines of a tool's output, for a closed row; the full text stays in the block. */
export function summariseOutput(output: string, limit = 120): string {
  const text = output.replace(/\r\n?/g, "\n").trim();
  if (!text) {
    return "";
  }
  const first = text.split("\n").find((line) => line.trim()) ?? "";
  const flat = first.trim().replace(/\s+/g, " ");
  return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
}

/** The one-line description a SKILL.md declares, or "" when the text is not a skill. */
export function skillDescription(output: string): string {
  const lines = output.replace(/\r\n?/g, "\n").split("\n");
  if ((lines[0] ?? "").trim() !== "---") {
    return "";
  }
  const closing = lines.findIndex((line, index) => index > 0 && line.trim() === "---");
  if (closing < 0) {
    return "";
  }
  for (let index = 1; index < closing; index += 1) {
    const line = lines[index] ?? "";
    if (!line.startsWith("description:")) {
      continue;
    }
    let value = line.slice("description:".length).trim();
    if (value === "|" || value === ">") {
      const continuation: string[] = [];
      for (let following = index + 1; following < closing; following += 1) {
        const row = lines[following] ?? "";
        if (row && !/^\s/.test(row)) {
          break;
        }
        if (row.trim()) {
          continuation.push(row.trim());
        }
      }
      value = continuation.join(value === "|" ? "\n" : " ");
    }
    return value.replace(/^["']+|["']+$/g, "").replace(/\s+/g, " ").trim();
  }
  return "";
}

/** Describe one tool call as a verb and a target, the way the transcript row reads. */
export function describeTool(name: string, args: Record<string, unknown>, output = ""): ToolDisplay {
  const path = stringArg(args, "path", "file_path", "file", "target");
  const command = stringArg(args, "command", "cmd");
  const pattern = stringArg(args, "pattern", "query", "glob");
  const url = stringArg(args, "url");
  const description = stringArg(args, "description", "prompt", "task");
  const bare = name.replace(/^.*__/, "").toLowerCase();

  // A namespaced name is `<server>__<tool>` (and a name with the family in front, `mcp__github__create_issue`,
  // reads the same way): the server is part of what the call was, and dropping it made the same `search` in two
  // servers look like one tool. The row says only what the name says — a plugin registers namespaced names of its
  // own with the same shape — and a name without a tool part is left whole.
  const remote = name.startsWith("mcp__") ? name.slice(5) : name.includes("__") ? name : "";
  const [server, ...rest] = remote.split("__");
  const tool = rest.join("__");
  if (remote && server && tool) {
    // A verb, like every other row, with the server in the target: the bold leading word is a verb column, and a
    // server name in it read as one word run into the next (`github create_issue`).
    return { verb: "Called", target: `${server}/${tool}` };
  }
  if (remote) {
    return { verb: name, target: "" };
  }

  switch (bare) {
    case "read_file":
    case "read":
      return pathRow("Read", path);
    case "write_file":
    case "write":
      return pathRow("Write", path, "markdown");
    case "edit":
    case "replace_in_file":
      return pathRow("Edit", path);
    case "glob":
      return { verb: "Glob", target: pattern || path || "files" };
    case "send_message":
      return { verb: "Message", target: `@${stringArg(args, "to") || "?"}` };
    case "grep":
      return {
        verb: "Grep",
        target: pattern ? (path ? `${pattern} in ${path}` : pattern) : path || "the workspace",
        ...(path ? { path } : {}),
      };
    case "bash":
    case "shell": {
      // The row says where the call runs when that is not the workspace, the way the terminal's does: a
      // resumed session has to record the directory, or the transcript cannot say what ran where.
      const where = stringArg(args, "work_dir");
      return { verb: "Bash", target: where ? `${command || "(command)"} · ${where}` : command || "(command)" };
    }
    case "web_search":
      return { verb: "Searched the web", target: pattern || command || "" };
    case "fetch":
    case "read_url":
      return { verb: "Fetched", target: url || pattern || "" };
    case "task":
    case "spawn_agent":
    case "agent":
      return { verb: "Delegated", target: description || "a subtask" };
    case "todo_write":
    case "todowrite":
      return { verb: "Updated the plan", target: "" };
    case "read_skill": {
      const skill = stringArg(args, "name");
      const description = skillDescription(output);
      return { verb: "Read skill", target: skill && description ? `${skill} · ${description}` : skill || description };
    }
    case "mentions":
      return { verb: "Looked up", target: pattern || "mentions" };
    default:
      return {
        verb: humanise(bare),
        target: path || command || pattern || url || description || "",
        ...(path ? { path } : {}),
      };
  }
}

/** The body of a tool row: the command, the edit, or the arguments as JSON. */
export function toolDetail(name: string, args: Record<string, unknown>): string {
  const bare = name.replace(/^.*__/, "").toLowerCase();
  const command = stringArg(args, "command", "cmd");
  if (bare === "send_message") {
    return stringArg(args, "message", "text") || JSON.stringify(args);
  }
  if ((bare === "bash" || bare === "shell") && command) {
    return command;
  }
  if (bare === "edit" || bare === "replace_in_file") {
    const pairs = Array.isArray(args.edits) ? args.edits : [args];
    const rows: string[] = [];
    pairs.forEach((pair, index) => {
      const record = (pair ?? {}) as Record<string, unknown>;
      const oldText = rawArg(record, "old_string", "old_text", "oldString", "oldText", "old");
      const newText = rawArg(record, "new_string", "new_text", "newString", "newText", "new");
      if (!oldText && !newText) {
        return;
      }
      if (pairs.length > 1) {
        rows.push(`@@ edit ${index + 1} of ${pairs.length}`);
      }
      rows.push(...oldText.split("\n").map((line) => `-${line}`), ...newText.split("\n").map((line) => `+${line}`));
    });
    if (rows.length) {
      return rows.join("\n");
    }
  }
  const output = safeJson(args);
  return output.length > 8000 ? `${output.slice(0, 8000)}\n…` : output;
}

/** Lines in a piece of text; an empty text has none, and the break that ends the last line does not start another. */
function countLines(text: string): number {
  if (!text) {
    return 0;
  }
  return text.split("\n").length - (text.endsWith("\n") ? 1 : 0);
}

/**
 * Lines an edit took out and put in, for the row that names it: an edit counts both sides of each replacement, and a
 * file written whole counts the lines it holds. Other tools have no such figure.
 */
export function lineStats(name: string, args: Record<string, unknown>): { added: number; removed: number } | null {
  const bare = name.replace(/^.*__/, "").toLowerCase();
  if (bare === "edit" || bare === "replace_in_file") {
    const pairs = Array.isArray(args.edits) ? args.edits : [args];
    let added = 0;
    let removed = 0;
    for (const pair of pairs) {
      const record = (pair ?? {}) as Record<string, unknown>;
      removed += countLines(rawArg(record, "old_string", "old_text", "oldString", "oldText", "old"));
      added += countLines(rawArg(record, "new_string", "new_text", "newString", "newText", "new"));
    }
    return added || removed ? { added, removed } : null;
  }
  if (bare === "write_file" || bare === "write") {
    const added = countLines(rawArg(args, "content", "text"));
    return added ? { added, removed: 0 } : null;
  }
  return null;
}

/** The language a tool's detail block is written in. */
export function toolLanguage(name: string, args: Record<string, unknown>): string {
  const bare = name.replace(/^.*__/, "").toLowerCase();
  if ((bare === "bash" || bare === "shell") && stringArg(args, "command", "cmd")) {
    return "shell";
  }
  if (bare === "edit" || bare === "replace_in_file") {
    return "diff";
  }
  return "json";
}

/**
 * `1234` as `1.2k`, `1234567` as `1.2M`, and `4064400000` as `4.06B`.
 *
 * A figure steps up to the next unit as soon as it would round to 1000 of the one below, so it is never written as
 * `1000k` or `1000.0M`. Billions keep two decimals under ten, one under a hundred, and none past that, because a
 * ledger that has counted thousands of millions needs the third digit to tell two models apart.
 */
export function formatTokens(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "0";
  }
  if (value < 1000) {
    return String(Math.round(value));
  }
  const thousands = value / 1000;
  if (thousands < 999.5) {
    return `${thousands >= 100 ? Math.round(thousands) : trimmed(thousands, 1)}k`;
  }
  const millions = value / 1_000_000;
  if (millions < 999.95) {
    return `${trimmed(millions, 1)}M`;
  }
  const billions = value / 1_000_000_000;
  return `${trimmed(billions, billions >= 100 ? 0 : billions >= 10 ? 1 : 2)}B`;
}

/** A number to a fixed number of decimals, without the zeros that add nothing: `4.10` is `4.1`, `4.00` is `4`. */
function trimmed(value: number, digits: number): string {
  return String(Number(value.toFixed(digits)));
}

/** A duration as the smallest useful unit. */
export function formatDuration(milliseconds: number): string {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) {
    return "";
  }
  if (milliseconds < 1000) {
    return `${Math.round(milliseconds)}ms`;
  }
  const seconds = milliseconds / 1000;
  if (seconds < 60) {
    return `${seconds < 10 ? seconds.toFixed(1).replace(/\.0$/, "") : Math.round(seconds)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}m ${rest}s`;
}

/**
 * A running clock, in whole seconds with its units: `8s`, `1m 19s`, `1h 4m`. It is what the status line ticks with,
 * so it never shows a decimal or a bare `1:19` that a reader has to read as minutes and seconds.
 */
export function formatClock(milliseconds: number): string {
  const total = Math.max(0, Math.floor(milliseconds / 1000));
  if (total < 60) {
    return `${total}s`;
  }
  const minutes = Math.floor(total / 60);
  if (minutes < 60) {
    return `${minutes}m ${total % 60}s`;
  }
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/** When a session was last active, in the words a history row uses. */
export function relativeTime(value: string | null | undefined, now = Date.now()): string {
  if (!value) {
    return "never";
  }
  const then = Date.parse(value);
  if (Number.isNaN(then)) {
    return "";
  }
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 45) {
    return "just now";
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m ago`;
  }
  if (seconds < 86_400) {
    return `${Math.round(seconds / 3600)}h ago`;
  }
  if (seconds < 7 * 86_400) {
    return `${Math.round(seconds / 86_400)}d ago`;
  }
  return new Date(then).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * A line of news as Markdown. The agent names a server the way Python prints a string, `'docs'`; shown as code it is
 * clearer where a name ends, whatever it contains. Only a quote that opens after a space or a bracket and closes before
 * a space or punctuation counts, so the apostrophe in "it's" is left alone.
 */
export function noticeMarkdown(text: string): string {
  return text.replace(NAME_IN_QUOTES, "$1`$2`");
}

/** The same line for a place that shows plain text, such as the status line: the names without their quotes. */
export function noticePlain(text: string): string {
  return text.replace(NAME_IN_QUOTES, "$1$2");
}

const NAME_IN_QUOTES = /(^|[\s(])'([^'\n]+)'(?=[\s).,:;\u2026]|$)/g;

/** A line that says work is going on, without the dots that trail it: the shimmer says it instead. */
export function withoutEllipsis(text: string): string {
  return text.replace(/\s*(?:\u2026|\.{3})\s*$/, "");
}

/** A title to show for a session that may not have one yet. */
export function sessionLabel(title: string | null | undefined): string {
  const clean = title?.trim();
  return clean ? clean : "Untitled session";
}

/** How a stopped request says it stopped. */
export function stopLabel(reason: string): string {
  switch (reason) {
    case "max_output":
      return "Hit the output limit";
    case "context_full":
      return "Context window full";
    case "refusal":
      return "The model refused";
    case "paused":
      return "Paused";
    case "interrupted":
      return "Interrupted";
    default: {
      const words = reason.replace(/_/g, " ");
      return words.charAt(0).toUpperCase() + words.slice(1);
    }
  }
}

/** The one-word label of a permission level. */
export function permissionLabel(permission: string): string {
  switch (permission) {
    case "deny":
      return "Deny";
    case "ask":
      return "Ask";
    case "safe":
      return "Safe";
    case "full":
    case "auto":
      return "Full";
    default:
      // A level this build has never heard of is shown as itself. Calling it "Ask" made a server that sends a newer
      // level look like a second Ask in the menu, which is worse than an unfamiliar word.
      return permission.trim() === "" ? "Unknown" : permission.charAt(0).toUpperCase() + permission.slice(1);
  }
}

/** What a permission level means, in the line the picker shows under it. */
export function permissionDescription(permission: string): string {
  switch (permission) {
    case "ask":
      return "Every shell command waits for your approval.";
    case "deny":
      return "Shell commands are refused; the model uses the file tools instead.";
    case "safe":
      return "Every command runs in a sandbox: it can write the workspace and /tmp only, and has no network.";
    case "full":
    case "auto":
      return "Every command runs with your own access, without asking.";
    default:
      return "This editor does not know this level; update the extension to see what it does.";
  }
}

function pathRow(verb: string, path: string, language?: string): ToolDisplay {
  return { verb, target: path || "", ...(path ? { path } : {}), ...(language ? { language } : {}) };
}

/** A string argument exactly as sent: indentation is part of a diff. */
function rawArg(args: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = args[key];
    if (typeof value === "string") {
      return value;
    }
  }
  return "";
}

function stringArg(args: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
    if (typeof value === "number") {
      return String(value);
    }
  }
  return "";
}

function humanise(name: string): string {
  const words = name.replace(/[_-]+/g, " ").trim();
  if (!words) {
    return "Used a tool";
  }
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? "";
  } catch {
    return String(value);
  }
}
