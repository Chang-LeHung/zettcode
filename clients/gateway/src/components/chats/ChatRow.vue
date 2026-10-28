<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { folderName, listTime } from "../../lib/format";
import { href } from "../../stores/route";
import type { Thread } from "../../types";
import Avatar from "../common/Avatar.vue";
import Icon from "../common/Icon.vue";

const props = defineProps<{ thread: Thread; current: boolean }>();

const typing = computed(() => props.thread.status === "working");
const kindIcon = computed(() => (props.thread.kind === "daemon" ? "bot" : props.thread.kind === "external" ? "plug" : "term"));
const mine = computed(() => props.thread.preview.startsWith("You: "));
/** The preview is one line of plain text: markdown marks and fences are noise in a list. */
const plainLine = (text: string): string =>
  text.replace(/```[\w+#.-]*/g, " ").replace(/[`*_#>]+/g, "").replace(/\s+/g, " ").trim();
const line = computed(() => {
  if (props.thread.status === "dead") return t("stopped");
  if (props.thread.preview) return plainLine(mine.value ? props.thread.preview.slice(5) : props.thread.preview);
  return folderName(props.thread.workspace) || props.thread.model || "";
});
</script>

<template>
  <a class="row" :href="href('chats', thread.id)" :aria-current="current ? 'true' : undefined">
    <Avatar :thread="thread" />
    <div class="row-body">
      <div class="row-top">
        <Icon class="row-kind" :name="kindIcon" size="xs" />
        <span class="row-name">{{ thread.name }}</span>
        <span class="row-time">{{ listTime(thread.updated_at) }}</span>
      </div>
      <div class="row-bottom">
        <span class="row-sub">
          <span v-if="typing" class="row-typing">{{ t("typing…") }}</span>
          <template v-else>
            <span v-if="mine" class="row-you">{{ t("You") }}: </span>{{ line }}
          </template>
        </span>
        <span v-if="thread.unread" class="badge">{{ thread.unread > 99 ? "99+" : thread.unread }}</span>
      </div>
    </div>
  </a>
</template>

<style>
.row {
  position: relative; display: flex; align-items: center; gap: 12px; width: 100%;
  padding: 8px 14px; min-height: var(--row); text-align: left; color: inherit; text-decoration: none !important;
  transition: background 0.12s;
}
.row:hover { background: var(--hover); }
.row[aria-current="true"] { background: var(--accent); color: var(--accent-text); }
.row[aria-current="true"] .row-sub, .row[aria-current="true"] .row-time, .row[aria-current="true"] .row-kind { color: inherit; opacity: 0.85; }
.row[aria-current="true"] .badge { background: var(--accent-text); color: var(--accent); }
.row[aria-current="true"] .avatar .presence { border-color: var(--accent); }
.row-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.row-top, .row-bottom { display: flex; align-items: center; gap: 6px; min-width: 0; }
.row-kind { color: var(--muted); }
.row-name { flex: 1; min-width: 0; font-weight: 600; font-size: 1.03rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row-time { font-size: 0.78rem; color: var(--muted); flex: none; }
.row-sub { flex: 1; min-width: 0; color: var(--muted); font-size: 0.92rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row-you, .row-typing { color: var(--accent); }
.row[aria-current="true"] .row-you, .row[aria-current="true"] .row-typing { color: inherit; }
</style>
