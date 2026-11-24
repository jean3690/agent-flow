<template>
  <a-drawer
    title="调试面板"
    placement="right"
    :open="open"
    :width="520"
    class="debug-drawer"
    :body-style="{ padding: 0 }"
    @close="emit('close')"
  >
    <div class="debug-drawer-content">
      <section class="debug-panel-section">
        <div class="debug-section-header">
          <div>
            <div class="debug-section-kicker">Test input</div>
            <h3>输入测试文本</h3>
          </div>
        </div>
        <a-textarea
          v-model:value="inputData"
          :rows="4"
          placeholder="请输入测试文本,例如: 人工智能的未来发展"
          :disabled="executing"
          class="debug-input-area"
        />
        <a-button
          type="primary"
          block
          :loading="executing"
          class="debug-run-button"
          @click="handleExecute"
        >
          <template #icon><PlayCircleOutlined /></template>
          {{ executing ? '执行中...' : '执行工作流' }}
        </a-button>
        <a-button
          v-if="executionResult?.status === 'FAILED' && (executionResult?.executionId || 0) > 0"
          block
          :loading="executing"
          class="debug-run-button"
          @click="handleResume"
        >
          <template #icon><ReloadOutlined /></template>
          从失败节点继续执行
        </a-button>
      </section>

      <section v-if="executing || executionResult" class="debug-panel-section">
        <div class="debug-section-header">
          <div>
            <div class="debug-section-kicker">Run status</div>
            <h3>执行状态</h3>
          </div>
          <span v-if="executionResult" class="debug-duration">{{ formatDuration(executionResult.duration) }}</span>
        </div>
        <div class="debug-status-card">
          <div v-if="executing && !executionResult" class="flex items-center gap-2">
            <LoadingOutlined class="text-blue-500" />
            <span>执行中...</span>
          </div>
          <template v-if="executionResult || nodeStatusMap.size > 0">
            <div class="flex items-center justify-between mb-2">
              <span>
                状态:
                <a-tag :color="executionStatusColor">{{ executionStatusText }}</a-tag>
              </span>
            </div>
            <a-progress :percent="progressPercent" :status="progressStatus" />
            <div class="mt-2 text-sm text-gray-600">
              已完成节点: {{ completedNodeCount }} / {{ progressTotal }}
            </div>
          </template>
        </div>
      </section>

      <section v-if="currentNodeResults.length > 0" class="debug-panel-section">
        <div class="debug-section-header">
          <div>
            <div class="debug-section-kicker">Nodes</div>
            <h3>节点执行结果</h3>
          </div>
          <span class="debug-count-pill">{{ currentNodeResults.length }}</span>
        </div>
        <a-collapse v-model:active-key="activeKeys" ghost class="debug-result-collapse">
          <a-collapse-panel v-for="nodeResult in currentNodeResults" :key="nodeResult.nodeId">
            <template #header>
              <div class="debug-node-collapse-label">
                <span class="debug-node-name">
                  <CheckCircleOutlined v-if="nodeResult.status === 'SUCCESS'" />
                  <CloseCircleOutlined v-else-if="nodeResult.status === 'FAILED'" />
                  <LoadingOutlined v-else />
                  {{ nodeResult.nodeName }}
                </span>
                <a-tag :color="nodeStatusColor(nodeResult)">{{ formatDuration(nodeResult.duration) }}</a-tag>
              </div>
            </template>
            <div class="debug-node-result-body">
              <div>
                <div class="debug-field-label">输入数据</div>
                <DebugValue :value="nodeResult.input" prefer-output-text />
              </div>
              <div>
                <div class="debug-field-label">输出数据</div>
                <RichOutput :value="nodeResult.output" prefer-output-text />
              </div>
              <a-alert
                v-if="nodeResult.error"
                message="错误信息"
                :description="nodeResult.error"
                type="error"
                show-icon
              />
            </div>
          </a-collapse-panel>
        </a-collapse>
      </section>

      <section v-if="executionResult && executionResult.status === 'SUCCESS'" class="debug-panel-section">
        <div class="debug-section-header">
          <div>
            <div class="debug-section-kicker">Final</div>
            <h3>最终输出</h3>
          </div>
        </div>
        <div class="debug-final-output">
          <div v-if="finalImageUrls.length > 0 || finalVideoUrls.length > 0" class="debug-final-media">
            <div v-if="finalImageUrls.length > 0" class="debug-media-grid">
              <a
                v-for="url in finalImageUrls"
                :key="url"
                :href="url"
                target="_blank"
                rel="noreferrer"
                class="debug-image-link"
              >
                <img :src="url" alt="workflow output" class="debug-generated-image" />
              </a>
            </div>
            <video v-for="url in finalVideoUrls" :key="url" :src="url" controls class="debug-generated-video" />
          </div>
          <AudioPlayer
            v-else-if="finalAudioOutput"
            :audio-url="finalAudioOutput.audioUrl"
            :file-name="finalAudioOutput.fileName"
          />
          <RichOutput v-else :value="executionResult.outputData" prefer-output-text />
        </div>
      </section>

      <section class="debug-panel-section">
        <div class="debug-section-header">
          <div>
            <div class="debug-section-kicker">Logs</div>
            <h3>执行日志</h3>
          </div>
        </div>
        <div class="debug-log-list">
          <div
            v-for="(log, index) in logs"
            :key="index"
            class="debug-log-line"
            :class="log.includes('❌') ? 'is-error' : log.includes('✅') ? 'is-success' : ''"
          >
            {{ log }}
          </div>
          <div v-if="logs.length === 0" class="debug-empty-log">暂无日志</div>
        </div>
      </section>
    </div>
  </a-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons-vue'
import AudioPlayer from './AudioPlayer.vue'
import DebugValue from './DebugValue.vue'
import RichOutput from './RichOutput.vue'
import {
  collectAudioOutput,
  collectImageUrls,
  collectVideoUrls,
  formatDuration,
  formatToolTraceLog,
  formatToolTraceLogs,
  isRecord,
  normalizeValue,
} from '../utils/debugOutput'
import {
  executeWorkflowStream,
  getLatestExecution,
  resumeWorkflowExecution,
  type ExecutionEvent,
  type ExecutionNodeResult,
  type ExecutionResponse as PersistedExecutionResponse,
} from '../api/workflow'

interface NodeResult {
  nodeId: string
  nodeName: string
  status: 'SUCCESS' | 'FAILED' | 'RUNNING'
  input: Record<string, unknown>
  output: Record<string, unknown>
  duration: number
  error?: string
}

interface ExecutionResponse {
  executionId: number
  status: 'SUCCESS' | 'FAILED' | 'RUNNING'
  nodeResults: NodeResult[]
  outputData: unknown
  duration: number
  errorMessage?: string
}

const props = defineProps<{
  open: boolean
  workflowId: number | null
  totalNodeCount: number
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const inputData = ref('')
const executing = ref(false)
const executionResult = ref<ExecutionResponse | null>(null)
const logs = ref<string[]>([])
const nodeStatusMap = ref<Map<string, NodeResult>>(new Map())
const latestExecutionRequestRef = ref(0)
const activeKeys = ref<string[]>([])
const seenNodeIds = new Set<string>()

const addLog = (message: string) => {
  const timestamp = new Date().toLocaleTimeString()
  logs.value = [...logs.value, `[${timestamp}] ${message}`]
}

const normalizeNodeResult = (nodeResult: ExecutionNodeResult): NodeResult => {
  const input = normalizeValue(nodeResult.input)
  const output = normalizeValue(nodeResult.output)

  return {
    nodeId: nodeResult.nodeId,
    nodeName: nodeResult.nodeName,
    status: nodeResult.status,
    input: isRecord(input) ? input : {},
    output: isRecord(output) ? output : {},
    duration: nodeResult.duration || 0,
    error: nodeResult.error,
  }
}

const extractInputText = (value: unknown) => {
  const normalizedInput = normalizeValue(value)
  if (typeof normalizedInput === 'string') {
    return normalizedInput
  }
  if (isRecord(normalizedInput) && typeof normalizedInput.input === 'string') {
    return normalizedInput.input
  }
  return ''
}

const toExecutionResult = (result: PersistedExecutionResponse) => {
  const restoredNodeResults = (result.nodeResults || []).map(normalizeNodeResult)
  return {
    restoredNodeResults,
    restoredResult: {
      executionId: result.executionId,
      status: result.status,
      nodeResults: restoredNodeResults,
      outputData: normalizeValue(result.outputData),
      duration: result.duration || 0,
      errorMessage: result.errorMessage,
    } as ExecutionResponse,
  }
}

const restoreExecution = (result: PersistedExecutionResponse) => {
  const { restoredNodeResults, restoredResult } = toExecutionResult(result)
  inputData.value = extractInputText(result.inputData)
  executionResult.value = restoredResult
  nodeStatusMap.value = new Map(restoredNodeResults.map((node) => [node.nodeId, node]))

  const restoredLogs = [
    `已加载最近一次执行记录 #${result.executionId}`,
    ...restoredNodeResults.flatMap((node) => {
      const nodeLog =
        node.status === 'FAILED'
          ? `❌ 节点 [${node.nodeName}] 执行失败${node.error ? `: ${node.error}` : ''}`
          : `✅ 节点 [${node.nodeName}] 执行成功,耗时 ${formatDuration(node.duration)}`
      const toolLogs = formatToolTraceLogs(node.output)
      return [nodeLog, ...toolLogs]
    }),
    `${result.status === 'SUCCESS' ? '✅' : '❌'} 工作流执行${result.status === 'SUCCESS' ? '成功' : '失败'},总耗时 ${formatDuration(result.duration)}`,
  ]

  logs.value = restoredLogs.map((message) => `[历史] ${message}`)
}

const applyExecutionResult = (result: PersistedExecutionResponse) => {
  const { restoredNodeResults, restoredResult } = toExecutionResult(result)
  executionResult.value = restoredResult
  nodeStatusMap.value = new Map(restoredNodeResults.map((node) => [node.nodeId, node]))
}

const syncLatestExecutionResult = async (targetWorkflowId: number) => {
  try {
    const result = await getLatestExecution(targetWorkflowId)
    if (result.code === 200 && result.data) {
      applyExecutionResult(result.data)
    }
  } catch (error) {
    console.warn('同步最近一次执行记录失败:', error)
  }
}

const addProgressLog = (event: ExecutionEvent) => {
  addLog(`📊 ${event.message}`)
  if (isRecord(event.data)) {
    const toolTraceLog = formatToolTraceLog(event.data)
    if (toolTraceLog) {
      addLog(toolTraceLog)
    }
  }
}

const addNodeSuccessLog = (node: NodeResult) => {
  addLog(`✅ 节点 [${node.nodeName}] 执行成功,耗时 ${formatDuration(node.duration)}`)
  formatToolTraceLogs(node.output).forEach(addLog)
}

const resetExecutionState = () => {
  inputData.value = ''
  executionResult.value = null
  logs.value = []
  nodeStatusMap.value = new Map()
}

const loadLatestExecution = async () => {
  const targetWorkflowId = props.workflowId
  const requestId = ++latestExecutionRequestRef.value

  if (!targetWorkflowId || executing.value) {
    return
  }

  try {
    const result = await getLatestExecution(targetWorkflowId)
    if (latestExecutionRequestRef.value !== requestId) {
      return
    }
    if (result.code === 200 && result.data) {
      restoreExecution(result.data)
    } else if (result.code === 200) {
      resetExecutionState()
      logs.value = [`[历史] 当前工作流 #${targetWorkflowId} 暂无执行记录`]
    }
  } catch (error) {
    if (latestExecutionRequestRef.value !== requestId) {
      return
    }
    console.warn('加载最近一次执行记录失败:', error)
  }
}

watch(
  () => props.workflowId,
  () => {
    latestExecutionRequestRef.value += 1
    resetExecutionState()
  }
)

watch([() => props.open, () => props.workflowId], () => {
  if (!props.open || executing.value) {
    return
  }
  loadLatestExecution()
})

const handleExecute = async () => {
  if (!inputData.value.trim()) {
    addLog('❌ 错误: 输入数据不能为空')
    return
  }

  if (!props.workflowId) {
    addLog('❌ 错误: 请先保存工作流')
    return
  }

  executing.value = true
  executionResult.value = null
  logs.value = []
  nodeStatusMap.value = new Map()
  addLog('🚀 开始执行工作流...')

  try {
    const nodeResults: NodeResult[] = []
    const tempNodeStatusMap = new Map<string, NodeResult>()
    let activeExecutionId = 0

    await executeWorkflowStream(
      props.workflowId,
      inputData.value,
      (event: ExecutionEvent) => {
        switch (event.eventType) {
          case 'WORKFLOW_START':
            if (typeof event.data === 'number') {
              activeExecutionId = event.data
            } else if (typeof event.data === 'string') {
              const parsedExecutionId = Number.parseInt(event.data, 10)
              activeExecutionId = Number.isNaN(parsedExecutionId) ? 0 : parsedExecutionId
            }
            addLog('🚀 工作流开始执行')
            break

          case 'NODE_START':
            addLog(`📍 节点 [${event.nodeName}] 开始执行...`)
            if (event.nodeId && event.nodeName) {
              const nodeResult: NodeResult = {
                nodeId: event.nodeId,
                nodeName: event.nodeName,
                status: 'RUNNING',
                input: {},
                output: {},
                duration: 0,
              }
              tempNodeStatusMap.set(event.nodeId, nodeResult)
              nodeStatusMap.value = new Map(tempNodeStatusMap)
            }
            break

          case 'NODE_SUCCESS':
            if (event.nodeId && event.nodeName) {
              const duration = event.message?.match(/耗时 (\d+)ms/)?.[1] || '0'

              const eventData = isRecord(event.data) ? event.data : {}
              const nodeResult: NodeResult = {
                nodeId: event.nodeId,
                nodeName: event.nodeName,
                status: 'SUCCESS',
                input: isRecord(eventData.input) ? eventData.input : {},
                output: isRecord(eventData.output) ? eventData.output : isRecord(event.data) ? event.data : {},
                duration: parseInt(duration),
              }
              addNodeSuccessLog(nodeResult)
              tempNodeStatusMap.set(event.nodeId, nodeResult)
              nodeResults.push(nodeResult)
              nodeStatusMap.value = new Map(tempNodeStatusMap)
            }
            break

          case 'NODE_PROGRESS':
            if (event.nodeId && event.message) {
              addProgressLog(event)
              const existingNode = tempNodeStatusMap.get(event.nodeId)
              if (existingNode) {
                existingNode.status = 'RUNNING'
                nodeStatusMap.value = new Map(tempNodeStatusMap)
              }
            }
            break

          case 'NODE_ERROR':
            if (event.nodeId && event.nodeName) {
              addLog(`❌ 节点 [${event.nodeName}] 执行失败: ${event.message}`)
              const nodeResult: NodeResult = {
                nodeId: event.nodeId,
                nodeName: event.nodeName,
                status: 'FAILED',
                input: {},
                output: {},
                duration: 0,
                error: event.message,
              }
              tempNodeStatusMap.set(event.nodeId, nodeResult)
              nodeResults.push(nodeResult)
              nodeStatusMap.value = new Map(tempNodeStatusMap)
            }
            break

          case 'WORKFLOW_COMPLETE': {
            const totalDuration = event.message?.match(/总耗时 (\d+)ms/)?.[1] || '0'
            addLog(
              `${event.status === 'SUCCESS' ? '✅' : '❌'} 工作流执行${event.status === 'SUCCESS' ? '成功' : '失败'},总耗时 ${formatDuration(totalDuration)}`
            )

            executionResult.value = {
              executionId: activeExecutionId,
              status: event.status as 'SUCCESS' | 'FAILED',
              nodeResults: Array.from(tempNodeStatusMap.values()),
              outputData: event.data || {},
              duration: parseInt(totalDuration),
              errorMessage: event.status === 'FAILED' ? event.message : undefined,
            }
            if (event.status === 'FAILED' && activeExecutionId === 0) {
              syncLatestExecutionResult(props.workflowId as number)
            }
            break
          }
        }
      },
      () => {
        executing.value = false
      },
      (error: Error) => {
        const errorMsg = error.message.includes('连接失败')
          ? '连接失败,请检查后端服务是否运行或重新登录'
          : error.message
        addLog(`❌ 执行异常: ${errorMsg}`)
        executing.value = false
      }
    )
  } catch (error) {
    addLog(`❌ 执行异常: ${error instanceof Error ? error.message : '未知错误'}`)
    executing.value = false
  }
}

const handleResume = async () => {
  if (!props.workflowId || !executionResult.value?.executionId) {
    addLog('❌ 错误: 缺少可恢复的执行记录')
    return
  }

  const currentResult = executionResult.value
  const failedNode = currentResult.nodeResults.find((node) => node.status === 'FAILED')
  executing.value = true
  addLog(`🔁 从执行记录 #${currentResult.executionId} 的失败断点继续执行...`)
  if (failedNode) {
    addLog(`📍 节点 [${failedNode.nodeName}] 重新执行...`)
    executionResult.value = {
      ...currentResult,
      status: 'RUNNING',
      nodeResults: currentResult.nodeResults.map((node) =>
        node.nodeId === failedNode.nodeId ? { ...node, status: 'RUNNING', error: undefined } : node
      ),
    }
    const next = new Map(nodeStatusMap.value)
    const currentFailedNode = next.get(failedNode.nodeId)
    if (currentFailedNode) {
      next.set(failedNode.nodeId, {
        ...currentFailedNode,
        status: 'RUNNING',
        error: undefined,
      })
    }
    nodeStatusMap.value = next
  }

  try {
    const result = await resumeWorkflowExecution(props.workflowId, currentResult.executionId, {
      skipSuccessNodes: true,
      useSnapshotVariables: true,
    })
    if (result.code !== 200) {
      throw new Error(result.message || '断点续执行失败')
    }

    applyExecutionResult(result.data)
    const retriedFailedNode = (result.data.nodeResults || []).find((node) => node.status === 'FAILED')
    if (result.data.status === 'SUCCESS') {
      addLog('✅ 断点续执行完成,状态: SUCCESS')
    } else {
      addLog('❌ 断点续执行完成,状态: FAILED')
      if (retriedFailedNode?.error) {
        addLog(`❌ 节点 [${retriedFailedNode.nodeName}] 仍然失败: ${retriedFailedNode.error}`)
      }
    }
  } catch (error) {
    addLog(`❌ 断点续执行异常: ${error instanceof Error ? error.message : '未知错误'}`)
  } finally {
    executing.value = false
  }
}

const currentNodeResults = computed<NodeResult[]>(() =>
  executionResult.value ? executionResult.value.nodeResults : Array.from(nodeStatusMap.value.values())
)

const progressTotal = computed(() => {
  if (executionResult.value) {
    return executionResult.value.nodeResults.length
  }
  return props.totalNodeCount > 0 ? props.totalNodeCount : nodeStatusMap.value.size
})

const completedNodeCount = computed(
  () => currentNodeResults.value.filter((result) => result.status === 'SUCCESS').length
)

const progressPercent = computed(() => {
  const total = progressTotal.value
  if (total === 0) return 0
  return Math.round((completedNodeCount.value / total) * 100)
})

const progressStatus = computed(() =>
  executionResult.value?.status === 'SUCCESS'
    ? 'success'
    : executionResult.value?.status === 'FAILED'
      ? 'exception'
      : 'active'
)

const executionStatusColor = computed(() =>
  executionResult.value?.status === 'SUCCESS'
    ? 'success'
    : executionResult.value?.status === 'FAILED'
      ? 'error'
      : 'processing'
)

const executionStatusText = computed(() =>
  executionResult.value?.status === 'SUCCESS'
    ? '成功'
    : executionResult.value?.status === 'FAILED'
      ? '失败'
      : '执行中'
)

const nodeStatusColor = (nodeResult: NodeResult) => {
  if (nodeResult.status === 'SUCCESS') return 'success'
  if (nodeResult.status === 'FAILED') return 'error'
  if (nodeResult.status === 'RUNNING') return 'processing'
  return 'default'
}

const finalImageUrls = computed(() =>
  executionResult.value ? collectImageUrls(executionResult.value.outputData) : []
)
const finalVideoUrls = computed(() =>
  executionResult.value ? collectVideoUrls(executionResult.value.outputData) : []
)
const finalAudioOutput = computed(() =>
  executionResult.value ? collectAudioOutput(executionResult.value.outputData) : null
)

watch(
  currentNodeResults,
  (results) => {
    const newIds = results.map((result) => result.nodeId).filter((id) => !seenNodeIds.has(id))
    newIds.forEach((id) => seenNodeIds.add(id))
    if (newIds.length > 0) {
      activeKeys.value = [...activeKeys.value, ...newIds]
    }
  },
  { immediate: true }
)
</script>
