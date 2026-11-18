// The sections of the two pages that are lists of sections, so the pane that lists them and the page that shows one agree.

import type { IconName } from "./components/common/icons";
import type { Nav } from "./stores/route";

export interface Section {
  id: string;
  label: string;
  icon: IconName;
}

/** One tab of the rail, which is the page's main navigation. `extra` tabs sit behind "More" on a phone, where seven would
 * not fit; the wide rail shows them all. */
export interface Tab {
  nav: Nav;
  label: string;
  icon: IconName;
  extra?: boolean;
}

/** Every section of the page has exactly one tab (a test holds this to `NAVS`), and four stay in a phone's bar. */
export const TABS: Tab[] = [
  { nav: "chats", label: "Chats", icon: "chat" },
  { nav: "new", label: "New", icon: "plus" },
  { nav: "config", label: "Config", icon: "config", extra: true },
  { nav: "logs", label: "Logs", icon: "logs", extra: true },
  { nav: "graph", label: "Graph", icon: "graph", extra: true },
  { nav: "dashboard", label: "Dashboard", icon: "chart" },
  { nav: "settings", label: "Settings", icon: "settings" },
];

/** How many tabs a phone's bar shows before "More" (which makes the fifth slot). `extra` is what hides a tab there (the
 * rail's CSS does it, below 720px); a test holds the count of the others to this, so the two are changed together. */
export const PHONE_TABS = 4;

export const CONFIG_SECTIONS: Section[] = [
  { id: "models", label: "Models", icon: "bot" },
  { id: "defaults", label: "Defaults", icon: "config" },
  { id: "workspaces", label: "Workspaces", icon: "folder" },
  { id: "sending", label: "Sending", icon: "send" },
  { id: "limits", label: "Limits", icon: "clock" },
];

export const DASHBOARD_SECTIONS: Section[] = [
  { id: "overview", label: "Overview", icon: "chart" },
  { id: "daemons", label: "Daemons", icon: "bot" },
];

export const SETTINGS_SECTIONS: Section[] = [
  { id: "servers", label: "Servers", icon: "plug" },
  { id: "connection", label: "Connection", icon: "info" },
  { id: "appearance", label: "Appearance", icon: "settings" },
  { id: "notifications", label: "Notifications", icon: "bell" },
  { id: "data", label: "Data", icon: "trash" },
];
