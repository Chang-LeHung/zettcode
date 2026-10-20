/**
 * Where the extension keeps the server it installs for itself, and the commands that put it there.
 *
 * `zettcode-server` is a small Python program that depends on `zettcode` (the agent) and FastAPI; it is not a binary and
 * nothing about it is compiled for a platform. So "downloading it with the extension" means installing it once, into an
 * environment of the extension's own, where it lives beside the agent it drives — the same packages, the same versions,
 * outside the reader's project.
 */

import * as path from "node:path";

/** The package installed, with the floor the extension is written against. */
export const PACKAGE = "zettcode-server>=0.1.1";

/** One command of an install, with what to say about it. */
export interface Step {
  command: string;
  args: string[];
  note: string;
}

/** Whether the environment can be made with `uv`, which also installs a Python when the machine has none. */
export interface Tools {
  /** `uv` on the PATH, or `null`. */
  uv: string | null;
  /** A Python 3 on the PATH, or `null`. */
  python: string | null;
}

/** The folder the extension owns inside its global storage. */
export function serverHome(storage: string): string {
  return path.join(storage, "server");
}

/** The environment inside that folder; it holds the server and the agent it depends on. */
export function environmentDirectory(home: string): string {
  return path.join(home, "venv");
}

/** A path in the shape of the platform the server will run on, whatever the platform running the tests. */
function join(platform: string): (...parts: string[]) => string {
  return platform === "win32" ? path.win32.join : path.posix.join;
}

/** The server's console script inside an environment, which is what the extension spawns. */
export function executable(directory: string, platform: string = process.platform): string {
  return platform === "win32"
    ? join(platform)(directory, "Scripts", "zettcode-server.exe")
    : join(platform)(directory, "bin", "zettcode-server");
}

/** The Python inside an environment, for the steps that have to call it. */
function interpreter(directory: string, platform: string): string {
  return platform === "win32"
    ? join(platform)(directory, "Scripts", "python.exe")
    : join(platform)(directory, "bin", "python");
}

/**
 * The commands that make an environment holding the server, or `null` when the machine has neither `uv` nor Python.
 *
 * `uv` comes first: it makes the environment in a moment, and it can fetch a Python when the machine has none. Python's
 * own `venv` is the fallback, and its `pip` needs the machine to have the packages' build-free wheels, which these are.
 */
export function installPlan(options: {
  directory: string;
  tools: Tools;
  platform?: string;
}): Step[] | null {
  const platform = options.platform ?? process.platform;
  const directory = options.directory;
  if (options.tools.uv !== null) {
    return [
      { command: options.tools.uv, args: ["venv", directory], note: "making the environment" },
      {
        command: options.tools.uv,
        args: ["pip", "install", "--python", interpreter(directory, platform), PACKAGE],
        note: `installing ${PACKAGE}`,
      },
    ];
  }
  if (options.tools.python !== null) {
    return [
      { command: options.tools.python, args: ["-m", "venv", directory], note: "making the environment" },
      {
        command: interpreter(directory, platform),
        args: ["-m", "pip", "install", "--upgrade", PACKAGE],
        note: `installing ${PACKAGE}`,
      },
    ];
  }
  return null;
}
