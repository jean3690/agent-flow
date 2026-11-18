import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import { runWorkflow, type SseEvent } from '../utils/sse'
import { executionApi } from '../api'

export interface RunLogEntry {
  event: string
  message: string
  level: string
  nodeId?: string
  at: number
}

export const useRunStore = defineStore('run', () => {
  const running = ref(false)
  const error = ref('')
  const output = ref<any>(null)
  const elapsed = ref(0)
  const runId = ref('')
  const failedRunId = ref('')
  const nodeStatus = reactive<Record<string, string>>({})
  const nodeElapsed = reactive<Record<string, number>>({})
  const nodeOutputs = reactive<Record<string, any>>({})
  const tokens = reactive<Record<string, string>>({})
  const logs = ref<RunLogEntry[]>([])
  let controller: AbortController | null = null

  const outputText = computed(() => {
    if (output.value === null || output.value === undefined) return ''
    if (typeof output.value === 'string') return output.value
    return JSON.stringify(output.value, null, 2)
  })

  function reset() {
    error.value = ''
    output.value = null
    elapsed.value = 0
    runId.value = ''
    failedRunId.value = ''
    logs.value = []
    Object.keys(nodeStatus).forEach((key) => delete nodeStatus[key])
    Object.keys(nodeElapsed).forEach((key) => delete nodeElapsed[key])
    Object.keys(nodeOutputs).forEach((key) => delete nodeOutputs[key])
    Object.keys(tokens).forEach((key) => delete tokens[key])
  }

  async function start(workflowId: number, input: Record<string, any>, resumeRunId?: string) {
    if (running.value) return
    reset()
    failedRunId.value = ''
    running.value = true
    const activeController = new AbortController()
    controller = activeController
    let receivedTerminal = false
    pushLog({
      event: 'run_started',
      message: resumeRunId ? '断点续跑：复用已成功节点的输出…' : '提交执行…',
      level: 'info',
      at: Date.now()
    })
    try {
      await runWorkflow({
        workflowId,
        input,
        resumeRunId,
        signal: activeController.signal,
        onEvent: (event) => {
          if (controller !== activeController || activeController.signal.aborted) return
          if (event.event === 'run_finished' || event.event === 'run_failed') receivedTerminal = true
          handleEvent(event)
        }
      })
      if (controller === activeController && !receivedTerminal) {
        throw new Error('执行流已断开，未收到结束事件，请到执行历史确认状态')
      }
    } catch (err: any) {
      if (controller !== activeController) return
      if (err?.name !== 'AbortError') {
        error.value = err?.message || '执行失败'
        finishActiveNodes('interrupted')
        pushLog({ event: 'run_failed', message: error.value, level: 'error', at: Date.now() })
      }
    } finally {
      // An aborted request may settle after the user has started a new run.
      if (controller === activeController) {
        running.value = false
        controller = null
      }
    }
  }

  function stop() {
    if (!running.value) return
    const id = runId.value
    if (id) {
      executionApi.cancel(id).catch(() => {})
    }
    controller?.abort()
    controller = null
    running.value = false
    finishActiveNodes('canceled')
    pushLog({
      event: 'run_canceled',
      message: id
        ? '已停止接收执行结果，取消请求已发送；最终状态请查看执行历史'
        : '已停止接收执行结果，尚未取得执行编号；任务状态请查看执行历史',
      level: 'warn',
      at: Date.now()
    })
  }

  function finishActiveNodes(status: string) {
    Object.keys(nodeStatus).forEach((id) => {
      if (nodeStatus[id] === 'running') nodeStatus[id] = status
    })
  }

  function handleEvent(event: SseEvent) {
    const data = event.data || {}
    switch (event.event) {
      case 'run_started':
        runId.value = data.runId
        pushLog({ event: event.event, message: '开始执行，共 ' + data.nodeCount + ' 个节点', level: 'info', at: Date.now() })
        break
      case 'node_started':
        nodeStatus[data.nodeId] = 'running'
        pushLog({
          event: event.event,
          nodeId: data.nodeId,
          message: (data.nodeName || data.nodeType) + ' 执行中',
          level: 'info',
          at: Date.now()
        })
        break
      case 'node_token':
        tokens[data.nodeId] = (tokens[data.nodeId] || '') + (data.delta || '')
        break
      case 'node_log':
        pushLog({
          event: event.event,
          nodeId: data.nodeId,
          message: data.message,
          level: data.level || 'info',
          at: Date.now()
        })
        break
      case 'node_finished':
        nodeStatus[data.nodeId] = 'success'
        nodeElapsed[data.nodeId] = data.elapsedMs
        if (data.output !== undefined) nodeOutputs[data.nodeId] = data.output
        pushLog({
          event: event.event,
          nodeId: data.nodeId,
          message: data.nodeId + ' 完成 (' + data.elapsedMs + 'ms)',
          level: 'success',
          at: Date.now()
        })
        break
      case 'node_failed':
        nodeStatus[data.nodeId] = 'failed'
        pushLog({
          event: event.event,
          nodeId: data.nodeId,
          message: data.error?.message || '节点失败',
          level: 'error',
          at: Date.now()
        })
        break
      case 'run_finished':
        output.value = data.output
        if (data.outputs) Object.assign(nodeOutputs, data.outputs)
        elapsed.value = data.elapsedMs || 0
        finishActiveNodes('success')
        pushLog({ event: event.event, message: '执行完成 (' + data.elapsedMs + 'ms)', level: 'success', at: Date.now() })
        break
      case 'run_failed':
        error.value = data.error?.message || '执行失败'
        elapsed.value = data.elapsedMs || 0
        failedRunId.value = data.runId || runId.value
        finishActiveNodes(data.status === 'CANCELED' ? 'canceled' : 'failed')
        pushLog({ event: event.event, message: error.value, level: 'error', at: Date.now() })
        break
      default:
        break
    }
  }

  function pushLog(entry: RunLogEntry) {
    logs.value.push(entry)
    if (logs.value.length > 400) logs.value.splice(0, logs.value.length - 400)
  }

  return {
    running,
    error,
    output,
    outputText,
    elapsed,
    runId,
    failedRunId,
    nodeStatus,
    nodeElapsed,
    nodeOutputs,
    tokens,
    logs,
    start,
    stop,
    reset
  }
})
