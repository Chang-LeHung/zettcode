// The sections of the two pages that are lists of sections, so the pane that lists them and the page that shows one agree.

import type { IconName } from "./components/common/icons";

export interface Section {
  id: string;
  label: string;
  icon: IconName;
}

export const CONFIG_SECTIONS: Section[] = [
  { id: "models", label: "Models", icon: "bot" },
  { id: "defaults", label: "Defaults", icon: "config" },
  { id: "workspaces", label: "Workspaces", icon: "folder" },
  { id: "sending", label: "Sending", icon: "send" },
  { id: "limits", label: "Limits", icon: "clock" },
];

export const SETTINGS_SECTIONS: Section[] = [
  { id: "connection", label: "Connection", icon: "info" },
  { id: "appearance", label: "Appearance", icon: "settings" },
  { id: "notifications", label: "Notifications", icon: "bell" },
  { id: "data", label: "Data", icon: "trash" },
];
