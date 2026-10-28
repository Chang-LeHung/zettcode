<template>
  <div class="msg in" aria-hidden="true">
    <div class="bubble typing"><i /><i /><i /></div>
  </div>
</template>

<style>
.bubble.typing { display: inline-flex; gap: 4px; padding: 12px 14px; }
.bubble.typing i { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); animation: blink 1.2s infinite ease-in-out; }
.bubble.typing i:nth-child(2) { animation-delay: 0.18s; }
.bubble.typing i:nth-child(3) { animation-delay: 0.36s; }
</style>
