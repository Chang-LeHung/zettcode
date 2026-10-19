<script setup lang="ts">
import logo from "../../../media/logo.svg";

withDefaults(defineProps<{ size?: number }>(), { size: 18 });
</script>

<template>
  <!-- The artwork is cropped to the mascot, so it fills the slot it is given the way other extensions' marks do. -->
  <img class="logo" :src="logo" :width="size" :height="size" alt="" draggable="false" />
</template>

<style>
.logo {
  flex-shrink: 0;
  object-fit: contain;
  user-select: none;
}
</style>
