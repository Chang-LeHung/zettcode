const REPO = "https://github.com/Chang-LeHung/zettcode";

const translations = {
  en: {
    groups: ["Start here", "Everyday use", "Configuration & extensions", "Help"],
    pages: ["Guide overview", "Getting started", "The interface", "Keys & mouse", "Commands", "Sessions", "Configuration", "Models & context", "Project instructions", "Skills & MCP", "Plugins", "Problems & questions"],
    guide: "Guide", reference: "Reference", setup: "Configure", install: "Get started",
    edit: "Edit this page on GitHub", license: "Released under the MIT license.", footer: "ZettCode — your terminal, your coding partner.",
    prev: "Previous", next: "Next", outline: "On this page", updated: "Last updated", top: "Back to top", menu: "Guide menu",
    appearance: "Appearance", light: "Switch to light theme", dark: "Switch to dark theme", language: "Change language",
    notFound: "Page not found", quote: "This page may have moved. Let’s find your next step.", back: "Back to the guide",
  },
  zh: {
    groups: ["第一次使用", "日常使用", "配置与扩展", "帮助"],
    pages: ["指南导览", "快速开始", "认识界面", "快捷键与鼠标", "命令参考", "会话管理", "配置参考", "模型与上下文", "项目指令", "Skills 与 MCP", "插件", "常见问题"],
    guide: "使用指南", reference: "操作参考", setup: "配置与扩展", install: "快速开始",
    edit: "在 GitHub 上编辑此页", license: "以 MIT 许可证发布。", footer: "ZettCode —— 你的终端，你的编码伙伴。",
    prev: "上一篇", next: "下一篇", outline: "本页目录", updated: "最近更新", top: "回到顶部", menu: "指南目录",
    appearance: "外观", light: "切换到浅色主题", dark: "切换到深色主题", language: "切换语言",
    notFound: "页面不存在", quote: "这一页可能被移动了。回到指南，找到下一步。", back: "回到使用指南",
  },
};

const slugs = ["overview", "getting-started", "interface", "keys", "commands", "sessions", "config", "models", "instructions", "skills-and-mcp", "plugins", "faq"];

export function navigation(language: keyof typeof translations) {
  const text = translations[language];
  const prefix = language === "zh" ? "/zh/guide/" : "/guide/";
  const pages = slugs.map((slug, index) => ({ text: text.pages[index], link: prefix + slug }));
  const groups = [pages.slice(0, 3), pages.slice(3, 6), pages.slice(6, 11), pages.slice(11)];
  return {
    nav: [
      { text: text.guide, link: prefix + "overview", activeMatch: `${prefix}(overview|getting-started|interface)` },
      { text: text.reference, activeMatch: `${prefix}(keys|commands|sessions)`, items: groups[1] },
      { text: text.setup, activeMatch: `${prefix}(config|models|instructions|skills-and-mcp|plugins)`, items: groups[2] },
      { text: text.install, link: prefix + "getting-started" },
    ],
    sidebar: { [prefix]: groups.map((items, index) => ({ text: text.groups[index], items })) },
    editLink: { pattern: `${REPO}/edit/main/docs/:path`, text: text.edit },
    footer: { message: text.license, copyright: text.footer },
    docFooter: { prev: text.prev, next: text.next },
    outline: { label: text.outline, level: [2, 3] as [number, number] },
    lastUpdated: { text: text.updated, formatOptions: { dateStyle: "medium" as const } },
    returnToTopLabel: text.top,
    sidebarMenuLabel: text.menu,
    darkModeSwitchLabel: text.appearance,
    lightModeSwitchTitle: text.light,
    darkModeSwitchTitle: text.dark,
    langMenuLabel: text.language,
    notFound: { title: text.notFound, quote: text.quote, linkText: text.back, link: prefix + "overview" },
  };
}
