<template>
  <aside class="panel">
    <div class="panel__title">节点</div>
    <div class="panel__hint">拖拽到画布，或单击快速添加</div>
    <div v-for="[category, items] in categories" :key="category" class="panel__group">
      <div class="panel__category">{{ category }}</div>
      <div
        v-for="item in items"
        :key="item.type"
        class="panel__item"
        draggable="true"
        :style="{ '--node-color': item.color }"
        @dragstart="onDragStart($event, item.type)"
        @click="emit('add', item.type)"
      >
        <span class="panel__dot" />
        <div class="panel__text">
          <div class="panel__name">{{ item.name }}</div>
          <div class="panel__desc">{{ item.description }}</div>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useWorkflowStore } from '../stores/workflow'

const emit = defineEmits<{ (e: 'add', type: string): void }>()
const workflowStore = useWorkflowStore()
const categories = computed(() => workflowStore.categories)

function onDragStart(event: DragEvent, type: string) {
  event.dataTransfer?.setData('application/agentflow-node', type)
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
  }
}
</script>

<style scoped>
.panel {
  width: 232px;
  padding: 16px 12px;
  border-right: 1px solid #262a36;
  background: #12151d;
  overflow-y: auto;
}

.panel__title {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.panel__hint {
  margin-top: 4px;
  font-size: 11px;
  color: #6b7387;
}

.panel__group {
  margin-top: 16px;
}

.panel__category {
  font-size: 11px;
  color: #6b7387;
  margin-bottom: 8px;
  letter-spacing: 0.08em;
}

.panel__item {
  display: flex;
  gap: 8px;
  padding: 9px 10px;
  margin-bottom: 8px;
  border-radius: 8px;
  background: #171a23;
  border: 1px solid #232833;
  cursor: grab;
  transition: border-color 0.16s ease, transform 0.16s ease;
}

.panel__item:hover {
  border-color: var(--node-color);
  transform: translateX(2px);
}

.panel__dot {
  width: 6px;
  height: 6px;
  margin-top: 5px;
  border-radius: 50%;
  background: var(--node-color);
  flex: none;
}

.panel__text {
  min-width: 0;
}

.panel__name {
  font-size: 12px;
  font-weight: 600;
}

.panel__desc {
  margin-top: 2px;
  font-size: 11px;
  line-height: 1.4;
  color: #6b7387;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
