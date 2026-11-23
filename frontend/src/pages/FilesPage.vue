<template>
  <div class="files">
    <header class="files__bar">
      <div class="files__brand">
        <el-button link @click="router.push('/')">← 工作流</el-button>
        <span class="files__name">AgentFlow</span>
        <span class="files__tag">文件中心</span>
      </div>
      <div class="files__right">
        <span class="af-muted">{{ authStore.user?.nickname || authStore.user?.username }}</span>
        <el-button link @click="logout">退出</el-button>
      </div>
    </header>

    <main class="files__main">
      <div class="files__head">
        <div>
          <h1>文件</h1>
          <p class="af-muted">当前用户目录中的上传文件与节点产物，预览、下载和删除均需登录</p>
        </div>
        <div class="files__tools">
          <el-input
            v-model="prefix"
            placeholder="按路径前缀筛选，如 reports/"
            clearable
            style="width: 240px"
            @change="load"
          />
          <el-button :loading="loading" @click="load">刷新</el-button>
          <el-button @click="openText">新建文本</el-button>
          <el-button type="primary" @click="pickUpload">上传文件</el-button>
          <input ref="uploadInput" type="file" style="display: none" @change="onUpload" />
        </div>
      </div>

      <div class="af-card files__table">
        <el-table :data="files" v-loading="loading" style="width: 100%" empty-text="存储目录还没有文件">
          <el-table-column label="路径" min-width="260">
            <template #default="{ row }">
              <span class="files__path mono">{{ row.path }}</span>
              <div class="files__meta">{{ row.contentType }}</div>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="110">
            <template #default="{ row }">{{ humanSize(row.size) }}</template>
          </el-table-column>
          <el-table-column label="更新时间" width="180">
            <template #default="{ row }">{{ formatTime(row.updatedAt) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="220" align="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="preview(row)">预览</el-button>
              <el-button link @click="download(row)">下载</el-button>
              <el-button link type="danger" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="files__footer af-muted">共 {{ files.length }} 个文件</div>
      </div>
    </main>

    <el-dialog v-model="previewVisible" :title="previewTitle" width="720px">
      <div v-loading="previewLoading" class="files__preview">
        <img v-if="previewKind === 'image'" :src="previewUrl" class="files__preview-image" alt="预览" />
        <video v-else-if="previewKind === 'video'" :src="previewUrl" class="files__preview-video" controls />
        <audio v-else-if="previewKind === 'audio'" :src="previewUrl" controls />
        <pre v-else-if="previewKind === 'text'" class="mono files__preview-text">{{ previewText }}</pre>
        <div v-else class="files__preview-empty">该类型不支持在线预览，请下载后查看</div>
      </div>
      <template #footer>
        <el-button v-if="previewRow" @click="download(previewRow)">下载</el-button>
        <el-button @click="previewVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="textVisible" title="新建文本文件" width="560px">
      <el-form label-position="top">
        <el-form-item label="文件路径">
          <el-input v-model="textForm.name" placeholder="例如 reports/today.md" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="textForm.content" type="textarea" :rows="10" placeholder="写入文件的内容" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="textVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveText">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fileApi } from '../api'
import { fetchPlatformFile } from '../utils/protectedFiles'
import { useAuthStore } from '../stores/auth'
import type { FileItem } from '../types'

const router = useRouter()
const authStore = useAuthStore()

const files = ref<FileItem[]>([])
const loading = ref(false)
const prefix = ref('')
const uploadInput = ref<HTMLInputElement | null>(null)

const previewVisible = ref(false)
const previewLoading = ref(false)
const previewTitle = ref('')
const previewKind = ref<'text' | 'image' | 'video' | 'audio' | 'other'>('text')
const previewText = ref('')
const previewUrl = ref('')
const previewRow = ref<FileItem | null>(null)
let previewController: AbortController | null = null
let previewObjectUrl = ''
const pendingDownloads = new Set<AbortController>()

function releasePreview() {
  previewController?.abort()
  previewController = null
  if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl)
  previewObjectUrl = ''
  previewUrl.value = ''
  previewLoading.value = false
}
watch(previewVisible, visible => { if (!visible) releasePreview() })
onBeforeUnmount(() => {
  releasePreview()
  pendingDownloads.forEach(controller => controller.abort())
  pendingDownloads.clear()
})

const textVisible = ref(false)
const saving = ref(false)
const textForm = reactive({ name: '', content: '' })

async function load() {
  loading.value = true
  try {
    files.value = await fileApi.list(prefix.value)
  } finally {
    loading.value = false
  }
}

function pickUpload() {
  uploadInput.value?.click()
}

async function onUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  try {
    const meta = await fileApi.upload(file)
    ElMessage.success('已上传 ' + meta.path)
    await load()
  } catch {
    /* interceptor 已提示 */
  }
}

function openText() {
  textForm.name = ''
  textForm.content = ''
  textVisible.value = true
}

async function saveText() {
  if (!textForm.name.trim()) {
    ElMessage.warning('请填写文件路径')
    return
  }
  saving.value = true
  try {
    await fileApi.writeText({ name: textForm.name, content: textForm.content })
    textVisible.value = false
    ElMessage.success('已保存')
    await load()
  } finally {
    saving.value = false
  }
}

async function download(row: FileItem) {
  const controller = new AbortController()
  pendingDownloads.add(controller)
  try {
    const source = row.url || fileApi.url(row.path)
    const blob = await fetchPlatformFile(source + (source.includes('?') ? '&' : '?') + 'download=true', controller.signal)
    if (controller.signal.aborted) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = row.fileName
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (reason: any) {
    if (!controller.signal.aborted) ElMessage.error(reason?.message || '文件下载失败')
  } finally {
    pendingDownloads.delete(controller)
  }
}

async function remove(row: FileItem) {
  try {
    await ElMessageBox.confirm('确定删除 ' + row.path + ' ？', '删除文件', { type: 'warning' })
  } catch {
    return
  }
  await fileApi.remove(row.path)
  ElMessage.success('已删除')
  await load()
}

async function preview(row: FileItem) {
  releasePreview()
  const controller = new AbortController()
  previewController = controller
  const suffix = row.fileName.split('.').pop()?.toLowerCase() || ''
  previewRow.value = row
  previewTitle.value = row.path
  previewText.value = ''
  previewVisible.value = true
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(suffix)) {
    previewKind.value = 'image'
  } else if (['mp4', 'webm', 'mov'].includes(suffix)) {
    previewKind.value = 'video'
  } else if (['mp3', 'wav', 'ogg', 'm4a'].includes(suffix)) {
    previewKind.value = 'audio'
  } else if (['txt', 'md', 'markdown', 'json', 'csv', 'yaml', 'yml', 'xml', 'log', 'html'].includes(suffix)) {
    previewKind.value = 'text'
  } else {
    previewKind.value = 'other'
    return
  }
  previewLoading.value = true
  try {
    const blob = await fetchPlatformFile(row.url || fileApi.url(row.path), controller.signal)
    if (controller.signal.aborted) return
    if (previewKind.value === 'text') {
      const content = await blob.text()
      if (!controller.signal.aborted) previewText.value = content
    } else {
      previewObjectUrl = URL.createObjectURL(blob)
      previewUrl.value = previewObjectUrl
    }
  } catch (reason: any) {
    if (!controller.signal.aborted) {
      previewKind.value = 'text'
      previewText.value = reason?.message || '预览失败，请下载后查看'
    }
  } finally {
    if (!controller.signal.aborted) previewLoading.value = false
  }
}

function humanSize(size: number) {
  if (!size) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = size
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return value.toFixed(index ? 1 : 0) + ' ' + units[index]
}

function formatTime(value: number) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function logout() {
  authStore.logout()
  router.push('/login')
}

onMounted(load)
</script>

<style scoped>
.files {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.files__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  height: 54px;
  border-bottom: 1px solid #262a36;
  background: #10131a;
}

.files__brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.files__name {
  font-weight: 600;
  font-size: 13px;
}

.files__tag {
  font-size: 11px;
  color: #6b7387;
  padding-left: 10px;
  border-left: 1px solid #262a36;
}

.files__right {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.files__main {
  flex: 1;
  overflow: auto;
  padding: 32px clamp(24px, 6vw, 84px);
}

.files__head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 20px;
}

.files__head h1 {
  margin: 0;
  font-size: 26px;
}

.files__head p {
  margin: 6px 0 0;
  font-size: 13px;
}

.files__tools {
  display: flex;
  gap: 10px;
}

.files__table {
  padding: 8px 16px 12px;
}

.files__path {
  font-weight: 600;
}

.files__meta {
  margin-top: 2px;
  font-size: 11px;
  color: #6b7387;
}

.files__footer {
  padding-top: 10px;
  font-size: 12px;
  text-align: right;
}

.files__preview {
  max-height: 60vh;
  overflow: auto;
}

.files__preview-image,
.files__preview-video {
  max-width: 100%;
  max-height: 56vh;
  display: block;
  margin: 0 auto;
}

.files__preview-text {
  margin: 0;
  padding: 12px;
  border-radius: 8px;
  background: #11141c;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.files__preview-empty {
  padding: 40px 0;
  text-align: center;
  color: #6b7387;
  font-size: 13px;
}
</style>
