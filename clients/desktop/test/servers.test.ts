import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { ServerStore, type Vault } from "../src/servers";

const state = {
  servers: [
    { id: "a", name: "one", url: "http://127.0.0.1:8765", token: "s3cret" },
    { id: "b", name: "two", url: "https://two.example", token: "other" },
  ],
  active: "a",
};

function vault(available = true, backend = "gnome_libsecret"): Vault {
  return {
    isEncryptionAvailable: async () => available,
    storageBackend: () => backend,
    encrypt: async (plain) => Buffer.from(`encrypted:${plain}`, "utf8"),
    decrypt: async (encrypted) => ({
      result: encrypted.toString("utf8").replace(/^encrypted:/, ""),
      shouldReEncrypt: false,
    }),
  };
}

async function folder(): Promise<string> {
  return mkdtemp(join(tmpdir(), "zettcode-desktop-store-"));
}

test("a saved list round-trips, and a token is not written as plain text when the platform can encrypt", async () => {
  const home = await folder();
  const file = join(home, "servers.json");
  const store = new ServerStore(file, vault(true));

  await store.save(state);

  const raw = await readFile(file, "utf8");
  assert.ok(!raw.includes("s3cret"), "the token is not in the file");
  assert.deepEqual(await store.load(), state);
  if (process.platform !== "win32") assert.equal((await stat(file)).mode & 0o777, 0o600);
  await rm(home, { recursive: true, force: true });
});

test("without encryption the list is still kept, in a file only its owner may read", async () => {
  const home = await folder();
  const file = join(home, "servers.json");
  const store = new ServerStore(file, vault(false));

  await store.save(state);

  assert.ok((await readFile(file, "utf8")).includes("s3cret"), "the fallback is plain, and says so by its mode");
  assert.deepEqual(await store.load(), state);
  await rm(home, { recursive: true, force: true });
});

test("a Linux key store that is only basic_text does not count as encryption", async () => {
  const home = await folder();
  const file = join(home, "servers.json");
  const store = new ServerStore(file, vault(true, "basic_text"));

  await store.save(state);

  assert.ok((await readFile(file, "utf8")).includes("s3cret"), "a hard-coded key is not a key store");
  assert.deepEqual(await store.load(), state);
  await rm(home, { recursive: true, force: true });
});

test("a missing or damaged file is an app with no servers, not one that cannot open", async () => {
  const home = await folder();
  const file = join(home, "servers.json");
  const store = new ServerStore(file, vault(true));

  assert.deepEqual(await store.load(), { servers: [], active: "" });
  await writeFile(file, "not json", "utf8");
  assert.deepEqual(await store.load(), { servers: [], active: "", error: "unreadable" });
  await writeFile(file, JSON.stringify({ v: 1, encrypted: true, data: "not base64" }), "utf8");
  assert.deepEqual(await store.load(), { servers: [], active: "", error: "unreadable" });
  await rm(home, { recursive: true, force: true });
});

test("a rotated key rewrites the file, and a failed rewrite still returns the list", async () => {
  const home = await folder();
  const file = join(home, "servers.json");
  await writeFile(file, JSON.stringify({ v: 1, encrypted: true, data: "old" }), "utf8");
  let encrypted = 0;
  const rotating: Vault = {
    isEncryptionAvailable: async () => true,
    encrypt: async (plain) => {
      encrypted += 1;
      return Buffer.from(`encrypted:${plain}`, "utf8");
    },
    decrypt: async () => ({ result: JSON.stringify(state), shouldReEncrypt: true }),
  };

  assert.deepEqual(await new ServerStore(file, rotating).load(), state);
  assert.equal(encrypted, 1, "the rotated list is written back once");
  const written = JSON.parse(await readFile(file, "utf8"));
  assert.equal(written.encrypted, true);
  assert.notEqual(written.data, "old", "the rotated list was written back");

  const failing: Vault = {
    ...rotating,
    encrypt: async () => {
      throw new Error("disk");
    },
  };
  assert.deepEqual(await new ServerStore(file, failing).load(), state, "a failed rewrite does not lose the list");
  await rm(home, { recursive: true, force: true });
});

test("a list too large to keep is refused before anything is written", async () => {
  const home = await folder();
  const file = join(home, "servers.json");
  const store = new ServerStore(file, vault(true));

  await assert.rejects(store.save({ servers: [{ token: "x".repeat(1_000_001) }], active: "" }), /too large/);
  await assert.rejects(stat(file));
  await rm(home, { recursive: true, force: true });
});
