import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { LLMConfigRequest, LLMGlobalConfig } from '../api/llmConfig'
import {
  deleteConfig as deleteConfigApi,
  getAllConfigs,
  getConfigsByProvider as getConfigsByProviderApi,
  saveConfig as saveConfigApi,
  setDefaultConfig as setDefaultConfigApi,
} from '../api/llmConfig'

export const useLLMConfigStore = defineStore('llmConfig', () => {
  const configs = ref<LLMGlobalConfig[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const fetchAllConfigs = async () => {
    loading.value = true
    error.value = null
    try {
      const result = await getAllConfigs()
      if (result.code === 200) {
        configs.value = result.data
        loading.value = false
      } else {
        error.value = result.message
        loading.value = false
      }
    } catch (err: any) {
      error.value = err.message || '获取配置列表失败'
      loading.value = false
    }
  }

  const fetchConfigsByProvider = async (provider: string) => {
    loading.value = true
    error.value = null
    try {
      const result = await getConfigsByProviderApi(provider)
      if (result.code === 200) {
        const otherConfigs = configs.value.filter((c) => c.provider !== provider)
        configs.value = [...otherConfigs, ...result.data]
        loading.value = false
      } else {
        error.value = result.message
        loading.value = false
      }
    } catch (err: any) {
      error.value = err.message || '获取配置列表失败'
      loading.value = false
    }
  }

  const saveConfig = async (config: LLMConfigRequest): Promise<LLMGlobalConfig | null> => {
    loading.value = true
    error.value = null
    try {
      const result = await saveConfigApi(config)
      if (result.code === 200) {
        await fetchAllConfigs()
        return result.data
      }
      error.value = result.message
      loading.value = false
      return null
    } catch (err: any) {
      error.value = err.message || '保存配置失败'
      loading.value = false
      return null
    }
  }

  const deleteConfig = async (id: number): Promise<boolean> => {
    loading.value = true
    error.value = null
    try {
      const result = await deleteConfigApi(id)
      if (result.code === 200) {
        configs.value = configs.value.filter((c) => c.id !== id)
        loading.value = false
        return true
      }
      error.value = result.message
      loading.value = false
      return false
    } catch (err: any) {
      error.value = err.message || '删除配置失败'
      loading.value = false
      return false
    }
  }

  const setDefaultConfig = async (id: number): Promise<boolean> => {
    loading.value = true
    error.value = null
    try {
      const result = await setDefaultConfigApi(id)
      if (result.code === 200) {
        await fetchAllConfigs()
        return true
      }
      error.value = result.message
      loading.value = false
      return false
    } catch (err: any) {
      error.value = err.message || '设置默认配置失败'
      loading.value = false
      return false
    }
  }

  const getConfigsByProvider = (provider: string) =>
    configs.value.filter((c) => c.provider === provider)

  const getDefaultConfig = (provider: string) =>
    configs.value.find((c) => c.provider === provider && c.isDefault === 1)

  const clearError = () => {
    error.value = null
  }

  return {
    configs,
    loading,
    error,
    fetchAllConfigs,
    fetchConfigsByProvider,
    saveConfig,
    deleteConfig,
    setDefaultConfig,
    getConfigsByProvider,
    getDefaultConfig,
    clearError,
  }
})
