<template>
  <div class="h-full flex flex-col overflow-hidden">
    <div class="node-library-header">
      <div>
        <h3 class="node-library-heading">节点库</h3>
        <p class="node-library-desc">流程组件</p>
      </div>
    </div>
    <div class="node-library-body">
      <div v-if="loading" class="text-center py-8 text-gray-400">加载中...</div>
      <template v-else>
        <a-collapse ghost :default-active-key="['llm', 'tool', 'control']">
          <a-collapse-panel v-for="section in sections" :key="section.key">
            <template #header>
              <div class="node-library-section-title">
                <span>{{ section.title }}</span>
                <a-tag :color="section.color">{{ section.nodes.length }}</a-tag>
              </div>
            </template>
            <div class="space-y-2">
              <div
                v-for="node in section.nodes"
                :key="node.nodeType"
                draggable="true"
                class="node-library-item"
                @dragstart="handleDragStart($event, node)"
                @dragend="dragging = false"
                @click="handleClick(node)"
              >
                <div class="node-library-icon" :class="getNodeTone(node)">{{ node.icon }}</div>
                <div class="min-w-0 flex-1">
                  <div class="node-library-title">{{ node.displayName }}</div>
                  <div class="node-library-meta">{{ node.nodeType }}</div>
                </div>
                <span class="node-library-drag" aria-hidden="true">⋮⋮</span>
              </div>
              <div v-if="section.nodes.length === 0" class="text-gray-400 text-center py-4">暂无节点</div>
            </div>
          </a-collapse-panel>
        </a-collapse>
        <div class="node-library-tip">输入 · 模型 · 工具 · 控制 · 输出</div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { getNodeTypes, type NodeDefinition } from '../api/workflow'

const emit = defineEmits<{
  (e: 'drag-start', event: DragEvent, nodeType: string, displayName: string): void
  (e: 'add-node', nodeType: string, displayName: string): void
}>()

const nodeTypes = ref<NodeDefinition[]>([])
const loading = ref(false)

const loadNodeTypes = async () => {
  loading.value = true
  try {
    const result = await getNodeTypes()
    if (result.code === 200) {
      nodeTypes.value = result.data
    } else {
      message.error(`加载节点类型失败: ${result.message || '未知错误'}`)
    }
  } catch (error) {
    message.error(`加载节点类型失败: ${error instanceof Error ? error.message : '网络错误'}`)
  } finally {
    loading.value = false
  }
}

const sections = computed(() => {
  const llmNodes = nodeTypes.value.filter((node) => node.category === 'LLM')
  const toolNodes = nodeTypes.value.filter((node) => node.category === 'TOOL')
  const controlNodes = nodeTypes.value.filter((node) => node.category === 'CONTROL')

  const items = [
    { key: 'llm', title: '大模型节点', color: 'blue', nodes: llmNodes },
    { key: 'tool', title: '工具节点', color: 'gold', nodes: toolNodes },
  ]

  if (controlNodes.length > 0) {
    items.push({ key: 'control', title: '控制节点', color: 'purple', nodes: controlNodes })
  }

  return items
})

const getNodeTone = (node: NodeDefinition) => {
  if (node.nodeType === 'input') return 'node-library-green'
  if (node.nodeType === 'output') return 'node-library-purple'
  if (node.category === 'TOOL') return 'node-library-amber'
  if (node.category === 'CONTROL') return 'node-library-purple'
  return 'node-library-blue'
}

let dragging = false

const handleDragStart = (event: DragEvent, node: NodeDefinition) => {
  dragging = true
  emit('drag-start', event, node.nodeType, node.displayName)
}

const handleClick = (node: NodeDefinition) => {
  if (dragging) return
  emit('add-node', node.nodeType, node.displayName)
}

onMounted(loadNodeTypes)
</script>
