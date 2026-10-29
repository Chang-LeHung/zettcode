<script setup lang="ts">
import { ref } from "vue";

import type { ApprovalBlock } from "../../core/state.js";
import { post } from "../store.js";
import Icon from "./Icon.vue";

const props = defineProps<{ block: ApprovalBlock }>();

const remember = ref(false);
const sent = ref(false);

function answer(approve: boolean): void {
  sent.value = true;
  post({ type: "approve", callId: props.block.callId, approve, remember: remember.value });
}
</script>

<template>
  <div class="approval step" :class="{ pending: block.approved === null, approved: block.approved === true, denied: block.approved === false }">
    <span class="step-dot" :class="block.approved === null ? 'amber pulse' : block.approved ? 'green' : 'red'" />
    <div class="approval-card">
      <div class="approval-head">
        <Icon :name="block.approved === null ? 'shield' : block.approved ? 'check' : 'x'" :size="13" />
        <strong>Bash</strong>
        <span class="approval-state">{{
          block.approved === null ? "wants to run" : block.approved ? "approved" : "denied"
        }}</span>
      </div>
      <pre class="approval-command"><span class="approval-prompt">$</span> <code>{{ block.command }}</code></pre>
      <div v-if="block.workDir" class="approval-where">in <code>{{ block.workDir }}</code></div>
      <div v-if="block.approved === null" class="approval-actions">
        <button class="btn solid small" type="button" :disabled="sent" @click="answer(true)">Approve</button>
        <button class="btn small danger" type="button" :disabled="sent" @click="answer(false)">Deny</button>
        <label class="approval-remember"><input v-model="remember" type="checkbox" :disabled="sent" /> Remember</label>
      </div>
    </div>
  </div>
</template>

<style>
.approval-card {
  margin: 3px 0 6px 6px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-m);
  background: var(--wash);
}

.approval.pending .approval-card {
  border-color: color-mix(in srgb, var(--amber) 45%, transparent);
  background: color-mix(in srgb, var(--amber) 7%, transparent);
}

.approval-head {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: var(--small);
}

.approval.pending .approval-head .icon {
  color: var(--amber);
}

.approval.approved .approval-head .icon {
  color: var(--green);
}

.approval.denied .approval-head .icon {
  color: var(--red);
}

.approval-state {
  color: var(--muted);
}

.approval-command {
  margin: 8px 0 0;
  padding: 8px 10px;
  max-height: 180px;
  overflow: auto;
  border-radius: var(--r-s);
  background: color-mix(in srgb, var(--bg) 70%, transparent);
  font-family: var(--mono);
  font-size: var(--code-size);
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.approval-prompt {
  color: var(--teal);
  font-weight: 700;
  user-select: none;
}

.approval-where {
  margin-top: 6px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: var(--small);
  overflow-wrap: anywhere;
}

.approval-where code {
  color: var(--text);
}

.approval-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}

.approval-remember {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--muted);
  font-size: var(--tiny);
}
</style>
