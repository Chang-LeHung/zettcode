<script setup lang="ts">
import { computed } from "vue";
import { hueOf, initialsOf } from "../../lib/avatar";
import type { Thread } from "../../types";

const props = defineProps<{ thread: Pick<Thread, "id" | "name" | "kind" | "status">; size?: "sm" | "xs" | "xl" }>();
const hue = computed(() => `av${hueOf(props.thread.id)}`);
const presence = computed(() => (["idle", "working", "dead"].includes(props.thread.status) ? props.thread.status : ""));
</script>

<template>
  <div class="avatar" :class="[hue, size]" aria-hidden="true">
    {{ initialsOf(thread.name) }}
    <span v-if="thread.kind !== 'external'" class="presence" :class="presence" />
  </div>
</template>

<style>
.avatar {
  position: relative; flex: none; display: grid; place-items: center;
  width: 54px; height: 54px; border-radius: 50%;
  color: #fff; font-weight: 650; font-size: 1.2rem; letter-spacing: 0.02em;
  background: linear-gradient(160deg, var(--a), var(--b));
  user-select: none;
}
.avatar.sm { width: 40px; height: 40px; font-size: 0.98rem; }
.avatar.xs { width: 30px; height: 30px; font-size: 0.8rem; }
.avatar.xl { width: 84px; height: 84px; font-size: 1.9rem; }
.avatar .presence {
  position: absolute; right: -1px; bottom: -1px; width: 15px; height: 15px; border-radius: 50%;
  border: 3px solid var(--surface); background: var(--muted);
}
.avatar.sm .presence { width: 13px; height: 13px; border-width: 2.5px; }
.avatar.xs .presence { display: none; }
.avatar .presence.idle { background: var(--ok); }
.avatar .presence.working { background: var(--warn); animation: pulse 1.4s ease-in-out infinite; }
.avatar .presence.dead { background: var(--bad); }
.av0 { --a: #ff885e; --b: #ff516a; }
.av1 { --a: #ffcd6a; --b: #ffa85c; }
.av2 { --a: #82b1ff; --b: #665fff; }
.av3 { --a: #a0de7e; --b: #54cb68; }
.av4 { --a: #53edd6; --b: #28c9b7; }
.av5 { --a: #72d5fd; --b: #2a9ef1; }
.av6 { --a: #e0a2f3; --b: #d669ed; }
.av7 { --a: #f7a3b6; --b: #ec5f87; }
</style>
