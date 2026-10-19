<script setup lang="ts">
import Logo from "./Logo.vue";
</script>

<template>
  <div id="splash" class="splash" role="status" aria-label="Starting ZettCode">
    <div class="splash-mark"><Logo :size="46" /></div>
  </div>
</template>

<style>
.splash {
  flex: 1;
  display: grid;
  place-items: center;
  animation: fade 0.25s ease-out both;
}

.splash-mark {
  animation: breathe 1.8s ease-in-out infinite;
}

@keyframes breathe {
  0%,
  100% {
    opacity: 0.45;
    transform: scale(0.97);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}
</style>
