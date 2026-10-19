/** The slash commands the composer offers: the terminal's, as far as the server reaches. */

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
  { name: "usage", description: "Workspace usage and tokens" },
  { name: "context", description: "The context window and what fills it" },
  { name: "doctor", description: "Check that every model answers" },
  { name: "btw", description: "Ask a side question that stays out of the conversation", args: "ask a side question…" },
  { name: "stop", description: "Stop the run in progress" },
  { name: "clear", description: "Clear this view (the session is kept)" },
];

/** The command with this name, if we know it. */
export function commandOf(name: string): SlashCommand | undefined {
  return SLASH_COMMANDS.find((command) => command.name === name);
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
      openOverlay("models");
      break;
    case "effort":
      openOverlay("effort");
      break;
    case "permission":
      openOverlay("permission");
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
