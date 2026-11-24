<template>
  <a-card title="🎵 音频播放器" size="small" class="mb-4">
    <audio ref="audioRef" :src="audioUrl" />

    <a-space direction="vertical" class="w-full">
      <div class="flex items-center justify-center gap-4">
        <a-button type="primary" shape="circle" size="large" @click="togglePlayPause">
          <PauseCircleOutlined v-if="isPlaying" />
          <PlayCircleOutlined v-else />
        </a-button>
      </div>

      <div class="px-2">
        <a-slider
          :value="currentTime"
          :max="duration || 100"
          :tooltip="{ formatter: (value: number) => formatTime(value || 0) }"
          @change="handleSliderChange"
        />
        <div class="flex justify-between text-xs text-gray-500">
          <span>{{ formatTime(currentTime) }}</span>
          <span>{{ formatTime(duration) }}</span>
        </div>
      </div>

      <div v-if="fileName" class="text-xs text-gray-600 text-center">
        文件: {{ fileName }}
      </div>
    </a-space>
  </a-card>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { PauseCircleOutlined, PlayCircleOutlined } from '@ant-design/icons-vue'

defineProps<{
  audioUrl: string
  fileName?: string
}>()

const audioRef = ref<HTMLAudioElement | null>(null)
const isPlaying = ref(false)
const currentTime = ref(0)
const duration = ref(0)

const formatTime = (seconds: number) => {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
}

const togglePlayPause = async () => {
  const audio = audioRef.value
  if (!audio) return

  try {
    if (isPlaying.value) {
      audio.pause()
      isPlaying.value = false
    } else {
      await audio.play()
      isPlaying.value = true
    }
  } catch (error) {
    console.error('播放失败:', error)
    isPlaying.value = false
  }
}

const handleSliderChange = (value: number | number[]) => {
  const nextValue = Array.isArray(value) ? value[0] : value
  if (audioRef.value) {
    audioRef.value.currentTime = nextValue
    currentTime.value = nextValue
  }
}

const updateTime = () => {
  if (audioRef.value) currentTime.value = audioRef.value.currentTime
}
const updateDuration = () => {
  if (audioRef.value) duration.value = audioRef.value.duration
}
const handleEnded = () => {
  isPlaying.value = false
}

onMounted(() => {
  const audio = audioRef.value
  if (!audio) return
  audio.addEventListener('timeupdate', updateTime)
  audio.addEventListener('loadedmetadata', updateDuration)
  audio.addEventListener('ended', handleEnded)
})

onBeforeUnmount(() => {
  const audio = audioRef.value
  if (!audio) return
  audio.removeEventListener('timeupdate', updateTime)
  audio.removeEventListener('loadedmetadata', updateDuration)
  audio.removeEventListener('ended', handleEnded)
})
</script>
