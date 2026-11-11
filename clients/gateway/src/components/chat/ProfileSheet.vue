<script setup lang="ts">
import { ref } from "vue";
import { gateway } from "../../api/gateway";
import { ApiError } from "../../api/http";
import { t } from "../../i18n";
import { squareAvatar } from "../../lib/image";
import { loadThreads } from "../../stores/threads";
import { toast } from "../../stores/ui";
import type { Thread } from "../../types";
import Avatar from "../common/Avatar.vue";

const props = defineProps<{ thread: Thread }>();
const emit = defineEmits<{ close: [] }>();
const name = ref(props.thread.name);
const avatar = ref(props.thread.avatar ?? "");
const input = ref<HTMLInputElement | null>(null);
const busy = ref(false);
const failure = ref("");

async function pick(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  target.value = "";
  if (!file) return;
  try {
    avatar.value = await squareAvatar(file);
  } catch {
    toast(t("That file is not a picture this browser can read."), "bad");
  }
}

async function save(): Promise<void> {
  busy.value = true;
  failure.value = "";
  try {
    await gateway.updateProfile(props.thread.id, { name: name.value.trim(), avatar: avatar.value });
    await loadThreads();
    emit("close");
  } catch (error) {
    failure.value = error instanceof ApiError ? error.message : String(error);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="profile-edit">
    <Avatar :thread="{ ...thread, name, avatar }" size="xl" />
    <div class="profile-actions">
      <button class="btn sm" type="button" @click="input?.click()">{{ t("Upload a picture") }}</button>
      <button v-if="avatar" class="btn sm ghost" type="button" @click="avatar = ''">{{ t("Use the default") }}</button>
    </div>
    <label class="field-row">
      <span>{{ t("Display name") }}</span>
      <input v-model="name" type="text" maxlength="80" autocomplete="off" />
    </label>
    <input ref="input" type="file" accept="image/*" class="sr" tabindex="-1" @change="pick" />
    <p v-if="failure" class="errcard" role="alert">{{ failure }}</p>
    <button class="btn block" type="button" :disabled="busy" @click="save">
      {{ busy ? t("Saving…") : t("Save") }}
    </button>
  </div>
</template>

<style>
.profile-edit { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 12px 16px 16px; }
.profile-edit .profile-actions { display: flex; gap: 8px; }
.profile-edit .field-row { width: 100%; display: flex; flex-direction: column; gap: 4px; }
.profile-edit .field-row > span { color: var(--muted); font-size: 0.78rem; font-weight: 600; }
.profile-edit input[type="text"] { min-height: 42px; padding: 8px 10px; border: 1px solid var(--divider); border-radius: 10px; background: var(--bg); color: var(--text); font: inherit; }
</style>
