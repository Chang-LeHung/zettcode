# Desktop and phone apps

Both are a window on the web gateway, not a second client: opening a server loads that gateway's own page, so chats,
daemons, groups, the graph, the logs and the configuration are the page you already know. The desktop app holds one
window and opens a link from a conversation in your real browser.

| App | Platform | How to get it |
| --- | --- | --- |
| Desktop (Electron) | macOS Apple Silicon, Windows, Linux | The `desktop-v<version>` installer, or `make desktop` |
| Android (WebView) | Android | The [0.1.1 APK](https://github.com/Chang-LeHung/zettcode/releases/tag/zettcode-mobile-0.1.1), or `make mobile` and `make mobile-apk`, which needs `ANDROID_HOME` |

The APK is written to `clients/mobile/android/app/build/outputs/apk/debug/`. `make desktop-package` writes the
installers for the machine it runs on.

The macOS app is signed ad hoc, not notarized, so the first launch is refused as an unidentified developer: open it
once, then allow it under **System Settings → Privacy & Security → Open Anyway**. An installer that reports the app
as damaged (the `desktop-v0.2.0` ones carried no signature) needs:

```sh
xattr -dr com.apple.quarantine /Applications/ZettCode.app
```

Windows SmartScreen asks for More info → Run anyway. The installers have not been run on a real Windows or Linux
machine yet, so report anything that does not start.

## Point it at a gateway

Start a gateway on an address the device can reach, with a token:

```sh
zettcode gateway start --host 0.0.0.0 --token "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
```

`start` prints the address and the token. Use the machine's LAN address, not `127.0.0.1`, and allow the port through
the firewall. Type the address into the app: the Android picker wants a bare one such as
`http://192.168.1.20:8765`, with no path. The gateway page then asks for its token once and keeps the cookie for 30
days. Neither app stores a token: the desktop keeps the address list and the last server, and Android keeps the list in
the picker page's `localStorage`. **Server → Switch server…** (Ctrl/Cmd+Shift+S) returns to the list, and so does a
server that cannot be reached.

The page is plain HTTP, so put it behind TLS if it leaves a network you trust; on a plain-HTTP LAN the token crosses the
network in the clear. To sign every device out, restart with a new token
(`zettcode gateway restart --token <new-token>`) and edit the server on each one.

## What they cannot do

- The page is the gateway's, so a current gateway is what gives you current features; the shell itself rarely needs an
  update.
- Notifications show only while the window is open: neither app has a push service.
- An Android link to another site opens in the same WebView, with no address bar; Back returns to the server list.
- There is no QR code or deep link. Type or paste the address.
- There is no iOS app in this checkout.
