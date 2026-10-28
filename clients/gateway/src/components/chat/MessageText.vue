<script setup lang="ts">
import { ref, watch } from "vue";
import { t } from "../../i18n";
import { copyText } from "../../lib/clipboard";
import { prefs } from "../../stores/prefs";
import { toast } from "../../stores/ui";

const props = defineProps<{ text: string; plain?: boolean }>();
const html = ref("");

// The renderer is a separate chunk, loaded the first time a message needs it; until then the text shows as it is.
watch(
  () => [props.text, props.plain, prefs.render, t("Copy")] as const,
  async ([text, plain, mode, copy]) => {
    if (plain || mode !== "markdown") {
      html.value = "";
      return;
    }
    const { renderMarkdown } = await import("../../lib/render");
    html.value = renderMarkdown(text, { copy });
  },
  { immediate: true },
);

async function onClick(event: MouseEvent): Promise<void> {
  const button = (event.target as HTMLElement).closest<HTMLElement>("[data-copy]");
  if (!button) return;
  const code = button.closest(".code")?.querySelector("code")?.textContent ?? "";
  if (await copyText(code)) toast(t("Copied"));
  else toast(t("Cannot copy here"), "bad");
}
</script>

<template>
  <div v-if="html" class="md" @click="onClick" v-html="html" />
  <div v-else class="plain">{{ text }}</div>
</template>

<style>
.plain { white-space: pre-wrap; }
.md { line-height: 1.55; }
.md > :first-child { margin-top: 0; }
.md > :last-child { margin-bottom: 0; }
.md p { margin: 0.5em 0; }
.md h1, .md h2, .md h3, .md h4 { margin: 0.9em 0 0.4em; line-height: 1.3; font-weight: 650; }
.md h1 { font-size: 1.35em; } .md h2 { font-size: 1.2em; } .md h3 { font-size: 1.08em; } .md h4 { font-size: 1em; }
.md ul, .md ol { margin: 0.4em 0; padding-left: 1.5em; }
.md li { margin: 0.15em 0; }
.md li > p { margin: 0.2em 0; }
.md input[type="checkbox"] { margin-right: 0.4em; }
.md blockquote { margin: 0.6em 0; padding: 0.1em 0 0.1em 0.9em; border-left: 3px solid var(--accent); color: var(--muted); }
.md hr { border: 0; border-top: 1px solid var(--divider); margin: 0.9em 0; }
.md a { color: var(--accent); text-decoration: underline; text-underline-offset: 2px; word-break: break-all; }
.md a:hover { text-decoration-thickness: 2px; }
.md img { max-width: 100%; height: auto; border-radius: 8px; }
.md code { font-family: var(--mono); font-size: 0.88em; background: var(--code-bg); padding: 0.1em 0.38em; border-radius: 5px; }
.md table { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; margin: 0.6em 0; font-size: 0.93em; }
.md th, .md td { border: 1px solid var(--divider); padding: 0.35em 0.7em; text-align: left; }
.md th { background: var(--code-bg); font-weight: 600; }
.md .katex-display { overflow-x: auto; overflow-y: hidden; padding: 0.2em 0; }

.code { margin: 0.6em 0; border-radius: 10px; overflow: hidden; background: var(--code-block); border: 1px solid var(--divider); }
.code-head { display: flex; align-items: center; justify-content: space-between; padding: 0.25em 0.4em 0.25em 0.8em; font-size: 0.78rem; color: var(--muted); background: var(--code-head); }
.code-lang { font-family: var(--mono); text-transform: lowercase; }
.code-copy { padding: 0.25em 0.7em; border-radius: 6px; color: var(--muted); font-size: 0.78rem; }
.code-copy:hover { background: var(--hover); color: var(--text); }
.md .code pre { margin: 0; padding: 0.7em 0.9em; overflow-x: auto; font-family: var(--mono); font-size: 0.84rem; line-height: 1.5; -webkit-overflow-scrolling: touch; }
.md .code code { background: none; padding: 0; border-radius: 0; font-size: inherit; color: var(--hl-fg); }

/* highlight.js tokens, one palette for light and one for dark, through variables */
.hljs-comment, .hljs-quote { color: var(--hl-comment); font-style: italic; }
.hljs-keyword, .hljs-selector-tag, .hljs-literal, .hljs-doctag, .hljs-meta .hljs-keyword { color: var(--hl-keyword); }
.hljs-string, .hljs-regexp, .hljs-addition, .hljs-meta .hljs-string { color: var(--hl-string); }
.hljs-number, .hljs-symbol, .hljs-bullet, .hljs-variable.constant_ { color: var(--hl-number); }
.hljs-title, .hljs-title.function_, .hljs-section, .hljs-selector-id { color: var(--hl-title); }
.hljs-title.class_, .hljs-type, .hljs-built_in, .hljs-class .hljs-title { color: var(--hl-type); }
.hljs-attr, .hljs-attribute, .hljs-property, .hljs-variable, .hljs-template-variable, .hljs-params { color: var(--hl-attr); }
.hljs-name, .hljs-tag, .hljs-selector-class { color: var(--hl-tag); }
.hljs-meta, .hljs-link, .hljs-subst { color: var(--hl-meta); }
.hljs-deletion { color: var(--bad); }
.hljs-emphasis { font-style: italic; } .hljs-strong { font-weight: 700; }
</style>
