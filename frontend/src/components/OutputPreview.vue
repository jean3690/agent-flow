<template>
  <div class="preview">
    <div v-for="(media, index) in visibleMedia" :key="index" class="preview__media">
      <img v-if="media.kind === 'image'" :src="media.url" alt="output" class="preview__image" />
      <video v-else-if="media.kind === 'video'" :src="media.url" controls class="preview__video" />
      <audio v-else :src="media.url" controls class="preview__audio" />
      <span class="preview__hint mono">{{ media.source }}</span>
    </div>
    <span v-if="error" class="af-muted">{{ error }}</span>
    <pre v-if="text" class="preview__text mono">{{ text }}</pre>
    <div v-if="!text && !mediaList.length" class="preview__empty">暂无输出</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useProtectedMedia } from '../composables/useProtectedMedia'

type MediaKind = 'image' | 'audio' | 'video'
interface MediaItem {
  url: string
  kind: MediaKind
}

const props = defineProps<{ value: unknown }>()

const parsed = computed(() => {
  const raw = props.value
  if (typeof raw !== 'string') return raw
  const trimmed = raw.trim()
  const looksJson =
    (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
    (trimmed.startsWith('[') && trimmed.endsWith(']'))
  if (!looksJson) return raw
  try {
    return JSON.parse(trimmed)
  } catch {
    return raw
  }
})

const text = computed(() => {
  const value = parsed.value
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
})

const mediaList = computed(() => {
  const found = collect(parsed.value)
  const seen = new Set<string>()
  return found.filter((item) => (seen.has(item.url) ? false : seen.add(item.url)))
})
const { urls, error } = useProtectedMedia(computed(() => mediaList.value.map(item => item.url)))
const visibleMedia = computed(() => mediaList.value.filter(item => urls.value[item.url])
  .map(item => ({ ...item, source: item.url, url: urls.value[item.url] })))

function collect(value: unknown, depth = 0): MediaItem[] {
  if (depth > 3 || value === null || value === undefined) return []
  if (typeof value === 'string') {
    const media = toMedia(value)
    return media ? [media] : []
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => collect(item, depth + 1)).slice(0, 6)
  }
  if (typeof value === 'object') {
    return Object.values(value as Record<string, unknown>)
      .flatMap((item) => collect(item, depth + 1))
      .slice(0, 6)
  }
  return []
}

function toMedia(value: string): MediaItem | null {
  const raw = value.trim()
  if (!raw || /\s/.test(raw)) return null

  if (/^data:image\//i.test(raw)) return { url: raw, kind: 'image' }
  if (/^data:audio\//i.test(raw)) return { url: raw, kind: 'audio' }
  if (/^data:video\//i.test(raw)) return { url: raw, kind: 'video' }

  if (!/^(https?:\/\/|\/|\.\/)/i.test(raw)) return null
  const path = raw.replace(/^https?:\/\/[^/]+/i, '')

  if (/\.(png|jpe?g|gif|webp|bmp)(\?|#|$)/i.test(path)) {
    return { url: resolve(raw), kind: 'image' }
  }
  if (/\.(mp3|wav|ogg|m4a|aac|flac)(\?|#|$)/i.test(path)) {
    return { url: resolve(raw), kind: 'audio' }
  }
  if (/\.(mp4|webm|mov|m4v)(\?|#|$)/i.test(path)) {
    return { url: resolve(raw), kind: 'video' }
  }
  return null
}

function resolve(url: string) {
  return url
}
</script>

<style scoped>
.preview {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}

.preview__media {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border-radius: 8px;
  background: #11141c;
  border: 1px solid #232833;
}

.preview__image,
.preview__video {
  max-width: 100%;
  max-height: 320px;
  border-radius: 6px;
  object-fit: contain;
  align-self: flex-start;
}

.preview__audio {
  width: 100%;
  height: 34px;
}

.preview__hint {
  font-size: 11px;
  color: #6b7387;
  word-break: break-all;
}

.preview__text {
  margin: 0;
  padding: 12px;
  border-radius: 8px;
  background: #11141c;
  border: 1px solid #232833;
  font-size: 12px;
  line-height: 1.65;
  max-height: 360px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.preview__empty {
  padding: 24px 0;
  text-align: center;
  font-size: 12px;
  color: #4b5266;
}
</style>
