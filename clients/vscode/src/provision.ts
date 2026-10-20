/**
 * Putting `zettcode-server` on the machine the first time the chat needs it.
 *
 * The extension installs it into an environment of its own (`globalStorage/server/venv`), which is where the agent it
 * drives lives too: the two are the same stack, and neither touches the reader's project or their own Python. `uv`
 * does the work when it is there, because it is quick and can fetch a Python of its own; otherwise the machine's
 * `python3` makes a virtual environment.
 */

import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import * as path from "node:path";
import * as vscode from "vscode";

import { environmentDirectory, executable, installPlan, serverHome, type Step, type Tools } from "./core/provision.js";

/** How long one command of an install may take: `uv` fetching a Python and pip's wheels are both slow the first time. */
const STEP_TIMEOUT_MS = 5 * 60_000;

/** Run one command to completion, collecting what it printed for the log. */
function run(step: Step, cwd: string): Promise<void> {
  return new Promise((resolve, reject) => {
    execFile(
      step.command,
      step.args,
      { cwd, timeout: STEP_TIMEOUT_MS, windowsHide: true, maxBuffer: 8 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (stdout) {
          process.stdout.write(stdout);
        }
        if (error) {
          reject(new Error(`${step.command} ${step.args.join(" ")}: ${stderr || error.message}`));
          return;
        }
        resolve();
      },
    );
  });
}

/** The first of these programs that the PATH has, or `null`. */
function onPath(names: string[]): string | null {
  const directories = (process.env.PATH ?? "").split(path.delimiter).filter(Boolean);
  const suffixes = process.platform === "win32" ? [".exe", ".cmd", ".bat", ""] : [""];
  for (const directory of directories) {
    for (const name of names) {
      for (const suffix of suffixes) {
        const candidate = path.join(directory, name + suffix);
        if (existsSync(candidate)) {
          return candidate;
        }
      }
    }
  }
  return null;
}

/** The tools an install may use, as the machine has them. */
export function findTools(): Tools {
  return {
    uv: onPath(["uv"]),
    python: onPath(process.platform === "win32" ? ["python", "python3"] : ["python3", "python"]),
  };
}

/**
 * The server the extension installed, or `null` when it could not be installed (no `uv`, no Python, no network).
 *
 * An environment that is already there answers at once, so this costs nothing after the first time. The install runs in
 * a notification that says what is happening, and its commands and their output go to the log.
 */
export async function installServer(options: {
  storage: string;
  output: vscode.OutputChannel;
}): Promise<string | null> {
  const home = serverHome(options.storage);
  const directory = environmentDirectory(home);
  const target = executable(directory);
  if (existsSync(target)) {
    return target;
  }
  const plan = installPlan({ directory, tools: findTools() });
  if (plan === null) {
    options.output.appendLine("[install] neither uv nor Python 3 is on the PATH; install zettcode-server yourself");
    return null;
  }
  options.output.appendLine(`[install] zettcode-server into ${directory}`);
  try {
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "ZettCode: installing the server",
        cancellable: false,
      },
      async (progress) => {
        for (const [index, step] of plan.entries()) {
          progress.report({ message: `${step.note} (${index + 1}/${plan.length})`, increment: 100 / plan.length });
          options.output.appendLine(`$ ${step.command} ${step.args.join(" ")}`);
          await run(step, home);
        }
      },
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    options.output.appendLine(`[install] failed: ${message}`);
    void vscode.window.showWarningMessage(
      `ZettCode could not install its server: ${message}. Install it yourself with “uv tool install zettcode-server”, or set zettcode.server.command.`,
    );
    return null;
  }
  if (!existsSync(target)) {
    options.output.appendLine(`[install] the install finished but ${target} is not there`);
    return null;
  }
  options.output.appendLine(`[install] zettcode-server is at ${target}`);
  return target;
}
