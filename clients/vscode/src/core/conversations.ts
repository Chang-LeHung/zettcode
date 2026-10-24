/**
 * The conversations the view has open, and which one is on show.
 *
 * A run belongs to the conversation it began in. Looking at another conversation does not stop it: it goes on writing to
 * its own turns, and opening that conversation again finds them where the run got to. So a conversation that is running
 * is kept when the reader leaves it, and one that is not is dropped, because the store holds everything it had and
 * opening it reads it back.
 */

import type { PendingRequest } from "../../../typescript/src/types.js";
import type { Turn } from "./state.js";

/** The part of a run this module needs: that there is one, which the host can stop. The HTTP client's `Run` fits. */
export interface RunHandle {
  cancel(): Promise<unknown> | unknown;
}

/** What belongs to one conversation: its transcript, and the run that may be going in it. */
export interface Conversation {
  turns: Turn[];
  /** How many turns at the front of `turns` have not been sent to the view. */
  hidden: number;
  /** The turn the run in progress is writing to. */
  running: Turn | null;
  run: RunHandle | null;
  busy: boolean;
  pending: PendingRequest | null;
}

export function newConversation(): Conversation {
  return { turns: [], hidden: 0, running: null, run: null, busy: false, pending: null };
}

export class Conversations {
  /** The conversation on show. */
  current: Conversation = newConversation();
  private readonly held = new Map<string, Conversation>();

  /** The conversation kept for a session, when one is: a running one. */
  find(id: string): Conversation | undefined {
    return this.held.get(id);
  }

  /** Keep a conversation under its session, so opening that session again finds the live transcript. */
  register(id: string, conversation: Conversation): void {
    this.held.set(id, conversation);
  }

  /**
   * Put a conversation on show. The one that was on show is kept only while it is running, so a run that is not on
   * show goes on being written to its own turns; an idle one is let go.
   */
  show(id: string, conversation: Conversation): void {
    const leaving = this.current;
    if (leaving !== conversation && !leaving.busy) {
      this.forget(leaving);
    }
    this.held.set(id, conversation);
    this.current = conversation;
  }

  /** Let go of a conversation, by identity: a run that ended while another one was on show. */
  forget(conversation: Conversation): void {
    for (const [id, held] of this.held) {
      if (held === conversation) {
        this.held.delete(id);
      }
    }
  }

  /** Whether a conversation is the one on show. */
  isShown(conversation: Conversation): boolean {
    return this.current === conversation;
  }

  /** Forget everything, as when the server restarted and none of its runs is still there. */
  reset(): void {
    this.held.clear();
    this.current = newConversation();
  }

  /** The sessions that are running, shown or not. */
  runningIds(): string[] {
    return [...this.held].filter(([, conversation]) => conversation.busy).map(([id]) => id);
  }
}
