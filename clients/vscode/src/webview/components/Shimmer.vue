<script setup lang="ts">
/**
 * Words that say work is going on: a band of light crosses them and they rest, as in the terminal's waiting row. Nothing
 * spins and the words carry no trailing ellipsis; the motion is what says it is not finished. The light, its width and
 * its pace are the `.shimmer` rule in media/base.css, so every place that waits looks the same.
 */
defineProps<{ text?: string }>();
</script>

<template>
  <span class="shimmer"><slot>{{ text }}</slot></span>
</template>
