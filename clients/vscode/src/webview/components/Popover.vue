<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string;
    /** Which edge of the composer the card hangs from. */
    align?: "left" | "right";
    /** Pixels from the left edge, so the card sits over the control that opened it. */
    offset?: number;
    width?: number;
    /** The tallest the card grows before it scrolls, in pixels; a form that is longer than a menu asks for more. */
    tall?: number;
  }>(),
  { title: "", align: "left", offset: 0, width: 320, tall: 420 },
);
</script>

<template>
  <div
    class="dropdown"
    :class="align"
    :style="{ '--offset': `${offset}px`, '--width': `${width}px`, '--tall': `${tall}px` }"
    role="dialog"
    tabindex="-1"
    :aria-label="title || undefined"
  >
    <div v-if="title" class="dropdown-title">{{ title }}</div>
    <slot />
  </div>
</template>

<style>
.dropdown {
  position: absolute;
  bottom: calc(100% + 8px);
  left: var(--offset);
  z-index: 40;
  width: min(var(--width), 100%);
  max-height: min(var(--tall, 420px), calc(100vh - 150px));
  overflow-y: auto;
  padding: 6px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-l);
  background: var(--raised);
  box-shadow: var(--shadow);
  animation: rise 0.14s ease-out;
  outline: none;
}

.dropdown.right {
  left: auto;
  right: 0;
}

.dropdown-title {
  padding: 5px 9px 4px;
  color: var(--faint);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.option-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.option {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 7px 9px;
  border: 0;
  border-radius: var(--r-s);
  background: none;
  text-align: left;
}

.option:hover {
  background: var(--wash-2);
}

.option.current {
  background: var(--wash);
}

.option > .icon:first-child {
  color: var(--muted);
}

.option-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  line-height: 1.35;
}

.option-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13.5px;
  font-weight: 550;
}

.option-desc {
  color: var(--muted);
  font-size: var(--tiny);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.option .tick {
  color: var(--green);
}

.dropdown-rule {
  height: 1px;
  margin: 5px 4px;
  background: var(--line);
}
</style>
