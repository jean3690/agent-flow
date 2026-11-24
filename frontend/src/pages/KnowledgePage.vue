<template>
  <div class="knowledge-shell">
    <header class="knowledge-topbar">
      <div class="knowledge-title-group">
        <a-button @click="navigate('/editor')">
          <template #icon><ArrowLeftOutlined /></template>
          工作流
        </a-button>
        <div>
          <div class="knowledge-kicker">Resource</div>
          <h2>知识库</h2>
        </div>
      </div>
      <a-button type="primary" @click="createOpen = true">
        <template #icon><PlusOutlined /></template>
        新建知识库
      </a-button>
    </header>

    <div class="knowledge-layout">
      <aside class="knowledge-sidebar">
        <a-input-search placeholder="搜索知识库" allow-clear />
        <a-list :loading="loading" :data-source="bases">
          <template #renderItem="{ item: base }">
            <a-list-item
              class="knowledge-base-item"
              :class="{ 'is-active': selectedBaseId === base.id }"
              @click="selectedBaseId = base.id"
            >
              <div class="knowledge-base-icon"><DatabaseOutlined /></div>
              <div class="knowledge-base-body">
                <div class="knowledge-base-name">{{ base.name }}</div>
                <div class="knowledge-muted">{{ base.documentCount || 0 }} 文档 · {{ base.chunkCount || 0 }} 分片</div>
              </div>
              <a-tag :color="statusColor[base.status] || 'default'">{{ statusText[base.status] || base.status }}</a-tag>
            </a-list-item>
          </template>
        </a-list>
      </aside>

      <main class="knowledge-main">
        <template v-if="selectedBase">
          <section class="knowledge-detail-header">
            <div>
              <h1>{{ selectedBase.name }}</h1>
              <p>{{ selectedBase.description || '暂无描述' }}</p>
            </div>
            <a-space>
              <a-button @click="importOpen = true">
                <template #icon><CloudUploadOutlined /></template>
                导入数据
              </a-button>
              <a-popconfirm title="确认删除该知识库？" @confirm="handleDeleteBase">
                <a-button danger>删除</a-button>
              </a-popconfirm>
            </a-space>
          </section>

          <section class="knowledge-metrics">
            <div><span>文档数</span><strong>{{ selectedBase.documentCount || 0 }}</strong></div>
            <div><span>分片数</span><strong>{{ selectedBase.chunkCount || 0 }}</strong></div>
            <div><span>字符数</span><strong>{{ selectedBase.charCount || 0 }}</strong></div>
            <div><span>切分策略</span><strong>{{ selectedBase.chunkSize }}/{{ selectedBase.chunkOverlap }}</strong></div>
          </section>

          <a-tabs>
            <a-tab-pane key="documents" tab="文档">
              <a-table
                row-key="id"
                :columns="documentColumns"
                :data-source="selectedBase.documents || []"
                :pagination="false"
              >
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'title'">
                    <a-space direction="vertical" :size="2">
                      <span class="knowledge-doc-title">{{ record.title }}</span>
                      <span class="knowledge-muted">{{ record.sourceType }} · {{ record.charCount || 0 }} 字符</span>
                    </a-space>
                  </template>
                  <template v-else-if="column.key === 'status'">
                    <a-tag :color="statusColor[record.status] || 'default'">
                      {{ statusText[record.status] || record.status }}
                    </a-tag>
                  </template>
                  <template v-else-if="column.key === 'action'">
                    <a-space>
                      <a-button size="small" @click="handlePreview(asDocument(record))">分片预览</a-button>
                      <a-button size="small" type="primary" @click="handleIndex(asDocument(record))">建立索引</a-button>
                    </a-space>
                  </template>
                </template>
              </a-table>
            </a-tab-pane>

            <a-tab-pane key="search" tab="检索测试">
              <div class="knowledge-search-panel">
                <a-space-compact class="knowledge-search-box">
                  <a-input
                    v-model:value="searchQuery"
                    placeholder="输入问题，测试召回效果"
                    @press-enter="handleSearch"
                  />
                  <a-button type="primary" @click="handleSearch">
                    <template #icon><SearchOutlined /></template>
                    检索
                  </a-button>
                </a-space-compact>
                <a-list
                  v-if="searchResult"
                  class="knowledge-search-results"
                  :data-source="searchResult.chunks || []"
                >
                  <template #renderItem="{ item: chunk }">
                    <a-list-item>
                      <div>
                        <div class="knowledge-doc-title">{{ chunk.title || `Chunk ${chunk.chunkId}` }}</div>
                        <div class="knowledge-muted">score {{ Number(chunk.score || 0).toFixed(3) }}</div>
                        <p>{{ chunk.content }}</p>
                      </div>
                    </a-list-item>
                  </template>
                </a-list>
              </div>
            </a-tab-pane>

            <a-tab-pane key="tasks" tab="索引任务">
              <a-list :data-source="selectedBase.recentTasks || []">
                <template #renderItem="{ item: task }">
                  <a-list-item>
                    <a-space direction="vertical" class="w-full">
                      <a-space>
                        <a-tag :color="statusColor[task.status] || 'default'">
                          {{ statusText[task.status] || task.status }}
                        </a-tag>
                        <span>文档 #{{ task.documentId }}</span>
                        <span>{{ task.finishedChunks }}/{{ task.totalChunks }} 分片</span>
                      </a-space>
                      <a-progress :percent="task.progress || 0" size="small" />
                      <span v-if="task.errorMessage" class="knowledge-error">{{ task.errorMessage }}</span>
                    </a-space>
                  </a-list-item>
                </template>
              </a-list>
            </a-tab-pane>
          </a-tabs>
        </template>

        <div v-else class="knowledge-empty">
          <DatabaseOutlined />
          <p>暂无知识库，先新建一个用于 RAG 的知识库。</p>
        </div>
      </main>
    </div>

    <a-modal title="新建知识库" :open="createOpen" :width="620" @ok="handleCreate" @cancel="createOpen = false">
      <a-form ref="createFormRef" :model="createFormModel" layout="vertical">
        <a-form-item name="name" label="知识库名称" :rules="[{ required: true, message: '请输入知识库名称' }]">
          <a-input v-model:value="createFormModel.name" :maxlength="20" placeholder="例如：产品 FAQ" />
        </a-form-item>
        <a-form-item name="description" label="知识库描述">
          <a-textarea v-model:value="createFormModel.description" :rows="3" :maxlength="200" placeholder="说明内容范围、适用工作流和维护规则" />
        </a-form-item>
        <a-form-item name="configId" label="Agent Plan 配置">
          <a-select
            v-model:value="createFormModel.configId"
            allow-clear
            option-label-prop="label"
            placeholder="可选。用于建立向量索引"
          >
            <a-select-option
              v-for="config in agentPlanConfigs"
              :key="config.id"
              :value="config.id"
              :label="getAgentPlanConfigLabel(config)"
            >
              <a-space direction="vertical" :size="0">
                <span>{{ getAgentPlanConfigLabel(config) }}</span>
                <span v-if="getAgentPlanConfigHint(config)" class="knowledge-muted">
                  {{ getAgentPlanConfigHint(config) }}
                </span>
              </a-space>
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-space class="knowledge-form-row" align="start">
          <a-form-item name="embeddingModel" label="向量模型">
            <a-input v-model:value="createFormModel.embeddingModel" placeholder="doubao-embedding-vision" />
          </a-form-item>
          <a-form-item name="chunkSize" label="分片长度">
            <a-input-number v-model:value="createFormModel.chunkSize" :min="100" :max="4000" />
          </a-form-item>
          <a-form-item name="chunkOverlap" label="重叠长度">
            <a-input-number v-model:value="createFormModel.chunkOverlap" :min="0" :max="1000" />
          </a-form-item>
        </a-space>
      </a-form>
    </a-modal>

    <a-modal title="导入数据" :open="importOpen" :footer="null" :width="720" @cancel="importOpen = false">
      <a-tabs>
        <a-tab-pane key="text" tab="粘贴文本">
          <a-form ref="importFormRef" :model="importFormModel" layout="vertical">
            <a-form-item name="title" label="标题">
              <a-input v-model:value="importFormModel.title" placeholder="未命名文本" />
            </a-form-item>
            <a-form-item name="tags" label="标签">
              <a-input v-model:value="importFormModel.tags" placeholder="多个标签用逗号分隔" />
            </a-form-item>
            <a-form-item name="content" label="文本内容" :rules="[{ required: true, message: '请输入文本内容' }]">
              <a-textarea v-model:value="importFormModel.content" :rows="10" placeholder="粘贴 FAQ、说明文档、业务规则等内容" />
            </a-form-item>
            <a-button type="primary" @click="handleImportText">导入文本</a-button>
          </a-form>
        </a-tab-pane>

        <a-tab-pane key="file" tab="上传文件">
          <div>
            <a-upload-dragger
              accept=".txt,.md,.markdown"
              :before-upload="beforeUploadFile"
              :max-count="1"
            >
              <p class="ant-upload-drag-icon"><FileTextOutlined /></p>
              <p class="ant-upload-text">拖拽文本文件到这里，或点击选择文件</p>
              <p class="ant-upload-hint">当前版本支持 txt、md、markdown</p>
            </a-upload-dragger>
            <a-button class="knowledge-upload-submit" type="primary" @click="handleUploadFile">
              上传并导入
            </a-button>
          </div>
        </a-tab-pane>
      </a-tabs>
    </a-modal>

    <a-modal
      :title="`分片预览 ${previewDocument?.title || ''}`"
      :open="previewOpen"
      :footer="null"
      :width="820"
      @cancel="previewOpen = false"
    >
      <a-list :data-source="previewChunks">
        <template #renderItem="{ item: chunk }">
          <a-list-item>
            <div class="knowledge-chunk-preview">
              <div class="knowledge-muted">#{{ chunk.chunkIndex + 1 }} · {{ chunk.charCount }} 字符</div>
              <p>{{ chunk.content }}</p>
            </div>
          </a-list-item>
        </template>
      </a-list>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  ArrowLeftOutlined,
  CloudUploadOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  PlusOutlined,
  SearchOutlined,
} from '@ant-design/icons-vue'
import { useRouter } from 'vue-router'
import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  getKnowledgeBase,
  getKnowledgeBases,
  importKnowledgeText,
  indexKnowledgeDocument,
  previewKnowledgeChunks,
  searchKnowledgeBase,
  uploadKnowledgeTextFile,
  type KnowledgeBase,
  type KnowledgeChunkPreview,
  type KnowledgeDocument,
  type KnowledgeSearchResult,
} from '../api/knowledge'
import { useLLMConfigStore } from '../stores/llmConfig'
import { getProviderLabel, normalizeProviderKey } from '../utils/provider'

const statusColor: Record<string, string> = {
  DRAFT: 'default',
  IMPORTED: 'processing',
  CHUNKED: 'cyan',
  RUNNING: 'processing',
  READY: 'success',
  SUCCESS: 'success',
  FAILED: 'error',
}

const statusText: Record<string, string> = {
  DRAFT: '草稿',
  IMPORTED: '已导入',
  CHUNKED: '已分片',
  RUNNING: '索引中',
  READY: '可检索',
  SUCCESS: '完成',
  FAILED: '失败',
}

const router = useRouter()
const navigate = (path: string) => router.push(path)

const llmConfigStore = useLLMConfigStore()
const llmConfigs = computed(() => llmConfigStore.configs)
const fetchAllConfigs = llmConfigStore.fetchAllConfigs

const bases = ref<KnowledgeBase[]>([])
const selectedBaseId = ref<number | null>(null)
const selectedBase = ref<KnowledgeBase | null>(null)
const loading = ref(false)
const createOpen = ref(false)
const importOpen = ref(false)
const previewOpen = ref(false)
const previewChunks = ref<KnowledgeChunkPreview[]>([])
const previewDocument = ref<KnowledgeDocument | null>(null)
const selectedFile = ref<File | null>(null)
const searchQuery = ref('')
const searchResult = ref<KnowledgeSearchResult | null>(null)

const createFormModel = reactive({
  name: '',
  description: '',
  configId: undefined as number | undefined,
  embeddingModel: 'doubao-embedding-vision',
  chunkSize: 800,
  chunkOverlap: 100,
})

const importFormModel = reactive({
  title: '',
  tags: '',
  content: '',
})

const agentPlanConfigs = computed(() =>
  llmConfigs.value.filter((config) => normalizeProviderKey(config.provider) === 'volcengine_agent_plan')
)

const asDocument = (record: unknown) => record as KnowledgeDocument

const documentColumns = [
  { title: '文档', dataIndex: 'title', key: 'title' },
  { title: '状态', dataIndex: 'status', key: 'status', width: 110 },
  { title: '操作', key: 'action', width: 220 },
]

const getAgentPlanConfigLabel = (config: { provider: string; model?: string; embeddingModel?: string; configName?: string }) => {
  const providerLabel = getProviderLabel(config.provider)
  const modelName =
    config.model?.trim() || config.embeddingModel?.trim() || cleanInternalConfigName(config.configName, config.provider)

  return modelName ? `${providerLabel} · ${modelName}` : providerLabel
}

const getAgentPlanConfigHint = (config: { embeddingModel?: string; memoryEnabled?: number }) =>
  [
    config.embeddingModel ? `向量: ${config.embeddingModel}` : '',
    config.memoryEnabled === 1 ? '记忆已启用' : '',
  ]
    .filter(Boolean)
    .join(' / ')

const cleanInternalConfigName = (configName?: string, provider?: string) => {
  if (!configName) return ''

  let name = configName.trim()
  const providerPrefixes = [
    provider,
    normalizeProviderKey(provider),
    'volcengine_agent_plan',
    'agent_plan',
    'volcengine',
    'ark',
  ].filter(Boolean) as string[]

  const matchedPrefix = providerPrefixes.find((prefix) => name.toLowerCase().startsWith(`${prefix.toLowerCase()}-`))
  if (matchedPrefix) {
    name = name.slice(matchedPrefix.length + 1)
  }

  return name.replace(/-\d{10,}$/, '')
}

const loadBases = async () => {
  loading.value = true
  try {
    const result = await getKnowledgeBases()
    if (result.code === 200) {
      bases.value = result.data
      if (!selectedBaseId.value && result.data.length > 0) {
        selectedBaseId.value = result.data[0].id
      }
    }
  } catch (error) {
    message.error(`加载知识库失败: ${error instanceof Error ? error.message : '网络错误'}`)
  } finally {
    loading.value = false
  }
}

const loadBaseDetail = async (id: number) => {
  try {
    const result = await getKnowledgeBase(id)
    if (result.code === 200) {
      selectedBase.value = result.data
    }
  } catch (error) {
    message.error(`加载知识库详情失败: ${error instanceof Error ? error.message : '网络错误'}`)
  }
}

const handleCreate = async () => {
  if (!createFormModel.name.trim()) {
    message.warning('请输入知识库名称')
    return
  }
  const result = await createKnowledgeBase(createFormModel)
  if (result.code === 200) {
    message.success('知识库创建成功')
    createOpen.value = false
    createFormModel.name = ''
    createFormModel.description = ''
    createFormModel.configId = undefined
    createFormModel.embeddingModel = 'doubao-embedding-vision'
    createFormModel.chunkSize = 800
    createFormModel.chunkOverlap = 100
    await loadBases()
    selectedBaseId.value = result.data.id
  }
}

const handleImportText = async () => {
  if (!selectedBaseId.value) return
  if (!importFormModel.content.trim()) {
    message.warning('请输入文本内容')
    return
  }
  const result = await importKnowledgeText(selectedBaseId.value, importFormModel)
  if (result.code === 200) {
    message.success('文本已导入，下一步可预览分片并建立索引')
    importOpen.value = false
    importFormModel.title = ''
    importFormModel.tags = ''
    importFormModel.content = ''
    await loadBaseDetail(selectedBaseId.value)
  }
}

const beforeUploadFile = (file: File) => {
  selectedFile.value = file
  return false
}

const handleUploadFile = async () => {
  if (!selectedBaseId.value || !selectedFile.value) {
    message.warning('请选择 txt 或 md 文件')
    return
  }
  const result = await uploadKnowledgeTextFile(selectedBaseId.value, selectedFile.value)
  if (result.code === 200) {
    message.success('文件已导入，下一步可预览分片并建立索引')
    importOpen.value = false
    selectedFile.value = null
    await loadBaseDetail(selectedBaseId.value)
  }
}

const handlePreview = async (document: KnowledgeDocument) => {
  if (!selectedBaseId.value) return
  const result = await previewKnowledgeChunks(selectedBaseId.value, document.id)
  if (result.code === 200) {
    previewDocument.value = document
    previewChunks.value = result.data
    previewOpen.value = true
  }
}

const handleIndex = async (document: KnowledgeDocument) => {
  if (!selectedBaseId.value) return
  const result = await indexKnowledgeDocument(selectedBaseId.value, document.id)
  if (result.code === 200) {
    const task = result.data
    if (task.status === 'FAILED') {
      message.error(task.errorMessage || '索引失败')
    } else {
      message.success('索引建立完成')
    }
    await loadBases()
    await loadBaseDetail(selectedBaseId.value)
  }
}

const handleSearch = async () => {
  if (!selectedBaseId.value || !searchQuery.value.trim()) {
    message.warning('请输入检索问题')
    return
  }
  const result = await searchKnowledgeBase(selectedBaseId.value, {
    query: searchQuery.value,
    topK: 5,
    scoreThreshold: 0,
  })
  if (result.code === 200) {
    searchResult.value = result.data
  }
}

const handleDeleteBase = async () => {
  if (!selectedBaseId.value) return
  const result = await deleteKnowledgeBase(selectedBaseId.value)
  if (result.code === 200) {
    message.success('知识库已删除')
    selectedBase.value = null
    selectedBaseId.value = null
    await loadBases()
  }
}

watch(selectedBaseId, (id) => {
  if (id) {
    loadBaseDetail(id)
  }
})

onMounted(() => {
  fetchAllConfigs()
  loadBases()
})
</script>
