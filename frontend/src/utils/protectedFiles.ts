import { API_BASE_URL, TOKEN_KEY } from '../api/request'

/** Only platform file URLs are fetched with credentials; remote media never receives our JWT. */
export function platformFileUrl(reference: string): string | null {
  if (reference.startsWith('/files/')) return API_BASE_URL + reference
  if (reference.startsWith('/api/files/')) return API_BASE_URL + reference.slice(4)
  try {
    const api = new URL(API_BASE_URL + '/', location.origin)
    const candidate = new URL(reference, location.origin)
    return candidate.origin === api.origin && candidate.pathname.startsWith(api.pathname + 'files/')
      ? candidate.href : null
  } catch {
    return null
  }
}

export async function fetchPlatformFile(reference: string, signal?: AbortSignal): Promise<Blob> {
  const url = platformFileUrl(reference)
  if (!url) throw new Error('不是平台文件地址')
  const token = localStorage.getItem(TOKEN_KEY)
  if (!token) throw new Error('文件预览需要登录')
  const controller = new AbortController()
  const cancel = () => controller.abort()
  signal?.addEventListener('abort', cancel, { once: true })
  if (signal?.aborted) controller.abort()
  const timer = window.setTimeout(cancel, 30000)
  try {
    const response = await fetch(url, { headers: { Authorization: 'Bearer ' + token }, signal: controller.signal })
    if (response.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      if (!location.hash.includes('/login')) location.hash = '#/login'
    }
    if (!response.ok) throw new Error('文件不可访问（HTTP ' + response.status + '）')
    return await response.blob()
  } finally {
    window.clearTimeout(timer)
    signal?.removeEventListener('abort', cancel)
  }
}
