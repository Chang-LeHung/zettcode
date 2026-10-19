/** A line diff for the changes card: counts, and rows with a little context around each change. */

export type DiffKind = "ctx" | "add" | "del" | "gap";

export interface DiffRow {
  kind: DiffKind;
  text: string;
  /** The line number in the old text; absent for an addition or a gap. */
  oldLine?: number;
  /** The line number in the new text; absent for a deletion or a gap. */
  newLine?: number;
}

export interface FileDiff {
  added: number;
  removed: number;
  rows: DiffRow[];
  /** True when the rows were cut at `maxRows`. */
  truncated: boolean;
}

export interface DiffOptions {
  /** Unchanged lines kept on each side of a change. */
  context?: number;
  /** Most rows returned; the counts stay exact. */
  maxRows?: number;
}

/** The product of two line counts past which the middle is shown as one replacement, not aligned. */
const ALIGN_LIMIT = 4_000_000;

type Op = { t: "=" | "+" | "-"; a: number; b: number };

/** Split text into lines; a final newline does not make an extra empty line, and `null` is no lines. */
export function splitLines(text: string | null): string[] {
  if (text === null || text === "") {
    return [];
  }
  const lines = text.split(/\r?\n/);
  if (lines[lines.length - 1] === "") {
    lines.pop();
  }
  return lines;
}

/** Diff two texts. `null` stands for a file that does not exist on that side. */
export function diffText(before: string | null, after: string | null, options: DiffOptions = {}): FileDiff {
  const context = Math.max(0, options.context ?? 3);
  const maxRows = Math.max(1, options.maxRows ?? 400);
  const a = splitLines(before);
  const b = splitLines(after);
  const ops = align(a, b);
  let added = 0;
  let removed = 0;
  for (const op of ops) {
    if (op.t === "+") {
      added += 1;
    } else if (op.t === "-") {
      removed += 1;
    }
  }
  const keep = new Array<boolean>(ops.length).fill(false);
  ops.forEach((op, index) => {
    if (op.t === "=") {
      return;
    }
    for (let near = Math.max(0, index - context); near <= Math.min(ops.length - 1, index + context); near += 1) {
      keep[near] = true;
    }
  });
  const rows: DiffRow[] = [];
  let truncated = false;
  let skipped = 0;
  for (let index = 0; index < ops.length; index += 1) {
    const op = ops[index];
    if (op === undefined) {
      continue;
    }
    if (!keep[index]) {
      skipped += 1;
      continue;
    }
    if (skipped > 0) {
      if (rows.length > 0) {
        rows.push({ kind: "gap", text: `${skipped} unchanged line${skipped === 1 ? "" : "s"}` });
      }
      skipped = 0;
    }
    if (rows.length >= maxRows) {
      truncated = true;
      break;
    }
    if (op.t === "=") {
      rows.push({ kind: "ctx", text: a[op.a] ?? "", oldLine: op.a + 1, newLine: op.b + 1 });
    } else if (op.t === "-") {
      rows.push({ kind: "del", text: a[op.a] ?? "", oldLine: op.a + 1 });
    } else {
      rows.push({ kind: "add", text: b[op.b] ?? "", newLine: op.b + 1 });
    }
  }
  return { added, removed, rows, truncated };
}

/** Align two line lists: trim the shared ends, then take a longest common subsequence of the middle. */
function align(a: string[], b: string[]): Op[] {
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) {
    start += 1;
  }
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA -= 1;
    endB -= 1;
  }
  const ops: Op[] = [];
  for (let index = 0; index < start; index += 1) {
    ops.push({ t: "=", a: index, b: index });
  }
  const n = endA - start;
  const m = endB - start;
  if (n > 0 && m > 0 && n * m <= ALIGN_LIMIT) {
    ops.push(...lcsOps(a, b, start, endA, endB));
  } else {
    for (let index = start; index < endA; index += 1) {
      ops.push({ t: "-", a: index, b: start });
    }
    for (let index = start; index < endB; index += 1) {
      ops.push({ t: "+", a: endA, b: index });
    }
  }
  for (let offset = 0; offset < a.length - endA; offset += 1) {
    ops.push({ t: "=", a: endA + offset, b: endB + offset });
  }
  return ops;
}

function lcsOps(a: string[], b: string[], start: number, endA: number, endB: number): Op[] {
  const n = endA - start;
  const m = endB - start;
  const width = m + 1;
  const table = new Uint32Array((n + 1) * width);
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      const same = a[start + i] === b[start + j];
      const down = table[(i + 1) * width + j] ?? 0;
      const right = table[i * width + j + 1] ?? 0;
      table[i * width + j] = same ? (table[(i + 1) * width + j + 1] ?? 0) + 1 : Math.max(down, right);
    }
  }
  const ops: Op[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[start + i] === b[start + j]) {
      ops.push({ t: "=", a: start + i, b: start + j });
      i += 1;
      j += 1;
    } else if ((table[(i + 1) * width + j] ?? 0) >= (table[i * width + j + 1] ?? 0)) {
      ops.push({ t: "-", a: start + i, b: start + j });
      i += 1;
    } else {
      ops.push({ t: "+", a: start + i, b: start + j });
      j += 1;
    }
  }
  while (i < n) {
    ops.push({ t: "-", a: start + i, b: start + j });
    i += 1;
  }
  while (j < m) {
    ops.push({ t: "+", a: start + i, b: start + j });
    j += 1;
  }
  return ops;
}
