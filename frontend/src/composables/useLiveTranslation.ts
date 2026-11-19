import { computed, onBeforeUnmount, ref } from 'vue'
import http, { API_BASE_URL } from '../api/request'

export type LiveStatus = 'idle' | 'connecting' | 'listening' | 'finishing' | 'finished' | 'error'
export interface LiveConfig {
  provider: 'qwen' | 'mock'
  targetLang: string
  apiHost: string
  outputAudio: boolean
}
export interface Caption { id: string; text: string; done: boolean }

export function websocketUrl() {
  const url = new URL(API_BASE_URL + '/translations/realtime/ws', window.location.href)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

export function useLiveTranslation() {
  const status = ref<LiveStatus>('idle')
  const error = ref('')
  const mock = ref(false)
  const originals = ref<Caption[]>([])
  const translations = ref<Caption[]>([])
  const usage = ref<Record<string, number>>({})
  const busy = computed(() => ['connecting', 'listening', 'finishing'].includes(status.value))
  let epoch = 0
  let socket: WebSocket | undefined
  let media: MediaStream | undefined
  let context: AudioContext | undefined
  let capture: AudioWorkletNode | undefined
  let source: MediaStreamAudioSourceNode | undefined
  let playbackAt = 0
  let flushResolve: (() => void) | undefined
  let readyTimer: ReturnType<typeof setTimeout> | undefined
  let finishTimer: ReturnType<typeof setTimeout> | undefined

  function stopCapture() {
    source?.disconnect()
    capture?.disconnect()
    media?.getTracks().forEach(track => track.stop())
    source = undefined
    capture = undefined
    media = undefined
    flushResolve?.()
    flushResolve = undefined
  }

  function clearTimers() {
    clearTimeout(readyTimer)
    clearTimeout(finishTimer)
  }

  function dispose() {
    epoch++
    clearTimers()
    stopCapture()
    socket?.close()
    socket = undefined
    void context?.close().catch(() => {})
    context = undefined
    playbackAt = 0
  }

  function fail(message: string) {
    error.value = message
    status.value = 'error'
    dispose()
  }

  function caption(list: Caption[], event: any, done: boolean) {
    const id = String(event.itemId || 'current')
    let item = list.find(item => item.id === id)
    if (!item) {
      if (list.length >= 500) throw new Error('字幕条数超过上限，请结束后重新开始')
      item = { id, text: '', done: false }
      list.push(item)
    }
    if (done) item.text = String(event.text || '')
    else if (!item.done) item.text += String(event.delta || '')
    item.done ||= done
  }

  function playAudio(encoded: string) {
    if (!context) return
    const bytes = Uint8Array.from(atob(encoded), value => value.charCodeAt(0))
    if (bytes.length % 2) throw new Error('译音 PCM 数据不完整')
    const audio = context.createBuffer(1, bytes.length / 2, 24000)
    const values = audio.getChannelData(0)
    const view = new DataView(bytes.buffer)
    for (let i = 0; i < values.length; i++) values[i] = view.getInt16(i * 2, true) / 32768
    if (playbackAt - context.currentTime > 30) throw new Error('译音播放积压超过 30 秒，请重新开始')
    const player = context.createBufferSource()
    player.buffer = audio
    player.connect(context.destination)
    const start = Math.max(context.currentTime + 0.03, playbackAt)
    player.start(start)
    playbackAt = start + audio.duration
  }

  async function start(config: LiveConfig) {
    if (busy.value) return
    dispose()
    const current = epoch
    originals.value = []
    translations.value = []
    usage.value = {}
    error.value = ''
    status.value = 'connecting'
    mock.value = config.provider === 'mock'
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
        throw new Error('麦克风翻译需要 HTTPS 或 localhost，以及支持 AudioWorklet 的浏览器')
      }
      // Create/resume the audio context within the user's click, before network awaits.
      context = new AudioContext()
      await context.resume()
      const stream = await navigator.mediaDevices.getUserMedia({ audio: {
        channelCount: 1, echoCancellation: true, noiseSuppression: true
      } })
      if (current !== epoch) { stream.getTracks().forEach(track => track.stop()); return }
      media = stream
      await context.audioWorklet.addModule(import.meta.env.BASE_URL + 'pcm-capture.js')
      if (current !== epoch) return
      capture = new AudioWorkletNode(context, 'pcm-capture', { numberOfOutputs: 0 })
      source = context.createMediaStreamSource(stream)
      const session = await http.post<any, { ticket: string; mock: boolean }>('/translations/realtime/sessions', config)
      if (current !== epoch) return
      const ws = new WebSocket(websocketUrl())
      socket = ws
      const processor = capture
      const input = source
      processor.port.onmessage = ({ data }) => {
        if (current !== epoch) return
        if (data.flushed) { flushResolve?.(); flushResolve = undefined; return }
        if (!data.audio || !['listening', 'finishing'].includes(status.value)) return
        if (ws.readyState !== WebSocket.OPEN || ws.bufferedAmount > 64 * 1024) {
          fail('网络发送积压，已停止录音；请检查网络后重新开始')
          return
        }
        const bytes = new Uint8Array(data.audio)
        const encoded = btoa(String.fromCharCode(...bytes))
        ws.send(JSON.stringify({ type: 'audio', audio: encoded }))
      }
      readyTimer = setTimeout(() => { if (current === epoch) fail('连接翻译服务超时，请检查业务空间域名与模型权限') }, 30000)
      ws.onopen = () => {
        if (current === epoch) ws.send(JSON.stringify({ type: 'connect', ticket: session.ticket }))
      }
      ws.onmessage = ({ data }) => {
        if (current !== epoch) return
        try {
          const event = JSON.parse(data)
          if (event.type === 'session.ready') {
            clearTimeout(readyTimer)
            mock.value = event.mock
            status.value = 'listening'
            input.connect(processor)
            finishTimer = setTimeout(() => { void finish() }, 600000)
          } else if (event.type === 'transcript.delta') caption(originals.value, event, false)
          else if (event.type === 'transcript.done') caption(originals.value, event, true)
          else if (event.type === 'translation.delta') caption(translations.value, event, false)
          else if (event.type === 'translation.done') caption(translations.value, event, true)
          else if (event.type === 'audio.delta' && config.outputAudio) playAudio(event.delta)
          else if (event.type === 'usage') usage.value = event.usage || {} // cumulative, not additive
          else if (event.type === 'session.finished') {
            status.value = 'finished'
            clearTimers()
            stopCapture()
            ws.close() // AudioContext stays alive to finish scheduled translation playback.
          } else if (event.type === 'error') fail(event.message || '翻译服务返回错误')
        } catch (cause) { fail(cause instanceof Error ? cause.message : '翻译事件格式错误') }
      }
      ws.onerror = () => { if (current === epoch) fail('无法连接实时翻译服务，请检查服务状态') }
      ws.onclose = () => {
        if (current === epoch && status.value !== 'finished') fail('翻译连接提前中断，结果可能不完整')
      }
    } catch (cause) {
      if (current === epoch) fail(cause instanceof Error ? cause.message : '无法启动麦克风翻译')
    }
  }

  async function finish() {
    if (status.value !== 'listening') return
    const current = epoch
    status.value = 'finishing'
    clearTimeout(finishTimer)
    source?.disconnect()
    await new Promise<void>(resolve => {
      const timer = setTimeout(resolve, 1000)
      flushResolve = () => { clearTimeout(timer); resolve() }
      capture?.port.postMessage('flush')
    })
    if (current !== epoch) return
    stopCapture()
    socket?.send(JSON.stringify({ type: 'finish' }))
    finishTimer = setTimeout(() => { if (current === epoch) fail('等待最终翻译结果超时') }, 60000)
  }

  function cancel() { dispose(); status.value = 'idle' }
  onBeforeUnmount(dispose)
  return { status, busy, error, mock, originals, translations, usage, start, finish, cancel }
}
