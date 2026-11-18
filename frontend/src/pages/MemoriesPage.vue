<template>
  <IntegrationShell title="记忆" description="工作流执行中写入的长期记忆。工作流范围只在本流程内召回，用户范围跟随账号，全局范围所有人可见。">
    <template #actions>
      <div>
        <el-select v-model="scope" placeholder="全部范围" clearable style="width:150px" @change="load">
          <el-option label="工作流" value="workflow" />
          <el-option label="用户" value="user" />
          <el-option label="全局" value="global" />
        </el-select>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </template>
    <section class="integration__editor" v-loading="loading">
      <el-table :data="memories" empty-text="还没有记忆。在工作流里加入「写入记忆」节点并执行一次即可生成。" style="width:100%">
        <el-table-column label="范围" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="scopeType(row.scope)">{{ scopeLabel(row.scope) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="memoryType" label="类型" width="90" />
        <el-table-column prop="content" label="内容" min-width="280" show-overflow-tooltip />
        <el-table-column label="标签" width="160">
          <template #default="{ row }">
            <el-tag v-for="tag in row.tags" :key="tag" size="small" effect="plain" style="margin-right:4px">{{ tag }}</el-tag>
            <span v-if="!row.tags?.length" class="af-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="sourceNodeId" label="来源节点" width="130" />
        <el-table-column label="写入时间" width="170">
          <template #default="{ row }">{{ formatTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </IntegrationShell>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import IntegrationShell from '../components/IntegrationShell.vue'
import { memoryApi } from '../api'
import type { MemoryItem } from '../types'

const memories = ref<MemoryItem[]>([])
const loading = ref(false)
const scope = ref('')

function scopeLabel(value: string) {
  return { workflow: '工作流', user: '用户', global: '全局' }[value] || value
}
function scopeType(value: string) {
  return value === 'global' ? 'danger' : value === 'user' ? 'warning' : 'success'
}
function formatTime(value?: string) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 19)
}
async function load() {
  loading.value = true
  try {
    memories.value = await memoryApi.list(scope.value)
  } finally {
    loading.value = false
  }
}
async function remove(row: MemoryItem) {
  try {
    await ElMessageBox.confirm('删除后该条记忆不再参与召回，确定删除？', '删除记忆', { type: 'warning' })
  } catch {
    return
  }
  await memoryApi.remove(row.id)
  ElMessage.success('记忆已删除')
  await load()
}
onMounted(load)
</script>
