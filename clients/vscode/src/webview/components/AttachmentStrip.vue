<script setup lang="ts">
import { state } from "../store.js";
import Icon from "./Icon.vue";
</script>

<template>
  <div v-if="state.attachments.length" id="attachments" class="attachments">
    <div v-for="(image, index) in state.attachments" :key="index" class="attachment">
      <img :src="`data:${image.mediaType};base64,${image.data}`" alt="" />
      <span>{{ image.name }}</span>
      <button class="icon-btn" type="button" title="Remove" aria-label="Remove" @click="state.attachments.splice(index, 1)">
        <Icon name="x" :size="11" />
      </button>
    </div>
  </div>
</template>

<style>
.attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
}

.attachment {
  display: flex;
  align-items: center;
  gap: 6px;
  max-width: 190px;
  padding: 3px 3px 3px 4px;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--wash);
  font-size: var(--tiny);
}

.attachment img {
  width: 22px;
  height: 22px;
  border-radius: 4px;
  object-fit: cover;
}

.attachment span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment .icon-btn {
  width: 20px;
  height: 20px;
}
</style>
