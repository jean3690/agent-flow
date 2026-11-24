import { buildBackendUrl } from '../config/api'

export const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

export const parseJsonIfPossible = (value: string) => {
  try {
    return JSON.parse(value) as unknown
  } catch {
    return value
  }
}

export const normalizeValue = (value: unknown): unknown =>
  typeof value === 'string' ? parseJsonIfPossible(value) : value

const IMAGE_URL_PATTERN = /\.(png|jpe?g|gif|webp|bmp|svg)(?:[?#].*)?$/i
const AUDIO_URL_PATTERN = /\.(mp3|wav|ogg|m4a|aac|flac)(?:[?#].*)?$/i
const VIDEO_URL_PATTERN = /\.(mp4|webm|mov|m4v)(?:[?#].*)?$/i

export const normalizeMediaUrl = (url: string) =>
  url.startsWith('/') ? buildBackendUrl(url) : url

const isLikelyImageUrl = (value: string) =>
  IMAGE_URL_PATTERN.test(value) || value.includes('/images/') || value.includes('/image/')

const isLikelyAudioUrl = (value: string) =>
  AUDIO_URL_PATTERN.test(value) || value.startsWith('/audio/') || value.includes('/audio/')

const isLikelyVideoUrl = (value: string) =>
  VIDEO_URL_PATTERN.test(value) || value.includes('/videos/') || value.includes('/video/')

const extractAudioSrc = (value: string) => {
  if (!value.includes('<audio') || !value.includes('src=')) {
    return null
  }
  const srcMatch = value.match(/src=["']([^"']+)["']/)
  return srcMatch?.[1] || null
}

const extractUrls = (value: string) =>
  value.match(/https?:\/\/[^\s"'<>，。；；)）]+|\/[^\s"'<>，。；；)）]+/g) || []

const uniqueUrls = (urls: string[]) =>
  Array.from(
    new Set(
      urls
        .map((url) => url.trim())
        .filter(Boolean)
        .map(normalizeMediaUrl)
    )
  )

export const collectImageUrls = (value: unknown): string[] => {
  const normalized = normalizeValue(value)
  const record = isRecord(normalized) && isRecord(normalized.output) ? normalized.output : normalized

  if (typeof record === 'string') {
    return uniqueUrls(extractUrls(record).filter(isLikelyImageUrl))
  }

  if (!isRecord(record)) {
    return []
  }

  const urls: string[] = []
  const appendValue = (candidate: unknown) => {
    if (typeof candidate === 'string') {
      const extractedUrls = extractUrls(candidate).filter(isLikelyImageUrl)
      if (extractedUrls.length > 0) {
        urls.push(...extractedUrls)
      } else if (isLikelyImageUrl(candidate)) {
        urls.push(candidate)
      }
    } else if (Array.isArray(candidate)) {
      candidate.forEach(appendValue)
    }
  }

  appendValue(record.imageUrls)
  appendValue(record.images)
  appendValue(record.imageUrl)
  appendValue(record.image_url)
  appendValue(record.url)
  appendValue(record.output)

  return uniqueUrls(urls)
}

export const collectVideoUrls = (value: unknown): string[] => {
  const normalized = normalizeValue(value)
  const record = isRecord(normalized) && isRecord(normalized.output) ? normalized.output : normalized

  if (typeof record === 'string') {
    return uniqueUrls(extractUrls(record).filter(isLikelyVideoUrl))
  }

  if (!isRecord(record)) {
    return []
  }

  const urls: string[] = []
  const appendValue = (candidate: unknown) => {
    if (typeof candidate === 'string') {
      const extractedUrls = extractUrls(candidate).filter(isLikelyVideoUrl)
      if (extractedUrls.length > 0) {
        urls.push(...extractedUrls)
      } else if (isLikelyVideoUrl(candidate)) {
        urls.push(candidate)
      }
    } else if (Array.isArray(candidate)) {
      candidate.forEach(appendValue)
    }
  }

  appendValue(record.videoUrls)
  appendValue(record.videos)
  appendValue(record.videoUrl)
  appendValue(record.video_url)
  appendValue(record.url)
  appendValue(record.output)

  return uniqueUrls(urls)
}

export const collectAudioOutput = (value: unknown): { audioUrl: string; fileName?: string } | null => {
  const normalized = normalizeValue(value)
  const record = isRecord(normalized) && isRecord(normalized.output) ? normalized.output : normalized

  if (typeof record === 'string') {
    const embeddedSrc = extractAudioSrc(record)
    const audioUrl = embeddedSrc || (isLikelyAudioUrl(record) ? record : null)
    return audioUrl ? { audioUrl: normalizeMediaUrl(audioUrl) } : null
  }

  if (!isRecord(record)) {
    return null
  }

  const fileName = typeof record.fileName === 'string' ? record.fileName : undefined
  const directAudioUrl =
    typeof record.audioUrl === 'string'
      ? record.audioUrl
      : typeof record.audio_url === 'string'
        ? record.audio_url
        : null

  if (directAudioUrl) {
    return { audioUrl: normalizeMediaUrl(directAudioUrl), fileName }
  }

  if (typeof record.output === 'string') {
    const embeddedSrc = extractAudioSrc(record.output)
    const audioUrl = embeddedSrc || (isLikelyAudioUrl(record.output) ? record.output : null)
    if (audioUrl) {
      return { audioUrl: normalizeMediaUrl(audioUrl), fileName }
    }
  }

  return null
}

export const getFriendlyOutputText = (value: unknown): string | null => {
  const normalizedValue = typeof value === 'string' ? parseJsonIfPossible(value) : value

  if (typeof normalizedValue === 'string') {
    return normalizedValue
  }

  if (isRecord(normalizedValue) && typeof normalizedValue.output === 'string') {
    return normalizedValue.output
  }

  return null
}

export const truncateText = (value: unknown, maxLength = 180) => {
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  if (!text) return ''
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text
}

const getToolTrace = (value: unknown): Record<string, unknown>[] => {
  const normalized = normalizeValue(value)
  const record = isRecord(normalized) && isRecord(normalized.output) ? normalized.output : normalized

  if (!isRecord(record) || !Array.isArray(record.toolTrace)) {
    return []
  }

  return record.toolTrace.filter((item): item is Record<string, unknown> => isRecord(item))
}

const summarizeToolInput = (toolInput: unknown) => {
  if (!isRecord(toolInput)) {
    return truncateText(toolInput, 120)
  }

  const query = typeof toolInput.query === 'string' ? toolInput.query : ''
  if (query) {
    return `query="${truncateText(query, 120)}"`
  }

  const urls = Array.isArray(toolInput.urls) ? toolInput.urls : undefined
  if (urls && urls.length > 0) {
    return `urls=${urls.length}`
  }

  return truncateText(toolInput, 120)
}

const summarizeObservation = (observation: unknown) => {
  if (!isRecord(observation)) {
    return truncateText(observation, 160)
  }

  if (typeof observation.error === 'string') {
    return `失败: ${truncateText(observation.error, 160)}`
  }

  const summary =
    typeof observation.summary === 'string'
      ? observation.summary
      : typeof observation.content === 'string'
        ? observation.content
        : ''
  const citations = Array.isArray(observation.citations) ? observation.citations.length : 0
  const results = Array.isArray(observation.results) ? observation.results.length : 0
  const parts = [
    summary ? `结果="${truncateText(summary, 120)}"` : '',
    results > 0 ? `results=${results}` : '',
    citations > 0 ? `citations=${citations}` : '',
  ].filter(Boolean)

  return parts.join('；') || truncateText(observation, 160)
}

export const formatToolTraceLog = (traceItem: Record<string, unknown>) => {
  const toolName = typeof traceItem.toolName === 'string' ? traceItem.toolName : ''
  if (!toolName) {
    return null
  }

  const step = typeof traceItem.step === 'number' ? `#${traceItem.step}` : ''
  const inputSummary = summarizeToolInput(traceItem.toolInput)
  const observationSummary = summarizeObservation(traceItem.observation)
  return `🔎 ReAct 工具调用${step ? ` ${step}` : ''}: ${toolName}${inputSummary ? ` | ${inputSummary}` : ''}${observationSummary ? ` | ${observationSummary}` : ''}`
}

export const formatToolTraceLogs = (output: unknown) =>
  getToolTrace(output)
    .map(formatToolTraceLog)
    .filter((log): log is string => Boolean(log))

export const formatDuration = (milliseconds: number | string | undefined | null) => {
  const ms = typeof milliseconds === 'string' ? Number.parseInt(milliseconds, 10) : milliseconds

  if (!Number.isFinite(ms) || !ms || ms <= 0) {
    return '0秒'
  }

  const totalSeconds = (ms as number) / 1000
  const minutes = Math.floor(totalSeconds / 60)
  let seconds = totalSeconds - minutes * 60

  if (minutes > 0) {
    seconds = Math.round(seconds)
    if (seconds === 60) {
      return `${minutes + 1}分0秒`
    }
    return `${minutes}分${seconds}秒`
  }

  if (totalSeconds < 10) {
    return `${Number(totalSeconds.toFixed(1))}秒`
  }

  return `${Math.round(totalSeconds)}秒`
}
