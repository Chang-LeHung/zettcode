<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { t } from "../../i18n";
import { closeSheet, closeTopSheet, sheets } from "../../stores/ui";
import Icon from "./Icon.vue";

const host = ref<HTMLElement | null>(null);

function onKey(event: KeyboardEvent): void {
  if (event.key === "Escape" && closeTopSheet()) event.stopPropagation();
}

onMounted(() => document.addEventListener("keydown", onKey, true));
onBeforeUnmount(() => document.removeEventListener("keydown", onKey, true));

/** Put focus inside a sheet as it opens, so a keyboard works in it at once. */
function focusFirst(element: Element): void {
  void nextTick(() => element.querySelector<HTMLElement>("button.menu-item, input, button.btn")?.focus());
}
</script>

<template>
  <div ref="host">
    <div
      v-for="entry in sheets"
      :key="entry.id"
      :ref="(element) => element && focusFirst(element as Element)"
      class="backdrop"
      @click.self="closeSheet(entry.id)"
    >
      <div class="sheet" role="dialog" aria-modal="true" :aria-label="entry.title">
        <div class="sheet-head">
          <h3>{{ entry.title }}</h3>
          <button class="iconbtn" :aria-label="t('Close')" @click="closeSheet(entry.id)"><Icon name="close" /></button>
        </div>
        <div class="sheet-body">
          <component :is="entry.component" v-bind="entry.props" @close="(value?: unknown) => closeSheet(entry.id, value)" />
        </div>
      </div>
    </div>
  </div>
</template>

<style>
.backdrop { position: fixed; inset: 0; z-index: 30; background: var(--scrim); display: flex; align-items: flex-end; justify-content: center; animation: fade 0.15s ease-out; }
.sheet {
  width: 100%; max-width: 30rem; max-height: 82dvh; display: flex; flex-direction: column;
  background: var(--surface); border-radius: 18px 18px 0 0; box-shadow: var(--sheet-shadow);
  padding-bottom: var(--safe-bottom); animation: rise 0.2s ease-out;
}
.sheet-head { display: flex; align-items: center; gap: 6px; padding: 8px 8px 4px 18px; min-height: 52px; }
.sheet-head h3 { flex: 1; margin: 0; font-size: 1.05rem; font-weight: 650; }
.sheet-body { overflow-y: auto; overscroll-behavior: contain; padding: 0 0 8px; }
@media (min-width: 720px) {
  .backdrop { align-items: center; }
  .sheet { border-radius: 18px; max-height: 80dvh; }
}
</style>
