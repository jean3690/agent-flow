import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { nodeApi } from '../api'
import type { FlowNodeModel, NodeDefinition } from '../types'

export const useWorkflowStore = defineStore('workflow', () => {
  const definitions = ref<NodeDefinition[]>([])
  const loaded = ref(false)

  const definitionMap = computed<Record<string, NodeDefinition>>(() => {
    const map: Record<string, NodeDefinition> = {}
    definitions.value.forEach((item) => {
      map[item.type] = item
    })
    return map
  })

  const categories = computed(() => {
    const groups: Record<string, NodeDefinition[]> = {}
    definitions.value.forEach((item) => {
      groups[item.category] = groups[item.category] || []
      groups[item.category].push(item)
    })
    return Object.entries(groups)
  })

  async function loadDefinitions() {
    if (loaded.value) return definitions.value
    definitions.value = (await nodeApi.list()) || []
    loaded.value = true
    return definitions.value
  }

  function defaultConfig(type: string): Record<string, any> {
    const definition = definitionMap.value[type]
    const config: Record<string, any> = {}
    definition?.configSchema?.forEach((field) => {
      // field.default comes from a deeply-reactive definition (a Vue Proxy).
      // structuredClone throws on Proxies, and toRaw only unwraps the top level
      // (nested reactive values would still throw). Node defaults are plain JSON,
      // so a JSON round-trip is a safe, Proxy-proof deep clone.
      const raw = field.default
      config[field.key] = raw !== undefined ? JSON.parse(JSON.stringify(raw)) : field.type === 'tags' ? [] : ''
    })
    return config
  }

  function createNode(type: string, position: { x: number; y: number }): FlowNodeModel {
    const definition = definitionMap.value[type]
    return {
      id: type + '-' + Math.random().toString(36).slice(2, 8),
      type,
      name: definition?.name || type,
      position,
      config: defaultConfig(type)
    }
  }

  return {
    definitions,
    definitionMap,
    categories,
    loaded,
    loadDefinitions,
    defaultConfig,
    createNode
  }
})
