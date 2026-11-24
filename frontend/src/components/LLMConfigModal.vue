<template>
  <a-button v-if="!visible" title="模型配置管理" @click="modalVisible = true">
    <template #icon><SettingOutlined /></template>
    模型管理
  </a-button>

  <a-modal
    title="全局模型配置管理"
    :open="modalVisible"
    :footer="null"
    :width="1100"
    :style="{ maxWidth: 'calc(100vw - 32px)' }"
    @cancel="handleCloseModal"
  >
    <div class="mb-4">
      <a-button type="primary" @click="handleOpenForm()">
        <template #icon><PlusOutlined /></template>
        新增配置
      </a-button>
      <div class="text-xs text-gray-500 mt-2">
        每条配置保存一组 API 地址、密钥和模型能力；联网搜索请在“MCP 工具”中添加 Agent Plan Harness 工具。
      </div>
    </div>

    <a-table
      :columns="columns"
      :data-source="configs"
      row-key="id"
      :loading="loading"
      :pagination="false"
      size="small"
      table-layout="fixed"
      :scroll="{ x: 1080 }"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'provider'">
          {{ getProviderLabel(asConfig(record).provider) }}
        </template>
        <template v-else-if="column.key === 'capabilities'">
          {{ getCapabilitySummary(asConfig(record)) }}
        </template>
        <template v-else-if="column.key === 'action'">
          <a-space size="small">
            <a-button type="link" size="small" @click="handleOpenForm(asConfig(record))">
              <template #icon><EditOutlined /></template>
              编辑
            </a-button>
            <a-popconfirm title="确定要删除此配置吗？" ok-text="确定" cancel-text="取消" @confirm="handleDelete(asConfig(record).id)">
              <a-button type="link" size="small" danger>
                <template #icon><DeleteOutlined /></template>
                删除
              </a-button>
            </a-popconfirm>
          </a-space>
        </template>
      </template>
    </a-table>

    <a-modal
      :title="editingConfig ? '编辑配置' : '新增配置'"
      :open="formVisible"
      :confirm-loading="loading"
      ok-text="保存"
      cancel-text="取消"
      :width="680"
      @cancel="handleCloseForm"
      @ok="handleSubmit"
    >
      <a-form ref="formRef" :model="formModel" layout="vertical" autocomplete="off">
        <a-form-item
          name="provider"
          label="提供商"
          :rules="providerRules"
          extra="支持直接手填，也可以从已有供应商中选择。"
        >
          <a-auto-complete
            v-model:value="formModel.provider"
            placeholder="请输入或选择提供商"
            :options="providerOptions"
            :disabled="!!editingConfig"
            :filter-option="filterProviderOption"
          />
        </a-form-item>

        <a-form-item name="apiUrl" label="API 地址" :rules="[{ required: true, message: '请输入 API 地址' }]">
          <a-input v-model:value="formModel.apiUrl" placeholder="例如: https://api.openai.com, https://api.stepfun.com/v1" />
        </a-form-item>

        <a-form-item name="apiKey" label="API 密钥" :rules="[{ required: true, message: '请输入 API 密钥' }]">
          <a-input-password v-model:value="formModel.apiKey" placeholder="输入 API 密钥" />
        </a-form-item>

        <a-form-item name="model" label="默认 LLM 模型" :rules="[{ required: true, message: '请输入默认模型' }]">
          <a-input v-model:value="formModel.model" placeholder="例如: gpt-4.1, deepseek-chat, step-3.5-flash-2603" />
        </a-form-item>

        <div class="config-capability-section">
          <div class="config-capability-section-title">能力配置</div>
          <a-select
            :key="capabilityPickerKey"
            placeholder="添加 TTS、向量、记忆、图片、视频等能力"
            :value="undefined"
            :options="capabilityOptions"
            style="width: 100%"
            @change="addCapability"
          />
          <div v-if="activeCapabilities.length === 0" class="config-capability-empty">
            当前只保存基础大模型配置，需要 TTS、RAG、记忆或视觉生成时再添加对应能力。
          </div>

          <div v-for="key in activeCapabilities" :key="key" class="config-capability-row">
            <div class="config-capability-head">
              <div>
                <div class="config-capability-title">{{ capabilityDefinition(key)?.label }}</div>
                <div class="config-capability-desc">{{ capabilityDefinition(key)?.description }}</div>
              </div>
              <a-button type="text" size="small" :title="`移除${capabilityDefinition(key)?.label}`" @click="removeCapability(key)">
                <template #icon><CloseOutlined /></template>
              </a-button>
            </div>

            <a-form-item
              v-if="key === 'tts'"
              name="ttsModel"
              label="默认 TTS 模型"
              :rules="[{ required: true, message: '请输入 TTS 模型' }]"
            >
              <a-input v-model:value="formModel.ttsModel" placeholder="例如: qwen3-tts-flash, stepaudio-2.5-tts" />
            </a-form-item>

            <a-form-item
              v-if="key === 'embedding'"
              name="embeddingModel"
              label="默认向量模型"
              :rules="[{ required: true, message: '请输入向量模型' }]"
            >
              <a-input v-model:value="formModel.embeddingModel" placeholder="doubao-embedding-vision" />
            </a-form-item>

            <a-form-item v-if="key === 'memory'" name="memoryEnabled" class="config-capability-switch">
              <a-checkbox v-model:checked="formModel.memoryEnabled">启用记忆能力</a-checkbox>
            </a-form-item>

            <a-form-item
              v-if="key === 'image'"
              name="imageModel"
              label="默认图片模型"
              :rules="[{ required: true, message: '请输入图片模型' }]"
            >
              <a-input v-model:value="formModel.imageModel" placeholder="例如: step-image-edit-2, step-1x-medium, seedream 相关图片生成模型" />
            </a-form-item>

            <a-form-item
              v-if="key === 'video'"
              name="videoModel"
              label="默认视频模型"
              :rules="[{ required: true, message: '请输入视频模型' }]"
            >
              <a-input v-model:value="formModel.videoModel" placeholder="例如: agnes-video-v2.0, seedance 相关视频生成模型" />
            </a-form-item>
          </div>
        </div>
      </a-form>
    </a-modal>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance } from 'ant-design-vue'
import { message } from 'ant-design-vue'
import {
  CloseOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  SettingOutlined,
} from '@ant-design/icons-vue'
import { storeToRefs } from 'pinia'
import { useLLMConfigStore } from '../stores/llmConfig'
import type { LLMConfigRequest, LLMGlobalConfig } from '../api/llmConfig'
import { getProviderLabel, normalizeProviderKey } from '../utils/provider'

const props = defineProps<{ visible?: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'qwen', label: '通义千问' },
  { value: 'step', label: '阶跃星辰' },
  { value: 'agnes', label: 'Agnes AI' },
  { value: 'apifree', label: 'APIFree / SkyClaw' },
  { value: 'volcengine_agent_plan', label: '火山方舟 Agent Plan' },
]

type CapabilityKey = 'tts' | 'embedding' | 'memory' | 'image' | 'video'

const CAPABILITIES: Array<{ key: CapabilityKey; label: string; description: string }> = [
  { key: 'tts', label: 'TTS 模型', description: '给音频合成节点提供默认语音模型。' },
  { key: 'embedding', label: '向量模型', description: '用于知识库索引、RAG 和记忆召回。' },
  { key: 'memory', label: '记忆能力', description: '给 Agent 启用跨轮次上下文召回。' },
  { key: 'image', label: '图片生成', description: '给图片生成工具提供默认模型。' },
  { key: 'video', label: '视频生成', description: '给视频生成工具提供默认模型。' },
]

const store = useLLMConfigStore()
const { configs, loading, error } = storeToRefs(store)
const { fetchAllConfigs, saveConfig, deleteConfig, clearError } = store

const modalVisible = ref(props.visible || false)
const formVisible = ref(false)
const editingConfig = ref<LLMGlobalConfig | null>(null)
const activeCapabilities = ref<CapabilityKey[]>([])
const capabilityPickerKey = ref(0)
const formRef = ref<FormInstance>()

const formModel = reactive({
  provider: '',
  apiUrl: '',
  apiKey: '',
  model: '',
  ttsModel: undefined as string | undefined,
  embeddingModel: undefined as string | undefined,
  imageModel: undefined as string | undefined,
  videoModel: undefined as string | undefined,
  memoryEnabled: false,
})

const providerOptions = computed(() =>
  Array.from(
    new Map(
      [
        ...PROVIDERS,
        ...configs.value.map((config) => ({
          value: normalizeProviderKey(config.provider),
          label: getProviderLabel(config.provider),
        })),
      ].map((item) => [normalizeProviderKey(item.value), item])
    ).values()
  ).map((item) => ({
    value: normalizeProviderKey(item.value),
    label: item.label,
  }))
)

const capabilityOptions = computed(() =>
  CAPABILITIES.filter((item) => !activeCapabilities.value.includes(item.key)).map((item) => ({
    value: item.key,
    label: `${item.label} - ${item.description}`,
  }))
)

const providerRules = [
  { required: true, message: '请输入或选择提供商' },
  {
    validator: (_rule: unknown, value: string) =>
      value && String(value).trim()
        ? Promise.resolve()
        : Promise.reject(new Error('请输入或选择提供商')),
  },
]

const columns = [
  { title: '提供商', dataIndex: 'provider', key: 'provider', ellipsis: true, width: 88 },
  { title: 'API 地址', dataIndex: 'apiUrl', key: 'apiUrl', ellipsis: true, width: 210 },
  { title: '模型', dataIndex: 'model', key: 'model', width: 170 },
  { title: '能力', key: 'capabilities', width: 300, ellipsis: true },
  { title: '操作', key: 'action', width: 96 },
]

watch(modalVisible, (value) => {
  if (value) {
    fetchAllConfigs()
  }
})

watch(
  () => props.visible,
  (value) => {
    if (value !== undefined) {
      modalVisible.value = value
    }
  }
)

watch(error, (value) => {
  if (value) {
    message.error(value)
    clearError()
  }
})

const filterProviderOption = (inputValue: string, option: { value?: string; label?: string } | undefined) =>
  (option?.value ?? '').toLowerCase().includes(inputValue.toLowerCase()) ||
  String(option?.label ?? '').toLowerCase().includes(inputValue.toLowerCase())

const handleCloseModal = () => {
  modalVisible.value = false
  formVisible.value = false
  editingConfig.value = null
  formRef.value?.clearValidate()
  emit('close')
}

const resetFormModel = () => {
  Object.assign(formModel, {
    provider: '',
    apiUrl: '',
    apiKey: '',
    model: '',
    ttsModel: undefined,
    embeddingModel: undefined,
    imageModel: undefined,
    videoModel: undefined,
    memoryEnabled: false,
  })
}

const getCapabilitiesFromConfig = (config: LLMGlobalConfig): CapabilityKey[] => {
  const capabilities: CapabilityKey[] = []
  if (config.ttsModel) capabilities.push('tts')
  if (config.embeddingModel) capabilities.push('embedding')
  if (config.memoryEnabled === 1) capabilities.push('memory')
  if (config.imageModel) capabilities.push('image')
  if (config.videoModel) capabilities.push('video')
  return capabilities
}

const handleOpenForm = (config?: LLMGlobalConfig) => {
  editingConfig.value = config || null
  formVisible.value = true

  if (config) {
    activeCapabilities.value = getCapabilitiesFromConfig(config)
    Object.assign(formModel, {
      provider: config.provider,
      apiUrl: config.apiUrl,
      apiKey: config.apiKey,
      model: config.model,
      ttsModel: config.ttsModel,
      embeddingModel: config.embeddingModel,
      imageModel: config.imageModel,
      videoModel: config.videoModel,
      memoryEnabled: config.memoryEnabled === 1,
    })
  } else {
    activeCapabilities.value = []
    resetFormModel()
    formRef.value?.clearValidate()
  }
}

const handleCloseForm = () => {
  formVisible.value = false
  editingConfig.value = null
  activeCapabilities.value = []
  resetFormModel()
  formRef.value?.clearValidate()
}

const hasCapability = (key: CapabilityKey) => activeCapabilities.value.includes(key)

const capabilityDefinition = (key: CapabilityKey) => CAPABILITIES.find((item) => item.key === key)

const addCapability = (rawKey?: unknown) => {
  const key = rawKey as CapabilityKey | undefined
  if (!key || hasCapability(key)) return
  activeCapabilities.value = [...activeCapabilities.value, key]
  capabilityPickerKey.value += 1

  if (key === 'embedding' && !formModel.embeddingModel) {
    formModel.embeddingModel = 'doubao-embedding-vision'
  }
  if (key === 'memory') {
    formModel.memoryEnabled = true
    if (!formModel.embeddingModel) {
      formModel.embeddingModel = 'doubao-embedding-vision'
    }
  }
}

const removeCapability = (key: CapabilityKey) => {
  activeCapabilities.value = activeCapabilities.value.filter((item) => item !== key)

  if (key === 'tts') formModel.ttsModel = undefined
  if (key === 'embedding') formModel.embeddingModel = undefined
  if (key === 'image') formModel.imageModel = undefined
  if (key === 'video') formModel.videoModel = undefined
  if (key === 'memory') formModel.memoryEnabled = false
}

const handleSubmit = async () => {
  try {
    await formRef.value?.validate()
  } catch (validationError) {
    console.error('Form validation failed:', validationError)
    return
  }

  const provider = normalizeProviderKey(formModel.provider)
  const request: LLMConfigRequest = {
    id: editingConfig.value?.id,
    provider,
    configName:
      editingConfig.value?.configName ||
      buildInternalConfigName(provider, formModel.model, formModel.ttsModel),
    apiUrl: formModel.apiUrl,
    apiKey: formModel.apiKey,
    model: formModel.model,
    ttsModel: hasCapability('tts') ? formModel.ttsModel : undefined,
    embeddingModel: hasCapability('embedding') ? formModel.embeddingModel : undefined,
    imageModel: hasCapability('image') ? formModel.imageModel : undefined,
    videoModel: hasCapability('video') ? formModel.videoModel : undefined,
    memoryEnabled: hasCapability('memory') && formModel.memoryEnabled ? 1 : 0,
  }

  const result = await saveConfig(request)
  if (result) {
    message.success(editingConfig.value ? '配置已更新' : '配置已创建')
    handleCloseForm()
  }
}

const buildInternalConfigName = (provider: string, model?: string, ttsModel?: string) => {
  const modelPart = (model || ttsModel || 'model').trim().replace(/\s+/g, '-')
  return `${provider}-${modelPart}-${Date.now()}`
}

const asConfig = (record: unknown) => record as LLMGlobalConfig

const getCapabilitySummary = (record: LLMGlobalConfig) =>
  [
    record.ttsModel ? `TTS: ${record.ttsModel}` : '',
    record.embeddingModel ? `向量: ${record.embeddingModel}` : '',
    record.memoryEnabled === 1 ? '记忆' : '',
    record.imageModel ? `生图: ${record.imageModel}` : '',
    record.videoModel ? `生视频: ${record.videoModel}` : '',
  ]
    .filter(Boolean)
    .join(' / ') || '-'

const handleDelete = async (id: number) => {
  const success = await deleteConfig(id)
  if (success) {
    message.success('配置已删除')
  }
}
</script>
