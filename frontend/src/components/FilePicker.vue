<template>
  <div class="file-picker">
    <el-input v-model="text" :placeholder="placeholder" clearable>
      <template #append>
        <el-button @click="open">浏览</el-button>
      </template>
    </el-input>

    <el-dialog v-model="visible" title="选择文件" width="640px" append-to-body>
      <div class="file-picker__bar">
        <el-input
          v-model="prefix"
          placeholder="按路径前缀筛选"
          clearable
          style="width: 220px"
          @change="load"
        />
        <div class="file-picker__actions">
          <el-button :loading="loading" @click="load">刷新</el-button>
          <el-button type="primary" @click="pickUpload">上传文件</el-button>
          <input ref="uploadInput" type="file" style="display: none" @change="onUpload" />
        </div>
      </div>

      <el-table
        :data="files"
        v-loading="loading"
        height="320"
        size="small"
        empty-text="存储目录还没有文件"
      >
        <el-table-column prop="name" label="路径" min-width="220" show-overflow-tooltip />
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ humanSize(row.size) }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="160">
          <template #default="{ row }">{{ formatTime(row.updatedAt) }}</template>
        </el-table-column>
        <el-table-column label="" width="70" align="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="choose(row)">选择</el-button>
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <el-button @click="visible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fileApi } from '../api'
import type { FileItem } from '../types'

const props = defineProps<{ modelValue?: string; placeholder?: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()

const text = computed({
  get: () => props.modelValue || '',
  set: (value: string) => emit('update:modelValue', value)
})

const visible = ref(false)
const loading = ref(false)
const files = ref<FileItem[]>([])
const prefix = ref('')
const uploadInput = ref<HTMLInputElement | null>(null)

async function load() {
  loading.value = true
  try {
    files.value = await fileApi.list(prefix.value)
  } finally {
    loading.value = false
  }
}

function open() {
  visible.value = true
  load()
}

function choose(row: FileItem) {
  text.value = row.path
  visible.value = false
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
    const meta = await fileApi.upload(file, prefix.value ? prefix.value.replace(/\/+$/, '') + '/' + file.name : file.name)
    ElMessage.success('已上传 ' + meta.path)
    text.value = meta.path
    await load()
  } catch {
    /* interceptor 已提示 */
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
</script>

<style scoped>
.file-picker {
  width: 100%;
}

.file-picker__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.file-picker__actions {
  display: flex;
  gap: 8px;
}
</style>
