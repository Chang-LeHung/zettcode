import { defineConfig } from "vitepress";

const REPO = "https://github.com/Chang-LeHung/zettcode";
const PYPI = "https://pypi.org/project/zettcode/";

const english = {
  nav: [
    { text: "Guide", link: "/guide/getting-started", activeMatch: "/guide/" },
    { text: "Commands", link: "/guide/commands" },
    { text: "Keys", link: "/guide/keys" },
    { text: "Install", link: PYPI },
  ],
  sidebar: {
    "/guide/": [
      {
        text: "Start",
        items: [
          { text: "Getting started", link: "/guide/getting-started" },
          { text: "The interface", link: "/guide/interface" },
        ],
      },
      {
        text: "Every day",
        items: [
          { text: "Keys and mouse", link: "/guide/keys" },
          { text: "Commands", link: "/guide/commands" },
          { text: "Sessions", link: "/guide/sessions" },
        ],
      },
      {
        text: "Setting it up",
        items: [
          { text: "Configuration", link: "/guide/config" },
          { text: "Models and context", link: "/guide/models" },
          { text: "Project instructions", link: "/guide/instructions" },
          { text: "Skills and MCP", link: "/guide/skills-and-mcp" },
          { text: "Plugins", link: "/guide/plugins" },
        ],
      },
      { text: "Help", items: [{ text: "Problems and questions", link: "/guide/faq" }] },
    ],
  },
  editLink: { pattern: `${REPO}/edit/main/docs/:path`, text: "Edit this page on GitHub" },
  footer: { message: "Released under the MIT license.", copyright: "ZettCode, a terminal coding agent" },
  docFooter: { prev: "Previous", next: "Next" },
  outline: { label: "On this page", level: [2, 3] },
  lastUpdated: { text: "Last updated", formatOptions: { dateStyle: "medium", timeStyle: "short" } },
  returnToTopLabel: "Back to top",
  sidebarMenuLabel: "Menu",
  darkModeSwitchLabel: "Appearance",
  lightModeSwitchTitle: "Switch to light theme",
  darkModeSwitchTitle: "Switch to dark theme",
  notFound: {
    title: "Page not found",
    quote: "That page has been moved, or never existed.",
    linkText: "Back to the guide",
  },
};

const chinese = {
  nav: [
    { text: "指南", link: "/zh/guide/getting-started", activeMatch: "/zh/guide/" },
    { text: "命令", link: "/zh/guide/commands" },
    { text: "快捷键", link: "/zh/guide/keys" },
    { text: "安装", link: PYPI },
  ],
  sidebar: {
    "/zh/guide/": [
      {
        text: "上手",
        items: [
          { text: "快速开始", link: "/zh/guide/getting-started" },
          { text: "界面", link: "/zh/guide/interface" },
        ],
      },
      {
        text: "日常使用",
        items: [
          { text: "快捷键与鼠标", link: "/zh/guide/keys" },
          { text: "命令", link: "/zh/guide/commands" },
          { text: "会话", link: "/zh/guide/sessions" },
        ],
      },
      {
        text: "配置",
        items: [
          { text: "配置文件", link: "/zh/guide/config" },
          { text: "模型与上下文", link: "/zh/guide/models" },
          { text: "项目指令", link: "/zh/guide/instructions" },
          { text: "Skills 与 MCP", link: "/zh/guide/skills-and-mcp" },
          { text: "插件", link: "/zh/guide/plugins" },
        ],
      },
      { text: "帮助", items: [{ text: "常见问题", link: "/zh/guide/faq" }] },
    ],
  },
  editLink: { pattern: `${REPO}/edit/main/docs/:path`, text: "在 GitHub 上编辑此页" },
  footer: { message: "以 MIT 许可证发布。", copyright: "ZettCode，终端编码智能体" },
  docFooter: { prev: "上一篇", next: "下一篇" },
  outline: { label: "本页目录", level: [2, 3] },
  lastUpdated: { text: "最后更新", formatOptions: { dateStyle: "medium", timeStyle: "short" } },
  returnToTopLabel: "回到顶部",
  sidebarMenuLabel: "目录",
  darkModeSwitchLabel: "外观",
  lightModeSwitchTitle: "切换到浅色主题",
  darkModeSwitchTitle: "切换到深色主题",
  notFound: {
    title: "页面不存在",
    quote: "这一页被移动了，或者从来没有过。",
    linkText: "回到指南",
  },
};

export default defineConfig({
  // Published as a project page: https://chang-lehung.github.io/zettcode/
  base: "/zettcode/",
  // Our own notes live in docs/internal and stay out of the site.
  srcExclude: ["internal/**"],
  cleanUrls: true,
  sitemap: { hostname: "https://chang-lehung.github.io/zettcode/" },
  head: [
    ["link", { rel: "icon", href: "/zettcode/logo.svg", type: "image/svg+xml" }],
    ["meta", { name: "theme-color", content: "#a7c080" }],
    ["meta", { property: "og:type", content: "website" }],
    ["meta", { property: "og:title", content: "ZettCode" }],
    ["meta", { property: "og:description", content: "A focused terminal coding agent" }],
  ],
  markdown: {
    theme: { light: "github-light", dark: "github-dark" },
  },
  locales: {
    root: {
      label: "English",
      lang: "en-US",
      title: "ZettCode",
      description: "A focused terminal coding agent: install it, drive it, and make it yours.",
    },
    zh: {
      label: "中文",
      lang: "zh-CN",
      link: "/zh/",
      title: "ZettCode",
      description: "专注的终端编码智能体：安装、使用与配置。",
    },
  },
  themeConfig: {
    logo: "/logo.svg",
    siteTitle: "ZettCode",
    socialLinks: [
      { icon: "github", link: REPO },
    ],
    search: { provider: "local" },
    lastUpdated: true,
    locales: {
      root: { label: "English", ...english },
      zh: { label: "中文", ...chinese },
    },
  },
});
