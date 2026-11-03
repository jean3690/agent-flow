<template>
  <div class="audio">
    <audio :src="src" controls preload="none" />
    <span class="audio__hint mono">{{ src }}</span>
  </div>
</template>

<script setup lang="ts">
defineProps<{ src: string }>()
</script>

<style scoped>
.audio {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.audio audio {
  width: 100%;
  height: 34px;
}

.audio__hint {
  font-size: 11px;
  color: #6b7387;
  word-break: break-all;
}
</style>
