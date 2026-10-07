import { defineConfig } from "vitepress";
import { navigation } from "./navigation";

export default defineConfig({
  base: "/zettcode/",
  srcExclude: ["internal/**"],
  cleanUrls: true,
  lastUpdated: true,
  sitemap: { hostname: "https://chang-lehung.github.io/zettcode/" },
  head: [
    ["link", { rel: "icon", href: "/zettcode/logo.svg", type: "image/svg+xml" }],
    ["meta", { name: "theme-color", content: "#397750" }],
    ["meta", { property: "og:type", content: "website" }],
  ],
  transformHead({ pageData }) {
    return [
      ["meta", { property: "og:title", content: `${pageData.title} · ZettCode` }],
      ["meta", { property: "og:description", content: pageData.description }],
    ];
  },
  markdown: { theme: { light: "github-light", dark: "github-dark" } },
  locales: {
    root: {
      label: "English", lang: "en-US", title: "ZettCode",
      description: "Your terminal. Your coding partner. The ZettCode user guide.",
      themeConfig: navigation("en"),
    },
    zh: {
      label: "简体中文", lang: "zh-CN", link: "/zh/", title: "ZettCode",
      description: "你的终端，你的编码伙伴。ZettCode 使用指南。",
      themeConfig: navigation("zh"),
    },
  },
  themeConfig: {
    logo: "/logo.svg",
    siteTitle: "ZettCode",
    socialLinks: [{ icon: "github", link: "https://github.com/Chang-LeHung/zettcode" }],
    search: {
      provider: "local",
      options: {
        locales: {
          zh: {
            translations: {
              button: { buttonText: "搜索文档", buttonAriaLabel: "搜索文档" },
              modal: {
                displayDetails: "显示详细结果", resetButtonTitle: "清除搜索", backButtonTitle: "关闭搜索",
                noResultsText: "没有找到相关结果", footer: { selectText: "选择", navigateText: "切换", closeText: "关闭" },
              },
            },
          },
        },
      },
    },
  },
});
