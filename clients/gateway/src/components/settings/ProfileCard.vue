<script setup lang="ts">
import { ref } from "vue";
import { t } from "../../i18n";
import { squareAvatar } from "../../lib/image";
import { prefs } from "../../stores/prefs";
import { toast } from "../../stores/ui";
import UserAvatar from "../common/UserAvatar.vue";

const input = ref<HTMLInputElement | null>(null);

async function pick(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  target.value = "";
  if (!file) return;
  try {
    prefs.avatar = await squareAvatar(file);
  } catch {
    toast(t("That file is not a picture this browser can read."), "bad");
  }
}
</script>

<template>
  <div class="card profile">
    <UserAvatar size="xl" />
    <div class="profile-side">
      <b>{{ t("Your picture") }}</b>
      <small>{{ t("Shown beside your messages. It stays in this browser.") }}</small>
      <div class="actions">
        <button class="btn sm" @click="input?.click()">{{ t("Upload a picture") }}</button>
        <button v-if="prefs.avatar" class="btn sm ghost" @click="prefs.avatar = ''">{{ t("Use the default") }}</button>
      </div>
    </div>
    <input ref="input" type="file" accept="image/*" class="sr" tabindex="-1" @change="pick" />
  </div>
</template>

<style>
.profile { display: flex; align-items: center; gap: 16px; padding: 16px; }
.profile-side { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.profile-side small { color: var(--muted); line-height: 1.35; }
.profile-side .actions { padding: 8px 0 0; }
</style>
