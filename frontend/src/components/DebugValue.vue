<template>
  <div v-if="friendlyText !== null" class="debug-markdown-output" v-html="renderedMarkdown" />
  <pre v-else class="debug-json-block">{{ JSON.stringify(value, null, 2) }}</pre>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { getFriendlyOutputText } from '../utils/debugOutput'
import { renderMarkdown } from '../utils/markdown'

const props = withDefaults(
  defineProps<{ value: unknown; preferOutputText?: boolean }>(),
  { preferOutputText: false }
)

const friendlyText = computed(() => (props.preferOutputText ? getFriendlyOutputText(props.value) : null))
const renderedMarkdown = computed(() => renderMarkdown(friendlyText.value || ''))
</script>
