<template>
  <div class="workflow-node" :class="{ 'is-selected': selected }">
    <Handle
      v-if="workflowType !== 'input'"
      type="target"
      :position="Position.Top"
      class="workflow-node-handle"
    />
    <div class="workflow-node-header">
      <div class="workflow-node-icon" :class="meta.tone">{{ meta.icon }}</div>
      <div class="workflow-node-title-wrap">
        <div class="workflow-node-title">{{ data.label || workflowType || '未命名节点' }}</div>
        <div class="workflow-node-subtitle">{{ modelLabel }}</div>
      </div>
    </div>
    <div v-if="isCondition && conditions.length > 0" class="workflow-node-conditions">
      <div v-for="(c, i) in conditions" :key="c.id" class="workflow-node-condition-item">
        <span class="condition-badge">{{ i + 1 }}</span>
        <span class="condition-label">{{ c.field }} {{ c.operator }} {{ c.value }}</span>
      </div>
      <div class="workflow-node-condition-item condition-default">
        <span class="condition-badge default">D</span>
        <span class="condition-label">否则(默认)</span>
      </div>
    </div>
    <div v-if="isReActMode || knowledgeBaseLabel" class="workflow-node-conditions">
      <div v-if="isReActMode" class="workflow-node-condition-item">
        <span class="condition-badge">A</span>
        <span class="condition-label">Agent策略 ReAct</span>
      </div>
      <div v-if="isReActMode && toolLabels.length > 0" class="workflow-node-condition-item">
        <span class="condition-badge default">{{ toolLabels.length }}</span>
        <span class="condition-label">工具 {{ toolLabels.join(', ') }}</span>
      </div>
      <div v-if="knowledgeBaseLabel" class="workflow-node-condition-item">
        <span class="condition-badge knowledge">K</span>
        <span class="condition-label">知识库 {{ knowledgeBaseLabel }}</span>
      </div>
    </div>
    <div class="workflow-node-footer">
      <span>{{ workflowType || 'node' }}</span>
      <span>{{ inputCount }} in / {{ outputCount }} out</span>
    </div>
    <template v-if="workflowType !== 'output'">
      <template v-if="isCondition">
        <Handle
          v-for="(c, i) in conditions"
          :key="c.id"
          type="source"
          :position="Position.Bottom"
          :id="c.id"
          class="workflow-node-handle condition-handle"
          :style="{ left: `${((i + 1) / (handleCount + 1)) * 100}%` }"
        />
        <Handle
          type="source"
          :position="Position.Bottom"
          id="default"
          class="workflow-node-handle condition-handle"
          :style="{ left: `${(handleCount / (handleCount + 1)) * 100}%` }"
        />
      </template>
      <Handle v-else type="source" :position="Position.Bottom" class="workflow-node-handle" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import {
  getKnowledgeBaseLabel,
  getNodeMeta,
  getToolLabels,
  type WorkflowNodeData,
} from '../utils/nodeVisual'

defineOptions({ inheritAttrs: false })

const props = defineProps<{
  data: WorkflowNodeData
  selected?: boolean
}>()

const workflowType = computed(() => props.data.type || '')
const meta = computed(() => getNodeMeta(workflowType.value))
const inputCount = computed(() => (Array.isArray(props.data.inputParams) ? props.data.inputParams.length : 0))
const outputCount = computed(() => (Array.isArray(props.data.outputParams) ? props.data.outputParams.length : 0))
const modelLabel = computed(() => props.data.model || props.data.provider || props.data.skillName || meta.value.caption)
const tools = computed(() => (Array.isArray(props.data.tools) ? props.data.tools : []))
const toolLabels = computed(() => getToolLabels(tools.value))
const isReActMode = computed(
  () => (workflowType.value === 'llm' && props.data.agentStrategy === 'react') || workflowType.value === 'react_agent'
)
const knowledgeBaseLabel = computed(() => getKnowledgeBaseLabel(props.data))
const isCondition = computed(() => workflowType.value === 'condition')
const conditions = computed(() => (Array.isArray(props.data.conditions) ? props.data.conditions : []))
const handleCount = computed(() => (isCondition.value ? conditions.value.length + 1 : 0))
</script>
