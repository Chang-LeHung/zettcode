<script setup lang="ts">
import { computed, ref } from "vue";

import type { QuestionBlock, Turn } from "../../core/state.js";
import { post, toast } from "../store.js";

const props = defineProps<{ block: QuestionBlock; turn: Turn }>();

const selected = ref<string[]>([]);
const typed = ref("");
const live = computed(() => props.turn.status === "running");

const verdict = computed(() => {
  if (props.block.answer === null) {
    return "Declined";
  }
  return props.block.answer ? `Answered: ${props.block.answer}` : "Answered";
});

function pick(option: string): void {
  if (!props.block.allowMultiple) {
    post({ type: "answer", callId: props.block.callId, answer: option });
    return;
  }
  selected.value = selected.value.includes(option)
    ? selected.value.filter((item) => item !== option)
    : [...selected.value, option];
}

function submit(): void {
  const answer = selected.value.length ? selected.value.join(", ") : typed.value.trim();
  if (!answer) {
    toast("Choose an option or type an answer.", "warn");
    return;
  }
  post({ type: "answer", callId: props.block.callId, answer });
}
</script>

<template>
  <div class="question step" :class="{ pending: !block.answered }">
    <span class="step-dot" :class="block.answered ? 'blue' : 'blue pulse'" />
    <div class="question-card">
      <div class="question-head">{{ block.answered ? verdict : "ZettCode asks" }}</div>
      <div class="question-text">{{ block.question }}</div>
      <template v-if="!block.answered">
        <div v-if="block.options.length" class="choices">
          <button
            v-for="option in block.options"
            :key="option"
            type="button"
            class="choice"
            :class="{ selected: selected.includes(option) }"
            :disabled="!live"
            @click="pick(option)"
          >
            <span v-if="block.allowMultiple" class="checkbox" />{{ option }}
          </button>
        </div>
        <div class="answer-row">
          <input
            v-model="typed"
            class="answer-input"
            placeholder="Type an answer"
            :disabled="!live"
            @keydown.enter.prevent="submit"
          />
          <button class="btn solid small" type="button" :disabled="!live" @click="submit">Answer</button>
          <button
            class="btn ghost small"
            type="button"
            :disabled="!live"
            @click="post({ type: 'answer', callId: block.callId, answer: null })"
          >
            Decline
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<style>
.question-card {
  margin: 3px 0 6px 6px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-m);
  background: var(--wash);
}

.question.pending .question-card {
  border-color: color-mix(in srgb, var(--blue) 40%, transparent);
  background: color-mix(in srgb, var(--blue) 6%, transparent);
}

.question-head {
  color: var(--muted);
  font-size: var(--tiny);
  font-weight: 600;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.question-text {
  margin-top: 4px;
  max-height: 240px;
  overflow-y: auto;
  font-size: 13.5px;
  white-space: pre-wrap;
}

.choices {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 10px;
}

.choice {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 11px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-s);
  background: transparent;
  text-align: left;
  font-size: 13px;
  transition: background 0.12s, border-color 0.12s;
}

.choice:hover:not(:disabled) {
  background: var(--wash-2);
}

.choice.selected {
  border-color: var(--blue);
  background: color-mix(in srgb, var(--blue) 12%, transparent);
}

.choice .checkbox {
  width: 12px;
  height: 12px;
  border: 1.5px solid var(--faint);
  border-radius: 3px;
}

.choice.selected .checkbox {
  background: var(--blue);
  border-color: var(--blue);
}

.answer-row {
  display: flex;
  gap: 6px;
  margin-top: 10px;
}

.answer-input {
  flex: 1;
  min-width: 0;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-s);
  background: var(--input);
  font-size: 13px;
  outline: none;
}

.answer-input:focus {
  border-color: color-mix(in srgb, var(--blue) 65%, transparent);
}
</style>
