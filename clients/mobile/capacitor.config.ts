import type { CapacitorConfig } from "@capacitor/cli";

// The app is a WebView shell. Its own page at http://localhost (which Android treats as trustworthy) is only the
// server list; opening one loads the gateway's page at the gateway's own origin, so the gateway's cookie, fetches and
// WebSocket are its ordinary same-origin ones. `allowNavigation` keeps that navigation in this WebView instead of
// handing it to a browser intent; a LAN gateway on plain HTTP is why mixed content is allowed. It cannot be narrowed to
// the chosen server's host: with no `server.url`, a host the mask does not match is treated as a local request, so the
// mask is what makes the remote page load at all. The README lists its side effects.
const config: CapacitorConfig = {
  appId: "dev.zettcode.mobile",
  appName: "ZettCode",
  webDir: "web",
  backgroundColor: "#17212b",
  android: {
    backgroundColor: "#17212b",
    allowMixedContent: true,
  },
  server: {
    androidScheme: "http",
    allowNavigation: ["*"],
  },
};

export default config;
