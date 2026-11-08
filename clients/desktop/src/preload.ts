// The one bridge the page may call. It carries the server list and notices; it holds no file system and no network,
// so a message that somehow ran a script in the page could not reach the machine through it.

import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("__zettcodeNative", {
  loadServers: () => ipcRenderer.invoke("servers:load") as Promise<unknown>,
  saveServers: (state: unknown) => ipcRenderer.invoke("servers:save", state) as Promise<void>,
  notify: (title: string, body: string): void => {
    void ipcRenderer.invoke("notice:show", title, body);
  },
});
