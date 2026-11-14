# Desktop and phone apps

The web gateway already works on a phone. The two clients package it differently:

- **Desktop** (macOS, Windows, Linux) is an Electron window with a server list. Opening a server loads that gateway's
  own page at the gateway's origin.
- **Android** is a WebView shell with the same idea: its own small page lists server addresses, and opening one loads
  that gateway's page.

In both, the token is typed on the gateway's sign-in page and kept by the page's cookie, and the app stores addresses
only.

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

The desktop app and the Android shell are both a window on the gateway: choosing a server loads the gateway's own page
from the gateway, so a gateway update changes what you see and the app itself rarely needs an update. Both work with any
gateway that serves its page.

## The desktop app

It is built for macOS (Apple Silicon), Windows and Linux. The installers are produced by CI on each system; they have
not been tried on a real Windows or Linux machine yet, so report anything that does not start. Installers for all three
are attached to the GitHub releases named `desktop-v<version>`. The macOS app is signed ad hoc — not with an Apple
Developer certificate, and not notarized — so macOS refuses its first launch as an unidentified developer. Open it once
and let that refusal happen: **System Settings → Privacy & Security** then lists it, and **Open Anyway** lets it start
(on macOS 14 and earlier, right-click → Open in Finder works on the first attempt). The `desktop-v0.2.0` installers
were built with no signature at all, which macOS 15 and later reports as *the app
is damaged* rather than as an unidentified developer. For those, or for any copy that still says damaged, copy it to
Applications and run:

```sh
xattr -dr com.apple.quarantine /Applications/ZettCode.app
```

Windows SmartScreen asks for More info → Run anyway. Or build it from the checkout:

```sh
make desktop                  # type-check, test and build the window
cd clients/desktop && npm start
```

`make desktop-package` writes the installers for the machine it runs on (dmg/zip on macOS, NSIS/zip on Windows,
AppImage/deb/tar.gz on Linux) under `clients/desktop/release/`. The app holds one window and opens a link from a
conversation in your real browser.

On first launch add a server's **address**; the gateway asks for its token on its own sign-in page, and the window keeps
that cookie. The next launch reopens the last server. **Server → Switch server…** (Ctrl/Cmd+Shift+S) returns to the list,
and so does a server that cannot be reached, with the reason.

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

The desktop app keeps no token: like the Android app it writes only the address list (and the last server used), and
the token lives in the gateway page's sign-in cookie inside the window, which persists across restarts (the gateway
issues it for 30 days). Clearing the app's data removes the addresses and signs out.

On Android the address list is in the picker page's `localStorage`, and the cookie lives inside the WebView. Android
backup is off for the app.

Anyone with the token can start agents that run commands as you. If a device is lost, change the token:
`zettcode gateway restart --token <new-token>`, then edit the server on every device you still use. Prefer HTTPS
outside your own network; on a plain-HTTP LAN the token crosses the network in the clear.

## Limits

- Neither app needs a particular gateway version for its shell, but the page you see is the gateway's, so run a current
  gateway to get current features.
- The page shows notifications while the window is open. There is no push service behind either app.
- In the Android shell a link to another site opens in the same WebView, without an address bar; Android Back returns
  to the server list.
- There is no QR code or deep link yet; type or paste the address.
- An iOS app is not part of this checkout.
