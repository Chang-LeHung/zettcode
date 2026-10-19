<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue";

import { post, state } from "../store.js";
import Icon from "./Icon.vue";
import FindBar from "./FindBar.vue";
import LiveStatus from "./LiveStatus.vue";
import MessageRail from "./MessageRail.vue";
import TurnView from "./TurnView.vue";
import Welcome from "./Welcome.vue";

const scroller = ref<HTMLElement | null>(null);
const pinned = ref(true);
const away = ref(false);

function nearBottom(): boolean {
  const element = scroller.value;
  return element === null || element.scrollHeight - element.scrollTop - element.clientHeight < 80;
}

function onScroll(): void {
  pinned.value = nearBottom();
  away.value = !pinned.value && state.turns.length > 0;
}

function toBottom(): void {
  away.value = false;
  window.requestAnimationFrame(() => {
    const element = scroller.value;
    if (element !== null) {
      element.scrollTop = element.scrollHeight;
    }
  });
}

function jump(): void {
  pinned.value = true;
  toBottom();
}

/**
 * Older requests arrive in front of the ones on show. The view keeps what the reader was looking at where it was: the
 * height the new rows add is added to the scroll position.
 */
let anchor: { height: number; top: number } | null = null;

function loadEarlier(): void {
  const element = scroller.value;
  if (element !== null) {
    anchor = { height: element.scrollHeight, top: element.scrollTop };
  }
  pinned.value = false;
  post({ type: "load-earlier" });
}

watch(
  () => state.turns[0]?.id,
  async () => {
    await nextTick();
    const element = scroller.value;
    if (anchor !== null && element !== null) {
      element.scrollTop = anchor.top + (element.scrollHeight - anchor.height);
    }
    anchor = null;
  },
);

/** New text follows the reader to the bottom, unless they scrolled up to read. */
watch(
  () => [state.tick, state.ui?.busy, state.ui?.pending?.kind],
  async () => {
    await nextTick();
    if (pinned.value) {
      toBottom();
    } else {
      away.value = state.turns.length > 0;
    }
  },
);

watch(
  () => state.turns.length,
  (now, before) => {
    if (now > before) {
      pinned.value = true;
    }
  },
);

onMounted(toBottom);
</script>

<template>
  <!-- The rail sits beside the scrolling view, not inside it, so it stays put while the conversation moves. -->
  <div class="transcript-wrap">
    <main id="transcript" ref="scroller" class="transcript" @scroll.passive="onScroll">
      <div class="column">
        <Welcome />
        <button v-if="state.earlier > 0" id="earlier" class="earlier" type="button" @click="loadEarlier">
          <Icon name="up" :size="12" />Show {{ state.earlier }} earlier request{{ state.earlier === 1 ? "" : "s" }}
        </button>
        <div id="turns" class="turns">
          <TurnView v-for="turn in state.turns" :key="turn.id" :turn="turn" />
        </div>
        <LiveStatus />
      </div>
      <button v-if="away" id="jump" class="jump" type="button" @click="jump">
        <Icon name="down" :size="13" />Latest
      </button>
    </main>
    <MessageRail :scroller="scroller" />
    <FindBar />
  </div>
</template>

<style>
.transcript-wrap {
  position: relative;
  display: flex;
  flex: 1;
  min-height: 0;
}

.transcript {
  position: relative;
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-gutter: stable;
}

.column {
  width: 100%;
  max-width: var(--column);
  margin: 0 auto;
  padding: 4px var(--gutter) 28px;
}

.earlier {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin: 10px auto 2px;
  padding: 5px 13px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  background: none;
  color: var(--muted);
  font-size: var(--small);
}

.earlier:hover {
  background: var(--wash-2);
  color: var(--fg);
}

.jump {
  position: sticky;
  bottom: 12px;
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 0 auto;
  width: max-content;
  padding: 5px 13px 5px 10px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  background: var(--raised);
  box-shadow: var(--shadow);
  font-size: var(--small);
  animation: rise 0.16s ease-out;
}

.jump:hover {
  background: var(--wash-2);
}
</style>
