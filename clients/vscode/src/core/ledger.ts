/** What the files looked like before and after each request, kept in memory the way the editor's own review does. */

import { diffText } from "./diff.js";

export type ChangeStatus = "added" | "modified" | "deleted";

/** One file a request changed, with both sides so the editor can open a real diff. */
export interface FileChange {
  /** The path as the workspace names it (relative, forward slashes) or absolute when it lies outside. */
  path: string;
  status: ChangeStatus;
  before: string | null;
  after: string | null;
  added: number;
  removed: number;
}

/** What the webview shows of a change; the text stays in the host. */
export interface ChangeSummary {
  path: string;
  status: ChangeStatus;
  added: number;
  removed: number;
}

/** Files larger than this are not snapshotted: the card would be a wall, and the memory would be real. */
export const MAX_TRACKED_BYTES = 1_000_000;

/** Requests whose snapshots are kept; older ones are forgotten so a long day stays small. */
export const MAX_TRACKED_TURNS = 40;

/** Tools whose arguments name a file they change. Removing a file is a shell command, not a tool, so it is not here. */
const FILE_TOOLS = new Set(["write_file", "write", "edit", "replace_in_file"]);

/** Whether a tool call changes the file its `path` argument names. */
export function changesFile(toolName: string): boolean {
  return FILE_TOOLS.has(toolName.replace(/^.*__/, "").toLowerCase());
}

/** Reads a file by the path the ledger holds: `null` when it does not exist, and a throw when it cannot be tracked. */
export type Reader = (path: string) => Promise<string | null>;

/** One replacement an edit call made; used to rebuild the old text when the snapshot lost a race with the tool. */
export interface EditPair {
  oldText: string;
  newText: string;
}

/** Files whose last known content is remembered between requests. */
const MAX_KNOWN = 300;

export class ChangeLedger {
  private readonly befores = new Map<string, Map<string, string | null>>();
  private readonly edits = new Map<string, Map<string, EditPair[]>>();
  private readonly settled = new Map<string, FileChange[]>();
  private readonly untracked = new Map<string, Set<string>>();
  /** What a file held the last time we looked, so a request that writes it can say what it replaced. */
  private readonly known = new Map<string, string | null>();

  constructor(
    private readonly read: Reader,
    private readonly root: string,
  ) {}

  /** The key a path is stored under: relative to the workspace when it lies inside it. */
  key(path: string): string {
    const normal = path.replace(/\\/g, "/");
    const root = this.root.replace(/\\/g, "/").replace(/\/+$/, "");
    if (root && (normal === root || normal.startsWith(`${root}/`))) {
      return normal.slice(root.length + 1);
    }
    return normal.replace(/^\.\//, "");
  }

  /**
   * Note what a file holds right now, without changing any request's record. The model reads a file before it
   * edits it, and the tool that edits can finish before the event announcing it has crossed the wire, so the
   * read is the one moment the old text is certain.
   */
  async observe(path: string): Promise<void> {
    const key = this.key(path);
    if (!key || this.known.has(key) || this.inFlight(key)) {
      return;
    }
    try {
      this.remember(key, await this.read(key));
    } catch {
      // A file too large or not text is simply not tracked.
    }
  }

  /**
   * Remember what a file held before the request first touched it. Later touches of the same file do nothing.
   *
   * `edits` are the replacements an edit call is about to make and `written` is the whole text a write call is about to
   * put there. They let the ledger tell a file that is still as it was from one the tool has already changed, and so
   * tell the remembered text (right in the second case) from a stale one (wrong in the first, when something else
   * changed the file since it was last seen).
   */
  async touch(turnId: string, path: string, edits: EditPair[] = [], written?: string): Promise<void> {
    const key = this.key(path);
    if (!key) {
      return;
    }
    if (edits.length) {
      let byFile = this.edits.get(turnId);
      if (byFile === undefined) {
        byFile = new Map();
        this.edits.set(turnId, byFile);
      }
      byFile.set(key, [...(byFile.get(key) ?? []), ...edits]);
    }
    let files = this.befores.get(turnId);
    if (files === undefined) {
      files = new Map();
      this.befores.set(turnId, files);
      this.prune();
    }
    if (files.has(key)) {
      return;
    }
    files.set(key, null);
    try {
      files.set(key, this.known.has(key) ? await this.beforeOf(key, edits, written) : await this.read(key));
    } catch {
      let skipped = this.untracked.get(turnId);
      if (skipped === undefined) {
        skipped = new Set();
        this.untracked.set(turnId, skipped);
      }
      skipped.add(key);
    }
  }

  /** Read every touched file again and keep those that really differ. */
  async settle(turnId: string): Promise<FileChange[]> {
    const files = this.befores.get(turnId);
    if (files === undefined) {
      return [];
    }
    const changes: FileChange[] = [];
    for (const [key, snapshot] of files) {
      if (this.untracked.get(turnId)?.has(key)) {
        continue;
      }
      let after: string | null;
      try {
        after = await this.read(key);
      } catch {
        continue;
      }
      this.remember(key, after);
      let before = snapshot;
      if (before === after && after !== null) {
        before = unapply(after, this.edits.get(turnId)?.get(key) ?? []) ?? before;
      }
      if (before === after) {
        continue;
      }
      const stat = diffText(before, after, { context: 0, maxRows: 1 });
      changes.push({
        path: key,
        status: before === null ? "added" : after === null ? "deleted" : "modified",
        before,
        after,
        added: stat.added,
        removed: stat.removed,
      });
    }
    changes.sort((left, right) => left.path.localeCompare(right.path));
    this.settled.set(turnId, changes);
    return changes;
  }

  changes(turnId: string): FileChange[] {
    return this.settled.get(turnId) ?? [];
  }

  find(turnId: string, path: string): FileChange | undefined {
    const key = this.key(path);
    return this.changes(turnId).find((change) => change.path === key);
  }

  summaries(turnId: string): ChangeSummary[] {
    return this.changes(turnId).map(({ path, status, added, removed }) => ({ path, status, added, removed }));
  }

  turnIds(): string[] {
    return [...this.settled.keys()];
  }

  clear(): void {
    this.known.clear();
    this.edits.clear();
    this.untracked.clear();
    this.befores.clear();
    this.settled.clear();
  }

  /**
   * What the file held before the tool changed it, when something is remembered about it.
   *
   * The remembered text is right for a tool that has already run (the file now shows its result) and stale for one
   * that has not, if the file changed behind the ledger's back since (a shell command, the reader, a checkout).
   * Reading the file now settles which: a write has landed when the file holds exactly what it wrote, and an edit has
   * when its replacements can be undone on the file. Anything else leaves the file as the tool will find it.
   */
  private async beforeOf(key: string, edits: EditPair[], written: string | undefined): Promise<string | null> {
    const remembered = this.known.get(key) ?? null;
    if (written === undefined && edits.length === 0) {
      return remembered;
    }
    const now = await this.read(key);
    if (written !== undefined) {
      return now === written ? remembered : now;
    }
    if (now === null) {
      return remembered;
    }
    if (now === remembered) {
      return now;
    }
    // The file is not as it was remembered. If none of the new text is in it, the edit has not landed and the file
    // is simply what the edit will replace; if it has, the old text is only believed when applying the edit to it
    // gives back exactly what is there now.
    if (!edits.some((edit) => edit.newText !== "" && now.includes(edit.newText))) {
      return now;
    }
    const rebuilt = unapply(now, edits);
    if (rebuilt !== null && applyAll(rebuilt, edits) === now) {
      return rebuilt;
    }
    return remembered;
  }

  private inFlight(key: string): boolean {
    for (const [turnId, files] of this.befores) {
      if (files.has(key) && !this.settled.has(turnId)) {
        return true;
      }
    }
    return false;
  }

  private remember(key: string, text: string | null): void {
    this.known.delete(key);
    this.known.set(key, text);
    while (this.known.size > MAX_KNOWN) {
      const oldest = this.known.keys().next().value;
      if (oldest === undefined) {
        return;
      }
      this.known.delete(oldest);
    }
  }

  private prune(): void {
    while (this.befores.size > MAX_TRACKED_TURNS) {
      const oldest = this.befores.keys().next().value;
      if (oldest === undefined) {
        return;
      }
      this.befores.delete(oldest);
      this.edits.delete(oldest);
      this.untracked.delete(oldest);
      this.settled.delete(oldest);
    }
  }
}

/** Undo edit calls on the text they produced; `null` when one of them cannot be found, so nothing is guessed. */
export function unapply(after: string, edits: EditPair[]): string | null {
  if (edits.length === 0) {
    return null;
  }
  let text = after;
  for (let index = edits.length - 1; index >= 0; index -= 1) {
    const edit = edits[index];
    if (edit === undefined) {
      continue;
    }
    const at = edit.newText === "" ? -1 : text.lastIndexOf(edit.newText);
    if (at < 0) {
      return null;
    }
    text = text.slice(0, at) + edit.oldText + text.slice(at + edit.newText.length);
  }
  return text;
}

/** Apply edit calls the way the tool does, each to the first place its old text is found; `null` when one is not. */
export function applyAll(before: string, edits: EditPair[]): string | null {
  let text = before;
  for (const edit of edits) {
    const at = edit.oldText === "" ? -1 : text.indexOf(edit.oldText);
    if (at < 0) {
      return null;
    }
    text = text.slice(0, at) + edit.newText + text.slice(at + edit.oldText.length);
  }
  return text;
}
