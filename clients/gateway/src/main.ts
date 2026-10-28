import { createApp, watch } from "vue";
import App from "./App.vue";
import { connect, disconnect } from "./stores/live";
import { auth, checkSession } from "./stores/auth";
import { watchPrefs } from "./stores/prefs";
import { watchRoute } from "./stores/route";
import "katex/dist/katex.min.css";
import "./styles/theme.css";
import "./styles/base.css";

watchPrefs();
watchRoute();

// The visual viewport, not the layout one, is what is left when a phone's keyboard is up.
function fitViewport(): void {
  const height = window.visualViewport?.height ?? window.innerHeight;
  document.documentElement.style.setProperty("--app-h", `${height}px`);
}
fitViewport();
window.visualViewport?.addEventListener("resize", fitViewport);

createApp(App).mount("#app");

watch(
  () => auth.signedIn,
  (signedIn) => (signedIn ? connect() : disconnect()),
);
void checkSession();
