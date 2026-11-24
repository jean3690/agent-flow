<template>
  <div ref="wrapperRef" class="relative h-full w-full">
    <VueFlow
      v-model:nodes="nodes"
      v-model:edges="edges"
      :node-types="nodeTypes"
      :default-edge-options="defaultEdgeOptions"
      :fit-view-options="{ padding: 0.28 }"
      fit-view
      snap-to-grid
      :snap-grid="[16, 16]"
      @connect="handleConnect"
      @drop="onDrop"
      @dragover="onDragOver"
      @node-click="handleNodeClick"
    >
      <Background color="#d8dee9" :gap="18" :size="1.2" />
      <Controls class="workflow-controls" />
      <MiniMap
        v-if="minimapOpen"
        pannable
        zoomable
        class="workflow-minimap"
        :node-color="getMiniMapNodeColor"
      />
    </VueFlow>
    <button
      v-if="minimapOpen"
      type="button"
      class="workflow-minimap-close"
      title="收起缩略图"
      @click="minimapOpen = false"
    >
      ×
    </button>
    <button
      v-else
      type="button"
      class="workflow-minimap-toggle"
      title="展开缩略图"
      @click="minimapOpen = true"
    >
      地图
    </button>
  </div>
</template>

<script setup lang="ts">
import { markRaw, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import type { Connection, Node } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'
import WorkflowNodeCard from './WorkflowNodeCard.vue'
import { useWorkflowStore } from '../stores/workflow'
import {
  WORKFLOW_EDGE_MARKER,
  WORKFLOW_EDGE_STYLE,
  getDefaultNodeData,
  getNodeMeta,
} from '../utils/nodeVisual'

const emit = defineEmits<{ (e: 'node-click', node: Node): void }>()

const { nodes, edges } = storeToRefs(useWorkflowStore())
const { addEdges, screenToFlowCoordinate } = useVueFlow()

const nodeTypes = { workflow: markRaw(WorkflowNodeCard) } as any

const defaultEdgeOptions = {
  type: 'smoothstep',
  style: WORKFLOW_EDGE_STYLE,
  markerEnd: WORKFLOW_EDGE_MARKER,
}

const handleConnect = (connection: Connection) => {
  addEdges([
    {
      ...connection,
      type: 'smoothstep',
      style: WORKFLOW_EDGE_STYLE,
      markerEnd: WORKFLOW_EDGE_MARKER,
    },
  ])
}

const onDrop = (event: DragEvent) => {
  event.preventDefault()

  const type = event.dataTransfer?.getData('application/reactflow-type')
  const label = event.dataTransfer?.getData('application/reactflow-label')

  if (!type) return

  const position = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })

  const newNode: Node = {
    id: `${type}-${Date.now()}`,
    type: 'workflow',
    position,
    data: { label: label || type, type, ...getDefaultNodeData(type) },
  }

  nodes.value = [...nodes.value, newNode]
}

const onDragOver = (event: DragEvent) => {
  event.preventDefault()
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'move'
  }
}

const handleNodeClick = (payload: { node: Node }) => {
  emit('node-click', payload.node)
}

const wrapperRef = ref<HTMLElement | null>(null)
const minimapOpen = ref(false)

const addNode = (type: string, label?: string) => {
  const rect = wrapperRef.value?.getBoundingClientRect()
  const center = rect
    ? screenToFlowCoordinate({ x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 })
    : { x: 0, y: 0 }
  const position = { x: center.x, y: center.y }
  let guard = 0
  while (
    guard++ < 20 &&
    nodes.value.some(
      (node) => Math.abs(node.position.x - position.x) < 48 && Math.abs(node.position.y - position.y) < 48,
    )
  ) {
    position.x += 32
    position.y += 32
  }

  nodes.value = [
    ...nodes.value,
    {
      id: `${type}-${Date.now()}`,
      type: 'workflow',
      position,
      data: { label: label || type, type, ...getDefaultNodeData(type) },
    },
  ]
}

defineExpose({ addNode })

const getMiniMapNodeColor = (node: Node) => {
  const tone = getNodeMeta(String(node.data?.type || '')).tone
  return tone.includes('green') ? '#22c55e' : '#64748b'
}
</script>
