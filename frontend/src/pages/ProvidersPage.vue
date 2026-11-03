<template>
  <div class="providers">
    <header class="providers__bar">
      <div class="providers__brand">
        <el-button link @click="router.push('/')">← 工作流</el-button>
        <span class="providers__name">AgentFlow</span>
        <span class="providers__tag">模型服务商</span>
      </div>
      <div class="providers__right">
        <span class="af-muted">{{ authStore.user?.nickname || authStore.user?.username }}</span>
        <el-button link @click="logout">退出</el-button>
      </div>
    </header>

    <main class="providers__main">
      <div class="providers__head">
        <div>
          <h1>模型服务商</h1>
          <p class="af-muted">
            Key 只保存在 Java 服务端，执行工作流时下发到 AI 服务，不会回传前端；留空 Key 表示沿用环境变量。
          </p>
        </div>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>

      <div v-loading="loading" class="providers__grid">
        <section v-for="item in providers" :key="item.provider" class="af-card providers__card">
          <div class="providers__card-head">
            <div>
              <div class="providers__label">{{ item.label }}</div>
              <div class="providers__meta mono">{{ item.provider }} · {{ item.defaultModel }}</div>
            </div>
            <el-tag size="small" :type="tagType(item)">{{ tagText(item) }}</el-tag>
          </div>

          <template v-if="item.provider !== 'mock'">
            <el-form label-position="top" size="small" class="providers__form">
              <el-form-item label="API Key">
                <el-input
                  v-model="forms[item.provider].apiKey"
                  type="password"
                  show-password
                  autocomplete="new-password"
                  :placeholder="item.apiKeyMasked ? `已保存 ${item.apiKeyMasked}，留空不修改` : '粘贴服务商 API Key'"
                />
              </el-form-item>
              <el-form-item label="Base URL（可选，OpenAI 兼容）">
                <el-input v-model="forms[item.provider].baseUrl" :placeholder="item.baseUrl || '使用服务商默认地址'" />
              </el-form-item>
            </el-form>

            <div class="providers__actions">
              <el-button size="small" type="primary" :loading="saving[item.provider]" @click="save(item)">保存</el-button>
              <el-button size="small" :loading="testing[item.provider]" @click="test(item)">测试连接</el-button>
              <el-button v-if="item.source === 'DB'" size="small" link type="danger" @click="clear(item)">清除</el-button>
            </div>

            <div v-if="item.source === 'ENV'" class="providers__hint">当前使用环境变量中的 Key，保存后将优先生效。</div>
            <div v-else-if="item.source === 'DB'" class="providers__hint">已保存到数据库（{{ item.apiKeyMasked }}）。</div>
          </template>

          <div v-else class="providers__hint">本地演示服务商，无需 Key，用于跑通链路。</div>
        </section>

        <div v-if="!loading && !providers.length" class="providers__empty">
          AI 服务不可用或未返回服务商列表，请确认 ai-service 已启动。
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { llmProviderApi } from '../api'
import { useAuthStore } from '../stores/auth'
import type { LlmProvider } from '../types'

const router = useRouter()
const authStore = useAuthStore()

const providers = ref<LlmProvider[]>([])
const loading = ref(false)
const saving = reactive<Record<string, boolean>>({})
const testing = reactive<Record<string, boolean>>({})
const forms = reactive<Record<string, { apiKey: string; baseUrl: string }>>({})

async function load() {
  loading.value = true
  try {
    const list = await llmProviderApi.list()
    Object.keys(forms).forEach((key) => delete forms[key])
    for (const item of list) {
      forms[item.provider] = { apiKey: '', baseUrl: item.baseUrl || '' }
    }
    providers.value = list
  } finally {
    loading.value = false
  }
}

function tagType(item: LlmProvider) {
  if (item.source === 'DB') return 'success'
  if (item.source === 'ENV') return 'warning'
  return item.configured ? 'info' : 'info'
}

function tagText(item: LlmProvider) {
  if (item.source === 'DB') return '已保存'
  if (item.source === 'ENV') return '环境变量'
  return item.configured ? '内置' : '未配置'
}

async function save(item: LlmProvider) {
  const form = forms[item.provider]
  if (!form.apiKey.trim() && item.source !== 'DB') {
    ElMessage.warning('请填写 API Key')
    return
  }
  saving[item.provider] = true
  try {
    await llmProviderApi.save(item.provider, {
      apiKey: form.apiKey.trim(),
      baseUrl: form.baseUrl.trim()
    })
    ElMessage.success(item.label + ' 配置已保存')
    await load()
  } finally {
    saving[item.provider] = false
  }
}

async function test(item: LlmProvider) {
  const form = forms[item.provider]
  testing[item.provider] = true
  try {
    const result = await llmProviderApi.test(item.provider, {
      apiKey: form.apiKey.trim(),
      baseUrl: form.baseUrl.trim()
    })
    if (result.ok) {
      ElMessage.success(`连接成功${result.latencyMs ? `，${result.latencyMs} ms` : ''}`)
    } else {
      ElMessage.error('连接失败：' + (result.message || '未知错误'))
    }
  } finally {
    testing[item.provider] = false
  }
}

async function clear(item: LlmProvider) {
  await ElMessageBox.confirm(`清除 ${item.label} 已保存的 Key？`, '确认', { type: 'warning' })
  await llmProviderApi.clear(item.provider)
  ElMessage.success('已清除')
  await load()
}

function logout() {
  authStore.logout()
  router.replace('/login')
}

onMounted(load)
</script>

<style scoped>
.providers {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.providers__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  height: 54px;
  border-bottom: 1px solid #262a36;
  background: #10131a;
}

.providers__brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.providers__name {
  font-weight: 600;
  font-size: 13px;
}

.providers__tag {
  font-size: 11px;
  color: #6b7387;
  padding-left: 10px;
  border-left: 1px solid #262a36;
}

.providers__right {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.providers__main {
  flex: 1;
  overflow: auto;
  padding: 32px clamp(24px, 6vw, 84px);
}

.providers__head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 20px;
}

.providers__head h1 {
  margin: 0;
  font-size: 26px;
  letter-spacing: -0.01em;
}

.providers__head p {
  margin: 6px 0 0;
  font-size: 13px;
  max-width: 720px;
}

.providers__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
  min-height: 200px;
}

.providers__card {
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.providers__card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.providers__label {
  font-size: 14px;
  font-weight: 600;
}

.providers__meta {
  margin-top: 3px;
  font-size: 11px;
  color: #6b7387;
}

.providers__form :deep(.el-form-item) {
  margin-bottom: 10px;
}

.providers__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.providers__hint {
  font-size: 11px;
  color: #6b7387;
  line-height: 1.6;
}

.providers__empty {
  grid-column: 1 / -1;
  padding: 40px 0;
  text-align: center;
  font-size: 13px;
  color: #6b7387;
}
</style>
