# ZettCode desktop

A window on the gateway you choose. The app holds a server list and nothing else: choosing a server loads **the
gateway's own page** at the gateway's origin, exactly as a browser would, so the sign-in cookie, the fetches and the
socket are the page's ordinary same-origin ones. There is no token store, no bridge into the page, no CORS or
WebSocket change on the gateway.

Because the page comes from the gateway, **a change to the Vue/TS/CSS ships with the gateway, never with an installer.**
A new installer is only for a change in this folder: the list (`web/index.html`), the window or menu (`src/main.ts`),
the navigation rules (`src/navigation.ts`) or the icon.

## Run it

```sh
cd clients/desktop
npm ci
npm start          # builds the main process and opens the window
```

Start a gateway (`zettcode gateway start --token …`), then add its address in the app. It reopens the last server on
the next launch; **Server → Switch server…** (Ctrl/Cmd+Shift+S) returns to the list, and so does a server that cannot
be reached, with the reason.

## Installers

```sh
npm run package    # for the system you run it on: dmg+zip, NSIS+zip, AppImage+deb+tar.gz under release/
```

Each system builds its own, which `.github/workflows/desktop.yml` does on all three: push a tag `desktop-v<version>`
(equal to `package.json`'s version) and it attaches the installers to a GitHub release. `build.mac.identity` is `"-"`,
so the macOS app is signed ad hoc: it gets a valid `_CodeSignature` (macOS then refuses the first launch as an
unidentified developer rather than as a damaged app) but it is not notarized. A machine with a Developer ID signs
properly by overriding the setting — `npm run package -- --config.mac.identity="Developer ID Application: …"` — because
the pinned identity wins over `CSC_NAME`; notarizing needs `notarize` options on top of that.

## Checks

```sh
npm run check      # tsc, no emit
npm test           # the navigation rules, without Electron
```

`docs/internal/clients-app.md` has the map and the security rules.
