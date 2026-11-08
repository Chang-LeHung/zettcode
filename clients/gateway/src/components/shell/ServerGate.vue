<script setup lang="ts">
// The app's front door: the servers this device knows, and the form that adds or changes one. The gateway's own page
// never draws this, because it already knows the one server that served it.

import { ref } from "vue";
import Icon from "../common/Icon.vue";
import { t } from "../../i18n";
import {
  addServer,
  connectServer,
  disconnectServer,
  removeServer,
  servers,
  testConnection,
  updateServer,
} from "../../stores/servers";
import type { ServerProfile } from "../../lib/servers";

type Editing = ServerProfile | "new" | null;

const editing = ref<Editing>(null);
const name = ref("");
const url = ref("http://127.0.0.1:8765");
const token = ref("");
const error = ref("");
const status = ref("");
const busy = ref(false);
const connecting = ref("");

function add(): void {
  editing.value = "new";
  name.value = "";
  url.value = "http://127.0.0.1:8765";
  token.value = "";
  error.value = "";
  status.value = "";
}

function change(profile: ServerProfile): void {
  editing.value = profile;
  name.value = profile.name;
  url.value = profile.url;
  token.value = profile.token;
  error.value = "";
  status.value = "";
}

function cancel(): void {
  editing.value = null;
  error.value = "";
  status.value = "";
}

async function test(): Promise<void> {
  busy.value = true;
  error.value = "";
  status.value = "";
  const result = await testConnection(url.value, token.value);
  if (result.ok) status.value = result.message;
  else error.value = result.message;
  busy.value = false;
}

async function save(): Promise<void> {
  busy.value = true;
  error.value = "";
  status.value = "";
  try {
    const checked = await testConnection(url.value, token.value);
    if (!checked.ok) {
      error.value = checked.message;
      return;
    }
    status.value = checked.message;
    const chosen = editing.value;
    const profile =
      chosen === "new" || chosen === null
        ? await addServer({ name: name.value, url: url.value, token: token.value })
        : await updateServer(chosen.id, { name: name.value, url: url.value, token: token.value });
    await connectServer(profile);
  } catch (failure) {
    error.value = failure instanceof Error ? t(failure.message) : String(failure);
  } finally {
    busy.value = false;
  }
}

async function connect(profile: ServerProfile): Promise<void> {
  connecting.value = profile.id;
  error.value = "";
  try {
    await connectServer(profile);
  } catch (failure) {
    error.value = failure instanceof Error ? t(failure.message) : String(failure);
    connecting.value = "";
  }
}

async function forget(profile: ServerProfile): Promise<void> {
  if (!confirm(t("Remove {name} from this device?", { name: profile.name }))) return;
  try {
    const wasActive = servers.active?.id === profile.id;
    await removeServer(profile.id);
    if (wasActive) await disconnectServer();
  } catch (failure) {
    error.value = failure instanceof Error ? t(failure.message) : String(failure);
  }
}

const insecure = (): boolean => url.value.trim().toLowerCase().startsWith("http://");
</script>

<template>
  <div class="gate">
    <div class="gate-inner">
      <header class="gate-head">
        <img src="/static/logo.svg" alt="" width="56" height="56" />
        <div>
          <h1>ZettCode</h1>
          <p>{{ t("Choose the gateway this device talks to") }}</p>
        </div>
      </header>

      <p v-if="servers.problem && !editing" class="errcard" role="alert">{{ t(servers.problem) }}</p>
      <p v-if="error && !editing" class="errcard" role="alert">{{ error }}</p>

      <form v-if="editing" class="card gate-form" @submit.prevent="save">
        <div class="card-title">{{ editing === "new" ? t("New server") : t("Edit server") }}</div>
        <label class="gate-field">
          <span>{{ t("Address") }}</span>
          <input v-model="url" type="text" inputmode="url" autocapitalize="off" spellcheck="false" placeholder="http://127.0.0.1:8765" required />
        </label>
        <label class="gate-field">
          <span>{{ t("Token") }}</span>
          <input v-model="token" type="password" autocomplete="off" autocapitalize="off" spellcheck="false" :placeholder="t('The token the gateway printed')" required />
        </label>
        <label class="gate-field">
          <span>{{ t("Name") }}</span>
          <input v-model="name" type="text" autocapitalize="words" :placeholder="t('Optional')" />
        </label>
        <p v-if="insecure()" class="card-hint warn">
          {{ t("Plain HTTP sends the token in the clear. Use HTTPS beyond the machine's own network.") }}
        </p>
        <p v-if="error" class="card-hint bad" role="alert">{{ error }}</p>
        <p v-else-if="status" class="card-hint">{{ status }}</p>
        <div class="actions">
          <button class="btn" type="submit" :disabled="busy">{{ t("Save and connect") }}</button>
          <button class="btn ghost" type="button" :disabled="busy" @click="test">{{ t("Test") }}</button>
          <button class="btn ghost" type="button" :disabled="busy" @click="cancel">{{ t("Cancel") }}</button>
        </div>
      </form>

      <template v-else>
        <div v-if="servers.list.length" class="card">
          <div v-for="profile in servers.list" :key="profile.id" class="gate-server">
            <button
              class="gate-pick"
              type="button"
              :disabled="connecting !== ''"
              @click="connect(profile)"
            >
              <span class="gate-plug"><Icon name="plug" /></span>
              <span class="gate-text">
                <b>{{ profile.name }}</b>
                <small>{{ profile.url }}</small>
              </span>
              <span v-if="servers.active?.id === profile.id" class="gate-active"><Icon name="check" size="sm" /></span>
              <span v-else-if="connecting === profile.id" class="spin" />
            </button>
            <button class="iconbtn" type="button" :aria-label="t('Edit {name}', { name: profile.name })" @click="change(profile)">
              <Icon name="settings" size="sm" />
            </button>
            <button class="iconbtn danger" type="button" :aria-label="t('Remove {name}', { name: profile.name })" @click="forget(profile)">
              <Icon name="trash" size="sm" />
            </button>
          </div>
        </div>
        <button class="btn block" type="button" @click="add"><Icon name="plus" size="sm" />{{ t("Add a server") }}</button>
        <p class="gate-hint">
          {{ t("The token stays on this device and is never written to the page. Every server keeps its own token.") }}
        </p>
      </template>
    </div>
  </div>
</template>

<style>
.gate { height: 100%; overflow-y: auto; background: var(--surface-2); overscroll-behavior: contain; }
.gate-inner {
  width: 100%; max-width: 34rem; margin: 0 auto; padding: calc(24px + var(--safe-top)) 16px calc(28px + var(--safe-bottom));
  display: flex; flex-direction: column; gap: 12px;
}
.gate-head { display: flex; align-items: center; gap: 14px; padding: 8px 4px 4px; }
.gate-head img { object-fit: contain; flex: none; }
.gate-head h1 { margin: 0; font-size: 1.45rem; line-height: 1.15; }
.gate-head p { margin: 4px 0 0; color: var(--muted); font-size: 0.92rem; line-height: 1.35; }
.gate-form { margin: 0; padding-bottom: 4px; }
.gate-field { display: flex; flex-direction: column; gap: 4px; padding: 9px 16px; }
.gate-field + .gate-field { border-top: 1px solid var(--divider); }
.gate-field span { color: var(--muted); font-size: 0.78rem; font-weight: 600; letter-spacing: 0.02em; text-transform: uppercase; }
.gate-field input { width: 100%; min-width: 0; border: 0; outline: 0; background: none; color: var(--text); font-size: 1rem; padding: 4px 0; }
.gate-server { display: flex; align-items: center; gap: 2px; padding-right: 4px; }
.gate-server + .gate-server { border-top: 1px solid var(--divider); }
.gate-pick {
  display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; min-height: 64px; padding: 8px 12px 8px 16px;
  text-align: left; color: inherit; transition: background 0.12s;
}
.gate-pick:hover { background: var(--hover); }
.gate-plug { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 11px; background: var(--accent-soft); color: var(--accent); flex: none; }
.gate-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.gate-text b { font-weight: 600; font-size: 1rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gate-text small { color: var(--muted); font-family: var(--mono); font-size: 0.76rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gate-active { color: var(--ok); flex: none; }
.gate-hint { margin: 0; padding: 4px 6px; color: var(--muted); font-size: 0.8rem; line-height: 1.4; text-align: center; }
.gate .iconbtn.danger { color: var(--bad); }
.gate .iconbtn.danger:hover { background: var(--bad-soft); }
@media (max-width: 719px) {
  .gate-inner { padding-left: 10px; padding-right: 10px; }
}
</style>
