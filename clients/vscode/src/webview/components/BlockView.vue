<script setup lang="ts">
import type { Block, Turn } from "../../core/state.js";
import ApprovalStep from "./ApprovalStep.vue";
import Markdown from "./Markdown.vue";
import NoteBlock from "./NoteBlock.vue";
import QuestionStep from "./QuestionStep.vue";
import ReasoningStep from "./ReasoningStep.vue";
import ToolStep from "./ToolStep.vue";

defineProps<{ turn: Turn; block: Block; index: number }>();
</script>

<template>
  <Markdown
    v-if="block.kind === 'text'"
    class="answer"
    :text="block.text"
    :live="turn.status === 'running' && index === turn.blocks.length - 1"
  />
  <ReasoningStep v-else-if="block.kind === 'reasoning'" :turn="turn" :block="block" :index="index" />
  <ToolStep v-else-if="block.kind === 'tool'" :tool="block.tool" :turn-id="turn.id" />
  <ApprovalStep v-else-if="block.kind === 'approval'" :block="block" />
  <QuestionStep v-else-if="block.kind === 'question'" :block="block" :turn="turn" />
  <NoteBlock v-else :block="block" :turn="turn" :index="index" />
</template>
