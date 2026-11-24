import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'
import type { Edge, Node } from '@vue-flow/core'
import { createDefaultWorkflowNodes, normalizeWorkflowNodes } from '../utils/workflowNode'

/**
 * 工作流编辑状态管理
 */
export const useWorkflowStore = defineStore('workflow', () => {
  const nodes = shallowRef<Node[]>(createDefaultWorkflowNodes())
  const edges = shallowRef<Edge[]>([])
  const selectedNode = shallowRef<Node | null>(null)
  const currentWorkflowId = ref<number | null>(null)

  const setNodes = (next: Node[]) => {
    nodes.value = normalizeWorkflowNodes(next)
  }

  const setEdges = (next: Edge[]) => {
    edges.value = next
  }

  const setSelectedNode = (node: Node | null) => {
    selectedNode.value = node
  }

  const setCurrentWorkflowId = (id: number | null) => {
    currentWorkflowId.value = id
  }

  const addNode = (node: Node) => {
    nodes.value = [...nodes.value, normalizeWorkflowNodes([node])[0]]
  }

  const updateNode = (id: string, data: Record<string, unknown>) => {
    nodes.value = nodes.value.map((node) =>
      node.id === id ? { ...node, data: { ...node.data, ...data } } : node
    )
  }

  const deleteNode = (id: string) => {
    nodes.value = nodes.value.filter((node) => node.id !== id)
    edges.value = edges.value.filter((edge) => edge.source !== id && edge.target !== id)
  }

  const clear = () => {
    nodes.value = createDefaultWorkflowNodes()
    edges.value = []
    selectedNode.value = null
    currentWorkflowId.value = null
  }

  return {
    nodes,
    edges,
    selectedNode,
    currentWorkflowId,
    setNodes,
    setEdges,
    setSelectedNode,
    setCurrentWorkflowId,
    addNode,
    updateNode,
    deleteNode,
    clear,
  }
})
