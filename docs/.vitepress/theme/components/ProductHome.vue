<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";
import { useData, withBase } from "vitepress";
import { homeCopy } from "../home";
import TerminalPreview from "./TerminalPreview.vue";

const { lang } = useData();
const chinese = computed(() => lang.value.startsWith("zh"));
const copy = computed(() => homeCopy[chinese.value ? "zh" : "en"]);
const guide = computed(() => `${chinese.value ? "/zh" : ""}/guide/`);
const status = ref("");
let timeout: ReturnType<typeof setTimeout> | undefined;

async function copyInstall() {
  try {
    await navigator.clipboard.writeText("uv tool install zettcode");
    status.value = copy.value.copied;
  } catch {
    status.value = copy.value.copyFailed;
  }
  clearTimeout(timeout);
  timeout = setTimeout(() => { status.value = ""; }, 2500);
}

onUnmounted(() => clearTimeout(timeout));
</script>

<template>
  <div class="product-home">
    <section class="product-hero" aria-labelledby="product-title">
      <div class="hero-copy">
        <p class="eyebrow">{{ copy.eyebrow }}</p>
        <h1 id="product-title">{{ copy.title[0] }}<br /><span>{{ copy.title[1] }}</span></h1>
        <p class="hero-description">{{ copy.description }}</p>
        <div class="hero-actions">
          <a class="primary-action" :href="withBase(guide + 'getting-started')">{{ copy.start }} <span aria-hidden="true">↗</span></a>
          <a class="secondary-action" :href="withBase(guide + 'overview')">{{ copy.guide }} <span aria-hidden="true">→</span></a>
        </div>
        <div class="install-command">
          <span aria-hidden="true">$</span>
          <code>uv tool install zettcode</code>
          <button type="button" :aria-label="copy.install" @click="copyInstall">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V4a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h4" /></svg>
          </button>
        </div>
        <p class="install-feedback" role="status">{{ status || copy.requirements }}</p>
      </div>
      <div class="brand-stage" aria-hidden="true">
        <div class="brand-orbit"><img :src="withBase('/logo.svg')" alt="" width="176" height="176" /></div>
        <span class="brand-wordmark">zettcode<span class="brand-caret">_</span></span>
        <span class="brand-caption">~/your-next-idea</span>
      </div>
    </section>

    <section class="product-showcase" aria-labelledby="preview-title">
      <div class="showcase-heading"><h2 id="preview-title">{{ copy.previewTitle }}</h2><p>{{ copy.previewDescription }}</p></div>
      <TerminalPreview :alt="copy.previewAlt" :caption="copy.previewCaption" />
    </section>

    <section class="product-principles" :aria-label="copy.previewTitle">
      <article v-for="item in copy.principles" :key="item.number">
        <span class="section-number">{{ item.number }}</span>
        <h3>{{ item.title }}</h3><p>{{ item.text }}</p>
        <a :href="withBase(item.link)">{{ item.label }} <span aria-hidden="true">→</span></a>
      </article>
    </section>

    <section class="guide-paths" aria-labelledby="paths-title">
      <p class="eyebrow">{{ copy.pathEyebrow }}</p><h2 id="paths-title">{{ copy.pathTitle }}</h2>
      <div class="path-grid">
        <article v-for="path in copy.paths" :key="path.title">
          <h3>{{ path.title }}</h3><p>{{ path.text }}</p>
          <ul><li v-for="link in path.links" :key="link.path"><a :href="withBase(guide + link.path)">{{ link.label }} <span aria-hidden="true">↗</span></a></li></ul>
        </article>
      </div>
    </section>

    <div class="home-help"><p>{{ copy.help }} <a :href="withBase(guide + 'faq')">{{ copy.faq }} <span aria-hidden="true">→</span></a></p><a href="https://github.com/Chang-LeHung/zettcode">{{ copy.source }} <span aria-hidden="true">↗</span></a></div>
  </div>
</template>
