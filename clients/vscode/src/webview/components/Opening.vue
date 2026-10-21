<script setup lang="ts">
import Logo from "./Logo.vue";
import Shimmer from "./Shimmer.vue";

defineProps<{ text: string }>();
</script>

<template>
  <!-- Over the conversation, not instead of it: it comes back as it was if the load fails, and its scroll is not lost. -->
  <div id="opening" class="opening" role="status" aria-live="polite">
    <div class="opening-mark"><Logo :size="38" /></div>
    <Shimmer :text="text" />
  </div>
</template>

<style>
.opening {
  position: absolute;
  inset: 0;
  z-index: 30;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  background: color-mix(in srgb, var(--bg) 90%, transparent);
  backdrop-filter: blur(2px);
  animation: opening-in 0.18s ease-out both;
}

@keyframes opening-in {
  from {
    opacity: 0;
  }
}

/* The mark breathes as it does on the splash, which is `breathe` in Splash.vue: one motion for "starting". */
.opening-mark {
  animation: breathe 1.8s ease-in-out infinite;
}

@media (prefers-reduced-motion: reduce) {
  .opening-mark {
    animation: none;
  }
}
</style>
