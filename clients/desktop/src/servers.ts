// What this computer remembers: the gateway servers and their tokens. The tokens are encrypted with the operating
// system's own key store where there is one, and the file is readable by its owner only either way.

import { mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

/** The part of Electron's `safeStorage` the store needs, so a test can stand in for the operating system. */
export interface Vault {
  /** Whether the platform can actually encrypt; Electron's `isAsyncEncryptionAvailable`. */
  isEncryptionAvailable(): Promise<boolean>;
  /** The selected backend on Linux; `basic_text` uses a hard-coded key and is not a key store. */
  storageBackend?(): string;
  /** Encrypt one string, asynchronously (Electron's `encryptStringAsync`). */
  encrypt(plain: string): Promise<Buffer>;
  /** Decrypt one buffer; `shouldReEncrypt` is Electron's key-rotation hint. */
  decrypt(encrypted: Buffer): Promise<{ result: string; shouldReEncrypt: boolean }>;
}

/** The file's shape. `data` is the server list itself, or that list encrypted and written as base64. */
interface Envelope {
  v: 1;
  encrypted: boolean;
  data: string;
}

/** What an app with no saved server opens on. */
const EMPTY = { servers: [], active: "" };

/** A store that exists but cannot be read: the list is empty, and the page is told rather than shown a silent zero. */
function damaged(): unknown {
  return { ...EMPTY, error: "unreadable" };
}

/** The most a saved list may be; a profile list is a few hundred bytes, and a runaway renderer is not. */
const LIMIT = 1_000_000;

export class ServerStore {
  /**
   * @param file Where the list is kept.
   * @param vault The operating system's encryption, or a stand-in in a test.
   */
  constructor(
    private readonly file: string,
    private readonly vault: Vault,
  ) {}

  /** Read the list; a missing, damaged, or undecryptable file is an app with no servers rather than one that cannot start. */
  async load(): Promise<unknown> {
    let text: string;
    try {
      text = await readFile(this.file, "utf8");
    } catch (failure) {
      if ((failure as NodeJS.ErrnoException).code === "ENOENT") return { ...EMPTY };
      throw failure;
    }
    let envelope: Partial<Envelope>;
    try {
      envelope = JSON.parse(text) as Partial<Envelope>;
    } catch {
      return damaged();
    }
    if (envelope.v !== 1 || typeof envelope.data !== "string") return damaged();
    let json = envelope.data;
    let reencrypt = false;
    try {
      if (envelope.encrypted) {
        const answer = await this.vault.decrypt(Buffer.from(envelope.data, "base64"));
        json = answer.result;
        reencrypt = answer.shouldReEncrypt;
      }
    } catch {
      return damaged();
    }
    try {
      const state = JSON.parse(json) as unknown;
      // The key rotated; write it back with the current one. A failed write still leaves the list readable.
      if (reencrypt) await this.save(state).catch(() => undefined);
      return state;
    } catch {
      return damaged();
    }
  }

  /** Keep the list, encrypting it where the platform can, and never writing a partial file. */
  async save(state: unknown): Promise<void> {
    const json = JSON.stringify(state ?? EMPTY);
    if (json.length > LIMIT) throw new Error("The server list is too large to keep");
    let envelope: Envelope;
    if (await this.canEncrypt()) {
      envelope = { v: 1, encrypted: true, data: (await this.vault.encrypt(json)).toString("base64") };
    } else {
      envelope = { v: 1, encrypted: false, data: json };
    }
    await mkdir(dirname(this.file), { recursive: true, mode: 0o700 });
    // One replace, so a reader never sees half a list and a crash never leaves one.
    const temporary = `${this.file}.${process.pid}.${Math.random().toString(36).slice(2, 10)}.tmp`;
    try {
      await writeFile(temporary, JSON.stringify(envelope), { encoding: "utf8", mode: 0o600 });
      await rename(temporary, this.file);
    } catch (failure) {
      await unlink(temporary).catch(() => undefined);
      throw failure;
    }
  }

  private async canEncrypt(): Promise<boolean> {
    try {
      if (!(await this.vault.isEncryptionAvailable())) return false;
      return this.vault.storageBackend?.() !== "basic_text";
    } catch {
      return false;
    }
  }
}
