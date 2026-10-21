/**
 * A file the reader copied and pasted into the box.
 *
 * A page in a webview is given a pasted file's name and its bytes, but no path, and the browser would put the bare name
 * into the box as text. The path is what the agent can open, so the host finds one, in this order: a path the
 * clipboard's own text already holds; the file in the workspace that has the very same bytes (the name alone is a
 * guess, since several files share one); a copy of the bytes kept in the extension's own storage, for a file that is
 * not in the workspace. A file too large to send is looked for by name. Free of the editor, so the choosing is a table.
 */

/** The largest file whose bytes are sent to the host, in bytes; a bigger one is found by its name. */
export const PASTE_LIMIT = 10 * 1024 * 1024;

/** How many pasted files are looked at in one paste. */
export const PASTE_FILES = 8;

/** The last part of a path, with either kind of slash. */
export function baseName(path: string): string {
  return path.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? "";
}

/** Whether a path starts at a root: `/usr/a`, `C:\a` or `\\server\share`. */
export function isAbsolutePath(path: string): boolean {
  return /^(?:[A-Za-z]:[\\/]|\\\\|\/)/.test(path);
}

/**
 * The paths the clipboard's text holds for the files that were pasted, by file name. A platform that puts the paths of
 * copied files on the clipboard as text (one to a line, or as `file://` addresses) already says what is wanted.
 */
export function pathsOnClipboard(text: string, names: readonly string[]): Map<string, string> {
  const found = new Map<string, string>();
  for (const path of absolutePaths(text)) {
    if (names.includes(baseName(path)) && !found.has(baseName(path))) {
      found.set(baseName(path), path);
    }
  }
  return found;
}

/**
 * Every absolute path in a text that lists files, one to a line: plain paths, `file://` addresses (what a file manager
 * puts on the clipboard on Linux), and nothing else, so a line such as `copy` or `cut` before them is ignored.
 */
export function absolutePaths(text: string): string[] {
  const paths: string[] = [];
  for (const line of text.split(/\r?\n/)) {
    const path = fromFileAddress(line.trim());
    if (path !== null && isAbsolutePath(path)) {
      paths.push(path);
    }
  }
  return paths;
}

/** `file:///a/b%20c` as `/a/b c`; anything else as it is; ``null`` for an empty line. */
function fromFileAddress(line: string): string | null {
  if (!line) {
    return null;
  }
  if (!/^file:\/\//i.test(line)) {
    return line;
  }
  try {
    const path = decodeURIComponent(line.replace(/^file:\/\//i, ""));
    // `file:///C:/a` is `C:/a`.
    return /^\/[A-Za-z]:/.test(path) ? path.slice(1) : path;
  } catch {
    return null;
  }
}

/** What to do with the files the workspace holds under a name. */
export type Choice = { kind: "none" } | { kind: "one"; path: string } | { kind: "many"; paths: string[] };

/**
 * Pick among the paths of one name. One is that file. Among several, the one the reader has open (or has in view in
 * the explorer) is the likely one, if exactly one of them is; otherwise they are asked.
 */
export function choose(candidates: readonly string[], preferred: readonly string[]): Choice {
  const unique = [...new Set(candidates)];
  const [only] = unique;
  if (only === undefined) {
    return { kind: "none" };
  }
  if (unique.length === 1) {
    return { kind: "one", path: only };
  }
  const likely = unique.filter((path) => preferred.includes(path));
  const [first] = likely;
  return likely.length === 1 && first !== undefined ? { kind: "one", path: first } : { kind: "many", paths: unique.slice(0, 20) };
}

/** A name as a file-search pattern: a character the pattern language reads as more than a letter matches any one letter. */
export function searchPattern(name: string): string {
  return `**/${name.replace(/[[\]{}*?!()]/g, "?")}`;
}

/** What the host does for one pasted file. */
export type Plan =
  | { kind: "path"; path: string }
  | { kind: "ask"; paths: string[] }
  | { kind: "save" }
  | { kind: "missing" };

/** What is known about one pasted file when its path is wanted. */
export interface Evidence {
  /** The path the clipboard's text gave for it, if it did. */
  known?: string | undefined;
  /** Files of the workspace with the same name and the very same bytes. Only meaningful when `hasBytes`. */
  identical: readonly string[];
  /** Files of the workspace with the same name. */
  byName: readonly string[];
  /** Whether the bytes came across, which is when a file can be told from another of its name, and kept. */
  hasBytes: boolean;
  /** The files the reader has open. */
  preferred: readonly string[];
}

/**
 * Decide what to do with a pasted file.
 *
 * With its bytes, the identical file of the workspace is the answer, and when there is none the file came from
 * elsewhere, so its bytes are kept and that copy is named. Without them (too large) only the name is left to go on, and
 * a name that no file of the workspace has is a file this cannot find.
 */
export function plan(evidence: Evidence): Plan {
  if (evidence.known !== undefined) {
    return { kind: "path", path: evidence.known };
  }
  const choice = choose(evidence.hasBytes ? evidence.identical : evidence.byName, evidence.preferred);
  if (choice.kind === "one") {
    return { kind: "path", path: choice.path };
  }
  if (choice.kind === "many") {
    return { kind: "ask", paths: choice.paths };
  }
  return evidence.hasBytes ? { kind: "save" } : { kind: "missing" };
}

/** A file name that can be written anywhere without leaving its folder or being refused by a platform. */
export function safeFileName(name: string): string {
  const base = baseName(name).replace(/[\u0000-\u001f<>:"|?*\\/]/g, "_").replace(/^\.+/, "_").trim();
  return base.slice(0, 120) || "pasted-file";
}
