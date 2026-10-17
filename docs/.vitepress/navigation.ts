const REPO = "https://github.com/Chang-LeHung/zettcode";

const translations = {
  en: {
    groups: ["Start here", "Everyday use", "Configuration & extensions", "Help"],
    pages: {
      overview: "Guide overview",
      "getting-started": "Getting started",
      interface: "The interface",
      keys: "Keys & mouse",
      commands: "Commands",
      sessions: "Sessions",
      messaging: "Talking between sessions",
      context: "The context window",
      usage: "Token usage",
      config: "Configuration",
      models: "Models",
      instructions: "Project instructions",
      "skills-and-mcp": "Skills & MCP",
      plugins: "Plugins",
      faq: "Problems & questions",
    },
    subgroups: { context: "Models & context" },
    guide: "Guide", reference: "Reference", setup: "Configure", install: "Get started",
    edit: "Edit this page on GitHub", license: "Released under the MIT license.", footer: "ZettCode — your terminal, your coding partner.",
    prev: "Previous", next: "Next", outline: "On this page", updated: "Last updated", top: "Back to top", menu: "Guide menu",
    appearance: "Appearance", light: "Switch to light theme", dark: "Switch to dark theme", language: "Change language",
    notFound: "Page not found", quote: "This page may have moved. Let’s find your next step.", back: "Back to the guide",
  },
  zh: {
    groups: ["第一次使用", "日常使用", "配置与扩展", "帮助"],
    pages: {
      overview: "指南导览",
      "getting-started": "快速开始",
      interface: "认识界面",
      keys: "快捷键与鼠标",
      commands: "命令参考",
      sessions: "会话管理",
      messaging: "会话之间互发消息",
      context: "上下文窗口",
      usage: "Token 用量",
      config: "配置参考",
      models: "模型",
      instructions: "项目指令",
      "skills-and-mcp": "Skills 与 MCP",
      plugins: "插件",
      faq: "常见问题",
    },
    subgroups: { context: "模型与上下文" },
    guide: "使用指南", reference: "操作参考", setup: "配置与扩展", install: "快速开始",
    edit: "在 GitHub 上编辑此页", license: "以 MIT 许可证发布。", footer: "ZettCode —— 你的终端，你的编码伙伴。",
    prev: "上一篇", next: "下一篇", outline: "本页目录", updated: "最近更新", top: "回到顶部", menu: "指南目录",
    appearance: "外观", light: "切换到浅色主题", dark: "切换到深色主题", language: "切换语言",
    notFound: "页面不存在", quote: "这一页可能被移动了。回到指南，找到下一步。", back: "回到使用指南",
  },
};

// The order of the guide, and the group each page sits in. `context` opens a subgroup: the three pages under it
// are one subject -- how much the model can read, what it spent, and where that is reported -- so they are listed
// nested under it rather than as three siblings that a reader has to guess belong together.
const layout = [
  { group: 0, pages: ["overview", "getting-started"] },
  { group: 1, pages: ["interface", "keys", "commands", "sessions", "messaging"] },
  {
    group: 2,
    pages: [
      { subgroup: true, pages: ["models", "context", "usage"] },
      "config",
      "instructions",
      "skills-and-mcp",
      "plugins",
    ],
  },
  { group: 3, pages: ["faq"] },
];

export function navigation(language: keyof typeof translations) {
  const text = translations[language];
  const prefix = language === "zh" ? "/zh/guide/" : "/guide/";
  const page = (slug: string) => ({ text: text.pages[slug as keyof typeof text.pages], link: prefix + slug });

  const sidebar = layout.map(({ group, pages }) => ({
    text: text.groups[group],
    items: pages.map((entry) => (typeof entry === "string" ? page(entry) : { text: text.subgroups.context, collapsed: false, items: entry.pages.map(page) })),
  }));

  // The nav menus list the pages flat: a dropdown is short, and a nested menu there reads as a second level of
  // navigation that is not one. The sidebar keeps the grouping, which is where a reader scans the subject list.
  const byGroup = (index: number) => pageSlugs(index).map(page);
  const pageSlugs = (index: number) =>
    layout[index].pages.flatMap((entry) => (typeof entry === "string" ? [entry] : entry.pages));

  return {
    nav: [
      { text: text.guide, link: prefix + "overview", activeMatch: `${prefix}(overview|getting-started|interface)` },
      { text: text.reference, activeMatch: `${prefix}(${pageSlugs(1).join("|")})`, items: byGroup(1) },
      { text: text.setup, activeMatch: `${prefix}(${pageSlugs(2).join("|")})`, items: byGroup(2) },
      { text: text.install, link: prefix + "getting-started" },
    ],
    sidebar: { [prefix]: sidebar },
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
