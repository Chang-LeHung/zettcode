// A daemon's log is one line per fact: "2026-11-01 19:49:04 tool bash · git status". The page reads those lines into
// something a person can scan: when, what kind of thing, what it was about. A line this does not recognise is kept
// whole as plain information, so a newer daemon's wording never disappears.

export type LogKind = "tool" | "turn" | "done" | "error" | "info";

export interface LogLine {
  /** Where the line was in the file, which is its key. */
  at: number;
  date: string;
  time: string;
  kind: LogKind;
  /** The tool's name, for a tool line; empty otherwise. */
  name: string;
  /** What the line says after its name. */
  text: string;
  /** The line as written. */
  raw: string;
}

const STAMP = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) (.*)$/;
const TROUBLE = /\b(fail(?:ed|ure)?|error|traceback|exception|could not|cannot|not retried|refused)\b/i;

export function parseLine(raw: string, at = 0): LogLine {
  const stamp = STAMP.exec(raw);
  const date = stamp?.[1] ?? "";
  const time = stamp?.[2] ?? "";
  const body = stamp?.[3] ?? raw;
  const base = { at, date, time, raw };
  const tool = /^tool (\S+)(?: (failed|skipped)\b[^:]*:?\s*(.*)| finished in (.*)| · (.*))?$/s.exec(body);
  if (tool) {
    const name = tool[1] ?? "";
    if (tool[2] === "failed") return { ...base, kind: "error", name, text: tool[3] ?? "" };
    if (tool[2] === "skipped") return { ...base, kind: "info", name, text: tool[3] || "skipped" };
    if (tool[4] !== undefined) return { ...base, kind: "info", name, text: `finished in ${tool[4]}` };
    return { ...base, kind: "tool", name, text: tool[5] ?? "" };
  }
  if (body.startsWith("turn from ")) return { ...base, kind: "turn", name: "", text: body.slice("turn from ".length) };
  if (body.startsWith("turn finished")) return { ...base, kind: "done", name: "", text: body.slice("turn ".length) };
  return { ...base, kind: TROUBLE.test(body) ? "error" : "info", name: "", text: body };
}

export function parseLog(text: string): LogLine[] {
  return text
    .split("\n")
    .filter((line) => line.trim() !== "")
    .map((line, at) => parseLine(line, at));
}

export type LogFilter = "all" | "tools" | "problems";

/** A line about a tool: its start, its failure, a skip or a slow finish all carry the tool's name. */
const aboutTool = (line: LogLine): boolean => line.name !== "";

/** Keep the lines a filter and a search ask for; a search matches the line as written, ignoring case. */
export function visible(lines: LogLine[], filter: LogFilter, search: string): LogLine[] {
  const needle = search.trim().toLowerCase();
  return lines.filter((line) => {
    if (filter === "tools" && !aboutTool(line)) return false;
    if (filter === "problems" && line.kind !== "error") return false;
    return needle === "" || line.raw.toLowerCase().includes(needle);
  });
}

/** How many lines of each kind there are, for the counts on the filter chips. */
export function counts(lines: LogLine[]): { all: number; tools: number; problems: number } {
  let tools = 0;
  let problems = 0;
  for (const line of lines) {
    if (aboutTool(line)) tools += 1;
    if (line.kind === "error") problems += 1;
  }
  return { all: lines.length, tools, problems };
}
