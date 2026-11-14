// The Electron shell. It holds no page of its own beyond a server list: choosing a server loads the gateway's page at
// the gateway's origin, so a change to the page ships with the gateway and never needs a new installer. There is no
// bridge into the page and no token here; the gateway's sign-in page keeps its cookie in this window's session.

import { app, BrowserWindow, Menu, protocol, session, shell } from "electron";
import { readFile } from "node:fs/promises";
import { extname, join, normalize, sep } from "node:path";
import { decide, opensExternally, ORIGIN } from "./navigation";

const SCHEME = "app";
const WEB = join(__dirname, "..", "web");
const ICON = join(__dirname, "..", "assets", "icon.png");
const LIST = `${ORIGIN}index.html`;
const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
};

protocol.registerSchemesAsPrivileged([{ scheme: SCHEME, privileges: { standard: true, secure: true } }]);

let window: BrowserWindow | null = null;

/** The list's files: a handful of static ones, and nothing outside their folder. */
async function serve(request: Request): Promise<Response> {
  let path: string;
  try {
    const url = new URL(request.url);
    if (url.host !== "-") return new Response("Not found", { status: 404 });
    path = decodeURIComponent(url.pathname);
  } catch {
    return new Response("Bad request", { status: 400 });
  }
  const file = normalize(join(WEB, path === "/" ? "index.html" : path.replace(/^\/+/, "")));
  if (!file.startsWith(WEB + sep)) return new Response("Not found", { status: 404 });
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

function showList(error = ""): void {
  void window?.loadURL(`${LIST}#choose${error ? `:${encodeURIComponent(error)}` : ""}`);
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
    webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true },
  });
  const contents = window.webContents;
  window.once("ready-to-show", () => window?.show());
  window.on("closed", () => {
    window = null;
  });
  contents.setWindowOpenHandler(({ url }) => {
    if (opensExternally(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  contents.on("will-navigate", (event, url) => {
    const verdict = decide(contents.getURL(), url);
    if (verdict === "allow") return;
    event.preventDefault();
    if (verdict === "external") void shell.openExternal(url);
  });
  // `will-navigate` is for navigations the page starts; a redirect the server answers with is a different event, and
  // without this a gateway could move the window to another origin that every later navigation would then trust.
  contents.on("will-redirect", (event, url) => {
    const verdict = decide(contents.getURL(), url);
    if (verdict === "allow") return;
    event.preventDefault();
    if (verdict === "external") void shell.openExternal(url);
  });
  // A server that cannot be reached leaves the window blank; the list, with the reason, is the way out.
  contents.on("did-fail-load", (_event, code, description, _url, isMainFrame) => {
    if (isMainFrame && code !== -3) showList(`${description} (${code})`);
  });
  void window.loadURL(LIST);
}

function menu(): void {
  const mac = process.platform === "darwin";
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      ...(mac ? [{ role: "appMenu" as const }] : []),
      {
        label: "Server",
        submenu: [
          { label: "Switch server…", accelerator: "CmdOrCtrl+Shift+S", click: () => showList() },
          { type: "separator" },
          mac ? { role: "close" } : { role: "quit" },
        ],
      },
      { role: "editMenu" },
      {
        label: "View",
        submenu: [
          { role: "reload" },
          { role: "forceReload" },
          { type: "separator" },
          { role: "resetZoom" },
          { role: "zoomIn" },
          { role: "zoomOut" },
          { type: "separator" },
          { role: "togglefullscreen" },
        ],
      },
      { role: "windowMenu" },
    ]),
  );
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
    // The gateway page asks for notifications and nothing else.
    session.defaultSession.setPermissionRequestHandler((_contents, permission, callback) => {
      callback(permission === "notifications");
    });
    session.defaultSession.setPermissionCheckHandler((_contents, permission) => permission === "notifications");
    protocol.handle(SCHEME, serve);
    menu();
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
