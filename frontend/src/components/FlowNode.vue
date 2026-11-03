<template>
  <div class="flow-node" :class="[statusClass, { 'is-selected': selected }]" :style="{ '--node-color': color }">
    <Handle type="target" :position="Position.Left" />
    <div class="flow-node__head">
      <span class="flow-node__dot" />
      <span class="flow-node__title">{{ label }}</span>
      <span v-if="statusClass === 'is-running'" class="flow-node__pulse" />
    </div>
    <div class="flow-node__meta">
      <span class="flow-node__type">{{ data.kind }}</span>
      <span v-if="elapsed" class="flow-node__elapsed">{{ elapsed }}ms</span>
    </div>
    <Handle type="source" :position="Position.Right" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { useRunStore } from '../stores/run'
import { useWorkflowStore } from '../stores/workflow'

const props = defineProps<{ id: string; data: any; selected?: boolean }>()

const runStore = useRunStore()
const workflowStore = useWorkflowStore()

const definition = computed(() => workflowStore.definitionMap[props.data.kind])
const color = computed(() => definition.value?.color || '#6366f1')
const label = computed(() => props.data.name || definition.value?.name || props.data.kind)
const status = computed(() => runStore.nodeStatus[props.id] || 'idle')
const elapsed = computed(() => runStore.nodeElapsed[props.id] || 0)
const statusClass = computed(() => 'is-' + status.value)
</script>

<style scoped>
.flow-node {
  min-width: 188px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #161a24;
  border: 1px solid #2a3040;
  border-left: 3px solid var(--node-color);
  color: #e5e7eb;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.25);
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.flow-node.is-selected {
  border-color: var(--node-color);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.35);
}

.flow-node.is-running {
  animation: pulse-border 1.4s ease-in-out infinite;
}

.flow-node.is-success {
  border-color: #22c55e;
}

.flow-node.is-failed {
  border-color: #ef4444;
}

.flow-node__head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
}

.flow-node__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--node-color);
}

.flow-node__pulse {
  margin-left: auto;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #22c55e;
  animation: blink 1s ease-in-out infinite;
}

.flow-node__meta {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 11px;
  color: #8b93a7;
  font-family: ui-monospace, monospace;
}

@keyframes blink {
  50% { opacity: 0.2; }
}

@keyframes pulse-border {
  50% { box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.18); }
}
</style>
