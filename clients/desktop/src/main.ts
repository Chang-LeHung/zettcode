// The Electron shell: it serves the app bundle from `app://-/` (so the page has a stable, secure origin), keeps the
// server list in the operating system's key store, and opens links outside the window. It holds no agent and no
// gateway: everything in the page is the same HTTP client the gateway's own page uses.

import { app, BrowserWindow, ipcMain, Notification, protocol, safeStorage, session, shell } from "electron";
import { readFile } from "node:fs/promises";
import { extname, join, normalize, sep } from "node:path";
import { ServerStore, type Vault } from "./servers";

const SCHEME = "app";
const ORIGIN = `${SCHEME}://-/`;
const RENDERER = join(__dirname, "..", "renderer");
const ICON = join(__dirname, "..", "assets", "icon.png");
const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".map": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".webmanifest": "application/manifest+json",
  ".ico": "image/x-icon",
};

protocol.registerSchemesAsPrivileged([
  {
    scheme: SCHEME,
    privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true },
  },
]);

let window: BrowserWindow | null = null;

function store(): ServerStore {
  const vault: Vault = {
    isEncryptionAvailable: () => safeStorage.isAsyncEncryptionAvailable(),
    // `basic_text` is a Linux backend with a hard-coded key; the other platforms have no such fallback.
    storageBackend: process.platform === "linux" ? () => safeStorage.getSelectedStorageBackend() : undefined,
    encrypt: (plain) => safeStorage.encryptStringAsync(plain),
    decrypt: (encrypted) => safeStorage.decryptStringAsync(encrypted),
  };
  return new ServerStore(join(app.getPath("userData"), "servers.json"), vault);
}

/** The bundle's files, with the page at the root and everything it asks for under /static. */
async function serve(request: Request): Promise<Response> {
  let url: URL;
  let path: string;
  try {
    url = new URL(request.url);
    path = decodeURIComponent(url.pathname);
  } catch {
    return new Response("Bad request", { status: 400 });
  }
  if (url.host !== "-") return new Response("Not found", { status: 404 });
  const relative = path === "/" ? "index.html" : path.replace(/^\/+/, "");
  const file = normalize(join(RENDERER, relative));
  if (file !== RENDERER && !file.startsWith(RENDERER + sep)) {
    return new Response("Not found", { status: 404 });
  }
  try {
    return new Response(await readFile(file), {
      headers: {
        "content-type": TYPES[extname(file).toLowerCase()] ?? "application/octet-stream",
        "cache-control": "no-store",
      },
    });
  } catch {
    return new Response("Not found", { status: 404 });
  }
}

function createWindow(): void {
  window = new BrowserWindow({
    width: 1180,
    height: 820,
    minWidth: 820,
    minHeight: 560,
    icon: ICON,
    backgroundColor: "#17212b",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: join(__dirname, "preload.cjs"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
    },
  });

  window.once("ready-to-show", () => window?.show());
  window.on("closed", () => {
    window = null;
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (url.startsWith(ORIGIN)) return;
    event.preventDefault();
    if (/^https?:/i.test(url)) void shell.openExternal(url);
  });
  void window.loadURL(`${ORIGIN}index.html`);
}

function ready(): void {
  if (!app.requestSingleInstanceLock()) {
    app.quit();
    return;
  }
  app.on("second-instance", () => {
    if (!window) return;
    if (window.isMinimized()) window.restore();
    window.show();
    window.focus();
  });
  app.whenReady().then(() => {
    app.setAppUserModelId("dev.zettcode.desktop");
    if (process.platform === "darwin") app.dock?.setIcon(ICON);
    session.defaultSession.setPermissionRequestHandler((_contents, permission, callback) => {
      callback(permission === "notifications");
    });
    session.defaultSession.setPermissionCheckHandler((_contents, permission) => permission === "notifications");
    protocol.handle(SCHEME, serve);
    ipcMain.handle("servers:load", () => store().load());
    ipcMain.handle("servers:save", async (_event, state: unknown) => {
      if (typeof state !== "object" || state === null) throw new Error("The server list is not an object");
      await store().save(state);
    });
    ipcMain.handle("notice:show", (_event, title: unknown, body: unknown) => {
      if (typeof title !== "string" || typeof body !== "string" || !Notification.isSupported()) return;
      const notice = new Notification({ title: title.slice(0, 120), body: body.slice(0, 500) });
      notice.on("click", () => {
        if (!window) return;
        if (window.isMinimized()) window.restore();
        window.show();
        window.focus();
      });
      notice.show();
    });
    createWindow();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

ready();
