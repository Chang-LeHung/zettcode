# ZettCode desktop

The gateway's page in an Electron window. The window is the same Vue application the gateway serves, built in its app
mode; this folder adds the server list, the key-store-backed token storage and `app://` serving. It holds no agent and
no second HTTP client.

## Run it

From the repository root, `make desktop` installs the page's build toolchain, checks this folder, and builds both
halves. Then:

```sh
cd clients/desktop
npm start          # builds the page and the main process, then opens the window
```

Start a gateway with a token first (`zettcode gateway start --token …`), then add its address in the app. A bare
`npm install` here is not enough on a fresh clone: `scripts/build.mjs` calls `../gateway/scripts/build.mjs`, which
needs the gateway's own `node_modules`.

## Build the installers

```sh
npm run package    # electron-builder: dmg/zip, NSIS, AppImage/deb under release/
```

`npm run build` alone writes `dist/` (main and preload) and `renderer/` (the page). The renderer comes from
`../gateway/scripts/build.mjs --app`, so a component change in the browser is in the desktop in the same commit. The
app icon is `assets/icon.png`, the ZettCode mark rendered at 1024px from `../gateway/public/logo.svg`; it is set in
`build.icon` and used for the window and the macOS dock.

## Checks

```sh
npm run check      # tsc, no emit
npm test           # the profile store, without Electron
```

`src/servers.ts` is plain Node: `safeStorage` encryption where the platform has it, a `0600` file, and a damaged file
read as an empty list. `src/main.ts` is the window and the protocol handler; `src/preload.ts` is the only bridge the
page may call. `docs/internal/clients-app.md` has the full map and the security rules.
