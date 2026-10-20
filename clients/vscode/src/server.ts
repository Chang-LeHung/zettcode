/** One `zettcode-server` per workspace, launched when the chat needs it and stopped with the extension. */

import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync } from "node:fs";
import * as net from "node:net";
import * as path from "node:path";
import * as vscode from "vscode";

import { ZettCodeClient } from "../../typescript/src/index.js";
import type { ServerStatus } from "./core/protocol.js";

export interface ServerState {
  status: ServerStatus;
  message: string;
  baseUrl: string | null;
}

interface LaunchOptions {
  autoStart: boolean;
  command: string;
  args: string[];
  port: number;
  externalUrl: string;
  externalToken: string;
  useToken: boolean;
  permission: string;
}

/** Owns the child process, its token, and the client the rest of the extension uses. */
export class ServerManager implements vscode.Disposable {
  private readonly changeEmitter = new vscode.EventEmitter<ServerState>();
  /** Fires whenever the child starts, becomes ready, stops, or fails. */
  readonly onDidChange = this.changeEmitter.event;

  private child: ChildProcessWithoutNullStreams | null = null;
  private client: ZettCodeClient | null = null;
  private starting: Promise<ZettCodeClient> | null = null;
  private state: ServerState = { status: "idle", message: "Not started", baseUrl: null };
  private shuttingDown = false;
  private disposed = false;
  private restartTimer: NodeJS.Timeout | null = null;
  private restarts = 0;
  private generation = 0;

  constructor(
    private readonly workspace: string,
    private readonly output: vscode.OutputChannel,
    /**
     * Install the server the extension runs itself, answering its path, or `null` when it could not be installed. Called
     * only when the configured command is nowhere to be found; `null` means the reader has to install it.
     */
    private readonly provision: (() => Promise<string | null>) | null = null,
  ) {}

  /** The current state, for the status bar and a newly opened webview. */
  get current(): ServerState {
    return this.state;
  }

  /** A client for the running server, starting it when necessary. */
  async getClient(force = false): Promise<ZettCodeClient> {
    if (this.client !== null && !force && this.state.status === "ready") {
      return this.client;
    }
    return this.start(force);
  }

  /** Start the server, or return the start already in flight. */
  async start(force = false): Promise<ZettCodeClient> {
    if (this.starting !== null) {
      return this.starting;
    }
    if (this.client !== null && !force && this.state.status === "ready") {
      return this.client;
    }
    this.starting = this.launch(force)
      .catch((error: unknown) => {
        if (!this.shuttingDown) {
          this.setState({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
            baseUrl: null,
          });
        }
        throw error;
      })
      .finally(() => {
        this.starting = null;
      });
    return this.starting;
  }

  /** Stop the child, then start a fresh one; the client and token change. */
  async restart(): Promise<ZettCodeClient> {
    this.shuttingDown = false;
    this.restarts = 0;
    if (this.restartTimer !== null) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    if (this.starting !== null) {
      await this.starting.catch(() => undefined);
    }
    await this.stopChild();
    this.client = null;
    this.state = { status: "idle", message: "Restarting", baseUrl: null };
    this.changeEmitter.fire(this.state);
    return this.start(true);
  }

  /** Stop the server this extension launched. An external server is left alone. */
  async shutdown(): Promise<void> {
    this.shuttingDown = true;
    if (this.restartTimer !== null) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    await this.stopChild();
    this.client = null;
    this.setState({ status: "idle", message: "Stopped", baseUrl: null });
  }

  dispose(): void {
    this.disposed = true;
    void this.shutdown().finally(() => this.changeEmitter.dispose());
  }

  private async launch(force: boolean): Promise<ZettCodeClient> {
    const options = this.readOptions();
    this.shuttingDown = false;
    const external = options.externalUrl.trim();
    if (external) {
      return this.connect(external, options.externalToken || process.env.ZETTCODE_SERVER_TOKEN || "");
    }
    if (!options.autoStart && !force) {
      const message = "The ZettCode server is not running. Run “ZettCode: Restart Server” to start it.";
      this.setState({ status: "idle", message, baseUrl: null });
      throw new Error(message);
    }
    if (!this.workspace) {
      const message = "Open a folder before starting ZettCode; the agent needs a workspace.";
      this.setState({ status: "error", message, baseUrl: null });
      throw new Error(message);
    }
    if (!vscode.workspace.isTrusted) {
      const message = "Trust this workspace before starting ZettCode; the agent runs commands in it.";
      this.setState({ status: "error", message, baseUrl: null });
      throw new Error(message);
    }

    this.setState({ status: "starting", message: "Starting zettcode-server…", baseUrl: null });
    const configuredPort = Number.isInteger(options.port) && options.port > 0 && options.port < 65_536 ? options.port : 3290;
    const port = (await isPortBusy(configuredPort)) ? await freePort() : configuredPort;
    const baseUrl = `http://127.0.0.1:${port}`;
    const token = options.useToken ? randomBytes(24).toString("hex") : "";
    const configured = resolveCommand(options.command, this.workspace);
    let command = configured;
    if (!isAvailable(configured)) {
      const installed = this.provision === null ? null : await this.provision();
      if (installed === null) {
        throw this.failed(
          new Error(
            `zettcode-server was not found. Install it with “uv tool install zettcode-server” (or “pip install zettcode-server”), or point zettcode.server.command at it.`,
          ),
          this.generation + 1,
        );
      }
      command = installed;
    }
    const args = [
      "--workspace",
      this.workspace,
      "--port",
      String(port),
      "--permission",
      options.permission,
      "--log-level",
      "warning",
      ...options.args,
    ];
    this.output.appendLine(`$ ${command} ${args.join(" ")}`);
    this.output.appendLine(`  token ${token ? "generated for this window" : "off"} · workspace ${this.workspace}`);

    const generation = ++this.generation;
    const env: NodeJS.ProcessEnv = { ...process.env, PYTHONUNBUFFERED: "1" };
    if (token) {
      env.ZETTCODE_SERVER_TOKEN = token;
    } else {
      delete env.ZETTCODE_SERVER_TOKEN;
    }
    let child: ChildProcessWithoutNullStreams;
    try {
      child = spawn(command, args, {
        cwd: this.workspace,
        env,
        windowsHide: true,
        // A Windows .cmd shim needs cmd.exe; an .exe does not.
        shell: process.platform === "win32" && /\.(cmd|bat)$/i.test(command),
      });
    } catch (error) {
      throw this.failed(error, generation);
    }
    this.child = child;
    const tail: string[] = [];
    const spawnState: { error: Error | null } = { error: null };
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      for (const line of chunk.split(/\r?\n/)) {
        if (line.trim()) {
          this.output.appendLine(`[server] ${line}`);
        }
      }
    });
    child.stderr.on("data", (chunk: string) => {
      for (const line of chunk.split(/\r?\n/)) {
        if (!line.trim()) {
          continue;
        }
        tail.push(line);
        if (tail.length > 20) {
          tail.shift();
        }
        this.output.appendLine(`[server] ${line}`);
      }
    });
    child.on("error", (error) => {
      spawnState.error = error;
      if (generation === this.generation) {
        this.output.appendLine(`[error] ${error.message}`);
      }
    });
    child.on("exit", (code, signal) => {
      if (generation !== this.generation || this.shuttingDown) {
        return;
      }
      this.child = null;
      this.client = null;
      const reason = signal ? `signal ${signal}` : `code ${code ?? "unknown"}`;
      const detail = tail.length ? `\n${tail.slice(-6).join("\n")}` : "";
      this.output.appendLine(`[server] exited with ${reason}${detail}`);
      this.setState({
        status: "error",
        message: `The server stopped (${reason}).${detail ? ` ${tail.slice(-2).join(" ")}` : ""}`,
        baseUrl: null,
      });
      this.scheduleRestart();
    });

    return this.waitForHealth(baseUrl, token, child, generation, tail, spawnState);
  }

  private async connect(baseUrl: string, token: string): Promise<ZettCodeClient> {
    this.setState({ status: "starting", message: `Connecting to ${baseUrl}…`, baseUrl: null });
    const client = new ZettCodeClient({ baseUrl, token: token || undefined });
    const health = await waitFor(() => client.health(), 10_000, 250);
    if (health.workspace && !samePath(health.workspace, this.workspace)) {
      this.output.appendLine(
        `[warn] ${baseUrl} serves ${health.workspace}, not ${this.workspace}; the transcript will show that workspace.`,
      );
    }
    this.client = client;
    this.restarts = 0;
    this.setState({
      status: "ready",
      message: `Connected to ${health.version} · ${baseUrl}`,
      baseUrl,
    });
    return client;
  }

  private async waitForHealth(
    baseUrl: string,
    token: string,
    child: ChildProcessWithoutNullStreams,
    generation: number,
    tail: string[],
    spawnState: { error: Error | null },
  ): Promise<ZettCodeClient> {
    const client = new ZettCodeClient({ baseUrl, token: token || undefined });
    const deadline = Date.now() + 25_000;
    let last = "";
    let exited = false;
    child.once("exit", () => {
      exited = true;
    });
    while (Date.now() < deadline && !this.shuttingDown && generation === this.generation) {
      if (exited || spawnState.error !== null) {
        break;
      }
      try {
        const health = await client.health();
        if (health.status === "ok") {
          if (health.workspace && !samePath(health.workspace, this.workspace)) {
            throw new Error(
              `The server started at ${baseUrl} serves ${health.workspace}, not ${this.workspace}. Another server may be using the port.`,
            );
          }
          this.client = client;
          this.restarts = 0;
          this.setState({
            status: "ready",
            message: `Ready · ${health.version} · ${baseUrl}`,
            baseUrl,
          });
          this.output.appendLine(`[server] ready at ${baseUrl} (${health.version})`);
          return client;
        }
      } catch (error) {
        last = error instanceof Error ? error.message : String(error);
      }
      await delay(150);
    }
    await this.stopChild(child);
    const detail = tail.slice(-6).join("\n");
    const message = spawnState.error
      ? `Could not start zettcode-server: ${spawnState.error.message}`
      : exited
        ? `zettcode-server exited before it was ready.${detail ? `\n${detail}` : ""}`
        : `zettcode-server did not become ready (${last || "timed out"}).${detail ? `\n${detail}` : ""}`;
    this.setState({ status: "error", message, baseUrl: null });
    throw new Error(message);
  }

  private scheduleRestart(): void {
    if (this.shuttingDown || this.restartTimer !== null) {
      return;
    }
    const options = this.readOptions();
    if (!options.autoStart || this.restarts >= 3) {
      return;
    }
    this.restarts += 1;
    const wait = 1500 * this.restarts;
    this.output.appendLine(`[server] restart ${this.restarts}/3 in ${wait}ms`);
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      void this.start(true).catch((error: unknown) => {
        this.output.appendLine(`[server] restart failed: ${error instanceof Error ? error.message : String(error)}`);
      });
    }, wait);
  }

  private async stopChild(child = this.child): Promise<void> {
    if (child === null) {
      return;
    }
    this.generation += 1;
    if (this.child === child) {
      this.child = null;
    }
    if (child.exitCode !== null || child.signalCode !== null) {
      return;
    }
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        try {
          child.kill("SIGKILL");
        } catch {
          // Already gone.
        }
        resolve();
      }, 2500);
      child.once("exit", () => {
        clearTimeout(timer);
        resolve();
      });
      try {
        child.kill("SIGTERM");
      } catch {
        clearTimeout(timer);
        resolve();
      }
    });
  }

  private failed(error: unknown, generation: number): Error {
    const message = error instanceof Error ? error.message : String(error);
    if (generation === this.generation) {
      this.setState({ status: "error", message, baseUrl: null });
    }
    return new Error(message);
  }

  private setState(state: ServerState): void {
    this.state = state;
    if (!this.disposed) {
      this.changeEmitter.fire(state);
    }
  }

  private readOptions(): LaunchOptions {
    const config = vscode.workspace.getConfiguration("zettcode");
    const permission = config.get<string>("permission", "ask");
    return {
      autoStart: config.get<boolean>("server.autoStart", true),
      command: config.get<string>("server.command", "zettcode-server"),
      args: config.get<string[]>("server.args", []),
      port: config.get<number>("server.port", 3290),
      externalUrl: config.get<string>("server.externalUrl", ""),
      externalToken: config.get<string>("server.externalToken", ""),
      useToken: config.get<boolean>("server.useToken", true),
      permission: ["deny", "ask", "safe", "auto"].includes(permission) ? permission : "ask",
    };
  }
}

function resolveCommand(command: string, workspace: string): string {
  const trimmed = command.trim();
  if (!trimmed) {
    return "zettcode-server";
  }
  const home = process.env.HOME ?? process.env.USERPROFILE ?? "";
  if (trimmed.startsWith("~/") && home) {
    return path.join(home, trimmed.slice(2));
  }
  if (trimmed.includes("/") || trimmed.includes("\\")) {
    return path.isAbsolute(trimmed) ? trimmed : path.resolve(workspace, trimmed);
  }
  const names =
    process.platform === "win32" ? [`${trimmed}.exe`, `${trimmed}.cmd`, `${trimmed}.bat`, trimmed] : [trimmed];
  const roots = [workspace];
  for (let index = 0; index < 3; index += 1) {
    const parent = path.dirname(roots[roots.length - 1] ?? workspace);
    if (!parent || parent === roots[roots.length - 1]) {
      break;
    }
    roots.push(parent);
  }
  const directories = [
    ...roots.flatMap((root) => [path.join(root, ".venv", "bin"), path.join(root, ".venv", "Scripts")]),
    ...(home
      ? [path.join(home, ".local", "bin"), path.join(home, ".local", "share", "uv", "tools", "zettcode-server", "bin")]
      : []),
    ...(process.env.PATH ?? "").split(path.delimiter).filter(Boolean),
  ];
  for (const directory of directories) {
    for (const name of names) {
      const candidate = path.join(directory, name);
      if (existsSync(candidate)) {
        return candidate;
      }
    }
  }
  return trimmed;
}

/** Whether a resolved command is something that can be run: a path that is there, or a name the PATH has. */
function isAvailable(command: string): boolean {
  if (command.includes("/") || command.includes("\\")) {
    return existsSync(command);
  }
  const suffixes = process.platform === "win32" ? [".exe", ".cmd", ".bat", ""] : [""];
  return (process.env.PATH ?? "")
    .split(path.delimiter)
    .filter(Boolean)
    .some((directory) => suffixes.some((suffix) => existsSync(path.join(directory, command + suffix))));
}

function samePath(left: string, right: string): boolean {
  const a = path.resolve(left);
  const b = path.resolve(right);
  return process.platform === "win32" ? a.toLowerCase() === b.toLowerCase() : a === b;
}

function isPortBusy(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = net.connect({ host: "127.0.0.1", port });
    const done = (busy: boolean): void => {
      socket.destroy();
      resolve(busy);
    };
    socket.setTimeout(500);
    socket.once("connect", () => done(true));
    socket.once("timeout", () => done(false));
    socket.once("error", () => done(false));
  });
}

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (address && typeof address === "object") {
        const port = address.port;
        server.close(() => resolve(port));
      } else {
        server.close(() => reject(new Error("Could not find a free loopback port")));
      }
    });
  });
}

async function waitFor<T>(operation: () => Promise<T>, timeout: number, interval: number): Promise<T> {
  const deadline = Date.now() + timeout;
  let last: unknown = null;
  while (Date.now() < deadline) {
    try {
      return await operation();
    } catch (error) {
      last = error;
      await delay(interval);
    }
  }
  throw last instanceof Error ? last : new Error(`Timed out after ${timeout}ms`);
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}
