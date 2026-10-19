/** The chat webview: a Vue application mounted on the empty document the host serves. */

import { createApp } from "vue";

import App from "./App.vue";
import { handleHost, post } from "./store.js";
import type { HostMessage } from "../core/protocol.js";

window.addEventListener("message", (event: MessageEvent<HostMessage>) => handleHost(event.data));

/**
 * Tell the host whether the cursor is in this view. A webview forwards every key to the editor, so Ctrl+F would also open
 * the find box of the file on the other side; the host's keybinding for it only applies while this is true, and takes
 * the key from the editor's.
 */
window.addEventListener("focus", () => post({ type: "focused", focused: true }));
window.addEventListener("blur", () => post({ type: "focused", focused: false }));

createApp(App).mount("#app");
post({ type: "ready" });
if (document.hasFocus()) {
  post({ type: "focused", focused: true });
}
