/** The chat view: one webview, the state it shows, and the server calls behind its buttons. */

import { createHash, randomBytes } from "node:crypto";
import * as path from "node:path";
import * as vscode from "vscode";

import { ChangeLedger, changesFile, MAX_TRACKED_BYTES, type EditPair } from "./core/ledger.js";
import { diffText } from "./core/diff.js";
import { type Conversation, Conversations, newConversation } from "./core/conversations.js";
import {
  type Api,
  APIS,
  apiChange,
  apiKeys,
  maxTemperature,
  parseTemperature,
  searchKeys,
  searchProblem,
} from "./core/model-form.js";
import { copiedFilePaths } from "./clipboard.js";
import { diffUri } from "./diffs.js";
import { RunFailedError, RunCancelledError, ZettCodeClient, ZettCodeError } from "../../typescript/src/index.js";
import type {
  ApprovalPolicy,
  ContextReport,
  CurrentSession,
  Health,
  ImageInput,
  MentionInfo,
  Message,
  ModelInfo,
  ModelInput,
  ModelUpdate,
  Permission,
  PendingRequest,
  ResumeInfo,
  Run,
  RunEvent,
  RunResult,
  SelfCompaction,
  SessionInfo,
  Settings,
  StreamFrame,
} from "../../typescript/src/index.js";
import type { CommandInfo } from "../../typescript/src/types.js";
import type {
  AttachedImage,
  HostMessage,
  PastedFile,
  SessionRow,
  WebviewMessage,
  WebviewState,
} from "./core/protocol.js";
import { parsePathTarget } from "./core/paths.js";
import { approvalsFor } from "./core/permission.js";
import { pageStart, requestsBefore } from "./core/paging.js";
import { baseName, PASTE_FILES, pathsOnClipboard, plan, safeFileName, searchPattern } from "./core/pasted.js";
import { readRemembered, remember, wantedPermission } from "./core/remember.js";
import { chatHtml } from "./html.js";
import {
  announcement,
  applyEvent,
  cancelTurn,
  createTurn,
  echoSteer,
  failTurn,
  finishTurn,
  markAnswer,
  markApproval,
  newTurnId,
  restoreTurns,
  retractSteer,
  type Turn,
} from "./core/state.js";
import { ServerManager } from "./server.js";
import { showDoctorPanel, showPluginsPanel, showUsagePanel } from "./usage.js";

const SESSION_KEY = "zettcode.sessionId";
/** The shell permissions the reader chose, per session and last (see core/remember.ts). */
const PERMISSION_KEY = "zettcode.permissions";
const MAX_IMAGES = 4;
/** What a model takes as a picture; every other file is attached by its path. */
const IMAGE_EXTENSION = /\.(?:png|jpe?g|gif|webp)$/i;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;

/** One prompt to run, as the composer and a command's preset both give it. */
interface PromptRequest {
  /** What the model reads. */
  text: string;
  /** The line the conversation shows, when it is not `text` (a command's preset behind the command as typed). */
  shown?: string;
  images?: ImageInput[];
  /** Refuse instead of steering when a run is in flight: a command's preset is a turn of its own. */
  refuseWhenBusy?: boolean;
}

const IMMEDIATE_EVENTS = new Set([
  "tool_started",
  "tool_finished",
  "server_tool_started",
  "server_tool_finished",
  "approval_requested",
  "question_asked",
  "compaction_finished",
  "notice",
  "model_stopped",
  "steered",
]);

/** Everything the chat view does, whether or not it is visible. */
export class ChatViewProvider implements vscode.WebviewViewProvider, vscode.Disposable {
  private view: vscode.WebviewView | null = null;
  private client: ZettCodeClient | null = null;
  private health: Health | null = null;
  private settings: Settings | null = null;
  private models: ModelInfo[] = [];
  private session: CurrentSession | null = null;
  private sessions: SessionRow[] = [];
  private selfCompaction: SelfCompaction | null = null;
  private contextReport: ContextReport | null = null;
  private resumable: ResumeInfo | null = null;
  /** What the plugins registered on `ctx.commands`, as the composer's `/` menu offers them. */
  private pluginCommands: CommandInfo[] = [];

  /**
   * What belongs to one conversation and not to the window: its transcript, and the run going in it. The conversation on
   * show is `conv`; one that is running when the reader looks elsewhere stays in `convs` and keeps writing to its own
   * turns, so coming back to it finds the run where it got to (see core/conversations.ts).
   */
  private readonly convs = new Conversations();
  private get conv(): Conversation {
    return this.convs.current;
  }

  private get pending(): PendingRequest | null {
    return this.conv.pending;
  }
  private set pending(value: PendingRequest | null) {
    this.conv.pending = value;
  }
  private get turns(): Turn[] {
    return this.conv.turns;
  }
  private set turns(value: Turn[]) {
    this.conv.turns = value;
  }
  /** How many turns at the front of `turns` the view has not been sent: a reloaded conversation shows its latest page. */
  private get hidden(): number {
    return this.conv.hidden;
  }
  private set hidden(value: number) {
    this.conv.hidden = value;
  }
  /** The turn the run in progress is writing to, so a steer can be drawn in it at once. */
  private get running(): Turn | null {
    return this.conv.running;
  }
  private set running(value: Turn | null) {
    this.conv.running = value;
  }
  private get run(): Run | null {
    // Only `startRun` stores one, and what it stores is the client's own `Run`; the module that holds it asks no more
    // of it than that it can be stopped.
    return this.conv.run as Run | null;
  }
  private set run(value: Run | null) {
    this.conv.run = value;
  }
  private get busy(): boolean {
    return this.conv.busy;
  }
  private set busy(value: boolean) {
    this.conv.busy = value;
  }
  private initialized = false;
  private initializing: Promise<void> | null = null;
  private disposed = false;
  /** The first load failed for a reason other than the server, so the view must not wait for it any longer. */
  private loadFailed = false;
  /** What is being loaded after the first load, for the view to say; see `WebviewState.loading`. */
  private loading: string | null = null;
  private readonly turnTimers = new Map<string, NodeJS.Timeout>();
  private deltaTimer: NodeJS.Timeout | null = null;
  private deltaTurn: Turn | null = null;
  private deltaText = "";
  private deltaReasoning = "";
  private readonly serverListener: vscode.Disposable;
  private ledgerValue: ChangeLedger | null = null;
  private titleTask: Promise<void> | null = null;
  private contextTimer: ReturnType<typeof setTimeout> | null = null;
  /** Asks the server for messages other sessions sent, which are answered as ordinary turns. */
  private messageTimer: ReturnType<typeof setInterval> | null = null;
  /** True while one message is being taken, so two polls cannot answer the same one. */
  private takingMessage = false;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly server: ServerManager,
    private readonly context: vscode.ExtensionContext,
    private readonly output: vscode.OutputChannel,
  ) {
    this.serverListener = server.onDidChange((state) => {
      if (state.status === "ready" && this.initialized && !this.disposed) {
        this.client = null;
        // A restarted server has none of the runs the old one had, so nothing here is still running.
        this.convs.reset();
        void this.refreshAll().catch((error: unknown) => this.say("error", messageOf(error)));
      }
      this.postState();
    });
  }

  // -- what a request changed ---------------------------------------------

  /** The ledger of this window's workspace; `null` without a folder, where there is nothing to diff. */
  get ledger(): ChangeLedger | null {
    if (this.ledgerValue === null) {
      const folder = vscode.workspace.workspaceFolders?.[0]?.uri;
      if (folder === undefined) {
        return null;
      }
      this.ledgerValue = new ChangeLedger((key) => this.readForLedger(key), folder.fsPath);
    }
    return this.ledgerValue;
  }

  private uriForKey(key: string): vscode.Uri | null {
    if (path.isAbsolute(key) || /^[A-Za-z]:[\\/]/.test(key)) {
      return vscode.Uri.file(key);
    }
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri;
    return folder === undefined ? null : vscode.Uri.joinPath(folder, ...key.split("/").filter(Boolean));
  }

  private async readForLedger(key: string): Promise<string | null> {
    const uri = this.uriForKey(key);
    if (uri === null) {
      throw new Error("no workspace");
    }
    let stat: vscode.FileStat;
    try {
      stat = await vscode.workspace.fs.stat(uri);
    } catch {
      return null;
    }
    if (stat.size > MAX_TRACKED_BYTES || (stat.type & vscode.FileType.Directory) !== 0) {
      throw new Error("not tracked");
    }
    const bytes = await vscode.workspace.fs.readFile(uri);
    if (bytes.includes(0)) {
      throw new Error("binary");
    }
    return new TextDecoder().decode(bytes);
  }

  /** Before a file tool runs, remember what it will replace; after a read, remember what the file held. */
  private trackFrame(turn: Turn, event: RunEvent): void {
    const ledger = this.ledger;
    if (ledger === null) {
      return;
    }
    if (event.type === "tool_started" && changesFile(event.name)) {
      const target = stringOf(event.arguments, "path", "file_path", "file");
      if (target) {
        // A write names the whole text it will leave; the ledger compares it with the file to tell whether it landed.
        const content = /(^|__)write(_file)?$/i.test(event.name) ? event.arguments.content : undefined;
        void ledger
          .touch(turn.id, target, editPairs(event.arguments), typeof content === "string" ? content : undefined)
          .catch(() => undefined);
      }
    } else if (event.type === "tool_finished" && /(^|__)(read_file|read)$/i.test(event.name)) {
      const call = findTool(turn, event.call_id);
      const target = call ? stringOf(call.arguments, "path", "file_path", "file") : "";
      if (target) {
        void ledger.observe(target).catch(() => undefined);
      }
    }
  }

  private async settleChanges(turn: Turn): Promise<void> {
    const ledger = this.ledger;
    if (ledger === null) {
      return;
    }
    await ledger.settle(turn.id).catch(() => []);
    this.postChanges(turn.id);
  }

  private postChanges(turnId: string): void {
    const files = this.ledger?.summaries(turnId) ?? [];
    if (files.length) {
      this.post({ type: "changes", turnId, files });
    }
  }

  private postAllChanges(): void {
    for (const turnId of this.ledger?.turnIds() ?? []) {
      this.postChanges(turnId);
    }
  }

  async openDiff(turnId: string, file: string): Promise<void> {
    const change = this.ledger?.find(turnId, file);
    if (change === undefined) {
      this.post({ type: "notice", level: "info", text: "That change is no longer kept in memory." });
      return;
    }
    const title = `${path.basename(change.path)} (${change.status === "added" ? "new" : change.status === "deleted" ? "deleted" : "this request"})`;
    await vscode.commands.executeCommand(
      "vscode.diff",
      diffUri("before", turnId, change.path),
      diffUri("after", turnId, change.path),
      title,
      { preview: true },
    );
  }

  private viewDiff(turnId: string, file: string): void {
    const change = this.ledger?.find(turnId, file);
    if (change === undefined) {
      return;
    }
    const diff = diffText(change.before, change.after, { context: 3, maxRows: 600 });
    this.post({ type: "diff-rows", turnId, path: change.path, rows: diff.rows, truncated: diff.truncated });
  }

  // -- the view ----------------------------------------------------------

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.joinPath(this.extensionUri, "media"),
        vscode.Uri.joinPath(this.extensionUri, "dist"),
      ],
    };
    view.webview.html = this.html(view.webview);
    view.webview.onDidReceiveMessage((message: WebviewMessage) => {
      void this.dispatch(message).catch((error: unknown) => this.say("error", messageOf(error)));
    });
    view.onDidDispose(() => {
      this.setFocused(false);
      if (this.view === view) {
        this.view = null;
      }
    });
    void this.initialize().catch((error: unknown) => {
      this.say("error", messageOf(error));
    });
  }

  dispose(): void {
    this.disposed = true;
    this.serverListener.dispose();
    for (const timer of this.turnTimers.values()) {
      clearTimeout(timer);
    }
    this.turnTimers.clear();
    if (this.contextTimer !== null) {
      clearTimeout(this.contextTimer);
      this.contextTimer = null;
    }
    if (this.messageTimer !== null) {
      clearInterval(this.messageTimer);
      this.messageTimer = null;
    }
    this.clearDeltas();
    this.run?.abort();
    this.run = null;
  }

  /** Start the server, load the session, and fill the view. Called once per extension. */
  async initialize(): Promise<void> {
    if (this.initialized) {
      this.postState();
      this.postTurns();
      return;
    }
    if (this.initializing !== null) {
      return this.initializing;
    }
    this.initializing = this.load()
      .catch((error: unknown) => {
        this.loadFailed = true;
        this.postState();
        throw error;
      })
      .finally(() => {
        this.initializing = null;
      });
    return this.initializing;
  }

  private async load(): Promise<void> {
    this.postState();
    const client = await this.ensureClient();
    this.client = client;
    const health = await client.health();
    this.health = health;
    const models = await client.models();
    this.models = models.models;
    if (!health.ready) {
      this.session = null;
      this.settings = null;
      this.initialized = true;
      this.postState();
      this.postTurns();
      this.post({ type: "model-form", open: true });
      return;
    }
    await this.readSettings();
    await this.restoreSession(client);
    await this.loadHistory();
    await this.readExtras();
    this.initialized = true;
    this.postState();
    this.postTurns();
    void this.refreshSessions(false).catch(() => undefined);
    this.watchMessages();
  }

  /** Read the server's state again; used after a restart and by the refresh button. */
  async refreshAll(): Promise<void> {
    const client = await this.ensureClient();
    this.client = client;
    const health = await client.health();
    this.health = health;
    const models = await client.models();
    this.models = models.models;
    if (!health.ready) {
      this.session = null;
      this.settings = null;
      this.initialized = true;
      this.postState();
      this.postTurns();
      this.post({ type: "model-form", open: true });
      return;
    }
    await this.readSettings();
    const previousId = this.session?.id;
    await this.restoreSession(client);
    const nextSession = await client.session.info();
    const changed = previousId !== nextSession.id;
    this.session = nextSession;
    if (changed) {
      await this.loadHistory();
    }
    await this.readExtras();
    this.initialized = true;
    if (changed) {
      this.postTurns();
    }
    this.postState();
    void this.refreshSessions(false).catch(() => undefined);
    this.watchMessages();
  }

  /**
   * Look for messages from other sessions, and answer each as a turn of its own.
   *
   * A received message is meant to behave like one the reader typed, so it goes through the same stream a prompt
   * does: the sender's name on the row, the answer streamed into the transcript, approvals and questions answered the
   * way a prompt's are. The server holds it until the chat asks, which is what keeps the transcript in one place.
   */
  private watchMessages(): void {
    if (this.messageTimer !== null) {
      return;
    }
    this.messageTimer = setInterval(() => {
      void this.takeMessage().catch(() => undefined);
    }, 2500);
  }

  private async takeMessage(): Promise<void> {
    if (this.busy || this.takingMessage || !this.initialized || this.health?.ready !== true) {
      return;
    }
    this.takingMessage = true;
    try {
      const client = await this.ensureClient();
      const waiting = await client.messages();
      const first = waiting[0];
      if (first === undefined || this.busy) {
        return;
      }
      const turn = createTurn(first.text, [], Date.now());
      turn.from = { id: first.sender_id, name: first.sender };
      this.turns.push(turn);
      this.postTurn(turn, true);
      await this.startRun(client.relay(first.id, this.runOptions([])), turn);
    } finally {
      this.takingMessage = false;
    }
  }

  /** Say that a load is going on while `work` runs, so the view can show it; it is said again, empty, however `work` ends. */
  private async whileLoading<T>(text: string, work: () => Promise<T>): Promise<T> {
    this.loading = text;
    this.postState();
    try {
      return await work();
    } finally {
      this.loading = null;
      this.postState();
    }
  }

  private async ensureClient(): Promise<ZettCodeClient> {
    if (this.client !== null && this.health?.status === "ok" && this.server.current.status === "ready") {
      return this.client;
    }
    this.client = await this.server.getClient();
    return this.client;
  }

  /** Read which model is in use and the list that marks it, together, so the two always agree. */
  private async readModels(client: ZettCodeClient): Promise<void> {
    try {
      const [models, settings] = await Promise.all([client.models(), client.settings()]);
      this.models = models.models;
      this.settings = settings;
    } catch (error) {
      this.output.appendLine(`[models] ${messageOf(error)}`);
    }
  }

  private async readSettings(): Promise<void> {
    if (this.client === null) {
      return;
    }
    this.settings = await this.client.settings();
  }

  private async restoreSession(client: ZettCodeClient): Promise<void> {
    const enabled = vscode.workspace.getConfiguration("zettcode").get<boolean>("restoreSession", true);
    const wanted = this.context.workspaceState.get<string>(SESSION_KEY);
    this.session = await client.session.info();
    if (!enabled || !wanted || this.session.id === wanted) {
      return;
    }
    try {
      this.session = await client.sessions.open(wanted);
      this.output.appendLine(`[session] reopened ${wanted}`);
    } catch (error) {
      this.output.appendLine(`[session] could not reopen ${wanted}: ${messageOf(error)}`);
      this.context.workspaceState.update(SESSION_KEY, undefined);
    }
  }

  private async loadHistory(): Promise<void> {
    if (this.client === null || this.session === null) {
      this.turns = [];
      this.hidden = 0;
      return;
    }
    try {
      // The whole conversation, not only what the model still works from: what a compaction folded away is shown too,
      // a page at a time (see `hidden`), with each summary where it was made.
      const messages: Message[] = await this.client.session.history({ full: true });
      this.turns = restoreTurns(messages);
      this.hidden = pageStart(this.turns);
    } catch (error) {
      this.output.appendLine(`[history] ${messageOf(error)}`);
      this.turns = [];
      this.hidden = 0;
    }
    if (this.session !== null) {
      this.context.workspaceState.update(SESSION_KEY, this.session.id);
    }
  }

  private async readExtras(): Promise<void> {
    if (this.client === null || this.health?.ready !== true) {
      this.selfCompaction = null;
      this.contextReport = null;
      this.resumable = null;
      return;
    }
    const client = this.client;
    // Every way into a session ends here, and opening one puts back the model it last used: read the model, and the
    // list that marks it, only now, or the chip and the menu would show the model from before the switch.
    await this.readModels(client);
    await this.applyRememberedPermission();
    const [selfCompaction, contextReport, resumable, runState, commands] = await Promise.all([
      client.selfCompaction().catch(() => null),
      client.session.context().catch(() => null),
      client.session.resumable().catch(() => null),
      client.runState().catch(() => null),
      client.commands().catch(() => this.pluginCommands),
    ]);
    this.selfCompaction = selfCompaction;
    this.contextReport = contextReport;
    this.resumable = resumable;
    this.pending = runState?.pending ?? null;
    this.pluginCommands = commands;
  }

  // -- messages from the webview ----------------------------------------

  private async dispatch(message: WebviewMessage): Promise<void> {
    switch (message.type) {
      case "ready":
        await this.initialize();
        this.postAllChanges();
        return;
      case "focused":
        this.setFocused(message.focused);
        return;
      case "prompt":
        await this.sendPrompt({ text: message.text, images: message.images });
        return;
      case "run-command":
        await this.runCommand(message.name, message.argument);
        return;
      case "steer":
        await this.steer(message.text);
        return;
      case "load-earlier":
        this.loadEarlier();
        return;
      case "cancel":
        await this.stop();
        return;
      case "approve":
        await this.approve(message.callId, message.approve, message.remember);
        return;
      case "answer":
        await this.answer(message.callId, message.answer);
        return;
      case "open":
        await this.openTarget(message.target);
        return;
      case "open-diff":
        await this.openDiff(message.turnId, message.path);
        return;
      case "view-diff":
        this.viewDiff(message.turnId, message.path);
        return;
      case "open-external":
        await this.openExternal(message.url);
        return;
      case "new-session":
        await this.newSession();
        return;
      case "open-session":
        await this.openSession(message.id);
        return;
      case "refresh-sessions":
        await this.refreshSessions(true);
        return;
      case "rename-session":
        await this.renameSession(message.title);
        return;
      case "name-session":
        await this.nameSession();
        return;
      case "fork-session":
        await this.forkSession();
        return;
      case "compact":
        await this.compactSession();
        return;
      case "export":
        await this.exportSession();
        return;
      case "usage":
        await this.showUsage();
        return;
      case "doctor":
        await this.showDoctor();
        return;
      case "plugins":
        await this.showPlugins();
        return;
      case "add-model":
        await this.addModel(message.model);
        return;
      case "update-model":
        await this.editModel(message.name, message.changes);
        return;
      case "remove-model":
        await this.removeModel(message.name);
        return;
      case "set-model":
        await this.updateSettings({ model: message.name });
        return;
      case "set-effort":
        await this.updateSettings({ effort: message.effort });
        return;
      case "set-permission":
        await this.updateSettings({ permission: message.permission });
        return;
      case "set-harness":
        await this.updateSettings({ harness: message.on });
        return;
      case "set-compact":
        await this.updateSettings({ compact_percent: message.percent });
        return;
      case "set-self-compaction":
        await this.setSelfCompaction(message.choice);
        return;
      case "refresh":
        await this.refreshAll();
        return;
      case "restart-server":
        await this.server.restart();
        await this.refreshAll();
        return;
      case "resume":
        await this.resumeRun();
        return;
      case "ask":
        await this.askAside(message.question);
        return;
      case "mentions":
        await this.lookupMentions(message.query);
        return;
      case "pick-files":
        await this.pickFiles();
        return;
      case "paste-files":
        await this.pasteFiles(message.files);
        return;
      case "copy":
        await vscode.env.clipboard.writeText(message.text);
        return;
      case "open-settings":
        await vscode.commands.executeCommand("workbench.action.openSettings", "zettcode");
        return;
      case "context":
        await this.refreshContext();
        return;
    }
  }

  // -- prompting ---------------------------------------------------------

  /**
   * Run one prompt: the line the conversation shows, and — behind it — what the model reads, when a command's preset
   * is the thing to run. A request in flight takes an ordinary prompt as a steer and refuses a command's preset
   * (`refuseWhenBusy`): a preset is a turn of its own, not a word added to the one running.
   */
  private async sendPrompt(request: PromptRequest): Promise<void> {
    const text = request.text.trim();
    const shown = (request.shown ?? request.text).trim();
    if (!shown) {
      return;
    }
    if (this.busy) {
      if (request.refuseWhenBusy === true) {
        this.say("warn", "A run is already going; try the command again when it ends.");
        return;
      }
      await this.steer(shown);
      return;
    }
    if (!this.readyForPrompt()) {
      return;
    }
    const images = request.images ?? [];
    const client = await this.ensureClient();
    const turn = createTurn(shown, images);
    this.turns.push(turn);
    this.postTurn(turn, true);
    const options = text === shown ? this.runOptions(images) : { ...this.runOptions(images), instructions: text };
    await this.startRun(client.prompt(shown, options), turn);
  }

  private async resumeRun(): Promise<void> {
    if (this.busy) {
      this.post({ type: "notice", level: "warn", text: "A run is already going." });
      return;
    }
    if (this.resumable?.resumable !== true) {
      this.post({ type: "notice", level: "info", text: "There is no interrupted request to continue." });
      return;
    }
    const client = await this.ensureClient();
    const turn = createTurn("", [], Date.now(), `turn-resume-${Date.now().toString(36)}`);
    turn.resumed = true;
    this.turns.push(turn);
    this.postTurn(turn, true);
    const run = client.session.resume(this.runOptions([]));
    await this.startRun(run, turn);
  }

  private async startRun(run: Run, turn: Turn): Promise<void> {
    // The run belongs to the conversation on show now and stays with it: looking at another one later changes `conv`,
    // not this, so the frames below go on being written to their own turns.
    const conv = this.conv;
    if (this.session !== null) {
      // Registered by its session, so that opening the session again while this runs finds the live transcript.
      this.convs.register(this.session.id, conv);
    }
    this.clearDeltas();
    conv.run = run;
    conv.running = turn;
    conv.busy = true;
    conv.pending = null;
    this.resumable = null;
    this.postState();
    void this.refreshSessions(false).catch(() => undefined);
    try {
      for await (const frame of run) {
        this.handleFrame(conv, turn, frame);
      }
    } catch (error) {
      if (error instanceof RunCancelledError) {
        cancelTurn(turn);
      } else {
        failTurn(turn, messageOf(error));
        this.output.appendLine(`[run] ${messageOf(error)}`);
      }
    } finally {
      conv.run = null;
      conv.running = null;
      conv.busy = false;
      conv.pending = null;
        if (this.convs.isShown(conv)) {
        this.postTurn(turn, true);
        await this.settleChanges(turn);
        await this.afterRun(turn);
      } else {
        await this.settleChanges(turn);
        await this.afterBackgroundRun(conv, turn);
      }
    }
  }

  /** Whether `conv` is the conversation on show, which is the only one the view is told about. */
  private isShown(conv: Conversation): boolean {
    return this.convs.isShown(conv);
  }

  private handleFrame(conv: Conversation, turn: Turn, frame: StreamFrame): void {
    const shown = this.isShown(conv);
    if (frame.event === "event") {
      const event = frame.data as RunEvent;
      this.trackFrame(turn, event);
      applyEvent(turn, event);
      if (shown && (event.type === "usage_updated" || event.type === "compaction_finished")) {
        this.scheduleContext();
      }
      if (event.type === "text_delta" || event.type === "reasoning_delta") {
        if (shown) {
          this.queueDelta(turn, event.type === "text_delta" ? "text" : "reasoning", event.text);
        }
        return;
      }
      if (shown) {
        this.flushDeltas();
      }
      if (event.type === "approval_requested" && event.approved === null) {
        conv.pending = {
          kind: "approval",
          call_id: event.call_id,
          command: event.command,
          remember_supported: true,
        };
      } else if (event.type === "question_asked" && !event.answered) {
        conv.pending = {
          kind: "question",
          call_id: event.call_id,
          question: event.question,
          options: event.options,
          allow_multiple: event.allow_multiple,
        };
      } else if (
        event.type === "tool_started" ||
        event.type === "tool_finished" ||
        event.type === "server_tool_started" ||
        event.type === "server_tool_finished"
      ) {
        if (conv.pending !== null && conv.pending.call_id !== event.call_id) {
          conv.pending = null;
        }
      }
      if (!shown) {
        if (event.type === "approval_requested" || event.type === "question_asked") {
          this.post({ type: "notice", level: "info", text: "A session that is running in the background is waiting for an answer." });
        }
        return;
      }
      this.postTurn(turn, IMMEDIATE_EVENTS.has(event.type));
      if (event.type === "approval_requested" || event.type === "question_asked") {
        this.postState();
      }
      return;
    }
    if (shown) {
      this.flushDeltas();
    }
    if (frame.event === "result") {
      finishTurn(turn, frame.data as RunResult);
    } else if (frame.event === "error") {
      const payload = frame.data as { message?: string };
      failTurn(turn, payload.message ?? "The run failed.");
    } else {
      cancelTurn(turn);
    }
    conv.pending = null;
    if (shown) {
      this.postTurn(turn, true);
    }
  }

  /**
   * A run that ended while another conversation was on show. Nothing of the one on show changes: its turns are in the
   * store already, so the conversation is forgotten here and read again if it is opened, and the list stops spinning.
   */
  private async afterBackgroundRun(conv: Conversation, turn: Turn): Promise<void> {
    this.convs.forget(conv);
    await this.refreshSessions(false).catch(() => undefined);
    const verb = turn.status === "done" ? "finished" : turn.status === "failed" ? "failed" : "was stopped";
    this.post({ type: "notice", level: turn.status === "failed" ? "warn" : "info", text: `A session in the background ${verb}.` });
  }

  private async afterRun(turn: Turn): Promise<void> {
    if (this.client === null) {
      this.postState();
      return;
    }
    const client = this.client;
    const [session, health] = await Promise.all([
      client.session.info().catch(() => null),
      client.health().catch(() => null),
    ]);
    if (session !== null) {
      this.session = session;
      this.context.workspaceState.update(SESSION_KEY, session.id);
    }
    if (health !== null) {
      this.health = health;
    }
    this.contextReport = await client.session.context().catch(() => null);
    this.selfCompaction = await client.selfCompaction().catch(() => null);
    this.resumable = await client.session.resumable().catch(() => null);
    this.postState();
    void this.refreshSessions(false).catch(() => undefined);
    if (turn.status === "done" && !turn.aside) {
      this.titleLater();
    }
  }

  /**
   * Name an untitled conversation from its first exchange, as the terminal does after every finished request.
   * The server keeps a title that exists, so asking again is harmless; a failure is a nicety lost, never an error.
   */
  private titleLater(): void {
    const client = this.client;
    const session = this.session;
    if (
      client === null ||
      session === null ||
      session.title ||
      this.titleTask !== null ||
      !vscode.workspace.getConfiguration("zettcode").get<boolean>("autoTitle", true)
    ) {
      return;
    }
    this.titleTask = client.session
      .nameIt()
      .then(async (named) => {
        if (!named.title || this.session?.id !== session.id) {
          return;
        }
        this.session = { ...this.session, title: named.title };
        this.postState();
        await this.refreshSessions(true);
      })
      .catch(() => undefined)
      .finally(() => {
        this.titleTask = null;
      });
  }

  private runOptions(images: ImageInput[]): {
    approvals: ApprovalPolicy;
    questions: "ask";
    answerTimeout: number;
    images?: ImageInput[];
  } {
    const permission = this.settings?.permission ?? this.configuredPermission();
    const answerTimeout = vscode.workspace.getConfiguration("zettcode").get<number>("answerTimeout", 90);
    const options: {
      approvals: ApprovalPolicy;
      questions: "ask";
      answerTimeout: number;
      images?: ImageInput[];
    } = {
      approvals: approvalsFor(permission),
      questions: "ask",
      answerTimeout: Math.max(5, answerTimeout),
    };
    if (images.length) {
      options.images = images;
    }
    return options;
  }

  private readyForPrompt(): boolean {
    if (this.health?.ready === true) {
      return true;
    }
    this.post({
      type: "notice",
      level: "warn",
      text: "No model is configured yet. Add one to start.",
    });
    this.post({ type: "model-form", open: true });
    if (this.view === null) {
      void vscode.window.showWarningMessage("ZettCode: add a model before using this command.");
    }
    return false;
  }

  private async steer(text: string): Promise<void> {
    const prompt = text.trim();
    if (!prompt) {
      return;
    }
    if (!this.busy || this.client === null) {
      await this.sendPrompt({ text: prompt });
      return;
    }
    const turn = this.running;
    // The message shows in the transcript the moment it is sent; the run reporting it later only settles that block.
    const echo = turn === null ? null : echoSteer(turn, prompt);
    if (turn !== null) {
      this.postTurn(turn, true);
    }
    let steered = false;
    try {
      steered = (await this.client.session.steer(prompt, { mentions: true })) !== null;
    } catch (error) {
      this.post({ type: "notice", level: "warn", text: `Could not steer: ${messageOf(error)}` });
    }
    if (!steered) {
      if (turn !== null && echo !== null) {
        retractSteer(turn, echo);
        this.postTurn(turn, true);
      }
      this.post({ type: "notice", level: "warn", text: "Nothing is running to steer." });
    }
  }

  private async approve(callId: string, approve: boolean, remember: boolean): Promise<void> {
    const client = await this.ensureClient();
    const resolved = await client.approve(callId, approve, remember);
    const turn = this.turns.find((candidate) =>
      candidate.blocks.some((block) => block.kind === "approval" && block.callId === callId),
    );
    if (turn) {
      markApproval(turn, callId, approve);
      this.postTurn(turn, true);
    }
    if (!resolved) {
      this.post({ type: "notice", level: "warn", text: "That request was already answered or timed out." });
    }
    if (this.pending?.call_id === callId) {
      this.pending = null;
      this.postState();
    }
  }

  private async answer(callId: string, answer: string | null): Promise<void> {
    const client = await this.ensureClient();
    const resolved = await client.answer(callId, answer);
    const turn = this.turns.find((candidate) =>
      candidate.blocks.some((block) => block.kind === "question" && block.callId === callId),
    );
    if (turn) {
      markAnswer(turn, callId, answer);
      this.postTurn(turn, true);
    }
    if (!resolved) {
      this.post({ type: "notice", level: "warn", text: "That question was already answered, or the run ended." });
    }
    if (this.pending?.call_id === callId) {
      this.pending = null;
      this.postState();
    }
  }

  /**
   * Keep the `zettcode.chatFocused` context key true exactly while the cursor is in the chat view. The view's own
   * `focusedView` does not follow a webview's focus reliably, and Ctrl+F must belong to the chat or to the editor, never both.
   */
  private setFocused(focused: boolean): void {
    void vscode.commands.executeCommand("setContext", "zettcode.chatFocused", focused);
  }

  /** Open the search over the conversation in the view; the keybinding and the palette both come here. */
  async find(): Promise<void> {
    if (this.view === null) {
      await vscode.commands.executeCommand("zettcode.openChat");
    }
    this.post({ type: "find" });
  }

  async stop(): Promise<void> {
    if (this.run !== null) {
      await this.run.cancel().catch(() => false);
      return;
    }
    if (this.client === null) {
      return;
    }
    await this.client.cancelRun().catch(() => false);
  }

  private async askAside(question: string): Promise<void> {
    const text = question.trim();
    if (!text) {
      return;
    }
    if (this.health?.ready !== true) {
      this.readyForPrompt();
      return;
    }
    if (this.busy) {
      this.post({ type: "notice", level: "warn", text: "A run is in progress; ask on the side when it ends." });
      return;
    }
    const client = await this.ensureClient();
    const turn = createTurn(`/btw ${text}`, [], Date.now(), `turn-aside-${Date.now().toString(36)}`);
    turn.aside = true;
    this.turns.push(turn);
    this.postTurn(turn, true);
    // Streamed like a prompt, so the answer is written as it arrives and Esc stops it; it still joins nothing.
    await this.startRun(client.session.askStream(text, { timeout: 180 }), turn);
  }

  // -- sessions ----------------------------------------------------------

  async newSession(): Promise<void> {
    const client = await this.ensureClient();
    await client.sessions.new();
    this.session = await client.session.info();
    this.context.workspaceState.update(SESSION_KEY, this.session.id);
    // A run in the conversation being left goes on there; this one starts empty and idle.
    this.showConversation(this.session.id, newConversation());
    this.resumable = null;
    this.contextReport = null;
    await this.readExtras();
    this.postTurns();
    this.postState();
    await this.refreshSessions(true);
    this.post({ type: "notice", level: "info", text: "Started a new session." });
  }

  /**
   * Put a conversation on show; see `Conversations.show` for which one is kept. The pending text deltas belong to the
   * conversation being left, so they are dropped with it.
   */
  private showConversation(id: string, conv: Conversation): void {
    this.clearDeltas();
    this.convs.show(id, conv);
  }

  async openSession(id: string, closeDrawer = true): Promise<void> {
    const client = await this.ensureClient();
    if (closeDrawer) {
      // The list goes away at once, so what the reader sees next is the conversation being opened and not a list that
      // has stopped answering.
      this.post({ type: "history", open: false });
    }
    await this.whileLoading("Opening the conversation", async () => {
      this.session = await client.sessions.open(id);
      this.context.workspaceState.update(SESSION_KEY, id);
      const running = this.convs.find(id);
      if (running !== undefined && running.busy) {
        // Still running: its transcript is the live one, with the run's frames in it, and is not read again.
        this.showConversation(id, running);
      } else {
        this.showConversation(id, newConversation());
        await this.loadHistory();
      }
      this.resumable = null;
      await this.readExtras();
      this.postTurns();
    });
    await this.refreshSessions(true);
  }

  async refreshSessions(postToView: boolean): Promise<void> {
    if (this.client === null || this.health?.ready !== true) {
      this.sessions = [];
      if (postToView) {
        this.post({ type: "sessions", sessions: [] });
      }
      return;
    }
    const limit = vscode.workspace.getConfiguration("zettcode").get<number>("historyLimit", 50);
    let list: SessionInfo[] = [];
    try {
      list = await this.client.sessions.list({ limit });
    } catch (error) {
      this.output.appendLine(`[sessions] ${messageOf(error)}`);
      list = [];
    }
    let stats: { id: string; entries: number; total_tokens: number }[] = [];
    try {
      stats = await this.client.sessionStats(list.map((session) => session.id));
    } catch {
      stats = [];
    }
    const byId = new Map(stats.map((item) => [item.id, item]));
    this.sessions = list.map((session) => {
      const found = byId.get(session.id);
      return {
        id: session.id,
        title: session.title,
        updatedAt: session.updated_at,
        entries: found?.entries ?? 0,
        tokens: found?.total_tokens ?? 0,
        current: session.id === this.session?.id || session.current,
        running: session.running === true,
      };
    });
    if (postToView || this.view !== null) {
      this.post({ type: "sessions", sessions: this.sessions });
    }
  }

  async renameSession(title?: string): Promise<void> {
    const client = await this.ensureClient();
    const name =
      title ??
      (await vscode.window.showInputBox({
        prompt: "Session name",
        value: this.session?.title ?? "",
        placeHolder: "Pagination work",
      }));
    if (name === undefined || !name.trim()) {
      return;
    }
    this.session = { ...(this.session ?? (await client.session.info())), title: (await client.session.rename(name.trim())).title };
    this.context.workspaceState.update(SESSION_KEY, this.session.id);
    this.postState();
    await this.refreshSessions(true);
  }

  private async nameSession(): Promise<void> {
    const client = await this.ensureClient();
    const name = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Naming the session…" },
      async () => client.session.nameIt(),
    );
    if (this.session) {
      this.session = { ...this.session, title: name.title };
    }
    this.postState();
    await this.refreshSessions(true);
  }

  async forkSession(): Promise<void> {
    if (this.busy) {
      this.post({ type: "notice", level: "warn", text: "Stop the run before forking." });
      return;
    }
    const client = await this.ensureClient();
    await this.whileLoading("Forking the conversation", async () => {
      this.session = await client.session.fork();
      this.context.workspaceState.update(SESSION_KEY, this.session.id);
      await this.loadHistory();
      await this.readExtras();
      this.postTurns();
    });
    await this.refreshSessions(true);
    this.post({ type: "notice", level: "info", text: "Forked this conversation into a new session." });
  }

  async compactSession(): Promise<void> {
    if (this.busy) {
      this.post({ type: "notice", level: "warn", text: "Stop the run before compacting." });
      return;
    }
    // The webview draws a running row for this and ends it with the next notice, so every way out sends exactly one.
    try {
      const client = await this.ensureClient();
      const result = await client.session.compact();
      if (result.applied) {
        this.post({
          type: "notice",
          level: "info",
          text: `Compacted ${result.compressed} messages into a summary; ${result.kept} kept.`,
          summary: result.summary,
        });
      } else {
        this.post({ type: "notice", level: "info", text: "There was nothing to compact yet." });
      }
    } catch (error) {
      this.post({
        type: "notice",
        level: "error",
        text: `Compaction failed: ${error instanceof Error ? error.message : String(error)}`,
      });
      return;
    }
    await this.refreshContext();
  }

  async exportSession(): Promise<void> {
    const client = await this.ensureClient();
    const html = await client.session.export();
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri;
    const target = await vscode.window.showSaveDialog({
      filters: { HTML: ["html"] },
      saveLabel: "Export session",
      ...(folder ? { defaultUri: vscode.Uri.joinPath(folder, "zettcode-session.html") } : {}),
    });
    if (target === undefined) {
      return;
    }
    await vscode.workspace.fs.writeFile(target, Buffer.from(html, "utf8"));
    this.post({ type: "notice", level: "info", text: `Exported to ${target.fsPath}` });
  }

  private async setSelfCompaction(choice: boolean | null): Promise<void> {
    const client = await this.ensureClient();
    this.selfCompaction = await client.useSelfCompaction(choice);
    this.postState();
    const label = choice === null ? "the configuration" : choice ? "on" : "off";
    this.post({ type: "notice", level: "info", text: `Self-compaction follows ${label}.` });
  }

  private async refreshContext(): Promise<void> {
    if (this.client === null) {
      return;
    }
    this.contextReport = await this.client.session.context().catch(() => null);
    this.postState();
  }

  /**
   * Keep the context figure current without being asked: after every model request, after a compaction, and when
   * the model changes. Calls close together share one read, and a read that fails keeps the figure it had.
   */
  private scheduleContext(delay = 350): void {
    if (this.contextTimer !== null || this.disposed) {
      return;
    }
    this.contextTimer = setTimeout(() => {
      this.contextTimer = null;
      const client = this.client;
      if (client === null || this.disposed) {
        return;
      }
      void Promise.all([client.session.context().catch(() => null), client.session.info().catch(() => null)]).then(
        ([report, session]) => {
          if (this.disposed) {
            return;
          }
          if (report !== null) {
            this.contextReport = report;
          }
          if (session !== null && this.session?.id === session.id) {
            this.session = { ...this.session, usage: session.usage };
          }
          this.postState();
        },
      );
    }, delay);
  }

  // -- models and settings -----------------------------------------------

  async updateSettings(update: {
    model?: string;
    effort?: string;
    permission?: Permission;
    harness?: boolean;
    compact_percent?: number;
  }): Promise<void> {
    const client = await this.ensureClient();
    const before = this.settings;
    this.settings = await client.updateSettings(update);
    if (update.permission !== undefined) {
      this.rememberPermission(this.settings.permission);
    }
    const [models, health] = await Promise.all([client.models(), client.health()]);
    this.models = models.models;
    this.health = health;
    this.postState();
    this.announceChanges(before, this.settings);
    if (update.model !== undefined || update.compact_percent !== undefined) {
      this.scheduleContext(0);
    }
    if (this.settings.unsaved) {
      this.post({
        type: "notice",
        level: "warn",
        text: `The compaction point holds for this run only: ${this.settings.unsaved}`,
      });
    }
  }

  /**
   * Remember a permission the reader chose, for this session and as the choice to start the next one with. The server
   * keeps it only in memory, so without this every new window would ask again.
   */
  private rememberPermission(permission: Permission): void {
    const stored = readRemembered(this.context.workspaceState.get(PERMISSION_KEY));
    void this.context.workspaceState.update(PERMISSION_KEY, remember(stored, this.session?.id ?? null, permission));
  }

  /** Put the permission this session was last set to (or the last one chosen here) back on the server, without a word. */
  private async applyRememberedPermission(): Promise<void> {
    if (this.client === null || this.settings === null || this.busy) {
      return;
    }
    const stored = readRemembered(this.context.workspaceState.get(PERMISSION_KEY));
    const wanted = wantedPermission(stored, this.session?.id ?? null, this.settings.permissions);
    if (wanted === null || wanted === this.settings.permission) {
      return;
    }
    try {
      this.settings = await this.client.updateSettings({ permission: wanted });
    } catch (error) {
      this.output.appendLine(`[permission] could not restore ${wanted}: ${messageOf(error)}`);
    }
  }

  /**
   * Say in the conversation what changed between two requests, as the terminal does: one centred line between two
   * rules for the model, the reasoning effort and the shell permission. Nothing is said when nothing differs, and not
   * before the first settings were read (that is the start, not a change).
   */
  private announceChanges(before: Settings | null, after: Settings): void {
    if (before === null) {
      return;
    }
    const lines: string[] = [];
    if (before.model.name !== after.model.name) {
      lines.push(`Model changed from ${before.model.name} to ${after.model.name}.`);
    }
    if (before.effort !== after.effort) {
      lines.push(`Reasoning effort changed from ${before.effort} to ${after.effort}.`);
    }
    if (before.permission !== after.permission) {
      lines.push(`Shell permission changed from ${before.permission} to ${after.permission}.`);
    }
    if (before.harness !== after.harness) {
      lines.push(`Tool harness turned ${after.harness ? "on" : "off"}.`);
    }
    for (const text of lines) {
      const turn = announcement(text, Date.now(), newTurnId("turn-announce"));
      this.turns.push(turn);
      this.postTurn(turn, true);
    }
  }

  private async editModel(name: string, changes: ModelUpdate): Promise<void> {
    const client = await this.ensureClient();
    const clean: Record<string, unknown> = { ...changes };
    if (typeof clean.model === "string") {
      clean.model = clean.model.trim();
      if (!clean.model) {
        throw new Error("A model id is required.");
      }
    }
    for (const key of ["token", "display_model", "base_url", "web_search_name"] as const) {
      const value = clean[key];
      if (typeof value === "string") {
        const trimmed = value.trim();
        // An empty name or address clears the key; an empty token means "keep it", because the current one is never
        // sent to the editor in the first place.
        clean[key] = key === "token" ? (trimmed ? trimmed : undefined) : trimmed ? trimmed : null;
      }
    }
    await client.updateModel(name, clean as ModelUpdate);
    this.models = (await client.models()).models;
    this.health = await client.health();
    this.postState();
  }

  private async addModel(input: ModelInput): Promise<void> {
    const client = await this.ensureClient();
    if (!input.model.trim()) {
      throw new Error("A model id is required.");
    }
    const clean: ModelInput = { model: input.model.trim() };
    for (const key of ["token", "display_model", "base_url"] as const) {
      const value = input[key];
      if (typeof value === "string" && value.trim()) {
        clean[key] = value.trim();
      }
    }
    if (input.context_window !== undefined && input.context_window > 0) {
      clean.context_window = input.context_window;
    }
    if (input.compact_percent !== undefined && input.compact_percent > 0) {
      clean.compact_percent = input.compact_percent;
    }
    if (input.multimodal !== undefined) {
      clean.multimodal = input.multimodal;
    }
    if (input.web_search === true) {
      clean.web_search = true;
      if (input.web_search_name?.trim()) {
        clean.web_search_name = input.web_search_name.trim();
      }
    }
    if (input.anthropic !== undefined) {
      clean.anthropic = input.anthropic;
    }
    if (input.responses_api !== undefined) {
      clean.responses_api = input.responses_api;
    }
    if (input.chat !== undefined) {
      clean.chat = input.chat;
    }
    if (input.temperature !== undefined && input.temperature >= 0) {
      clean.temperature = input.temperature;
    }
    if (input.reasoning_efforts !== undefined && input.reasoning_efforts.length > 0) {
      clean.reasoning_efforts = input.reasoning_efforts;
    }
    await client.addModel(clean);
    const models = await client.models();
    this.models = models.models;
    this.health = await client.health();
    if (this.health.ready) {
      this.session = await client.session.info();
      if (this.session !== null) {
        this.context.workspaceState.update(SESSION_KEY, this.session.id);
      }
      if (this.turns.length === 0) {
        await this.loadHistory();
      }
    }
    await this.readSettings();
    await this.readExtras();
    this.initialized = true;
    this.postTurns();
    this.postState();
    this.post({ type: "model-form", open: false });
    this.post({ type: "notice", level: "info", text: `Added ${clean.display_model ?? clean.model}.` });
    void this.refreshSessions(false).catch(() => undefined);
  }

  async addModelInteractive(): Promise<void> {
    const model = await vscode.window.showInputBox({
      prompt: "Model id",
      placeHolder: "claude-sonnet-4-5",
      ignoreFocusOut: true,
      validateInput: (value) => (value.trim() ? undefined : "A model id is required"),
    });
    if (!model?.trim()) {
      return;
    }
    const displayModel = await vscode.window.showInputBox({
      prompt: "Display name (optional)",
      placeHolder: "sonnet",
      ignoreFocusOut: true,
    });
    const token = await vscode.window.showInputBox({
      prompt: "API key (optional; leave empty for a local model or an environment variable)",
      password: true,
      ignoreFocusOut: true,
    });
    const baseUrl = await vscode.window.showInputBox({
      prompt: "Base URL (optional)",
      placeHolder: "https://api.anthropic.com",
      ignoreFocusOut: true,
    });
    const contextWindow = await vscode.window.showInputBox({
      prompt: "Context window in tokens (optional)",
      placeHolder: "200000",
      ignoreFocusOut: true,
      validateInput: (value) => (!value.trim() || Number.isFinite(Number(value)) ? undefined : "A number is required"),
    });
    const api = await vscode.window.showQuickPick(
      APIS.map((item) => ({ label: item.label, description: item.detail, api: item.value })),
      { placeHolder: "Which API does the endpoint speak?", ignoreFocusOut: true },
    );
    const chosen: Api = api?.api ?? "chat";
    const temperature = await vscode.window.showInputBox({
      prompt: `Temperature, 0 to ${maxTemperature(chosen)} (optional; empty uses the provider's own)`,
      placeHolder: "0.2",
      ignoreFocusOut: true,
      validateInput: (value) => {
        const read = parseTemperature(value, chosen);
        return read.kind === "error" ? read.message : undefined;
      },
    });
    const multimodal = await vscode.window.showQuickPick(["No", "Yes"], {
      placeHolder: "Does this model accept images?",
      ignoreFocusOut: true,
    });
    const search = await vscode.window.showQuickPick(["No", "Yes"], {
      placeHolder: "Let the provider search the web for it?",
      ignoreFocusOut: true,
    });
    const input: ModelInput = { model: model.trim(), ...apiKeys(chosen) };
    const read = parseTemperature(temperature ?? "", chosen);
    if (read.kind === "value") {
      input.temperature = read.value;
    }
    if (displayModel?.trim()) {
      input.display_model = displayModel.trim();
    }
    if (token?.trim()) {
      input.token = token.trim();
    }
    if (baseUrl?.trim()) {
      input.base_url = baseUrl.trim();
    }
    if (contextWindow?.trim()) {
      input.context_window = Number(contextWindow);
    }
    if (multimodal === "Yes") {
      input.multimodal = true;
    }
    if (search === "Yes") {
      const problem = searchProblem(chosen, model.trim(), baseUrl?.trim() ?? "");
      if (problem !== null) {
        void vscode.window.showWarningMessage(problem);
        return;
      }
      Object.assign(input, searchKeys(true, ""));
    }
    await this.addModel(input);
  }

  async selectModel(): Promise<void> {
    const client = await this.ensureClient();
    const { models, current } = await client.models();
    this.models = models;
    const items: (vscode.QuickPickItem & { name?: string; add?: boolean })[] = models.map((model) => ({
      label: `${model.active ? "$(check) " : ""}${model.name}`,
      description: `${model.model} · ${model.context_window} tokens${model.multimodal ? " · images" : ""}${model.web_search ? " · search" : ""}`,
      detail: model.efforts.length ? `Effort: ${model.efforts.join(", ")}` : undefined,
      name: model.name,
    }));
    items.push({ label: "$(add) Add a model…", add: true });
    const picked = await vscode.window.showQuickPick(items, {
      placeHolder: current ? `Model (now ${current})` : "Select a model",
      matchOnDescription: true,
    });
    if (picked === undefined) {
      return;
    }
    if (picked.add) {
      await this.addModelInteractive();
      return;
    }
    if (picked.name) {
      await this.updateSettings({ model: picked.name });
    }
  }

  async selectEffort(): Promise<void> {
    const client = await this.ensureClient();
    const settings = await client.settings();
    this.settings = settings;
    if (settings.efforts.length === 0) {
      this.post({ type: "notice", level: "info", text: `${settings.model.name} reports no reasoning efforts.` });
      return;
    }
    const picked = await vscode.window.showQuickPick(
      settings.efforts.map((effort) => ({
        label: `${effort === settings.effort ? "$(check) " : ""}${effort}`,
      })),
      { placeHolder: `Reasoning effort (now ${settings.effort})` },
    );
    if (picked !== undefined) {
      await this.updateSettings({ effort: picked.label.replace("$(check) ", "") });
    }
  }

  async selectPermission(): Promise<void> {
    const client = await this.ensureClient();
    const settings = await client.settings();
    this.settings = settings;
    const descriptions: Record<string, string> = {
      deny: "Refuse every shell command",
      ask: "Ask before every shell command",
      safe: "Run every command in a sandbox: writes only the workspace and /tmp, no network",
      full: "Run every command with your own access, without asking",
    };
    const picked = await vscode.window.showQuickPick(
      settings.permissions.map((permission) => ({
        label: `${permission === settings.permission ? "$(check) " : ""}${permission}`,
        description: descriptions[permission] ?? "",
      })),
      { placeHolder: `Shell permission (now ${settings.permission})` },
    );
    if (picked !== undefined) {
      const permission = picked.label.replace("$(check) ", "") as Permission;
      await this.updateSettings({ permission });
    }
  }

  /** Turn the tool harness on or off, or flip it when no answer is given. The server keeps it for the run. */
  async toggleHarness(): Promise<void> {
    const client = await this.ensureClient();
    const settings = await client.settings();
    this.settings = settings;
    const picked = await vscode.window.showQuickPick(
      [
        {
          label: `${settings.harness ? "" : "$(check) "}Off`,
          description: "The model has no harness (the default)",
          on: false,
        },
        {
          label: `${settings.harness ? "$(check) " : ""}On`,
          description: "The model may write small Python tools and run them, outside the shell permission",
          on: true,
        },
      ],
      { placeHolder: `Tool harness (now ${settings.harness ? "on" : "off"})` },
    );
    if (picked !== undefined && picked.on !== settings.harness) {
      await this.updateSettings({ harness: picked.on });
    }
  }

  async editModelInteractive(): Promise<void> {
    const client = await this.ensureClient();
    const { models } = await client.models();
    const model = await vscode.window.showQuickPick(
      models.map((item) => ({ label: item.name, description: item.model })),
      { placeHolder: "Which model?" },
    );
    if (model === undefined) {
      return;
    }
    const field = await vscode.window.showQuickPick(
      [
        { label: "API key", value: "token", password: true },
        { label: "Display name", value: "display_model" },
        { label: "Base URL", value: "base_url" },
        { label: "Context window", value: "context_window" },
        { label: "Reasoning efforts", value: "reasoning_efforts" },
        { label: "Compact percent", value: "compact_percent" },
        { label: "Multimodal", value: "multimodal" },
        { label: "Web search", value: "web_search" },
        { label: "Web search tool name", value: "web_search_name" },
        { label: "API (chat, Responses or Anthropic)", value: "api" },
        { label: "Temperature", value: "temperature" },
      ],
      { placeHolder: `Change what on ${model.label}?` },
    );
    if (field === undefined) {
      return;
    }
    if (field.value === "api") {
      const api = await vscode.window.showQuickPick(
        APIS.map((item) => ({ label: item.label, description: item.detail, api: item.value })),
        { placeHolder: `Which API does ${model.label} speak?` },
      );
      if (api === undefined) {
        return;
      }
      await client.updateModel(model.label, apiChange(api.api));
    } else if (field.value === "temperature") {
      const value = await vscode.window.showInputBox({
        prompt: `Temperature, 0 to ${maxTemperature(null)} (1 for an Anthropic model); empty goes back to the provider's own`,
        placeHolder: "0.2",
        validateInput: (text) => {
          const read = parseTemperature(text, null);
          return read.kind === "error" ? read.message : undefined;
        },
      });
      if (value === undefined) {
        return;
      }
      const read = parseTemperature(value, null);
      await client.updateModel(model.label, { temperature: read.kind === "value" ? read.value : null });
    } else if (field.value === "multimodal") {
      const answer = await vscode.window.showQuickPick(["Yes", "No"], {
        placeHolder: "Does this model accept images?",
      });
      if (answer === undefined) {
        return;
      }
      await client.updateModel(model.label, { multimodal: answer === "Yes" });
    } else if (field.value === "web_search") {
      const answer = await vscode.window.showQuickPick(["Yes", "No"], {
        placeHolder: "Let the provider search the web for this model?",
      });
      if (answer === undefined) {
        return;
      }
      // Off removes the key, so the file never holds `web_search = false`; the server refuses DeepSeek's chat endpoint.
      await client.updateModel(model.label, { web_search: answer === "Yes" ? true : null });
    } else if (field.value === "web_search_name") {
      const value = await vscode.window.showInputBox({
        prompt: "The tool type the search is sent as; empty sends the default for the API",
        placeHolder: "web_search_20260318",
      });
      if (value === undefined) {
        return;
      }
      await client.updateModel(model.label, { web_search_name: value.trim() ? value.trim() : null });
    } else if (field.value === "compact_percent") {
      const value = await vscode.window.showInputBox({
        prompt: "Compact when this percent of the window is used",
        placeHolder: "80",
        validateInput: (text) => (!text.trim() || Number.isFinite(Number(text)) ? undefined : "A number is required"),
      });
      if (value === undefined || !value.trim()) {
        return;
      }
      await client.updateModel(model.label, { compact_percent: Number(value) });
    } else if (field.value === "reasoning_efforts") {
      const value = await vscode.window.showInputBox({
        prompt: "Reasoning efforts, comma separated",
        placeHolder: "low, medium, high",
      });
      if (value === undefined) {
        return;
      }
      await client.updateModel(model.label, {
        reasoning_efforts: value
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      });
    } else if (field.value === "context_window") {
      const value = await vscode.window.showInputBox({ prompt: "Context window in tokens" });
      if (value === undefined || !value.trim()) {
        return;
      }
      await client.updateModel(model.label, { context_window: Number(value) });
    } else {
      const value = await vscode.window.showInputBox({
        prompt: field.label,
        password: field.value === "token",
        ignoreFocusOut: true,
      });
      if (value === undefined) {
        return;
      }
      if (field.value === "token" && !value.trim()) {
        return;
      }
      if (field.value === "token") {
        await client.updateModel(model.label, { token: value });
      } else if (field.value === "display_model") {
        await client.updateModel(model.label, { display_model: value });
      } else if (field.value === "base_url") {
        await client.updateModel(model.label, { base_url: value });
      }
    }
    await this.refreshAll();
    this.post({ type: "notice", level: "info", text: `Updated ${model.label}.` });
  }

  /** Remove a model. The webview has already asked the reader to confirm, inline in the model menu. */
  private async removeModel(name: string): Promise<void> {
    const client = await this.ensureClient();
    try {
      const result = await client.removeModel(name);
      this.models = result.models;
      this.health = await client.health();
      await this.refreshAll();
      this.post({ type: "notice", level: "info", text: `Removed ${name}.` });
    } catch (error) {
      this.say("error", messageOf(error));
    }
  }

  private async lookupMentions(query: string): Promise<void> {
    if (this.client === null || this.health?.ready !== true) {
      this.post({ type: "mentions", query, items: [] });
      return;
    }
    try {
      const items: MentionInfo[] = await this.client.mentions(query, { limit: 30 });
      this.post({ type: "mentions", query, items });
    } catch {
      this.post({ type: "mentions", query, items: [] });
    }
  }

  // -- editor integration ------------------------------------------------

  private async openTarget(target: string): Promise<void> {
    // An address is not a file: a link the reader pressed that reached here by way of a tool's output still opens in
    // the browser rather than failing with a sentence about paths.
    if (/^https?:\/\//i.test(target.trim())) {
      await this.openExternal(target.trim());
      return;
    }
    const parsed = parsePathTarget(target);
    if (parsed === null) {
      this.post({ type: "notice", level: "warn", text: `That is not a path this window can open: ${shorten(target)}` });
      return;
    }
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri;
    let uri: vscode.Uri;
    if (path.isAbsolute(parsed.path) || /^[A-Za-z]:[\\/]/.test(parsed.path)) {
      uri = vscode.Uri.file(parsed.path);
    } else if (parsed.path.startsWith("~/")) {
      uri = vscode.Uri.file(path.join(process.env.HOME ?? "", parsed.path.slice(2)));
    } else if (folder !== undefined) {
      const parts = parsed.path.replace(/^\.\//, "").split(/[\\/]+/).filter(Boolean);
      uri = vscode.Uri.joinPath(folder, ...parts);
    } else {
      this.post({ type: "notice", level: "warn", text: "Open a folder first; a relative path has no root." });
      return;
    }
    let stat: vscode.FileStat;
    try {
      stat = await vscode.workspace.fs.stat(uri);
    } catch {
      const found = folder === undefined || isRooted(parsed.path) ? null : await this.findByName(folder, parsed.path);
      if (found === undefined) {
        return;
      }
      if (found === null) {
        this.post({ type: "notice", level: "warn", text: `Cannot find “${parsed.path}” in this workspace.` });
        return;
      }
      uri = found;
      try {
        stat = await vscode.workspace.fs.stat(uri);
      } catch {
        this.post({ type: "notice", level: "warn", text: `Cannot find “${parsed.path}” in this workspace.` });
        return;
      }
    }
    if ((stat.type & vscode.FileType.Directory) !== 0 || target.endsWith("/")) {
      await vscode.commands.executeCommand("revealInExplorer", uri);
      return;
    }
    try {
      const document = await vscode.workspace.openTextDocument(uri);
      const line = Math.max(0, Math.min((parsed.line ?? 1) - 1, Math.max(0, document.lineCount - 1)));
      const lineLength = document.lineAt(line).text.length;
      const character = Math.max(0, Math.min((parsed.column ?? 1) - 1, lineLength));
      const selection = new vscode.Range(line, character, line, character);
      const editor = await vscode.window.showTextDocument(document, { preview: true, selection });
      editor.revealRange(selection, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
    } catch {
      await vscode.commands.executeCommand("vscode.open", uri);
    }
  }

  /**
   * Find a file the answer named by its bare name or a partial path, the way the editor's Quick Open would.
   * The model says `sync_runtime.py`, and the file lives somewhere under the workspace; one match opens, several
   * ask which, and `undefined` means the reader dismissed the choice.
   */
  private async findByName(folder: vscode.Uri, relative: string): Promise<vscode.Uri | null | undefined> {
    const clean = relative.replace(/^\.\//, "").replace(/\\/g, "/").replace(/^\/+/, "");
    if (!clean) {
      return null;
    }
    const pattern = new vscode.RelativePattern(folder, `**/${clean.replace(/[{}[\]*?!()]/g, "[$&]")}`);
    const exclude = "**/{node_modules,.git,.venv,venv,dist,build,out,__pycache__,.mypy_cache,.ruff_cache}/**";
    const matches = await vscode.workspace.findFiles(pattern, exclude, 30);
    if (matches.length === 0) {
      return null;
    }
    if (matches.length === 1) {
      return matches[0] ?? null;
    }
    const items = matches
      .map((uri) => ({ uri, label: path.basename(uri.fsPath), description: vscode.workspace.asRelativePath(uri, false) }))
      .sort((left, right) => left.description.length - right.description.length || left.description.localeCompare(right.description));
    const picked = await vscode.window.showQuickPick(items, {
      placeHolder: `${items.length} files match ${clean}`,
      matchOnDescription: true,
    });
    return picked === undefined ? undefined : picked.uri;
  }

  private async openExternal(url: string): Promise<void> {
    if (!/^(?:https?|mailto):/i.test(url)) {
      return;
    }
    await vscode.env.openExternal(vscode.Uri.parse(url));
  }

  /**
   * Files the reader copied and pasted. The page has their names and bytes but no path, so one is found or made here
   * (see `plan` in core/pasted.ts): the path the system clipboard holds for the file (the real one, of any size, from
   * anywhere), else the file in the workspace with the very same bytes, else a copy of the bytes kept in the extension's
   * storage. What cannot be done is said, with the way that always works.
   */
  private async pasteFiles(files: PastedFile[]): Promise<void> {
    const wanted = files.slice(0, PASTE_FILES);
    const onClipboard = pathsOnClipboard(
      await vscode.env.clipboard.readText().then((text) => text, () => ""),
      wanted.map((file) => file.name),
    );
    // The system's clipboard is the reader's own only when the window is local; over SSH or in WSL it is another machine's.
    const system = vscode.env.remoteName === undefined ? await copiedFilePaths() : [];
    const preferred = [
      ...vscode.window.tabGroups.all.flatMap((group) => group.tabs.map((tab) => tabPath(tab.input))),
      vscode.window.activeTextEditor?.document.uri.fsPath ?? "",
    ].filter(Boolean);
    const paths: string[] = [];
    const missing: string[] = [];
    for (const file of wanted) {
      const bytes = file.data === undefined ? undefined : Buffer.from(file.data, "base64");
      const byName = (await vscode.workspace.findFiles(searchPattern(file.name), "**/{node_modules,.git}/**", 40))
        .map((uri) => uri.fsPath)
        .filter((candidate) => baseName(candidate) === file.name);
      const decision = plan({
        known: onClipboard.get(file.name) ?? system.find((candidate) => baseName(candidate) === file.name),
        identical: bytes === undefined ? [] : await sameBytes(byName, bytes),
        byName,
        hasBytes: bytes !== undefined,
        preferred,
      });
      let found: string | undefined;
      if (decision.kind === "path") {
        found = decision.path;
      } else if (decision.kind === "ask") {
        found = (
          await vscode.window.showQuickPick(
            decision.paths.map((candidate) => ({ label: vscode.workspace.asRelativePath(candidate), description: candidate, candidate })),
            { placeHolder: `Which ${file.name} did you copy?` },
          )
        )?.candidate;
      } else if (decision.kind === "save" && bytes !== undefined) {
        found = await this.keepCopy(file.name, bytes);
      }
      if (found === undefined) {
        missing.push(file.name);
      } else {
        paths.push(found);
      }
    }
    if (paths.length) {
      this.post({ type: "files", paths });
    }
    if (missing.length) {
      this.post({
        type: "notice",
        level: "warn",
        text: `No path found for ${missing.join(", ")}. Attach ${missing.length === 1 ? "it" : "them"} with the paperclip to send the path.`,
      });
    }
  }

  /**
   * Keep the bytes of a pasted file that is not in the workspace, in the extension's own storage, and return the path of
   * the copy. The folder is named for the bytes, so two files of one name never overwrite each other and pasting the
   * same file again finds the copy already there.
   */
  private async keepCopy(name: string, bytes: Buffer): Promise<string | undefined> {
    try {
      const folder = vscode.Uri.joinPath(this.context.globalStorageUri, "pasted", createHash("sha256").update(bytes).digest("hex").slice(0, 16));
      await vscode.workspace.fs.createDirectory(folder);
      const target = vscode.Uri.joinPath(folder, safeFileName(name));
      await vscode.workspace.fs.writeFile(target, bytes);
      return target.fsPath;
    } catch (error) {
      this.output.appendLine(`[paste] could not keep ${name}: ${messageOf(error)}`);
      return undefined;
    }
  }

  /**
   * Attach files. A picture is sent as a picture; anything else (a PDF, an archive, a spreadsheet) cannot be read by
   * the model from here, so what goes into the message is its path, which the agent can open with its own tools.
   */
  private async pickFiles(): Promise<void> {
    const picked = await vscode.window.showOpenDialog({ canSelectMany: true, openLabel: "Attach" });
    if (!picked?.length) {
      return;
    }
    const pictures = picked.filter((uri) => IMAGE_EXTENSION.test(uri.fsPath));
    const others = picked.filter((uri) => !IMAGE_EXTENSION.test(uri.fsPath));
    if (others.length) {
      this.post({ type: "files", paths: others.map((uri) => uri.fsPath) });
    }
    const images: AttachedImage[] = [];
    for (const uri of pictures.slice(0, MAX_IMAGES)) {
      const data = await vscode.workspace.fs.readFile(uri);
      if (data.byteLength > MAX_IMAGE_BYTES) {
        this.post({ type: "notice", level: "warn", text: `${path.basename(uri.fsPath)} is larger than 8 MB.` });
        continue;
      }
      images.push({
        name: path.basename(uri.fsPath),
        mediaType: mediaTypeOf(uri.fsPath),
        data: Buffer.from(data).toString("base64"),
      });
    }
    if (images.length) {
      this.post({ type: "images", images });
    }
  }

  // -- panels ------------------------------------------------------------

  async showUsage(): Promise<void> {
    const client = await this.ensureClient();
    if (this.health?.ready !== true) {
      await this.refreshAll();
    }
    if (this.health?.ready !== true) {
      this.readyForPrompt();
      return;
    }
    await showUsagePanel(client, this.extensionUri, this.workspaceName(), this.workspacePath()).catch((error: unknown) =>
      this.say("error", messageOf(error)),
    );
  }

  async showDoctor(): Promise<void> {
    const client = await this.ensureClient();
    if (this.health?.ready !== true) {
      await this.refreshAll();
    }
    if (this.health?.ready !== true) {
      this.readyForPrompt();
      return;
    }
    const checks = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Checking every configured model…" },
      async () => client.checkModels({ timeout: 30 }),
    );
    await showDoctorPanel(client, checks, this.extensionUri, this.workspaceName());
  }

  async showPlugins(): Promise<void> {
    if (this.health?.ready !== true) {
      await this.refreshAll();
    }
    if (this.health?.ready !== true) {
      this.readyForPrompt();
      return;
    }
    const client = await this.ensureClient();
    await showPluginsPanel(client, this.extensionUri, this.workspaceName());
  }

  /**
   * Offer the commands a plugin registered on `ctx.commands` and run the one the reader picks.
   *
   * The argument comes next, prefilled with the word the command takes first when it declares them (a command like
   * `/plugins disable <name>` still takes more after it, so the word is offered rather than run).
   */
  async runCommandInteractive(): Promise<void> {
    const client = await this.ensureClient();
    const commands = await client.commands();
    if (commands.length === 0) {
      void vscode.window.showInformationMessage("ZettCode: no plugin offers a command yet.");
      return;
    }
    const picked = await vscode.window.showQuickPick(
      commands.map((command) => ({ label: command.name, description: command.summary, command })),
      { title: "ZettCode: run a plugin command", placeHolder: "A command a plugin registered" },
    );
    if (picked === undefined) {
      return;
    }
    if (this.busy && picked.command.when_busy === "refuse") {
      this.say("warn", `${picked.command.name} cannot run while a request is in flight; try it again when that ends.`);
      return;
    }
    const word = await this.pickWord(picked.command);
    if (word === null) {
      return;
    }
    const argument = await vscode.window.showInputBox({
      title: picked.command.name,
      prompt: picked.command.summary,
      placeHolder: "Argument (optional)",
      value: word === "" ? "" : `${word} `,
    });
    if (argument === undefined) {
      return;
    }
    await this.runCommand(picked.command.name, argument.trim());
  }

  /**
   * Ask which word a command starts with, when it declares any; `""` means it takes none and `null` that the reader
   * closed the list. The choice is only a head start for the argument: it is filled into the box, not run.
   */
  private async pickWord(command: CommandInfo): Promise<string | null> {
    if (command.subcommands.length === 0) {
      return "";
    }
    const picked = await vscode.window.showQuickPick(
      command.subcommands.map((word) => ({ label: word })),
      { title: command.name, placeHolder: "The first word it takes" },
    );
    return picked === undefined ? null : picked.label;
  }

  /**
   * Run one command by name and follow what it answered with: words go to the conversation, and a preset starts a
   * turn with the command as its line and the brief as the instructions the model reads.
   *
   * The palette and the composer's `/` menu both come through here, so a command behaves the same whichever door the
   * reader used.
   */
  private async runCommand(name: string, argument: string): Promise<void> {
    const client = await this.ensureClient();
    const known = this.pluginCommands.length > 0 ? this.pluginCommands : await client.commands();
    const command = known.find((entry) => entry.name === name || entry.name === `/${name}`);
    if (command === undefined) {
      this.say("warn", `No plugin offers a command called ${name}.`);
      return;
    }
    if (this.busy && command.when_busy === "refuse") {
      this.say("warn", `${command.name} cannot run while a request is in flight; try it again when that ends.`);
      return;
    }
    const answer = await client.runCommand(command.name, argument);
    if (answer.notification !== "") {
      void vscode.window.showInformationMessage(`ZettCode: ${answer.notification}`);
    }
    if (answer.prompt !== "") {
      await this.startCommandTurn(answer.prompt, answer.shown || `${command.name} ${argument}`.trim());
      return;
    }
    if (answer.message !== "") {
      await this.announce(answer.message);
    }
  }

  /**
   * Start a command's preset as a turn: the command is what the conversation shows, the preset is what the model
   * reads. The chat is opened first, because a preset is worth a window of its own whereas words are not.
   */
  private async startCommandTurn(instructions: string, shown: string): Promise<void> {
    if (this.busy) {
      this.say("warn", "A run is already going; try the command again when it ends.");
      return;
    }
    // The view first: `readyForPrompt()` reads the health a `load()` writes, and a window that never resolved the
    // chat has none. `initialize()` is idempotent, so it is awaited even when the view is already there.
    if (this.view === null) {
      await vscode.commands.executeCommand("zettcode.openChat");
    }
    await this.initialize();
    await this.sendPrompt({ text: instructions, shown, refuseWhenBusy: true });
  }

  /** Put a command's words where a reader will still find them: a line in the conversation, or a message. */
  private async announce(text: string): Promise<void> {
    if (this.view === null) {
      void vscode.window.showInformationMessage(`ZettCode: ${text}`);
      return;
    }
    const turn = announcement(text, Date.now(), newTurnId("turn-command"));
    this.turns.push(turn);
    this.postTurn(turn, true);
  }

  /** Open the recent-sessions drawer from a command. */
  async showSessions(): Promise<void> {
    if (this.view === null) {
      await vscode.commands.executeCommand("zettcode.openChat");
    }
    await this.initialize();
    await this.refreshSessions(true);
    this.post({ type: "history", open: true });
  }

  private workspaceName(): string {
    return vscode.workspace.workspaceFolders?.[0]?.name ?? "workspace";
  }

  private workspacePath(): string {
    return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? "";
  }

  private configuredPermission(): Permission {
    const value = vscode.workspace.getConfiguration("zettcode").get<string>("permission", "ask");
    // `auto` is what `full` was called; a setting written under the old name still means it.
    const level = value === "auto" ? "full" : value;
    return (["deny", "ask", "safe", "full"].includes(level) ? level : "ask") as Permission;
  }

  // -- webview state -----------------------------------------------------

  private buildState(): WebviewState {
    const server = this.server.current;
    return {
      server: { status: server.status, message: server.message },
      loaded: this.initialized || this.loadFailed,
      loading: this.loading,
      ready: this.health?.ready === true,
      health: this.health,
      settings: this.settings,
      models: this.models,
      currentModel: this.settings?.model.name ?? this.models.find((model) => model.active)?.name ?? null,
      session: this.session,
      sessions: this.sessions,
      busy: this.busy,
      pending: this.pending,
      resumable: this.resumable,
      selfCompaction: this.selfCompaction,
      context: this.contextReport,
      commands: this.pluginCommands,
      version: this.health?.version ?? null,
    };
  }

  private postState(): void {
    this.post({ type: "state", state: this.buildState() });
  }

  private postTurns(): void {
    for (const timer of this.turnTimers.values()) {
      clearTimeout(timer);
    }
    this.turnTimers.clear();
    this.clearDeltas();
    this.post({ type: "turns", turns: this.turns.slice(this.hidden), earlier: requestsBefore(this.turns, this.hidden) });
  }

  /** Send the page of older requests before the ones on show. */
  private loadEarlier(): void {
    if (this.hidden <= 0) {
      return;
    }
    const end = this.hidden;
    this.hidden = pageStart(this.turns, end);
    this.post({
      type: "earlier",
      turns: this.turns.slice(this.hidden, end),
      earlier: requestsBefore(this.turns, this.hidden),
    });
  }

  private postTurn(turn: Turn, immediate: boolean): void {
    this.flushDeltas();
    if (this.view === null) {
      return;
    }
    const existing = this.turnTimers.get(turn.id);
    if (existing !== undefined) {
      clearTimeout(existing);
      this.turnTimers.delete(turn.id);
    }
    if (immediate) {
      this.post({ type: "turn", turn });
      return;
    }
    const timer = setTimeout(() => {
      this.turnTimers.delete(turn.id);
      this.flushDeltas();
      this.post({ type: "turn", turn });
    }, 45);
    this.turnTimers.set(turn.id, timer);
  }

  /** Buffer the deltas of the turn that is running, so the webview gets one small message per frame. */
  private queueDelta(turn: Turn, kind: "text" | "reasoning", text: string): void {
    if (!text) {
      return;
    }
    if (this.deltaTurn !== turn) {
      this.flushDeltas();
      this.deltaTurn = turn;
    }
    if (kind === "text") {
      this.deltaText += text;
    } else {
      this.deltaReasoning += text;
    }
    if (this.deltaTimer === null) {
      this.deltaTimer = setTimeout(() => {
        this.deltaTimer = null;
        this.flushDeltas();
      }, 33);
    }
  }

  private flushDeltas(): void {
    if (this.deltaTimer !== null) {
      clearTimeout(this.deltaTimer);
      this.deltaTimer = null;
    }
    const turn = this.deltaTurn;
    const text = this.deltaText;
    const reasoning = this.deltaReasoning;
    this.deltaTurn = null;
    this.deltaText = "";
    this.deltaReasoning = "";
    if (turn === null || (!text && !reasoning)) {
      return;
    }
    this.post({
      type: "turn-delta",
      turnId: turn.id,
      ...(text ? { text } : {}),
      ...(reasoning ? { reasoning } : {}),
    });
  }

  private clearDeltas(): void {
    if (this.deltaTimer !== null) {
      clearTimeout(this.deltaTimer);
      this.deltaTimer = null;
    }
    this.deltaTurn = null;
    this.deltaText = "";
    this.deltaReasoning = "";
  }

  private post(message: HostMessage): void {
    if (this.view === null) {
      return;
    }
    try {
      void this.view.webview.postMessage(message).then(undefined, () => undefined);
    } catch {
      // The view was disposed between the check and the post.
    }
  }

  /**
   * Say something where the reader will see it: in the conversation when the chat is open, and as an editor message
   * when it is not. An error also goes to the output channel, which is where the one worth keeping is.
   */
  private say(level: "info" | "warn" | "error", text: string): void {
    if (level === "error") {
      this.output.appendLine(`[error] ${text}`);
    }
    if (this.view === null) {
      const message = `ZettCode: ${text}`;
      const shown =
        level === "error"
          ? vscode.window.showErrorMessage(message)
          : level === "warn"
            ? vscode.window.showWarningMessage(message)
            : vscode.window.showInformationMessage(message);
      void shown;
      return;
    }
    this.post({ type: "notice", level, text });
  }

  // -- html --------------------------------------------------------------

  private html(webview: vscode.Webview): string {
    return chatHtml({
      styles: [
        webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "media", "base.css")).toString(),
        webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "dist", "webview.css")).toString(),
      ],
      script: webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "dist", "webview.js")).toString(),
      cspSource: webview.cspSource,
      nonce: randomBytes(16).toString("base64"),
    });
  }
}

/** A long address inside a sentence: its beginning, with an ellipsis where the rest was left out. */
function shorten(text: string, limit = 100): string {
  const clean = text.trim();
  return clean.length <= limit ? clean : `${clean.slice(0, limit)}…`;
}

/** Whether a path already names a place: absolute, a drive path, or home-relative. */
function isRooted(value: string): boolean {
  return path.isAbsolute(value) || /^[A-Za-z]:[\\/]/.test(value) || value.startsWith("~/");
}

function stringOf(args: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

/** The old/new text of an edit call: `old_string`/`new_string`, and the `edits` list of a stored older one. */
function editPairs(args: Record<string, unknown>): EditPair[] {
  const edits = args.edits;
  const list = Array.isArray(edits) ? edits : [args];
  const pairs: EditPair[] = [];
  for (const edit of list) {
    if (edit !== null && typeof edit === "object") {
      const record = edit as Record<string, unknown>;
      const oldText = record.old_string ?? record.old_text ?? record.oldString ?? record.oldText;
      const newText = record.new_string ?? record.new_text ?? record.newString ?? record.newText;
      if (typeof oldText === "string" && typeof newText === "string") {
        pairs.push({ oldText, newText });
      }
    }
  }
  return pairs;
}

function findTool(turn: Turn, callId: string): { arguments: Record<string, unknown> } | null {
  for (const block of turn.blocks) {
    if (block.kind === "tool" && block.tool.callId === callId) {
      return block.tool;
    }
  }
  return null;
}

/** The files among `candidates` whose bytes are exactly `bytes`; a file of another size is not read. */
async function sameBytes(candidates: readonly string[], bytes: Buffer): Promise<string[]> {
  const same: string[] = [];
  for (const candidate of candidates) {
    try {
      const uri = vscode.Uri.file(candidate);
      if ((await vscode.workspace.fs.stat(uri)).size === bytes.length && Buffer.from(await vscode.workspace.fs.readFile(uri)).equals(bytes)) {
        same.push(candidate);
      }
    } catch {
      // A file that cannot be read is not the one that was copied.
    }
  }
  return same;
}

/** The file an editor tab shows, or an empty string for a tab that is not one (a webview, a diff, a terminal). */
function tabPath(input: unknown): string {
  return input instanceof vscode.TabInputText ? input.uri.fsPath : "";
}

function messageOf(error: unknown): string {
  if (error instanceof ZettCodeError) {
    return error.message;
  }
  if (error instanceof RunFailedError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function mediaTypeOf(file: string): string {
  switch (path.extname(file).toLowerCase()) {
    case ".jpg":
    case ".jpeg":
      return "image/jpeg";
    case ".gif":
      return "image/gif";
    case ".webp":
      return "image/webp";
    default:
      return "image/png";
  }
}
