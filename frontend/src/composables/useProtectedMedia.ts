import { ref, watch, type Ref } from 'vue'
import { fetchPlatformFile, platformFileUrl } from '../utils/protectedFiles'

/** Revoke blobs and cancel stale downloads when output changes or the component is disposed. */
export function useProtectedMedia(sources: Ref<string[]>) {
  const urls = ref<Record<string, string>>({})
  const error = ref('')
  watch(sources, (items, _old, onCleanup) => {
    const controller = new AbortController()
    const allocated: string[] = []
    urls.value = {}
    error.value = ''
    onCleanup(() => {
      controller.abort()
      allocated.forEach(url => URL.revokeObjectURL(url))
    })
    for (const source of new Set(items)) {
      if (!platformFileUrl(source)) {
        urls.value[source] = source
        continue
      }
      void fetchPlatformFile(source, controller.signal).then(blob => {
        if (controller.signal.aborted) return
        const url = URL.createObjectURL(blob)
        allocated.push(url)
        urls.value[source] = url
      }).catch(reason => {
        if (!controller.signal.aborted) error.value = reason?.message || '文件预览失败'
      })
    }
  }, { immediate: true })
  return { urls, error }
}
