/** The slash commands the composer offers: the terminal's, as far as the server reaches. */

import { formatTokens, permissionDescription } from "../core/format.js";
import type { Permission } from "../../../typescript/src/types.js";
import { openOverlay, post, state, toast } from "./store.js";

export interface SlashCommand {
  name: string;
  description: string;
  /** What follows the name, shown as a ghost hint once the name is typed; a command with one waits for it. */
  args?: string;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { name: "new", description: "Start a new session" },
  { name: "resume", description: "Recent sessions" },
  { name: "continue", description: "Carry on the request that was cut short" },
  { name: "compact", description: "Summarize the conversation now" },
  { name: "fork", description: "Fork this conversation into a new session" },
  { name: "rename", description: "Rename this session", args: "a new name for this session" },
  { name: "name", description: "Let the model name this session" },
  { name: "export", description: "Export the conversation as HTML" },
  { name: "model", description: "Choose a model or add one" },
  { name: "effort", description: "Choose the reasoning effort" },
  { name: "permission", description: "Choose the shell permission" },
  { name: "harness", description: "Let the model write and run its own tools: on or off", args: "on or off" },
  { name: "usage", description: "Workspace usage and tokens" },
  { name: "context", description: "The context window and what fills it" },
  { name: "doctor", description: "Check that every model answers" },
  { name: "btw", description: "Ask a side question that stays out of the conversation", args: "ask a side question…" },
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
 * takes a name one of these already has does not replace it — the view's own `/stop` still stops.
 */
export function allCommands(): SlashCommand[] {
  const own = new Set(SLASH_COMMANDS.map((command) => command.name));
  return [...SLASH_COMMANDS, ...pluginCommands().filter((command) => !own.has(command.name))];
}

/** The command with this name, if we know it. */
export function commandOf(name: string): SlashCommand | undefined {
  return allCommands().find((command) => command.name === name);
}

/** The words a plugin command declares it takes first, in the order it declared them. */
function pluginWords(name: string): string[] {
  return state.ui?.commands.find((command) => command.name.replace(/^\//, "") === name)?.subcommands ?? [];
}

export interface CommandArgument {
  /** The word typed after the command, such as `on` for `/harness on`. */
  word: string;
  /** What it does, in the line the menu shows beside it. */
  description: string;
}

/**
 * The words one command takes, when they can be listed: the levels, the models, `on` and `off`.
 *
 * A command whose argument is free text (`/rename`, `/btw`) has none, and gets no second-level menu; the list is read
 * from the state the host last sent, so `/model ` offers the models that are configured now.
 */
export function argumentsOf(name: string): CommandArgument[] {
  const words = pluginWords(name);
  if (words.length > 0) {
    return words.map((word) => ({ word, description: "" }));
  }
  const settings = state.ui?.settings ?? null;
  switch (name) {
    case "harness":
      return [
        { word: "on", description: "Let the model write and run small Python tools of its own" },
        { word: "off", description: "The model has only the tools ZettCode ships" },
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

/** `/name rest`, when `name` is a command we know; anything else is a message. */
export function parseSlash(text: string): { name: string; rest: string } | null {
  const match = /^\/([\w-]+)(?:\s+([\s\S]*))?$/.exec(text);
  if (match?.[1] === undefined) {
    return null;
  }
  if (commandOf(match[1]) === undefined) {
    return null;
  }
  return { name: match[1], rest: match[2] ?? "" };
}

export function runSlash(name: string, rest = ""): void {
  if (!SLASH_COMMANDS.some((command) => command.name === name)) {
    // A command a plugin registered: the host runs it against the server, the way the palette does, so what came back
    // (words, a toast, a preset for a turn) is handled in exactly one place.
    post({ type: "run-command", name: `/${name}`, argument: rest.trim() });
    return;
  }
  switch (name) {
    case "new":
      post({ type: "new-session" });
      break;
    case "resume":
      openOverlay("drawer");
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
    case "rename":
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
      post({ type: "export" });
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
    case "harness": {
      const word = rest.trim().toLowerCase();
      const now = state.ui?.settings?.harness === true;
      if (word === "on" || word === "off") {
        post({ type: "set-harness", on: word === "on" });
      } else if (word === "") {
        toast(`The tool harness is ${now ? "on" : "off"}. Use /harness on or /harness off.`, "info");
      } else {
        toast("Use /harness on or /harness off.", "info");
      }
      break;
    }
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
        post({ type: "ask", question: rest.trim() });
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
