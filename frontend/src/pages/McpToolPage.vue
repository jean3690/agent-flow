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
          <h2>MCP 工具</h2>
        </div>
      </div>
      <a-button type="primary" @click="createOpen = true">
        <template #icon><PlusOutlined /></template>
        添加 Agent Plan 联网搜索
      </a-button>
    </header>

    <div class="knowledge-layout">
      <aside class="knowledge-sidebar">
        <a-list :loading="loading" :data-source="tools">
          <template #renderItem="{ item: tool }">
            <a-list-item class="knowledge-base-item">
              <div class="knowledge-base-icon"><ApiOutlined /></div>
              <div class="knowledge-base-body">
                <div class="knowledge-base-name">{{ tool.name }}</div>
                <div class="knowledge-muted">{{ tool.toolName }} · {{ tool.transport }}</div>
              </div>
              <a-tag :color="tool.enabled === 1 ? 'success' : 'default'">{{ tool.enabled === 1 ? '启用' : '停用' }}</a-tag>
            </a-list-item>
          </template>
        </a-list>
      </aside>

      <main class="knowledge-main">
        <div class="knowledge-panel">
          <div class="knowledge-panel-header">
            <div>
              <div class="knowledge-kicker">MCP Runtime</div>
              <h3>工具配置</h3>
            </div>
          </div>
          <a-list :data-source="tools" :locale="{ emptyText: '还没有 MCP 工具，先添加 Agent Plan 联网搜索' }">
            <template #renderItem="{ item: tool }">
              <a-list-item>
                <template #actions>
                  <a-button key="test" @click="handleOpenTest(tool)">
                    <template #icon><SearchOutlined /></template>
                    测试
                  </a-button>
                  <a-popconfirm key="delete" title="删除这个 MCP 工具？" @confirm="handleDelete(tool.id)">
                    <a-button danger>
                      <template #icon><DeleteOutlined /></template>
                      删除
                    </a-button>
                  </a-popconfirm>
                </template>
                <a-list-item-meta>
                  <template #avatar>
                    <div class="knowledge-base-icon"><ApiOutlined /></div>
                  </template>
                  <template #title>
                    <a-space>
                      <span>{{ tool.name }}</span>
                      <a-tag>{{ tool.toolType }}</a-tag>
                      <a-tag v-if="tool.preset === 1" color="blue">预设</a-tag>
                    </a-space>
                  </template>
                  <template #description>
                    <a-space direction="vertical" :size="4">
                      <span>{{ tool.description || '未填写描述' }}</span>
                      <a-typography-text code>{{ tool.command }} {{ tool.args.join(' ') }}</a-typography-text>
                      <span class="knowledge-muted">
                        Env: {{ Object.keys(tool.env || {}).join(', ') || '无' }}
                      </span>
                    </a-space>
                  </template>
                </a-list-item-meta>
              </a-list-item>
            </template>
          </a-list>
        </div>
      </main>
    </div>

    <a-modal
      title="添加 Agent Plan 联网搜索 MCP"
      :open="createOpen"
      :ok-text="'添加'"
      :width="640"
      @cancel="createOpen = false"
      @ok="handleCreateAgentPlanSearch"
    >
      <a-form :model="createFormModel" layout="vertical">
        <a-form-item name="name" label="名称" :rules="[{ required: true, message: '请输入名称' }]">
          <a-input v-model:value="createFormModel.name" />
        </a-form-item>
        <a-form-item name="description" label="描述">
          <a-textarea v-model:value="createFormModel.description" :rows="2" placeholder="可选，用于区分不同 Agent Plan key 或额度来源" />
        </a-form-item>
        <a-form-item name="apiKey" label="联网搜索 API Key" :rules="[{ required: true, message: '请输入联网搜索 API Key' }]">
          <a-input-password v-model:value="createFormModel.apiKey" placeholder="来自 Agent Plan 使用配置 / 配置 Harness 的联网搜索 API Key" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      :title="`测试 ${testingTool?.name || ''}`"
      :open="testOpen"
      :ok-text="'调用'"
      :confirm-loading="testLoading"
      :width="860"
      @cancel="testOpen = false"
      @ok="handleTest"
    >
      <a-form :model="testFormModel" layout="vertical">
        <a-form-item name="query" label="搜索 Query" :rules="[{ required: true, message: '请输入搜索 Query' }]">
          <a-input v-model:value="testFormModel.query" />
        </a-form-item>
      </a-form>

      <div v-if="testResult" class="mcp-test-result">
        <div class="mcp-test-summary">
          <a-space wrap>
            <a-tag color="success">调用成功</a-tag>
            <span>返回 {{ resultCount }} 条结果</span>
            <a-typography-text v-if="requestId" type="secondary">RequestId: {{ requestId }}</a-typography-text>
          </a-space>
        </div>

        <a-list v-if="webResults.length > 0" class="mcp-test-result-list" :data-source="webResults">
          <template #renderItem="{ item, index }">
            <a-list-item>
              <a-list-item-meta>
                <template #title>
                  <a-space :size="8" wrap>
                    <a-tag>{{ item.sortId || index + 1 }}</a-tag>
                    <a-typography-link v-if="item.url" :href="item.url" target="_blank" rel="noreferrer">
                      {{ item.title || item.url }}
                    </a-typography-link>
                    <span v-else>{{ item.title || '未命名结果' }}</span>
                    <a-tag v-if="item.siteName" color="blue">{{ item.siteName }}</a-tag>
                  </a-space>
                </template>
                <template #description>
                  <a-space direction="vertical" :size="4">
                    <a-typography-text v-if="item.url" type="secondary">{{ item.url }}</a-typography-text>
                    <a-typography-paragraph class="mcp-test-snippet">
                      {{ truncateText(item.summary || item.snippet || '没有摘要') }}
                    </a-typography-paragraph>
                  </a-space>
                </template>
              </a-list-item-meta>
            </a-list-item>
          </template>
        </a-list>

        <a-typography-paragraph v-else class="mcp-test-snippet">
          {{ typeof testResult.summary === 'string' ? testResult.summary : '没有可展示的搜索结果' }}
        </a-typography-paragraph>

        <details class="mcp-test-raw">
          <summary>查看原始返回</summary>
          <pre>{{ JSON.stringify(testResult, null, 2) }}</pre>
        </details>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  ApiOutlined,
  ArrowLeftOutlined,
  DeleteOutlined,
  PlusOutlined,
  SearchOutlined,
} from '@ant-design/icons-vue'
import { useRouter } from 'vue-router'
import {
  createAgentPlanWebSearchMcp,
  deleteMcpTool,
  getMcpTools,
  testMcpTool,
  type McpToolConfig,
} from '../api/mcpTools'

interface WebSearchResultItem {
  title?: string
  siteName?: string
  url?: string
  snippet?: string
  summary?: string
  sortId?: number
}

const router = useRouter()
const navigate = (path: string) => router.push(path)

const tools = ref<McpToolConfig[]>([])
const loading = ref(false)
const createOpen = ref(false)
const testOpen = ref(false)
const testingTool = ref<McpToolConfig | null>(null)
const testResult = ref<Record<string, unknown> | null>(null)
const testLoading = ref(false)

const createFormModel = reactive({
  name: 'Agent Plan 联网搜索',
  description: '',
  apiKey: '',
})

const testFormModel = reactive({
  query: '',
})

const loadTools = async () => {
  loading.value = true
  try {
    const result = await getMcpTools()
    if (result.code === 200) {
      tools.value = result.data
    }
  } catch (error) {
    message.error(`加载 MCP 工具失败: ${error instanceof Error ? error.message : '网络错误'}`)
  } finally {
    loading.value = false
  }
}

const handleCreateAgentPlanSearch = async () => {
  if (!createFormModel.name.trim()) {
    message.warning('请输入名称')
    return
  }
  if (!createFormModel.apiKey.trim()) {
    message.warning('请输入联网搜索 API Key')
    return
  }

  const result = await createAgentPlanWebSearchMcp({
    name: createFormModel.name,
    description: createFormModel.description,
    apiKey: createFormModel.apiKey,
  })
  if (result.code === 200) {
    message.success('Agent Plan 联网搜索 MCP 已添加')
    createOpen.value = false
    createFormModel.name = 'Agent Plan 联网搜索'
    createFormModel.description = ''
    createFormModel.apiKey = ''
    await loadTools()
  }
}

const handleDelete = async (id: number) => {
  const result = await deleteMcpTool(id)
  if (result.code === 200) {
    message.success('MCP 工具已删除')
    await loadTools()
  }
}

const handleOpenTest = (tool: McpToolConfig) => {
  testingTool.value = tool
  testResult.value = null
  testFormModel.query = '沉默王二 人物 外貌'
  testOpen.value = true
}

const handleTest = async () => {
  if (!testingTool.value) return
  if (!testFormModel.query.trim()) {
    message.warning('请输入搜索 Query')
    return
  }

  testLoading.value = true
  try {
    const result = await testMcpTool(testingTool.value.id, { query: testFormModel.query })
    if (result.code === 200) {
      testResult.value = result.data
      message.success('MCP 工具调用成功')
    }
  } finally {
    testLoading.value = false
  }
}

const webResults = computed<WebSearchResultItem[]>(() => {
  const result = testResult.value
  if (!result || !Array.isArray(result.webResults)) {
    return []
  }
  return (result.webResults as unknown[])
    .filter((item): item is Record<string, unknown> => item !== null && typeof item === 'object')
    .map((item) => ({
      title: String(item.title || ''),
      siteName: String(item.siteName || ''),
      url: String(item.url || ''),
      snippet: String(item.snippet || ''),
      summary: String(item.summary || ''),
      sortId: typeof item.sortId === 'number' ? item.sortId : undefined,
    }))
})

const requestId = computed(() =>
  typeof testResult.value?.requestId === 'string' ? (testResult.value.requestId as string) : ''
)

const resultCount = computed(() => {
  const value = testResult.value?.resultCount
  return typeof value === 'number' ? value : webResults.value.length
})

const truncateText = (text: string, maxLength = 360) => {
  if (!text || text.length <= maxLength) return text
  return `${text.slice(0, maxLength)}...`
}

onMounted(loadTools)
</script>
