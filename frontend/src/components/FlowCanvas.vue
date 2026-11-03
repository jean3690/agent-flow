<template>
  <div class="canvas" @drop="onDrop" @dragover.prevent @dragenter.prevent>
    <VueFlow
      v-model:nodes="nodesModel"
      v-model:edges="edgesModel"
      :default-viewport="{ x: 0, y: 0, zoom: 1 }"
      :min-zoom="0.3"
      :max-zoom="1.6"
      :delete-key-code="['Backspace', 'Delete']"
      fit-view-on-init
      class="canvas__flow"
      @connect="onConnect"
      @node-click="onNodeClick"
      @pane-click="emit('select', null)"
    >
      <template #node-flow="nodeProps">
        <FlowNode v-bind="nodeProps" />
      </template>
      <Background :gap="18" pattern-color="#242936" />
      <MiniMap pannable zoomable :height="110" :width="160" />
    </VueFlow>
    <div class="canvas__controls">
      <button type="button" title="放大" @click="zoomIn()">+</button>
      <button type="button" title="缩小" @click="zoomOut()">−</button>
      <button type="button" title="适应画布" @click="fitView({ padding: 0.25 })">⤢</button>
    </div>
    <div v-if="!nodes.length" class="canvas__empty">
      <div class="canvas__empty-title">从左侧拖入节点开始编排</div>
      <div class="canvas__empty-hint">开始 → 大模型 → 结束，就是一条最小可用工作流</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { MiniMap } from '@vue-flow/minimap'
import FlowNode from './FlowNode.vue'

const props = defineProps<{ nodes: any[]; edges: any[] }>()
const emit = defineEmits<{
  (e: 'update:nodes', value: any[]): void
  (e: 'update:edges', value: any[]): void
  (e: 'select', value: any): void
  (e: 'add-node', type: string, position: { x: number; y: number }): void
}>()

const { screenToFlowCoordinate, zoomIn, zoomOut, fitView } = useVueFlow()

const nodesModel = computed({
  get: () => props.nodes,
  set: (value) => emit('update:nodes', value)
})

const edgesModel = computed({
  get: () => props.edges,
  set: (value) => emit('update:edges', value)
})

function onConnect(params: any) {
  emit('update:edges', [
    ...props.edges,
    { id: 'edge-' + params.source + '-' + params.target, source: params.source, target: params.target }
  ])
}

function onNodeClick(event: any) {
  emit('select', event.node)
}

function onDrop(event: DragEvent) {
  const type = event.dataTransfer?.getData('application/agentflow-node')
  if (!type) return
  const position = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  emit('add-node', type, { x: Math.round(position.x), y: Math.round(position.y) })
}
</script>

<style scoped>
.canvas {
  position: relative;
  height: 100%;
  background: radial-gradient(circle at 30% 20%, #171b26 0%, #0f1117 60%);
}

.canvas__flow {
  height: 100%;
}

.canvas__empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  pointer-events: none;
}

.canvas__empty-title {
  font-size: 15px;
  color: #6b7387;
}

.canvas__empty-hint {
  font-size: 12px;
  color: #4b5266;
}

:deep(.vue-flow__edge-path) {
  stroke: #3b4254;
  stroke-width: 1.6;
}

:deep(.vue-flow__handle) {
  width: 8px;
  height: 8px;
  background: #6366f1;
  border: 2px solid #0f1117;
}

:deep(.vue-flow__controls) {
  box-shadow: none;
}

.canvas__controls {
  position: absolute;
  left: 14px;
  bottom: 14px;
  display: flex;
  border: 1px solid #262a36;
  border-radius: 8px;
  overflow: hidden;
  background: #171a23;
}

.canvas__controls button {
  width: 28px;
  height: 28px;
  border: none;
  border-right: 1px solid #262a36;
  background: transparent;
  color: #c7ccd8;
  font-size: 14px;
  cursor: pointer;
}

.canvas__controls button:last-child {
  border-right: none;
}

.canvas__controls button:hover {
  background: #232833;
}

:deep(.vue-flow__minimap) {
  background: #12151d;
  border: 1px solid #262a36;
  border-radius: 8px;
}

:deep(.vue-flow__minimap-mask) {
  fill: rgba(15, 17, 23, 0.72);
}

:deep(.vue-flow__minimap-node) {
  fill: #4f46e5;
  stroke: none;
}
</style>
