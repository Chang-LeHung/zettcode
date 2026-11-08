// The servers this app can reach: the list kept by the shell, the one that is active, and the hand-off to the API
// layer. Choosing another server reloads the page, so nothing one gateway answered can be drawn beside another's.

import { reactive } from "vue";
import { configure, normalizeBaseUrl } from "../api/connection";
import { t } from "../i18n";
import { nativeBridge, type NativeBridge } from "../lib/native";
import { makeProfile, parseStored, type ServerProfile } from "../lib/servers";
import { useScope } from "../lib/storage";

export const servers = reactive({
  /** `app` when a shell carries this page; `web` for the page the gateway serves itself. */
  mode: "web" as "web" | "app",
  active: null as ServerProfile | null,
  list: [] as ServerProfile[],
  /** Why the last attempt to reach the active server failed, shown over the server list. */
  problem: "",
  bridge: null as NativeBridge | null,
});

/** Read the servers the shell keeps and point the API layer at the active one. */
export async function loadServers(): Promise<void> {
  const bridge = nativeBridge();
  if (!bridge) {
    servers.mode = "web";
    useScope("");
    return;
  }
  servers.mode = "app";
  servers.bridge = bridge;
  try {
    const stored = parseStored(await bridge.loadServers());
    servers.list = stored.servers;
    servers.active = stored.servers.find((server) => server.id === stored.active) ?? null;
    servers.problem =
      stored.error === "unreadable" ? "The saved server list could not be read" : (stored.error ?? "");
  } catch (failure) {
    servers.problem = message(failure);
  }
  if (servers.active) use(servers.active);
  useScope(servers.active?.id ?? "");
}

/** Point every API call at one server. */
function use(profile: ServerProfile): void {
  configure({ baseUrl: profile.url, token: profile.token });
}

/** Keep a list and a chosen id in the shell's own store, as plain data the bridge can copy. */
async function keep(list: ServerProfile[], active: ServerProfile | null): Promise<void> {
  if (!servers.bridge) return;
  await servers.bridge.saveServers({
    servers: list.map(({ id, name, url, token }) => ({ id, name, url, token })),
    active: active?.id ?? "",
  });
}

/** Add a server from a form, keeping it only when its address and token are usable. */
export async function addServer(input: { name: string; url: string; token: string }): Promise<ServerProfile> {
  const profile = makeProfile(input);
  await keep([...servers.list, profile], servers.active);
  servers.list = [...servers.list, profile];
  return profile;
}

/** Change a server in place, keeping its id so it stays the one the app used last. */
export async function updateServer(
  id: string,
  input: { name: string; url: string; token: string },
): Promise<ServerProfile> {
  const profile = makeProfile(input, id);
  const next = servers.list.map((server) => (server.id === id ? profile : server));
  await keep(next, servers.active);
  servers.list = next;
  return profile;
}

/** Forget a server; the chosen one is forgotten too when it is the one removed. */
export async function removeServer(id: string): Promise<void> {
  const next = servers.list.filter((server) => server.id !== id);
  const active = servers.active?.id === id ? null : servers.active;
  await keep(next, active);
  servers.list = next;
  servers.active = active;
}

/** Use a server now: remember it first, then point the API at it and reload, so a failed save changes nothing. */
export async function connectServer(profile: ServerProfile): Promise<void> {
  const switching = servers.active?.id !== profile.id;
  await keep(servers.list, profile);
  servers.active = profile;
  servers.problem = "";
  use(profile);
  // A chat id belongs to one gateway: opening the same one on another would show its refusal, not a conversation.
  if (switching) location.hash = "#/chats";
  location.reload();
}

/** Go back to the server list; a sign-out in the app is this, not a cookie the server would revoke. */
export async function disconnectServer(): Promise<void> {
  await keep(servers.list, null);
  servers.active = null;
  servers.problem = "";
  configure({ baseUrl: "", token: "" });
  location.reload();
}

/** Ask a server whether it is reachable and whether this token is its own, before anything is saved. */
export async function testConnection(url: string, token: string): Promise<{ ok: boolean; message: string }> {
  let base: string;
  try {
    base = normalizeBaseUrl(url);
  } catch (failure) {
    return { ok: false, message: t(message(failure)) };
  }
  const given = token.trim();
  if (!given) return { ok: false, message: t("The gateway's token is required") };
  try {
    const answer = await fetch(`${base}/api/session`, { headers: { authorization: `Bearer ${given}` } });
    const data = (await answer.json().catch(() => null)) as
      | { authenticated?: boolean; open?: boolean; error?: { message?: string } }
      | null;
    if (answer.status === 401 || data?.authenticated !== true) {
      return { ok: false, message: data?.error?.message || t("That is not the token") };
    }
    if (data.open === true) {
      return { ok: false, message: t("This gateway has no token; start it with --token to use the app") };
    }
    const status = await fetch(`${base}/api/status`, { headers: { authorization: `Bearer ${given}` } });
    if (!status.ok) {
      const body = (await status.json().catch(() => null)) as { error?: { message?: string } } | null;
      return {
        ok: false,
        message: body?.error?.message || t("The gateway answered {status}", { status: status.status }),
      };
    }
    const body = (await status.json()) as { version?: string; gateway?: { handle?: string } };
    const version = body.version ? `ZettCode ${body.version}` : "ZettCode";
    const handle = body.gateway?.handle ? ` · @${body.gateway.handle}` : "";
    return { ok: true, message: `${version}${handle}` };
  } catch {
    return { ok: false, message: t("Cannot reach that server") };
  }
}

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}
