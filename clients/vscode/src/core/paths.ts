/** Turning the paths an answer mentions into a file and a place in it. */

/** A path with the line and column a link asked for; both are one-based. */
export interface PathTarget {
  path: string;
  line?: number;
  column?: number;
}

const URL_SCHEME = /^(?:https?|mailto|tel|data):/i;
const WINDOWS_DRIVE = /^[A-Za-z]:[\\/]/;

/** The extensions and names that make a bare word look like a file rather than prose. */
const FILE_EXTENSION =
  /\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|json|jsonc|md|mdx|txt|toml|ya?ml|ini|cfg|conf|css|scss|sass|less|html?|vue|svelte|rs|go|java|kt|kts|c|h|cc|cpp|cxx|hpp|cs|rb|php|swift|sh|bash|zsh|fish|ps1|bat|cmd|sql|lock|env|tf|tfvars|proto|graphql|gql|xml|svg|png|jpe?g|gif|webp|pdf|ipynb|dockerfile)$/i;

const FILE_NAME = /^(?:Dockerfile|Makefile|Justfile|Procfile|README|LICENSE|Cargo\.toml|Gemfile|Rakefile)$/i;

/**
 * Read `path:line:column`, `path#L12`, or just a path.
 *
 * Returns `null` for a URL, an empty string, or prose. A Windows drive letter is not mistaken for a line suffix.
 */
export function parsePathTarget(raw: string): PathTarget | null {
  let value = raw.trim();
  if (!value) {
    return null;
  }
  if (value.startsWith("file://")) {
    try {
      value = decodeURIComponent(value.slice("file://".length));
    } catch {
      value = value.slice("file://".length);
    }
  }
  if (URL_SCHEME.test(value)) {
    return null;
  }
  value = stripWrapping(value);
  if (!value) {
    return null;
  }
  if (/\s/.test(value)) {
    return null;
  }

  const hash = /^(.*?)#L(\d+)(?:-L?\d+)?$/i.exec(value);
  if (hash?.[1] && hash[2] && !URL_SCHEME.test(hash[1])) {
    return withPlace(hash[1], Number(hash[2]), undefined);
  }

  const lineAndColumn = /^(.+):(\d+):(\d+)$/.exec(value);
  if (lineAndColumn?.[1] && lineAndColumn[2] && lineAndColumn[3]) {
    return withPlace(lineAndColumn[1], Number(lineAndColumn[2]), Number(lineAndColumn[3]));
  }

  const lineOnly = /^(.+):(\d+)$/.exec(value);
  if (lineOnly?.[1] && lineOnly[2]) {
    return withPlace(lineOnly[1], Number(lineOnly[2]), undefined);
  }

  return { path: value };
}

/** Whether a token is worth linking: it names a file by shape, not a sentence that happens to contain a dot. */
export function looksLikePath(value: string): boolean {
  const target = parsePathTarget(value);
  if (target === null) {
    return false;
  }
  const path = target.path;
  if (path.startsWith("-") || path.startsWith("@") || path.includes("*") || path.includes("?")) {
    return false;
  }
  if (!WINDOWS_DRIVE.test(path) && /^[A-Za-z][A-Za-z0-9+.-]*:/.test(path)) {
    return false;
  }
  if (target.path.includes("/") || target.path.includes("\\")) {
    return true;
  }
  return FILE_EXTENSION.test(path) || FILE_NAME.test(path);
}

/** Return the path as a link label: a workspace path, without the place suffix. */
export function pathLabel(raw: string): string {
  return parsePathTarget(raw)?.path ?? raw.trim();
}

function withPlace(path: string, line: number, column: number | undefined): PathTarget {
  const target: PathTarget = { path };
  if (Number.isFinite(line) && line > 0) {
    target.line = line;
  }
  if (column !== undefined && Number.isFinite(column) && column > 0) {
    target.column = column;
  }
  return target;
}

/**
 * Put attached files into a draft as their paths, one separated from the next and from what was already typed. A path
 * with a space in it is quoted so it still reads as one.
 */
export function withPaths(draft: string, paths: readonly string[]): string {
  const text = paths.map((path) => (/\s/.test(path) ? `"${path}"` : path)).join(" ");
  if (text === "") {
    return draft;
  }
  return draft === "" || /\s$/.test(draft) ? `${draft}${text} ` : `${draft} ${text} `;
}

function stripWrapping(value: string): string {
  if (value.length >= 2) {
    const first = value[0];
    const last = value[value.length - 1];
    if ((first === "<" && last === ">") || (first === "`" && last === "`") || (first === '"' && last === '"')) {
      return value.slice(1, -1).trim();
    }
  }
  return value;
}
