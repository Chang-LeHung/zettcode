/** The slash commands the composer offers: the terminal's, as far as the server reaches. */

import { formatTokens, permissionDescription } from "../core/format.js";
import type { Permission } from "../../../typescript/src/types.js";
import { enqueueAsk, openOverlay, post, state, toast } from "./store.js";

export interface SlashCommand {
  name: string;
  description: string;
  /** What follows the name, shown as a ghost hint once the name is typed; `requiresArg` says whether running it bare is wrong. */
  args?: string;
  /** Other spellings that reach this command, kept out of the menu so one command has one name in it. */
  aliases?: readonly string[];
  /** Whether the command cannot run without what follows, so choosing it completes the line instead of running it. */
  requiresArg?: boolean;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { name: "help", description: "Show the commands and keys" },
  { name: "new", description: "Start a new session" },
  { name: "resume", description: "Recent sessions", args: "a session id, or pick from the list" },
  { name: "continue", description: "Carry on the request that was cut short" },
  { name: "compact", description: "Summarize the conversation now" },
  { name: "fork", description: "Fork this conversation into a new session" },
  { name: "title", description: "Name this session", aliases: ["rename"], args: "a new name for this session" },
  { name: "name", description: "Let the model name this session" },
  { name: "export", description: "Export the conversation as HTML", args: "a path, or pick one" },
  { name: "model", description: "Choose a model or add one" },
  { name: "config", description: "Add, change or remove models", args: "add | edit <name> | remove <name> | list" },
  { name: "plugins", description: "Switch a plugin on or off for the next start", args: "enable | disable <name>" },
  { name: "effort", description: "Choose the reasoning effort" },
  { name: "permission", description: "Choose the shell permission" },
  { name: "usage", description: "Workspace usage and tokens" },
  { name: "context", description: "The context window and what fills it" },
  { name: "doctor", description: "Check that every model answers" },
  { name: "btw", description: "Ask a side question that stays out of the conversation", args: "ask a side question…", requiresArg: true },
  { name: "stop", description: "Stop the run in progress" },
  { name: "clear", description: "Clear this view (the session is kept)" },
];

/**
 * The plugin commands the host last sent, spelled the way the ones above are: the server's `/greet` is `name: "greet"`.
 *
 * A command that declares the words it takes first gets them as its ghost hint, so the composer waits for one.
 */
export function pluginCommands(): SlashCommand[] {
  return (state.ui?.commands ?? []).map((command) => ({
    name: command.name.replace(/^\//, ""),
    description: command.summary,
    ...(command.subcommands.length === 0 ? {} : { args: command.subcommands.join(" | ") }),
  }));
}

/**
 * Every command the menu offers: the ones this view knows how to run, then the ones a plugin registered. A plugin that
 * takes a name one of these already has does not replace it — the view's own `/stop` still stops. An alias is not a
 * second row: `/rename` reaches `/title`, and the menu keeps the terminal's name.
 */
export function allCommands(): SlashCommand[] {
  const own = new Set(SLASH_COMMANDS.flatMap((command) => [command.name, ...(command.aliases ?? [])]));
  return [...SLASH_COMMANDS, ...pluginCommands().filter((command) => !own.has(command.name))];
}

/** The command with this name, if we know it; an alias finds the command it stands for. */
export function commandOf(name: string): SlashCommand | undefined {
  return allCommands().find((command) => command.name === name || command.aliases?.includes(name) === true);
}

/** The command a plugin registered, as the host last sent it. */
function pluginDefinition(name: string) {
  return state.ui?.commands.find((command) => command.name.replace(/^\//, "") === name);
}

export interface CommandArgument {
  /** The word typed after the command, such as `gen` for `/harness gen`. */
  word: string;
  /** What it does, in the line the menu shows beside it. */
  description: string;
  /** Whether something follows the word, so choosing it fills the name in instead of running it. */
  needsMore?: boolean;
}

/**
 * The words one command takes, when they can be listed: the levels, the models, the harness words.
 *
 * A command whose argument is free text (`/title`, `/btw`) has none, and gets no second-level menu; the list is read
 * from the state the host last sent, so `/model ` offers the models that are configured now.
 */
export function argumentsOf(name: string): CommandArgument[] {
  const plugin = pluginDefinition(name);
  const words = plugin?.subcommands ?? [];
  if (words.length > 0) {
    const needsMore = new Set(plugin?.needs_more ?? []);
    return words.map((word) => ({ word, description: "", needsMore: needsMore.has(word) }));
  }
  const settings = state.ui?.settings ?? null;
  switch (name) {
    case "config":
      return [
        { word: "add", description: "Add a model to the configuration file" },
        { word: "edit", description: "Change one model's settings", needsMore: true },
        { word: "remove", description: "Remove a model", needsMore: true },
        { word: "list", description: "Show the models in the file" },
      ];
    case "plugins":
      return [
        { word: "enable", description: "Switch a plugin on at the next start", needsMore: true },
        { word: "disable", description: "Leave a plugin out at the next start", needsMore: true },
      ];
    case "permission":
      return (settings?.permissions ?? []).map((level) => ({ word: level, description: permissionDescription(level) }));
    case "effort":
      return (settings?.efforts ?? []).map((level) => ({ word: level, description: "" }));
    case "model":
      return [
        ...(state.ui?.models ?? []).map((model) => ({
          word: model.name,
          description: `${model.model} \u00b7 ${formatTokens(model.context_window)}`,
        })),
        { word: "add", description: "Add a model to the configuration file" },
      ];
    default:
      return [];
  }
}

/** `/name rest`, when `name` is a command we know; anything else is a message. An alias is answered as its command. */
export function parseSlash(text: string): { name: string; rest: string } | null {
  const match = /^\/([\w-]+)(?:\s+([\s\S]*))?$/.exec(text);
  if (match?.[1] === undefined) {
    return null;
  }
  const command = commandOf(match[1]);
  if (command === undefined) {
    return null;
  }
  return { name: command.name, rest: match[2] ?? "" };
}

/** The commands and what they take, as the `/help` document a reader can keep beside the chat. */
export function helpText(): string {
  const lines = [
    "# Commands",
    "",
    "Type `/` to see them; `Tab` completes a name and `Enter` runs it. Text after a command is what it acts on.",
    "",
  ];
  for (const command of allCommands()) {
    const name = `/${command.name}${command.args ? ` ${command.args}` : ""}`;
    lines.push(`- \`${name}\` — ${command.description}`);
  }
  return lines.join("\n");
}

export function runSlash(name: string, rest = ""): void {
  const command = commandOf(name);
  const canonical = command?.name ?? name;
  if (!SLASH_COMMANDS.some((entry) => entry.name === canonical)) {
    // A command a plugin registered: the host runs it against the server, the way the palette does, so what came back
    // (words, a toast, a preset for a turn) is handled in exactly one place.
    post({ type: "run-command", name: `/${canonical}`, argument: rest.trim() });
    return;
  }
  switch (canonical) {
    case "help":
      post({ type: "show-document", title: "Commands", markdown: helpText() });
      break;
    case "new":
      post({ type: "new-session" });
      break;
    case "resume":
      if (rest.trim()) {
        post({ type: "open-session", id: rest.trim() });
      } else {
        openOverlay("drawer");
      }
      break;
    case "continue":
      if (state.ui?.resumable?.resumable !== true) {
        toast("There is no interrupted request to continue.", "info");
        break;
      }
      post({ type: "resume" });
      break;
    case "compact":
      post({ type: "compact" });
      break;
    case "fork":
      post({ type: "fork-session" });
      break;
    case "title":
      if (rest.trim()) {
        post({ type: "rename-session", title: rest.trim() });
      } else {
        state.renaming = true;
      }
      break;
    case "name":
      post({ type: "name-session" });
      break;
    case "export":
      post({ type: "export", ...(rest.trim() ? { path: rest.trim() } : {}) });
      break;
    case "model":
      if (rest.trim() === "add") {
        state.editingModel = null;
        openOverlay("add-model");
      } else if (rest.trim()) {
        post({ type: "set-model", name: rest.trim() });
      } else {
        openOverlay("models");
      }
      break;
    case "config": {
      const [word, ...tail] = rest.trim().split(/\s+/);
      const name = tail.join(" ").trim();
      const known = (state.ui?.models ?? []).some((model) => model.name === name);
      if (word === undefined || word === "" || word === "list") {
        openOverlay("models");
      } else if (word === "add") {
        state.editingModel = null;
        openOverlay("add-model");
      } else if (word === "edit" && name) {
        if (!known) {
          toast(`No model called ${name}.`, "info");
          break;
        }
        state.editingModel = name;
        openOverlay("edit-model");
      } else if (word === "remove" && name) {
        if (!known) {
          toast(`No model called ${name}.`, "info");
          break;
        }
        // The model menu's own row asks before it removes; a typed name opens that row in the same state.
        state.confirmingModel = name;
        openOverlay("models");
      } else {
        toast("Use /config, /config add, /config edit <name> or /config remove <name>.", "info");
      }
      break;
    }
    case "plugins": {
      const [word, ...tail] = rest.trim().split(/\s+/);
      const name = tail.join(" ").trim();
      if (word === undefined || word === "") {
        post({ type: "plugins" });
      } else if ((word === "enable" || word === "disable") && name) {
        post({ type: "set-plugin", name, enabled: word === "enable" });
      } else {
        toast("Use /plugins, /plugins enable <name> or /plugins disable <name>.", "info");
      }
      break;
    }
    case "effort":
      if (rest.trim()) {
        post({ type: "set-effort", effort: rest.trim() });
      } else {
        openOverlay("effort");
      }
      break;
    case "permission":
      if (rest.trim()) {
        post({ type: "set-permission", permission: rest.trim() as Permission });
      } else {
        openOverlay("permission");
      }
      break;
    case "usage":
      post({ type: "usage" });
      break;
    case "context":
      openOverlay("context");
      break;
    case "doctor":
      post({ type: "doctor" });
      break;
    case "btw":
      if (rest.trim()) {
        if (state.ui?.busy === true) {
          enqueueAsk(rest.trim());
        } else {
          post({ type: "ask", question: rest.trim() });
        }
      } else {
        toast("Use /btw followed by a question.", "info");
      }
      break;
    case "stop":
      post({ type: "cancel" });
      break;
    case "clear":
      state.turns = [];
      state.collapsed.clear();
      break;
    default:
      toast(`Unknown command: /${name}`, "warn");
      break;
  }
}
