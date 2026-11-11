# The desktop app and the Android shell

The two clients share a page, not a transport.

* **Desktop** (`clients/desktop`) is the gateway's Vue application built in its app mode, with a native server list and
  a token kept by the operating system (Electron `safeStorage`). It calls the chosen gateway from `app://-`, so the
  gateway needs its origin allowlist, CORS and the WebSocket token.
* **Android** (`clients/mobile`) is a thin Capacitor WebView shell. `web/index.html` is a small server list; opening a
  server loads the gateway's own page at the gateway's origin. The page's cookie, fetches and WebSocket are its ordinary
  same-origin ones. The app stores addresses only; the token is typed on the gateway's sign-in page and kept by the
  WebView cookie. No native plugin, no key store, no CORS/WebSocket change is involved on this side.
  `server.allowNavigation: ["*"]` keeps that navigation in the WebView; a link to another http(s) host in a conversation
  also opens there, with no address bar. Back on a gateway page walks that page's own history, like its `<` arrow,
  and at the root a second Back leaves the app; Back from the picker leaves the app. The same setting adds `https://*` to
  Capacitor's allowed origin rules and `*` as a local-server authority, but no Capacitor script is injected into the
  remote page.

```
clients/gateway/src ──build --app──► renderer/ ──► Electron (app://-)
        │                                           server list + safeStorage
        │                                           HTTP bearer + CORS + WS token
        ▼
packages/zettcode-gateway  ◄── HTTP (same origin) ── Android Capacitor (http://localhost picker → server page)
```

## Desktop connection layer

| File | What it owns |
| --- | --- |
| `clients/gateway/src/api/connection.ts` | The one connection: `baseUrl`, `token`, `apiUrl`, `authorization`, `normalizeBaseUrl`, and the base64url token protocol. |
| `clients/gateway/src/api/http.ts` | prefixes every path, sends the bearer, and never sends a cookie from an app (`credentials: "omit"`). |
| `clients/gateway/src/api/events.ts` | the socket's address and the `zettcode` / `zettcode.token.<base64url>` protocols; a browser cannot put a header on a WebSocket. |
| `clients/gateway/src/api/pictures.ts` | a page draws a picture from its own address; the desktop app reads it with the bearer into a blob URL. |
| `clients/gateway/src/lib/servers.ts` | `ServerProfile`, `parseStored`, `makeProfile`: the list's shape and what a new server must pass. |
| `clients/gateway/src/lib/native.ts` | the Electron bridge (`loadServers`, `saveServers`, `notify`). A page with no bridge stays the gateway's page. |
| `clients/gateway/src/stores/servers.ts` | the reactive list, the active server, adding/editing/removing, and the reload that makes a switch safe. |
| `clients/gateway/src/components/shell/ServerGate.vue` | first-run and switch screen: list, add, test, edit, remove. |
| `clients/gateway/src/components/settings/ServersSection.vue` | the active server in Settings, and the way back to the list. |

The page the gateway serves has an empty `baseUrl`, its cookie and its strict CSP. The desktop bundle is the same page
with `servers.mode = "app"` and the server it chose. `index.html` carries a meta CSP that allows a configured
`http:`/`https:` origin, `ws:`/`wss:` and `blob:` pictures; the gateway's response header is stricter, and the two are
intersected, so the server page does not gain any of it.

Switching servers writes the new profile first, then sets the active server and reloads. Every store is in memory. The
look and language (`theme`, `size`, `language`, `render`, `avatar`, `notify`, `askReply`, `confirmSession`) are the
device's and stay global; a server's `defaults`, `templates`, `recent` and drafts are keyed by its id. Reloading is what
guarantees that no thread, chat, live turn, graph, default, template, recent folder or draft from one gateway is drawn
beside another's. **Settings → Data → Clear browser data** removes every server's keys from this device.

## What the gateway had to grow (desktop only)

The gateway already accepted `Authorization: Bearer <token>`; a page at another origin still could not use it.

| Change | Where | Why |
| --- | --- | --- |
| `APP_ORIGINS = ("app://-",)` and `Settings.allowed_origins` | `settings.py` | the desktop page is let in **only when a token is set**. An origin is not a credential; the token is. |
| `--client-origin ORIGIN` | `cli.py` | one more origin for a client of your own; refused without a token, recorded for `restart`, passed to the background child. |
| `CORSMiddleware` | `app.py` | answers the preflight `OPTIONS` without a token (a browser never sends `Authorization` on it), and puts `Access-Control-Allow-Origin` on refusals too so the app can read them. |
| `same_origin(..., allowed=…)` | `app.py` | a write or a socket from an allowed origin passes the check that otherwise requires the gateway's own `Host`. |
| WebSocket token subprotocol | `app.py` | `Sec-WebSocket-Protocol: zettcode, zettcode.token.<base64url>`; the token is not put in a URL. The server echoes `zettcode`. |

The desktop app therefore needs a gateway from the same release. The Android shell loads the gateway's page itself, so
it does not need these changes and works with a gateway that predates them.

## What the shells keep

The desktop keeps `{ servers: ServerProfile[], active: id }`, parsed by `lib/servers.ts` so a damaged store opens the
server list rather than stopping the app. `${userData}/servers.json` is encrypted with `safeStorage` (Keychain, DPAPI
or libsecret) where it is available and is not Linux's `basic_text` fallback, written in one replace with mode `0600`.
`clients/desktop/src/servers.ts` is plain Node and its rules are tested without Electron.

The Android app keeps `[{ url, name }]` in the picker's `localStorage`; no token is written there. The token lives in
the gateway page's cookie inside the WebView, which persists across restarts. Clearing the app's data signs out; the
server list is the only app-owned state.

## Icons and logos

Both use the ZettCode mark, rendered at 1024px from `clients/gateway/public/logo.svg`:

* `clients/desktop/assets/icon.png` is the 1024px master electron-builder uses for the app and the window; the page's
  own `logo.svg` is used inside the window.
* `clients/mobile/assets/icon-only.png`, `icon-foreground.png`, `icon-background.png`, `splash.png` and `splash-dark.png`
  are the custom-mode masters `@capacitor/assets` generates the legacy and adaptive launcher tiles and splash from;
  `clients/mobile/web/logo.svg` is the mark on the server list. The foreground/background pair is what keeps the older
  24–25 tiles dark and padded instead of a clipped white square.

## Building and packaging

```bash
make desktop          # check, test, build the renderer and the main process; `npm start` in clients/desktop opens it
make mobile           # type-check the config and copy web/ into the Gradle project
make package          # electron-builder installers + the debug APK
make desktop-package  # only the installers
make mobile-apk       # only the APK (needs ANDROID_HOME or android/local.properties, and JDK 21+)
```

The APK is written to `clients/mobile/android/app/build/outputs/apk/debug/app-debug.apk`; the desktop installers to
`clients/desktop/release/`. `make package` runs both.

To try the Android shell, start a gateway with a token and reach it from the app:

```bash
zettcode gateway start --host 0.0.0.0 --token "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
```

The picker stores the address (`http://192.168.1.20:8765`); the gateway asks for the token on its own page. The
emulator reaches the host at `http://10.0.2.2:<port>`.

## Rules

| # | Rule (what breaks) | Test |
| --- | --- | --- |
| A1 | The desktop origin is let in only while the gateway has a token; without one, no CORS answer and no write passes. | `test_gateway_app.py::test_with_no_token_a_native_origin_is_not_let_in`, `test_a_native_client_without_the_token_is_refused_and_a_foreign_origin_is_refused` |
| A2 | The desktop client can read and write from its own origin with the bearer, and a foreign origin still cannot. | `test_gateway_app.py::test_a_native_client_origin_may_read_and_write_with_the_token_and_is_told_so` |
| A3 | A preflight is answered without the token and names only the allowed origin. | `test_gateway_app.py::test_a_preflight_is_answered_without_the_token_and_names_only_the_native_origin` |
| A4 | The event socket takes the token as a subprotocol and still refuses a foreign origin; the refusal echoes the offered subprotocol before closing 4401, or a browser that negotiated one never opens. | `test_gateway_app.py::test_the_event_socket_takes_the_token_as_a_subprotocol_from_a_native_origin`, `test_the_event_socket_from_a_foreign_origin_still_needs_the_gateway_itself` |
| A5 | `--client-origin` is normalised, refused without a token, kept across a restart and passed to a background gateway. | `test_gateway_cli.py::test_a_client_origin_is_normalised_and_needs_a_token`, `test_a_restart_keeps_the_client_origins_and_a_flag_given_wins`, `test_a_background_start_keeps_the_token_in_the_environment_not_on_the_command_line` |
| A6 | The desktop transport prefixes the chosen server, sends the bearer, and offers the token as a valid WebSocket protocol. | `clients/gateway/test/connection.test.ts` |
| A7 | A saved list keeps only usable profiles, and the active id must name one of them. | `clients/gateway/test/connection.test.ts` |
| A8 | The desktop list is encrypted when the platform can (and not with Linux's `basic_text` fallback), written `0600`, and a damaged file is an empty list plus a message rather than a failed start. | `clients/desktop/test/servers.test.ts` |
| A9 | The look and language stay device-wide, while a server's `defaults`, `templates`, `recent` and drafts are keyed by its id; two gateways never see each other's values, and Clear removes every server's keys. | `clients/gateway/test/storage.test.ts`, `clients/gateway/test/prefs.test.ts` |

The Android shell has no native token store to test: its only native code is `MainActivity`, which walks the
WebView history when the previous entry is an http(s) page other than the picker, before a second Back leaves the
app at the root; `web/index.html` keeps URLs and never a token. An open sheet or full-screen dialog is Vue state,
not a route, so Back does not close it — its × or Escape does.

## Not yet

* The APK is not built in CI (it needs the SDK); `make mobile` only copies `web/` and syncs. It was built and run in an
  Android 36 arm64 emulator while this change was made, with the gateway page, token sign-in, cookie and chat list
  checked; no physical-device test beyond that.
* The macOS desktop installers (dmg/zip) were built unsigned. There is no signing/notarisation recipe yet, and
  electron-builder's download can fail on a bad network; the Electron app itself was also run against a real gateway.
* No push notification; no QR/deep link; no iOS shell; no auto-update. The app versions are `0.1.0` and are not tied
  to `version.py` while they are unpublished.
