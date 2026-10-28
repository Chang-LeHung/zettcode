<script setup lang="ts">
import { onMounted, ref } from "vue";
import { gateway } from "../../api/gateway";
import { ApiError } from "../../api/http";
import { t } from "../../i18n";
import type { DirectoryListing } from "../../types";
import Icon from "../common/Icon.vue";

const props = defineProps<{ start: string }>();
const emit = defineEmits<{ close: [path?: string] }>();

const listing = ref<DirectoryListing | null>(null);
const error = ref("");
const loading = ref(false);

async function open(path: string): Promise<void> {
  loading.value = true;
  try {
    listing.value = await gateway.directories(path);
    error.value = "";
  } catch (failure) {
    error.value = failure instanceof ApiError ? failure.message : String(failure);
    if (path) await open("");
  } finally {
    loading.value = false;
  }
}

onMounted(() => void open(props.start));
</script>

<template>
  <div v-if="listing">
    <div class="picker-path">{{ listing.path || t("Folders agents may work in") }}</div>
    <p v-if="error" class="card-hint bad">{{ error }}</p>
    <button v-if="listing.parent !== null" class="menu-item" @click="open(listing.parent)">
      <Icon name="back" /><span>{{ t("Up") }}</span>
    </button>
    <button v-for="dir in listing.dirs" :key="dir.path" class="menu-item" @click="open(dir.path)">
      <Icon name="folder" /><span class="picker-name">{{ dir.name }}</span><Icon class="chev" name="chevron" size="sm" />
    </button>
    <p v-if="!listing.dirs.length" class="card-hint">{{ t("No folders here.") }}</p>
    <div v-if="listing.path" class="actions">
      <button class="btn block" @click="emit('close', listing.path)">{{ t("Use this folder") }}</button>
    </div>
  </div>
  <div v-else class="empty"><span v-if="loading" class="spin" /><template v-else>{{ error }}</template></div>
</template>

<style>
.picker-path { padding: 4px 18px 8px; font-family: var(--mono); font-size: 0.8rem; color: var(--muted); overflow-wrap: anywhere; }
.picker-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.menu-item .chev { color: var(--muted); }
</style>
