import { reactive } from "vue";
import { attributed, quoted } from "../lib/messages";

/** The message a draft is a reply to: shown above the input as a bar, and written into the message as a quote when it is sent. */
export interface Reply {
  who: string;
  text: string;
}

/** The reply being written in each thread or group (a group's key is `#name`). Kept for the session, not on disk. */
export const replies = reactive<Record<string, Reply | undefined>>({});

export function setReply(key: string, who: string, text: string): void {
  replies[key] = { who, text };
}

export function clearReply(key: string): void {
  delete replies[key];
}

/** What to send for `body` in `key`: the quote of the message being replied to, a blank line, then the text. */
export function withReply(key: string, body: string): string {
  const reply = replies[key];
  return reply ? quoted(attributed(reply.who, reply.text)) + body : body;
}
