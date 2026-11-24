<template>
  <div v-if="hasRichContent" class="space-y-3">
    <div v-if="imageUrls.length > 0" class="debug-media-grid">
      <img v-for="url in imageUrls" :key="url" :src="url" alt="generated" class="debug-generated-image" />
    </div>
    <video v-if="videoUrl" :src="videoUrl" controls class="debug-generated-video" />
    <DebugValue v-if="summary || context" :value="summary || context" prefer-output-text />
    <div v-if="citations.length > 0" class="debug-citation-list">
      <a-tag v-for="(citation, index) in citations" :key="`${String(citation)}-${index}`">
        {{ String(citation) }}
      </a-tag>
    </div>
    <DebugValue :value="record" :prefer-output-text="preferOutputText" />
  </div>
  <DebugValue v-else :value="value" :prefer-output-text="preferOutputText" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import DebugValue from './DebugValue.vue'
import {
  collectImageUrls,
  collectVideoUrls,
  isRecord,
  normalizeValue,
} from '../utils/debugOutput'

const props = withDefaults(
  defineProps<{ value: unknown; preferOutputText?: boolean; renderMedia?: boolean }>(),
  { preferOutputText: false, renderMedia: false }
)

const record = computed(() => {
  const normalized = normalizeValue(props.value)
  return isRecord(normalized) && isRecord(normalized.output) ? normalized.output : normalized
})

const imageUrls = computed(() => (props.renderMedia && isRecord(record.value) ? collectImageUrls(record.value) : []))
const videoUrl = computed(() => (props.renderMedia ? collectVideoUrls(record.value)[0] || null : null))
const summary = computed(() => (isRecord(record.value) && typeof record.value.summary === 'string' ? record.value.summary : null))
const context = computed(() => (isRecord(record.value) && typeof record.value.context === 'string' ? record.value.context : null))
const citations = computed(() => (isRecord(record.value) && Array.isArray(record.value.citations) ? record.value.citations : []))

const hasRichContent = computed(() =>
  isRecord(record.value) &&
  (imageUrls.value.length > 0 ||
    Boolean(videoUrl.value) ||
    Boolean(summary.value) ||
    Boolean(context.value) ||
    citations.value.length > 0)
)
</script>
