<script setup lang="ts">
import { computed, ref } from "vue";
import { ApiError } from "../../api/http";
import { t } from "../../i18n";
import { createGroup, GROUP_NAME } from "../../stores/groups";
import { go } from "../../stores/route";
import { lobby } from "../../stores/threads";
import { toast } from "../../stores/ui";
import Avatar from "../common/Avatar.vue";

const emit = defineEmits<{ close: []; busy: [on: boolean] }>();
const name = ref("");
const query = ref("");
const chosen = ref<string[]>([]);
const busy = ref(false);
const failure = ref("");

const clean = computed(() => name.value.trim().replace(/^#/, "").toLowerCase());
const valid = computed(() => GROUP_NAME.test(clean.value));
const hint = computed(() => (clean.value && !valid.value ? t("1 to 40 letters, digits, - or _") : ""));
const wanted = computed(() => query.value.trim().toLowerCase());
const candidates = computed(() =>
  lobby.threads.filter(
    (thread) =>
      thread.online && (!wanted.value || [thread.name, thread.title, thread.handle].some((field) => field.toLowerCase().includes(wanted.value))),
  ),
);

function toggle(id: string): void {
  chosen.value = chosen.value.includes(id) ? chosen.value.filter((item) => item !== id) : [...chosen.value, id];
}

async function create(): Promise<void> {
  if (!valid.value || busy.value) return;
  busy.value = true;
  emit("busy", true);
  failure.value = "";
  try {
    const made = await createGroup(clean.value, chosen.value);
    emit("busy", false);
    emit("close");
    toast(t("Created #{name}", { name: made }));
    go("chats", `#${made}`);
  } catch (error) {
    emit("busy", false);
    failure.value = error instanceof ApiError ? error.message : String(error);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <form class="invite newgroup" @submit.prevent="create">
    <label class="ng-name">
      <span>#</span>
      <input v-model="name" type="text" maxlength="40" autocomplete="off" autocapitalize="none" spellcheck="false" :placeholder="t('group-name')" :aria-label="t('Group name')" />
    </label>
    <small v-if="hint" class="ng-hint">{{ hint }}</small>

    <div class="invite-group">{{ t("Members") }} · {{ t("{count} chosen", { count: chosen.length }) }}</div>
    <input v-model="query" type="search" :placeholder="t('Search sessions or agents')" :aria-label="t('Search sessions or agents')" />
    <div class="ng-list">
      <button v-for="thread in candidates" :key="thread.id" type="button" class="invite-row" :aria-pressed="chosen.includes(thread.id)" @click="toggle(thread.id)">
        <Avatar :thread="thread" size="sm" />
        <span class="invite-copy">
          <b>{{ thread.name }}</b>
          <small>{{ thread.title && thread.title !== thread.name ? thread.title : thread.kind }}</small>
        </span>
        <span class="ng-check" :class="{ on: chosen.includes(thread.id) }">{{ chosen.includes(thread.id) ? "✓" : "" }}</span>
      </button>
      <div v-if="!candidates.length" class="empty">{{ query.trim() ? t("Nothing matches") : t("No session is online to add yet. You can invite later.") }}</div>
    </div>

    <p v-if="failure" class="errcard" role="alert">{{ failure }}</p>
    <button class="btn block" type="submit" :disabled="!valid || busy"><span v-if="busy" class="spin" />{{ t("Create group") }}</button>
  </form>
</template>

<style>
.newgroup { gap: 6px; }
.ng-name { display: flex; align-items: center; gap: 4px; padding: 0 12px; min-height: 44px; border: 1px solid var(--divider); border-radius: 11px; background: var(--bg); color: var(--muted); }
.ng-name:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.ng-name input { flex: 1; min-height: 0; margin: 0; padding: 8px 0; border: 0; box-shadow: none; background: none; }
.ng-name input:focus { box-shadow: none; }
.ng-hint { color: var(--bad); padding: 0 4px; }
.ng-list { max-height: 36dvh; overflow-y: auto; overscroll-behavior: contain; }
.ng-check { flex: none; width: 22px; height: 22px; border-radius: 50%; border: 1.5px solid var(--divider); display: grid; place-items: center; font-size: 0.8rem; color: var(--accent-text); }
.ng-check.on { background: var(--accent); border-color: var(--accent); }
.newgroup .btn { margin-top: 8px; }
</style>
