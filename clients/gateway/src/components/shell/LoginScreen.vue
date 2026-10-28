<script setup lang="ts">
import { ref } from "vue";
import { ApiError } from "../../api/http";
import { t } from "../../i18n";
import { signIn } from "../../stores/auth";

const token = ref(new URLSearchParams(location.hash.replace(/^#/, "")).get("token") ?? "");
const error = ref("");
const busy = ref(false);

// A token in the address is for one sign-in: take it out of the bar and the history at once.
if (token.value) history.replaceState(null, "", location.pathname);

async function submit(): Promise<void> {
  busy.value = true;
  error.value = "";
  try {
    await signIn(token.value);
  } catch (failure) {
    error.value = failure instanceof ApiError ? failure.message : String(failure);
  } finally {
    busy.value = false;
  }
}
if (token.value) void submit();
</script>

<template>
  <div class="login">
    <form @submit.prevent="submit">
      <img src="/static/logo.svg" alt="" width="72" height="72" />
      <h1>ZettCode Gateway</h1>
      <p>{{ t("Type the token the gateway printed when it started.") }}</p>
      <input v-model="token" type="password" autocomplete="current-password" autocapitalize="off" spellcheck="false" :placeholder="t('Token')" :aria-label="t('Token')" />
      <div class="err" role="alert">{{ error }}</div>
      <button class="btn block" type="submit" :disabled="busy || !token.trim()"><span v-if="busy" class="spin" />{{ t("Sign in") }}</button>
    </form>
  </div>
</template>

<style>
.login { height: 100%; display: grid; place-items: center; padding: 20px; background: var(--surface-2); }
.login form { width: 100%; max-width: 22rem; padding: 28px 22px; border-radius: 20px; background: var(--surface); box-shadow: 0 8px 40px rgba(0, 0, 0, 0.2); display: flex; flex-direction: column; gap: 14px; text-align: center; }
.login img { margin: 0 auto; object-fit: contain; }
.login h1 { margin: 0; font-size: 1.35rem; }
.login p { margin: 0; color: var(--muted); font-size: 0.92rem; line-height: 1.4; }
.login input { height: 48px; padding: 0 14px; border-radius: 12px; border: 1px solid var(--divider); background: var(--surface-2); color: var(--text); font-size: 1rem; text-align: center; }
.login .err { color: var(--bad); font-size: 0.9rem; min-height: 1.2em; }
</style>
