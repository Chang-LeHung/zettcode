import DefaultTheme from "vitepress/theme";
import type { Theme } from "vitepress";
import ProductHome from "./components/ProductHome.vue";

import "./custom.css";

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component("ProductHome", ProductHome);
  },
} satisfies Theme;
