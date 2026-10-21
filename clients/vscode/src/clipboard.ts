/**
 * The files the operating system's clipboard holds.
 *
 * Copy a file in Finder, Explorer or a Linux file manager and the clipboard holds the file itself: its real path, however
 * large the file is and wherever it lives. A page in a webview is shown a copy of the contents and a name, never that
 * path, so the one place the path can be had is here, on the host, by asking the system. It is best effort: a system
 * without the tool, a clipboard with no files in it, a command that fails or hangs, all come back as no files, and the
 * caller falls back to the contents it was given.
 *
 * This only means something on the machine the reader is sitting at. A window that works on a remote machine (SSH, WSL,
 * a container) runs the host over there, where the clipboard is not the one they copied on; the caller does not ask.
 */

import { execFile } from "node:child_process";

import { absolutePaths } from "./core/pasted.js";

/** One command and its arguments. */
type Command = readonly [string, readonly string[]];

/** Runs a command and returns what it printed; an empty string for any failure. Replaceable, so a test needs no system. */
export type Runner = (command: string, args: readonly string[]) => Promise<string>;

/** Seconds a command may take before it is given up on: the clipboard answers at once or not at all. */
const TIMEOUT_MS = 3000;

/**
 * macOS: the file URLs on the general pasteboard, one path to a line. `osascript` ships with the system, and a script in
 * JavaScript can ask the pasteboard for URLs as the objects they are, which is how several files come back at once.
 */
const MAC_SCRIPT = [
  "ObjC.import('AppKit');",
  "const urls = $.NSPasteboard.generalPasteboard.readObjectsForClassesOptions(",
  "$.NSArray.arrayWithObject($.NSURL), $({ NSPasteboardURLReadingFileURLsOnlyKey: true }));",
  "const out = [];",
  "if (urls) { for (let i = 0; i < urls.count; i++) out.push(ObjC.unwrap(urls.objectAtIndex(i).path)); }",
  "out.join('\\n');",
].join(" ");

/** The commands to try on each system, in order; the first that prints any path is the answer. */
export function commandsFor(platform: string): Command[] {
  switch (platform) {
    case "darwin":
      return [["osascript", ["-l", "JavaScript", "-e", MAC_SCRIPT]]];
    case "win32":
      return [
        [
          "powershell",
          ["-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard -Format FileDropList | ForEach-Object { $_.FullName }"],
        ],
      ];
    case "linux":
      return [
        ["wl-paste", ["--type", "text/uri-list"]],
        ["xclip", ["-selection", "clipboard", "-t", "text/uri-list", "-o"]],
        ["xclip", ["-selection", "clipboard", "-t", "x-special/gnome-copied-files", "-o"]],
      ];
    default:
      return [];
  }
}

const run: Runner = (command, args) =>
  new Promise((resolve) => {
    execFile(
      command,
      [...args],
      { timeout: TIMEOUT_MS, maxBuffer: 1024 * 1024, windowsHide: true, encoding: "utf8" },
      (error, stdout) => resolve(error === null ? String(stdout) : ""),
    );
  });

/** The absolute paths of the files on the system clipboard; none when there are none, or when they cannot be had. */
export async function copiedFilePaths(platform: string = process.platform, runner: Runner = run): Promise<string[]> {
  for (const [command, args] of commandsFor(platform)) {
    const paths = absolutePaths(await runner(command, args));
    if (paths.length > 0) {
      return paths;
    }
  }
  return [];
}
