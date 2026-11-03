<template>
  <div class="knowledge">
    <header class="knowledge__bar">
      <div class="knowledge__brand">
        <el-button link @click="router.push('/')">← 工作流</el-button>
        <span class="knowledge__name">AgentFlow</span>
        <span class="knowledge__tag">知识库</span>
      </div>
      <div class="knowledge__right">
        <span class="af-muted">{{ authStore.user?.nickname || authStore.user?.username }}</span>
        <el-button link @click="logout">退出</el-button>
      </div>
    </header>

    <main class="knowledge__main">
      <aside class="knowledge__side">
        <div class="knowledge__side-head">
          <span>知识库</span>
          <el-button size="small" type="primary" @click="openCreate">新建</el-button>
        </div>
        <div class="knowledge__list">
          <div
            v-for="item in bases"
            :key="item.id"
            class="knowledge__item"
            :class="{ 'is-active': selected?.id === item.id }"
            @click="selectBase(item.id)"
          >
            <div class="knowledge__item-name">{{ item.name }}</div>
            <div class="knowledge__item-meta">{{ item.documentCount }} 篇 / {{ item.chunkCount }} 分片</div>
          </div>
          <div v-if="!bases.length" class="knowledge__empty-side">还没有知识库</div>
        </div>
      </aside>

      <section class="knowledge__panel">
        <div v-if="!selected" class="knowledge__empty">选择或创建左侧的知识库</div>

        <template v-else>
          <div class="knowledge__head af-card">
            <div class="knowledge__head-main">
              <div class="knowledge__title">{{ selected.name }}</div>
              <div class="knowledge__desc">{{ selected.description || '未填写描述' }}</div>
              <div class="knowledge__meta mono">
                {{ selected.embeddingProvider }} / {{ selected.embeddingModel }} ·
                chunk {{ selected.chunkSize }} / overlap {{ selected.chunkOverlap }}
              </div>
            </div>
            <div class="knowledge__actions">
              <el-button size="small" @click="openImport">导入文本</el-button>
              <el-button size="small" @click="pickFile">上传文件</el-button>
              <el-button size="small" type="danger" plain @click="removeBase">删除</el-button>
              <input ref="fileInput" type="file" accept=".txt,.md,.markdown" class="knowledge__file" @change="onFile" />
            </div>
          </div>

          <div class="knowledge__search af-card">
            <el-input v-model="searchQuery" placeholder="输入问题，测试检索效果" clearable @keyup.enter="search" />
            <el-input-number v-model="topK" :min="1" :max="10" controls-position="right" style="width: 120px" />
            <el-button type="primary" :loading="searching" @click="search">检索</el-button>
          </div>

          <div v-if="searchResults.length" class="knowledge__hits af-card">
            <div v-for="hit in searchResults" :key="hit.chunkId" class="knowledge__hit">
              <div class="knowledge__hit-head">
                <span>{{ hit.title }}</span>
                <span class="mono af-muted">score {{ hit.score.toFixed(3) }}</span>
              </div>
              <p>{{ hit.content }}</p>
            </div>
          </div>

          <div class="af-card knowledge__docs">
            <el-table :data="documents" v-loading="docsLoading" size="small" empty-text="还没有文档，先导入或上传">
              <el-table-column prop="title" label="文档" min-width="200" />
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag size="small" :type="statusType(row.status)">{{ row.status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="charCount" label="字符" width="90" />
              <el-table-column prop="chunkCount" label="分片" width="80" />
              <el-table-column label="创建时间" width="170">
                <template #default="{ row }">{{ formatDate(row.createdAt) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="190" align="right">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openPreview(row)">预览</el-button>
                  <el-button link @click="indexDoc(row)">建立索引</el-button>
                  <el-button link type="danger" @click="removeDoc(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </section>
    </main>

    <el-dialog v-model="createVisible" title="新建知识库" width="480px">
      <el-form label-position="top" size="small">
        <el-form-item label="名称">
          <el-input v-model="createForm.name" placeholder="例如：产品手册" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="Embedding 服务商">
          <el-select v-model="createForm.embeddingProvider" style="width: 100%">
            <el-option label="Mock（无需 Key，按词重叠检索）" value="mock" />
            <el-option label="OpenAI" value="openai" />
            <el-option label="通义千问" value="qwen" />
            <el-option label="智谱 GLM" value="zhipu" />
            <el-option label="AiPing" value="aiping" />
          </el-select>
          <div class="knowledge__hint">
            mock 不调用真实模型；选择其他服务商需先在「模型配置」保存对应 Key（需支持 embeddings 接口）。
          </div>
        </el-form-item>
        <el-form-item label="Embedding 模型">
          <el-input v-model="createForm.embeddingModel" placeholder="text-embedding-3-small" />
        </el-form-item>
        <div class="knowledge__row">
          <el-form-item label="分片大小">
            <el-input-number v-model="createForm.chunkSize" :min="200" :max="2000" :step="100" />
          </el-form-item>
          <el-form-item label="重叠长度">
            <el-input-number v-model="createForm.chunkOverlap" :min="0" :max="500" :step="20" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createBase">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importVisible" title="导入文本" width="640px">
      <el-form label-position="top" size="small">
        <el-form-item label="标题">
          <el-input v-model="importForm.title" placeholder="文档标题" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="importForm.content" type="textarea" :rows="12" placeholder="粘贴要入库的文本" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="submitImport">导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewVisible" :title="`分片预览 · ${previewTitle}`" width="760px">
      <div class="knowledge__preview">
        <div v-for="chunk in previewChunks" :key="chunk.chunkIndex" class="knowledge__chunk">
          <div class="af-muted mono">#{{ chunk.chunkIndex + 1 }} · {{ chunk.charCount }} 字符</div>
          <p>{{ chunk.content }}</p>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { knowledgeApi } from '../api'
import { useAuthStore } from '../stores/auth'
import type { KnowledgeBase, KnowledgeChunk, KnowledgeDocument, KnowledgeSearchHit } from '../types'

const router = useRouter()
const authStore = useAuthStore()

const bases = ref<KnowledgeBase[]>([])
const selected = ref<KnowledgeBase | null>(null)
const documents = ref<KnowledgeDocument[]>([])
const docsLoading = ref(false)

const createVisible = ref(false)
const creating = ref(false)
const createForm = reactive({
  name: '',
  description: '',
  embeddingProvider: 'mock',
  embeddingModel: 'text-embedding-3-small',
  chunkSize: 600,
  chunkOverlap: 80
})

const importVisible = ref(false)
const importing = ref(false)
const importForm = reactive({ title: '', content: '' })

const previewVisible = ref(false)
const previewTitle = ref('')
const previewChunks = ref<KnowledgeChunk[]>([])

const searchQuery = ref('')
const topK = ref(4)
const searching = ref(false)
const searchResults = ref<KnowledgeSearchHit[]>([])

const fileInput = ref<HTMLInputElement | null>(null)

async function loadBases(selectId?: number) {
  bases.value = await knowledgeApi.list()
  const target = selectId ? bases.value.find((item) => item.id === selectId) : selected.value
  if (target) {
    selected.value = bases.value.find((item) => item.id === target.id) || null
  }
  if (!selected.value && bases.value.length) {
    selected.value = bases.value[0]
  }
  if (selected.value) {
    await loadDocuments(selected.value.id)
  } else {
    documents.value = []
  }
}

async function loadDocuments(id: number) {
  docsLoading.value = true
  try {
    documents.value = await knowledgeApi.documents(id)
  } finally {
    docsLoading.value = false
  }
}

async function selectBase(id: number) {
  selected.value = bases.value.find((item) => item.id === id) || null
  searchResults.value = []
  if (selected.value) {
    await loadDocuments(selected.value.id)
  }
}

function openCreate() {
  createForm.name = ''
  createForm.description = ''
  createForm.embeddingProvider = 'mock'
  createForm.embeddingModel = 'text-embedding-3-small'
  createForm.chunkSize = 600
  createForm.chunkOverlap = 80
  createVisible.value = true
}

async function createBase() {
  if (!createForm.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  creating.value = true
  try {
    const created = await knowledgeApi.create({ ...createForm })
    createVisible.value = false
    selected.value = created
    await loadBases(created.id)
    ElMessage.success('知识库已创建')
  } finally {
    creating.value = false
  }
}

async function removeBase() {
  if (!selected.value) return
  await ElMessageBox.confirm(`删除知识库「${selected.value.name}」及其文档？`, '确认', { type: 'warning' })
  await knowledgeApi.remove(selected.value.id)
  selected.value = null
  documents.value = []
  searchResults.value = []
  await loadBases()
  ElMessage.success('已删除')
}

function openImport() {
  importForm.title = ''
  importForm.content = ''
  importVisible.value = true
}

async function submitImport() {
  if (!selected.value) return
  if (!importForm.content.trim()) {
    ElMessage.warning('请填写内容')
    return
  }
  importing.value = true
  try {
    await knowledgeApi.importText(selected.value.id, {
      title: importForm.title.trim() || '未命名文档',
      content: importForm.content
    })
    importVisible.value = false
    await refreshCurrent()
    ElMessage.success('已导入，下一步建立索引')
  } finally {
    importing.value = false
  }
}

function pickFile() {
  fileInput.value?.click()
}

async function onFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !selected.value) return
  await knowledgeApi.upload(selected.value.id, file)
  await refreshCurrent()
  ElMessage.success('文件已导入，下一步建立索引')
}

async function openPreview(document: KnowledgeDocument) {
  if (!selected.value) return
  previewChunks.value = await knowledgeApi.preview(selected.value.id, document.id)
  previewTitle.value = document.title
  previewVisible.value = true
}

async function indexDoc(document: KnowledgeDocument) {
  if (!selected.value) return
  const result = await knowledgeApi.index(selected.value.id, document.id)
  if (result.status === 'FAILED') {
    ElMessage.error(result.errorMessage || '索引失败')
  } else {
    ElMessage.success(`索引完成，共 ${result.chunkCount} 个分片`)
  }
  await refreshCurrent()
}

async function removeDoc(document: KnowledgeDocument) {
  if (!selected.value) return
  await ElMessageBox.confirm(`删除文档「${document.title}」？`, '确认', { type: 'warning' })
  await knowledgeApi.removeDocument(selected.value.id, document.id)
  await refreshCurrent()
}

async function search() {
  if (!selected.value) return
  if (!searchQuery.value.trim()) {
    ElMessage.warning('请输入检索内容')
    return
  }
  searching.value = true
  try {
    searchResults.value = await knowledgeApi.search(selected.value.id, {
      query: searchQuery.value.trim(),
      topK: topK.value
    })
    if (!searchResults.value.length) {
      ElMessage.info('没有检索到内容，确认文档已建立索引')
    }
  } finally {
    searching.value = false
  }
}

async function refreshCurrent() {
  if (!selected.value) return
  await loadBases(selected.value.id)
}

function statusType(status: string) {
  if (status === 'INDEXED') return 'success'
  if (status === 'FAILED') return 'danger'
  return 'info'
}

function formatDate(value?: string) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function logout() {
  authStore.logout()
  router.replace('/login')
}

onMounted(async () => {
  try {
    await loadBases()
  } catch {
    bases.value = []
  }
})
</script>

<style scoped>
.knowledge {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.knowledge__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  height: 54px;
  border-bottom: 1px solid #262a36;
  background: #10131a;
}

.knowledge__brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.knowledge__name {
  font-weight: 600;
  font-size: 13px;
}

.knowledge__tag {
  font-size: 11px;
  color: #6b7387;
  padding-left: 10px;
  border-left: 1px solid #262a36;
}

.knowledge__right {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.knowledge__main {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 16px;
  padding: 20px clamp(20px, 4vw, 56px);
  overflow: hidden;
}

.knowledge__side {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.knowledge__side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: #8b93a7;
  margin-bottom: 8px;
}

.knowledge__list {
  flex: 1;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.knowledge__item {
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid #232833;
  background: #14171f;
  cursor: pointer;
}

.knowledge__item:hover {
  border-color: #333a4a;
}

.knowledge__item.is-active {
  border-color: #6366f1;
  background: rgba(99, 102, 241, 0.12);
}

.knowledge__item-name {
  font-size: 13px;
  font-weight: 600;
}

.knowledge__item-meta {
  margin-top: 3px;
  font-size: 11px;
  color: #6b7387;
}

.knowledge__empty-side {
  padding: 16px 0;
  text-align: center;
  font-size: 12px;
  color: #4b5266;
}

.knowledge__panel {
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.knowledge__empty {
  padding: 60px 0;
  text-align: center;
  font-size: 13px;
  color: #6b7387;
}

.knowledge__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
}

.knowledge__title {
  font-size: 18px;
  font-weight: 600;
}

.knowledge__desc {
  margin-top: 4px;
  font-size: 12px;
  color: #8b93a7;
}

.knowledge__meta {
  margin-top: 6px;
  font-size: 11px;
  color: #6b7387;
}

.knowledge__actions {
  display: flex;
  gap: 8px;
  flex: none;
}

.knowledge__file {
  display: none;
}

.knowledge__search {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
}

.knowledge__hits {
  padding: 6px 16px 14px;
  max-height: 260px;
  overflow: auto;
}

.knowledge__hit {
  padding: 10px 0;
  border-bottom: 1px solid #232833;
}

.knowledge__hit:last-child {
  border-bottom: none;
}

.knowledge__hit-head {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
}

.knowledge__hit p {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: #c7ccd8;
  white-space: pre-wrap;
}

.knowledge__docs {
  padding: 6px 14px 12px;
}

.knowledge__row {
  display: flex;
  gap: 16px;
}

.knowledge__hint {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.6;
  color: #6b7387;
}

.knowledge__preview {
  max-height: 460px;
  overflow: auto;
}

.knowledge__chunk {
  padding: 10px 0;
  border-bottom: 1px solid #232833;
}

.knowledge__chunk p {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
}
</style>
