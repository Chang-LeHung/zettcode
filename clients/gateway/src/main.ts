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

// The visual viewport, not the layout one, is what is left when a phone's keyboard is up. iOS Safari does not resize the
// page for the keyboard: it slides the layout viewport up under the address bar instead, which is what makes a fixed
// page "run away". So the root is pinned to the visual viewport (its size and its offset), and any scroll the browser
// does to bring the field into view is undone.
function fitViewport(): void {
  const view = window.visualViewport;
  const root = document.documentElement;
  const height = view?.height ?? window.innerHeight;
  root.style.setProperty("--app-h", `${height}px`);
  root.style.setProperty("--app-top", `${view?.offsetTop ?? 0}px`);
  // The keyboard is up when a good part of the window is gone; the home indicator's inset is then not wanted.
  root.dataset.keyboard = String(window.innerHeight - height > 120);
  if (window.scrollY !== 0 || window.scrollX !== 0) window.scrollTo(0, 0);
}
fitViewport();
window.visualViewport?.addEventListener("resize", fitViewport);
window.visualViewport?.addEventListener("scroll", fitViewport);
window.addEventListener("scroll", fitViewport, { passive: true });
window.addEventListener("orientationchange", fitViewport);

createApp(App).mount("#app");

watch(
  () => auth.signedIn,
  (signedIn) => (signedIn ? connect() : disconnect()),
);
void checkSession();
