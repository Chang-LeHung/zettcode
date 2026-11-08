# Desktop and phone apps

The web gateway already works on a phone. The two clients package it differently:

- **Desktop** wraps the gateway's own Vue page in an Electron window, adds a server list, and keeps each token in the
  platform's key store where it has one.
- **Android** is a WebView shell. Its own small page lists server addresses; opening one loads that gateway's page at
  the gateway's origin, so the token is typed on the gateway's sign-in page and kept by the page's cookie. The app
  stores addresses only.

Everything past the sign-in — chats, daemons, groups, the graph, the logs, the configuration pages — is the gateway's
page you already know.

## Before you start

Start a gateway with a token:

```sh
zettcode gateway start --host 0.0.0.0 --token "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
```

`start` prints the address and the token. Use the address the phone can reach (the machine's LAN address, not
`127.0.0.1`), and allow the port through the machine's firewall. The page is plain HTTP; put it behind TLS if it
leaves a network you trust.

The desktop client needs a gateway from the same release, because it calls the API from its own `app://` origin. The
Android shell loads the gateway's page at the gateway's own origin and works with older gateways too.

## The desktop app

Until the apps are published, build the desktop app from the checkout:

```sh
make desktop                  # type-check, test and build the window
cd clients/desktop && npm start
```

`make desktop-package` also writes the installers for the machine it runs on (dmg/zip on macOS, NSIS on Windows,
AppImage/deb on Linux) under `clients/desktop/release/`. The app holds one window, keeps the page in it, and opens a
link from a conversation in your real browser.

On its first screen, add a server with its **address**, its **token**, and an optional **name**; it tests the token
before saving. **Settings → Servers** shows the active one, and **Switch server** returns to the list. A switch reloads
the page, so nothing from one gateway is drawn beside another's.

## The Android app

The build needs a JDK (21 or newer) and the Android SDK with `compileSdk 36`:

```sh
make mobile                   # type-check the config and copy web/ into the Android project
make mobile-apk               # needs ANDROID_HOME (or android/local.properties)
```

The APK is written under `clients/mobile/android/app/build/outputs/apk/debug/`. Install it on the phone and open
**ZettCode**. `make package` builds this APK and the desktop installers together.

The first screen asks for the gateway's **address**, such as `http://192.168.1.20:8765`; the gateway is served at the
root of its address, so a path is refused. Tapping a server opens the gateway page, which asks for its token once and
keeps its cookie. The list stores addresses only — not tokens — and Android Back from a gateway page returns to the
list so another server can be opened.

The icon and splash are generated from the ZettCode mark in `clients/mobile/assets/`; the desktop uses
`clients/desktop/assets/icon.png`, both rendered from the gateway's `public/logo.svg`.

## Where the token lives

The desktop app encrypts its server list and tokens with `safeStorage` (macOS Keychain, Windows DPAPI, libsecret on
Linux) and writes the file only its owner can read. If the platform has no real key store (an older Linux without a
secret service, or the `basic_text` backend, which uses a hard-coded key), it still writes the list with owner-only
permissions; on Linux that file is then plain text (`0600`).

The Android app does not write a token to its own storage. It writes the address list to the picker page's
`localStorage`; the token lives in the gateway page's sign-in cookie inside the WebView, which persists across app
restarts (the gateway issues it for 30 days). Clearing the app's data removes the addresses and signs out. Android
backup is off for the app.

Anyone with the token can start agents that run commands as you. If a device is lost, change the token:
`zettcode gateway restart --token <new-token>`, then edit the server on every device you still use. Prefer HTTPS
outside your own network; on a plain-HTTP LAN the token crosses the network in the clear.

## Limits

- The desktop app talks to a gateway from the same release; older gateways do not know its origin or socket token.
  The Android shell loads the gateway's page itself and has no such minimum.
- The desktop app shows a native notice while it runs. The Android app does not show notifications yet; there is no
  push service behind it.
- In the Android shell a link to another site opens in the same WebView, without an address bar; Android Back returns
  to the server list.
- There is no QR code or deep link yet; type or paste the address (and, on the desktop, the token).
- An iOS app is not part of this checkout.
