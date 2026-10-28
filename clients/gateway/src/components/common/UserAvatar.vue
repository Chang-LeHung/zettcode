<script setup lang="ts">
import { prefs } from "../../stores/prefs";
import Icon from "./Icon.vue";

defineProps<{ size?: "sm" | "xl" }>();
</script>

<template>
  <div class="avatar user-avatar" :class="size" aria-hidden="true">
    <img v-if="prefs.avatar" :src="prefs.avatar" alt="" />
    <Icon v-else name="user" />
  </div>
</template>

<style>
.user-avatar { background: linear-gradient(160deg, #7cc4fa, #3390ec); overflow: hidden; }
.user-avatar img { width: 100%; height: 100%; object-fit: cover; }
.user-avatar svg { width: 58%; height: 58%; stroke-width: 1.7; }
</style>
