# The desktop app and the Android shell

The two clients are the same idea: **a shell around the gateway's own page.** Neither holds a page of its own beyond a
server list, and neither carries a token.

* **Desktop** (`clients/desktop`) is an Electron window. `web/index.html` is the server list, served as `app://-/`;
  opening a server navigates the window to the gateway's origin, so the page's cookie, fetches and WebSocket are its
  ordinary same-origin ones. It runs on macOS, Windows and Linux.
* **Android** (`clients/mobile`) is a thin Capacitor WebView shell with `web/index.html` as its list, loaded the same
  way. `server.allowNavigation: ["*"]` keeps that navigation in the WebView. Back on a gateway page walks that page's
  history and at the root a second Back leaves the app.

**Release boundary.** A shell contains only the list, the window or WebView configuration, the menu, the navigation
rules and the icons. The gateway page is built from `clients/gateway` into the gateway's `static/` and served by the
gateway, so **changing Vue/TS/HTML/CSS needs a gateway release and never an installer or an APK.** A new installer is
only for a change under `clients/desktop`, a new APK only for one under `clients/mobile`. CI enforces the shape: the
desktop job runs on `clients/desktop/` changes only and never builds the page.

```
clients/gateway/src ──build──► gateway static/ ──served by──► packages/zettcode-gateway
                                                                  ▲
        Electron (app://- list → navigates)  ───────────────────┤  same origin, cookie sign-in
        Android  (http://localhost list → navigates) ────────────┘
```

## What the desktop shell owns

| File | What it owns |
| --- | --- |
| `clients/desktop/web/index.html` | the list. Remembers `{url, name}` and the last server in `localStorage`; opens the last server at launch unless the URL hash is `#choose` (menu or a failed load, with the reason after a colon). |
| `clients/desktop/src/main.ts` | the window, `app://` serving of `web/` only, the menu (Server → Switch server…), notification permission, single instance. |
| `clients/desktop/src/navigation.ts` | `decide` / `opensExternally`: the list may open any http(s) address; a server's page stays on its origin and other links go to the system browser; anything else is denied. Tested without Electron. |

There is no preload script and no IPC: nothing in the page can reach the machine through the shell. The sandbox, context
isolation and `webSecurity` stay on, and the only permission granted is notifications.

The desktop installers are built by `.github/workflows/desktop.yml` on all three systems (electron-builder cannot make a
Windows or Linux package from a Mac without extra tools): a tag `desktop-v<version>`, equal to `package.json`, attaches
dmg/zip, NSIS/zip and AppImage/deb/tar.gz to a GitHub release. They are unsigned.

## What the gateway keeps for other origins

`--client-origin` and the bearer/CORS/WebSocket-subprotocol path (`Settings.allowed_origins`, `CORSMiddleware`,
`clients/gateway/src/api/connection.ts` and the page's app mode with its `ServerGate`) were written for the previous,
page-bundling desktop app. No shell uses them now. They stay for a page of your own at another origin (rule W10 in
`invariants.md`, rules A1–A7 below) and can be removed together if nobody does.

## What the shells keep

Both keep only addresses. The desktop keeps `zettcode.servers` and `zettcode.last` in the list page's `localStorage`
(under `app://-`), the Android app `zettcode.servers`. The token is typed on the gateway's sign-in page and lives in that
page's cookie inside the window or WebView (30 days). Clearing the app's data signs out.

## Icons and logos

Both use the ZettCode mark rendered at 1024px from `clients/gateway/public/logo.svg`: `clients/desktop/assets/icon.png`
is the master electron-builder uses; `clients/mobile/assets/` holds the `@capacitor/assets` masters (the
foreground/background pair keeps the older launcher tiles padded instead of a clipped white square). Each shell's
`web/logo.svg` is the mark on its list.

## Building and packaging

```bash
make desktop          # install, type-check, test and build the main process; `npm start` in clients/desktop opens it
make mobile           # type-check the config and copy web/ into the Gradle project
make package          # electron-builder installers for this system + the debug APK
make desktop-package  # only the installers
make mobile-apk       # only the APK (needs ANDROID_HOME or android/local.properties, and JDK 21+)
```

The APK is written to `clients/mobile/android/app/build/outputs/apk/debug/app-debug.apk`; the desktop installers to
`clients/desktop/release/`.

To try either shell, start a gateway with a token and add its address:

```bash
zettcode gateway start --host 0.0.0.0 --token "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
```

The picker stores the address (`http://192.168.1.20:8765`). The Android emulator reaches the host at
`http://10.0.2.2:<port>`.

## Rules

| # | Rule (what breaks) | Test |
| --- | --- | --- |
| A1 | A client origin is let in only while the gateway has a token; without one, no CORS answer and no write passes. | `test_gateway_app.py::test_with_no_token_a_native_origin_is_not_let_in`, `test_a_native_client_without_the_token_is_refused_and_a_foreign_origin_is_refused` |
| A2 | A client origin can read and write with the bearer, and a foreign origin still cannot. | `test_gateway_app.py::test_a_native_client_origin_may_read_and_write_with_the_token_and_is_told_so` |
| A3 | A preflight is answered without the token and names only the allowed origin. | `test_gateway_app.py::test_a_preflight_is_answered_without_the_token_and_names_only_the_native_origin` |
| A4 | The event socket takes the token as a subprotocol and still refuses a foreign origin. | `test_gateway_app.py::test_the_event_socket_takes_the_token_as_a_subprotocol_from_a_native_origin`, `test_the_event_socket_from_a_foreign_origin_still_needs_the_gateway_itself` |
| A5 | `--client-origin` is normalised, refused without a token, kept across a restart and passed to a background gateway. | `test_gateway_cli.py::test_a_client_origin_is_normalised_and_needs_a_token`, `test_a_restart_keeps_the_client_origins_and_a_flag_given_wins`, `test_a_background_start_keeps_the_token_in_the_environment_not_on_the_command_line` |
| A6 | The page's app-mode transport prefixes the chosen server, sends the bearer, and offers the token as a valid WebSocket protocol. | `clients/gateway/test/connection.test.ts` |
| A7 | A saved list keeps only usable profiles, and the active id must name one of them. | `clients/gateway/test/connection.test.ts` |
| A8 | The desktop window only follows a web address, keeps a server's page on its origin (other links leave for the system browser) and denies `file:`, `javascript:` and anything unparsable. | `clients/desktop/test/navigation.test.ts` |
| A9 | The look and language stay device-wide, while a server's `defaults`, `templates`, `recent` and drafts are keyed by its id. | `clients/gateway/test/storage.test.ts`, `clients/gateway/test/prefs.test.ts` |

The Android shell's only native code is `MainActivity`, which walks the WebView history when the previous entry is an
http(s) page other than the picker, before a second Back leaves the app at the root. An open sheet or full-screen dialog
is Vue state, not a route, so Back does not close it — its × or Escape does.

## Not yet

* The APK is not built in CI (it needs the SDK). It was built and run in an Android 36 arm64 emulator; no
  physical-device test beyond that.
* The installers are unsigned and not notarised; there is no signing recipe. The Windows and Linux installers are built
  by CI and have not been run on those systems by us.
* No push notification; no QR/deep link; no iOS shell; no auto-update (a gateway update already changes the page).
