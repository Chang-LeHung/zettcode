# ZettCode for Android

A thin WebView shell for the gateway's own page. `web/` is a small server list served by Capacitor; opening a server
loads that gateway's page at the gateway's origin, so its sign-in cookie, fetches and WebSocket are the page's ordinary
same-origin ones. The app stores addresses only; the token is typed on the gateway's sign-in page and kept by the
WebView cookie.

## Build

Needs Node 20+, JDK 21+ and the Android SDK with `compileSdk 36`.

```sh
# from the repository root
make mobile            # type-check the config and copy web/ into the Gradle project
make mobile-apk        # with ANDROID_HOME set, or android/local.properties
```

The APK is written to `android/app/build/outputs/apk/debug/app-debug.apk`. `make package` builds this and the desktop
installers. `make mobile` does not need the gateway's Node toolchain; it only copies `web/` and runs Capacitor sync.

The launcher icons and splash are generated from the ZettCode mark rendered from `../gateway/public/logo.svg`. The
custom-mode sources are `assets/icon-only.png`, `icon-foreground.png`, `icon-background.png`, `splash.png` and
`splash-dark.png` (the foreground/background pair is what gives the adaptive icon its dark, padded tile):

```sh
npm install
npm run assets
```

## How it is put together

* `web/index.html` is the server list. It keeps `{url, name}` entries in `localStorage`; it never stores a token.
* `capacitor.config.ts` serves `web/` from `http://localhost` and allows navigation to the chosen server's origin
  (`server.allowNavigation: ["*"]`), so the gateway page opens in this WebView rather than in a browser intent. A link
  to another http(s) host in a conversation also opens in the shell (no address bar); Back returns to the gateway.
* `android/app/src/main/java/dev/zettcode/mobile/MainActivity.java` is the only native code: on a gateway page Android
  Back (the button or a left-edge swipe) walks that page's own history, like its `<` arrow, and never sends the reader
  back to the picker; at the page root a second Back leaves the app. Back from the picker leaves the app. An open
  sheet or full-screen dialog is page state, not a route: close it with its × or Escape.
* `AndroidManifest.xml` turns off backup and allows cleartext HTTP for a gateway on a LAN; the picker says that the
  gateway asks for its token itself.

There is no native key-store plugin and no gateway CORS/WebSocket change on this side: the loaded page is already at
the gateway's origin. `docs/internal/clients-app.md` has the full map.
