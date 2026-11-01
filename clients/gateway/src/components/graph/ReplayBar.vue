<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { gateway } from "../../api/gateway";
import { t } from "../../i18n";
import { fractionOf, fromLocalInput, stepTarget, timeAt, toLocalInput } from "../../lib/graphBar";
import { compress, formatClock, formatSpan, histogram, presets, windowFor, type Preset } from "../../lib/graphReplay";
import {
  exitReplay,
  graphReplay as rp,
  loadReplay,
  pause,
  play,
  seek,
  setSpeed,
  setSpeedFit30,
  toggleSkip,
} from "../../stores/graph";

const open = ref(false);
const chosen = ref<Preset | "">("1h");
const from = ref("");
const to = ref("");
const busy = ref(false);
let lastRange: [number, number] | "all" | Preset = "1h";

function resetCustom(): void {
  const now = Date.now() / 1000;
  from.value = toLocalInput(now - 3600);
  to.value = toLocalInput(now);
}
resetCustom();

const labels: Record<Preset, string> = { "15m": "15 min", "1h": "1 h", "24h": "24 h", "7d": "7 d", all: "All stored" };

function pick(id: Preset): void {
  chosen.value = id;
  const seconds = presets.find((p) => p.id === id)?.seconds;
  if (seconds) {
    const now = Date.now() / 1000;
    from.value = toLocalInput(now - seconds);
    to.value = toLocalInput(now);
  }
}

async function start(range: Preset | [number, number]): Promise<void> {
  lastRange = range;
  busy.value = true;
  try {
    if (typeof range === "string") {
      const now = Date.now() / 1000;
      let span: [number, number] | null = null;
      if (range === "all") {
        try {
          span = (await gateway.timeline(0, now, 1)).span;
        } catch {
          span = null;
        }
      }
      const w = windowFor(range, now, span);
      await loadReplay(w.since, w.until);
    } else {
      await loadReplay(range[0], range[1]);
    }
  } finally {
    busy.value = false;
  }
}

const customError = ref("");

function load(): void {
  const a = fromLocalInput(from.value);
  const b = fromLocalInput(to.value);
  if (a === null || b === null || b <= a) {
    customError.value = t("Choose a start before the end.");
    return;
  }
  customError.value = "";
  void start([a, b]);
}

/** The chips and the custom fields name the same window; "Load" loads what is typed, a chip loads at once. */
function chip(id: Preset): void {
  pick(id);
  void start(id);
}

function retry(): void {
  void start(lastRange as Preset | [number, number]);
}

watch(
  () => rp.mode,
  (mode) => {
    if (mode === "live") open.value = false;
  },
);

// --- replay controls ---------------------------------------------------------------------------------------------------

const ready = computed(() => rp.mode === "replay" && rp.status === "ready" && rp.replay);
const empty = computed(() => ready.value && rp.replay!.messages.length === 0);
const frac = computed(() => (rp.replay ? fractionOf(rp.replay, rp.playhead) : 0));
const clock = computed(() => (rp.playhead ? formatClock(rp.playhead) : "--:--:--"));
const day = computed(() => (rp.playhead ? new Date(rp.playhead * 1000).toLocaleDateString() : ""));
const bars = computed(() => {
  if (!rp.replay) return [];
  const counts = histogram(rp.replay, 80);
  const peak = Math.max(1, ...counts);
  return counts.map((c) => (c ? 0.14 + (0.86 * c) / peak : 0));
});
const skipped = computed(() => {
  if (!rp.replay || !rp.skipSilence) return 0;
  return compress(rp.replay, rp.speed, true).skippedBefore(rp.playhead);
});
const speeds = [1, 5, 10, 20, 30, 40, 50, 60, 600];
const speedValue = computed(() => (speeds.includes(rp.speed) ? String(rp.speed) : "fit"));

function onSpeed(event: Event): void {
  const v = (event.target as HTMLSelectElement).value;
  if (v === "fit") setSpeedFit30();
  else setSpeed(Number(v));
}

function toggle(): void {
  if (rp.playing) pause();
  else play();
}

function restart(): void {
  if (rp.replay) seek(rp.replay.start);
}

function step(dir: 1 | -1): void {
  if (rp.replay) seek(stepTarget(rp.replay, rp.playhead, dir));
}

// --- the scrubber ------------------------------------------------------------------------------------------------------

const track = ref<HTMLElement | null>(null);
const drag = reactive({ on: false, resume: false });

function fromPointer(event: PointerEvent): void {
  const box = track.value?.getBoundingClientRect();
  if (!box || !rp.replay || box.width <= 0) return;
  seek(timeAt(rp.replay, (event.clientX - box.left) / box.width));
}

function down(event: PointerEvent): void {
  if (event.button !== 0) return;
  drag.on = true;
  drag.resume = rp.playing;
  pause();
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  fromPointer(event);
}

function moveDrag(event: PointerEvent): void {
  if (drag.on) fromPointer(event);
}

function up(): void {
  if (!drag.on) return;
  drag.on = false;
  if (drag.resume) play();
}

function sliderKey(event: KeyboardEvent): void {
  const r = rp.replay;
  if (!r) return;
  const big = event.shiftKey ? 0.1 : 0.01;
  let handled = true;
  if (event.key === "ArrowLeft" || event.key === "ArrowDown") seek(rp.playhead - r.duration * big);
  else if (event.key === "ArrowRight" || event.key === "ArrowUp") seek(rp.playhead + r.duration * big);
  else if (event.key === "Home") seek(r.start);
  else if (event.key === "End") seek(r.end);
  else if (event.key === "PageUp") seek(rp.playhead - r.duration * 0.1);
  else if (event.key === "PageDown") seek(rp.playhead + r.duration * 0.1);
  else handled = false;
  if (handled) {
    event.preventDefault();
    event.stopPropagation();
  }
}

const valueText = computed(() => `${day.value} ${clock.value}`);

// --- the keyboard ------------------------------------------------------------------------------------------------------

function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}

function onKey(event: KeyboardEvent): void {
  if (rp.mode !== "replay" || typing(event.target) || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.key === "Escape") exitReplay();
  else if (!ready.value) return;
  else if (event.key === " " || event.code === "Space") {
    if ((event.target as HTMLElement | null)?.tagName === "BUTTON") return;
    event.preventDefault();
    toggle();
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    step(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    step(1);
  }
}

onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <div class="rb" :class="{ replay: rp.mode === 'replay' }">
    <!-- live: a button that opens the range picker -->
    <template v-if="rp.mode === 'live'">
      <div v-if="open" class="rb-card rb-picker" role="group" :aria-label="t('Replay')">
        <div class="rb-row">
          <b class="rb-title">{{ t("Replay") }}</b>
          <span class="rb-hint">{{ t("Watch stored traffic again. Nothing is sent.") }}</span>
          <button class="iconbtn rb-x" :aria-label="t('Close')" @click="open = false">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>
        <div class="rb-chips" role="group" :aria-label="t('Period')">
          <button v-for="p in presets" :key="p.id" class="rb-chip" :class="{ on: chosen === p.id }" :disabled="busy" @click="chip(p.id)">{{ t(labels[p.id]) }}</button>
        </div>
        <div class="rb-custom">
          <label>{{ t("From") }}<input v-model="from" type="datetime-local" @input="chosen = ''" /></label>
          <label>{{ t("To") }}<input v-model="to" type="datetime-local" @input="chosen = ''" /></label>
          <button class="btn ghost sm" :disabled="busy" @click="load">{{ t("Load") }}</button>
        </div>
        <div v-if="customError" class="rb-err" role="alert">{{ customError }}</div>
      </div>
      <button v-else class="rb-open" @click="open = true">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5Z" /></svg>
        {{ t("Replay") }}
      </button>
    </template>

    <!-- replay -->
    <div v-else class="rb-card rb-panel">
      <div v-if="rp.status === 'loading'" class="rb-skel" role="status" :aria-label="t('Loading…')">
        <i class="sk a" /><i class="sk b" /><i class="sk c" />
        <span>{{ t("Loading stored messages…") }}</span>
      </div>

      <div v-else-if="rp.status === 'error'" class="rb-row rb-bad" role="alert">
        <span class="rb-errtext">{{ t("Cannot load the replay.") }} <small>{{ rp.error }}</small></span>
        <button class="btn ghost sm" @click="retry">{{ t("Retry") }}</button>
        <button class="btn sm rb-plain" @click="exitReplay">{{ t("Back to live") }}</button>
      </div>

      <div v-else-if="empty" class="rb-row">
        <span class="rb-emptytext">{{ t("No messages in this period") }}</span>
        <button class="btn ghost sm" @click="exitReplay">{{ t("Back to live") }}</button>
      </div>

      <template v-else-if="ready && rp.replay">
        <div class="rb-main">
          <div class="rb-ctl">
            <button class="rb-btn" :aria-label="t('Restart')" :title="t('Restart')" @click="restart">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M6 5h2v14H6zM19 5.7v12.6a.8.8 0 0 1-1.25.66l-8.6-6.3a.8.8 0 0 1 0-1.32l8.6-6.3A.8.8 0 0 1 19 5.7Z" /></svg>
            </button>
            <button class="rb-btn" :aria-label="t('Previous message')" :title="t('Previous message')" @click="step(-1)">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 6-6 6 6 6" /></svg>
            </button>
            <button class="rb-btn big" :aria-label="rp.playing ? t('Pause') : t('Play')" :title="rp.playing ? t('Pause') : t('Play')" @click="toggle">
              <svg v-if="rp.playing" viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" /></svg>
              <svg v-else viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5Z" /></svg>
            </button>
            <button class="rb-btn" :aria-label="t('Next message')" :title="t('Next message')" @click="step(1)">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 6 6 6-6 6" /></svg>
            </button>
          </div>

          <div class="rb-clock" aria-hidden="true">
            <b>{{ clock }}</b>
            <small>{{ day }}</small>
          </div>

          <div class="rb-opts">
            <label class="rb-speed">
              <span>{{ t("Speed") }}</span>
              <select :value="speedValue" :aria-label="t('Speed')" @change="onSpeed">
                <option v-for="s in speeds" :key="s" :value="String(s)">{{ s }}x</option>
                <option value="fit">{{ t("Fit 30 s") }}</option>
              </select>
            </label>
            <button class="rb-toggle" role="switch" :aria-checked="rp.skipSilence" :class="{ on: rp.skipSilence }" @click="toggleSkip">
              <i /> {{ t("Skip silence") }}
            </button>
            <span v-if="skipped >= 1" class="rb-skipped">{{ t("skipped {time}", { time: formatSpan(skipped) }) }}</span>
          </div>

          <button class="btn ghost sm rb-exit" @click="exitReplay">{{ t("Back to live") }}</button>
        </div>

        <div class="rb-scrub">
          <time class="rb-end">{{ formatClock(rp.replay.start) }}</time>
          <div
            ref="track"
            class="rb-track"
            role="slider"
            tabindex="0"
            :aria-label="t('Playhead')"
            aria-orientation="horizontal"
            :aria-valuemin="Math.round(rp.replay.start)"
            :aria-valuemax="Math.round(rp.replay.end)"
            :aria-valuenow="Math.round(rp.playhead)"
            :aria-valuetext="valueText"
            @pointerdown="down"
            @pointermove="moveDrag"
            @pointerup="up"
            @pointercancel="up"
            @keydown="sliderKey"
          >
            <div class="rb-hist" aria-hidden="true"><i v-for="(h, i) in bars" :key="i" :style="{ height: `${h * 100}%` }" /></div>
            <div class="rb-rail" aria-hidden="true"><i :style="{ width: `${frac * 100}%` }" /></div>
            <div class="rb-knob" :class="{ drag: drag.on }" :style="{ left: `${frac * 100}%` }" aria-hidden="true" />
          </div>
          <time class="rb-end">{{ formatClock(rp.replay.end) }}</time>
        </div>
      </template>
    </div>
  </div>
</template>

<style>
.rb { position: absolute; left: 0; right: 0; bottom: 0; z-index: 3; display: flex; justify-content: center; padding: 0 12px calc(12px + var(--safe-bottom, 0px)); pointer-events: none; }
.rb > * { pointer-events: auto; }
.rb.replay { padding-left: 12px; padding-right: 12px; }
.rb-open {
  display: inline-flex; align-items: center; gap: 7px; height: 36px; padding: 0 16px 0 13px; border-radius: 999px; font-size: 0.85rem; font-weight: 600;
  color: var(--text); background: var(--graph-card); border: 1px solid var(--graph-card-border); box-shadow: var(--graph-shadow);
  -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); transition: transform 0.12s, border-color 0.15s;
}
.rb-open svg { color: var(--accent); }
.rb-open:hover { border-color: var(--accent); }
.rb-open:active { transform: scale(0.97); }
.rb-card {
  width: min(880px, 100%); border-radius: 16px; padding: 12px 16px; background: var(--graph-card); border: 1px solid var(--graph-card-border);
  box-shadow: var(--graph-shadow); -webkit-backdrop-filter: blur(16px); backdrop-filter: blur(16px); color: var(--text); animation: spring 0.25s ease-out;
}
.rb-picker { width: min(560px, 100%); display: flex; flex-direction: column; gap: 12px; }
.rb-row { display: flex; align-items: center; gap: 10px; min-width: 0; }
.rb-title { font-size: 0.95rem; font-weight: 650; }
.rb-hint { flex: 1; min-width: 0; font-size: 0.76rem; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rb-x { width: 30px; height: 30px; margin-left: auto; }
.rb-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.rb-chip { height: 30px; padding: 0 13px; border-radius: 999px; font-size: 0.8rem; font-weight: 550; background: var(--chip-bg, var(--surface-2)); color: var(--text); border: 1px solid transparent; transition: background 0.15s, color 0.15s; }
.rb-chip:hover:not(:disabled) { background: var(--hover); }
.rb-chip.on { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
.rb-chip:disabled { opacity: 0.5; }
.rb-custom { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px; }
.rb-custom label { display: flex; flex-direction: column; gap: 4px; font-size: 0.72rem; color: var(--muted); flex: 1; min-width: 150px; }
.rb-custom input {
  height: 34px; padding: 0 10px; border-radius: 10px; font: inherit; font-size: 0.85rem; color: var(--text); background: var(--surface-2); border: 1px solid var(--divider);
  color-scheme: light dark; font-variant-numeric: tabular-nums;
}
.rb-custom input:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.rb-err { font-size: 0.78rem; color: var(--bad); }

.rb-panel { display: flex; flex-direction: column; gap: 10px; }
.rb-main { display: flex; align-items: center; gap: 16px; flex-wrap: nowrap; }
.rb-ctl { display: flex; align-items: center; gap: 4px; flex: none; }
.rb-btn { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; color: var(--text); transition: background 0.15s, transform 0.1s; }
.rb-btn:hover { background: var(--hover); }
.rb-btn:active { transform: scale(0.92); }
.rb-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.rb-btn.big { width: 42px; height: 42px; background: var(--accent); color: #fff; margin: 0 2px; }
.rb-btn.big:hover { background: var(--accent); filter: brightness(1.08); }
.rb-clock { display: flex; flex-direction: column; align-items: flex-start; line-height: 1.05; flex: none; }
.rb-clock b { font-size: 1.7rem; font-weight: 650; letter-spacing: -0.01em; font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }
.rb-clock small { font-size: 0.7rem; color: var(--muted); margin-top: 2px; }
.rb-opts { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; flex-wrap: wrap; justify-content: flex-end; }
.rb-speed { display: inline-flex; align-items: center; gap: 6px; font-size: 0.75rem; color: var(--muted); }
.rb-speed select {
  height: 30px; padding: 0 10px; border-radius: 9px; font: inherit; font-size: 0.82rem; font-weight: 550; color: var(--text); background: var(--surface-2); border: 1px solid var(--divider); cursor: pointer;
}
.rb-speed select:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.rb-toggle { display: inline-flex; align-items: center; gap: 7px; height: 30px; padding: 0 10px 0 6px; border-radius: 999px; font-size: 0.78rem; font-weight: 550; color: var(--muted); }
.rb-toggle i { position: relative; width: 26px; height: 16px; border-radius: 999px; background: var(--divider); transition: background 0.15s; }
.rb-toggle i::after { content: ""; position: absolute; left: 2px; top: 2px; width: 12px; height: 12px; border-radius: 50%; background: #fff; transition: transform 0.15s; }
.rb-toggle.on { color: var(--text); }
.rb-toggle.on i { background: var(--accent); }
.rb-toggle.on i::after { transform: translateX(10px); }
.rb-toggle:focus-visible { outline: 2px solid var(--accent); }
.rb-skipped { padding: 2px 9px; border-radius: 999px; font-size: 0.7rem; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--accent); background: var(--accent-soft); white-space: nowrap; }
.rb-exit { flex: none; }
.rb-plain { background: var(--surface-2); color: var(--text); }

.rb-scrub { display: flex; align-items: center; gap: 10px; }
.rb-end { flex: none; font-size: 0.72rem; color: var(--muted); font-variant-numeric: tabular-nums; min-width: 56px; }
.rb-end:last-child { text-align: right; }
.rb-track { position: relative; flex: 1; height: 38px; cursor: pointer; touch-action: none; border-radius: 8px; outline: none; user-select: none; -webkit-user-select: none; }
.rb-track:focus-visible { box-shadow: 0 0 0 2px var(--accent); }
.rb-hist { position: absolute; left: 0; right: 0; bottom: 8px; top: 2px; display: flex; align-items: flex-end; gap: 1px; pointer-events: none; }
.rb-hist i { flex: 1; min-height: 0; border-radius: 1.5px 1.5px 0 0; background: color-mix(in srgb, var(--accent) 38%, transparent); }
.rb-rail { position: absolute; left: 0; right: 0; bottom: 4px; height: 4px; border-radius: 2px; background: var(--divider); pointer-events: none; }
.rb-rail i { display: block; height: 100%; border-radius: 2px; background: var(--accent); }
.rb-knob { position: absolute; bottom: 6px; width: 16px; height: 16px; margin: 0 0 -8px -8px; border-radius: 50%; background: #fff; border: 3px solid var(--accent); box-shadow: 0 1px 6px rgba(0, 0, 0, 0.35); transition: transform 0.12s; pointer-events: none; }
.rb-track:hover .rb-knob, .rb-knob.drag { transform: scale(1.18); }

.rb-skel { display: flex; align-items: center; gap: 12px; min-height: 64px; font-size: 0.82rem; color: var(--muted); }
.rb-skel .sk { display: block; height: 28px; border-radius: 8px; background: linear-gradient(90deg, var(--surface-2), var(--hover), var(--surface-2)); background-size: 200% 100%; animation: rb-shimmer 1.2s linear infinite; }
.rb-skel .a { width: 42px; border-radius: 50%; height: 42px; }
.rb-skel .b { width: 110px; }
.rb-skel .c { flex: 1; max-width: 340px; }
.rb-skel span { margin-left: auto; }
@keyframes rb-shimmer { from { background-position: 100% 0; } to { background-position: -100% 0; } }
.rb-bad { color: var(--bad); }
.rb-errtext { flex: 1; min-width: 0; font-size: 0.85rem; }
.rb-errtext small { display: block; font-size: 0.72rem; opacity: 0.8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rb-emptytext { flex: 1; font-size: 0.9rem; color: var(--muted); }

@media (max-width: 719px) {
  .rb { padding-left: 8px; padding-right: 8px; }
  .rb-card { padding: 10px 12px; }
  .rb-main { flex-wrap: wrap; gap: 8px 12px; }
  .rb-clock b { font-size: 1.4rem; }
  .rb-clock { order: 1; margin-left: auto; align-items: flex-end; }
  .rb-ctl { order: 0; }
  .rb-opts { order: 2; flex-basis: 100%; justify-content: flex-start; }
  .rb-exit { order: 3; margin-left: auto; }
  .rb-hint { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .rb-card, .rb-skel .sk { animation: none; }
}
</style>
