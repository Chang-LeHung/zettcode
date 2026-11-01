// Where the page is: a section and, inside it, one thing. The address is the state, so the back button of a phone
// and a link to a conversation both work, and a reload comes back to the same place.
//
//   #/chats/<thread id>   #/new   #/config/<section>   #/logs/<thread id>   #/graph   #/settings/<section>

import { reactive } from "vue";

export const NAVS = ["chats", "new", "config", "logs", "graph", "settings"] as const;
export type Nav = (typeof NAVS)[number];

export const route = reactive<{ nav: Nav; arg: string }>({ nav: "chats", arg: "" });

export function parseRoute(hash: string): { nav: Nav; arg: string } {
  const [name = "", arg = ""] = hash.replace(/^#\/?/, "").split("/");
  const nav = NAVS.find((candidate) => candidate === name) ?? "chats";
  let decoded = arg;
  try {
    decoded = decodeURIComponent(arg);
  } catch {
    // An address that does not decode names nothing.
    decoded = "";
  }
  return { nav, arg: decoded };
}

export function href(nav: Nav, arg = ""): string {
  return `#/${nav}${arg ? `/${encodeURIComponent(arg)}` : ""}`;
}

export function go(nav: Nav, arg = ""): void {
  location.hash = href(nav, arg);
}

export function readRoute(): void {
  Object.assign(route, parseRoute(location.hash));
}

export function watchRoute(): void {
  readRoute();
  window.addEventListener("hashchange", readRoute);
}
