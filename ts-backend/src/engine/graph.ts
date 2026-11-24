import { Annotation, END, START, StateGraph } from '@langchain/langgraph';
import { FlowConfig, FlowEdge, FlowNode, buildEdgeIndexes, topologicalSort } from './parser';
import { ExecutorRegistry, Progress } from './executors';
import { jdump, stripRuntime } from '../common';
import * as events from './events';

export type GraphEventCallback = (event: any) => void;

const WorkflowState = Annotation.Root({
  currentInput: Annotation<Record<string, any>>({
    reducer: (_previous: Record<string, any>, next: Record<string, any>) => next,
    default: () => ({}),
  }),
  nodeOutputs: Annotation<Record<string, any>>({
    reducer: (previous: Record<string, any>, next: Record<string, any>) => ({ ...previous, ...next }),
    default: () => ({}),
  }),
});

export interface GraphRunResult {
  status: 'SUCCESS' | 'FAILED';
  errorMessage: string | null;
  nodeResults: any[];
  finalOutput: Record<string, any>;
}

interface NodeRunRecord {
  nodeId: string;
  nodeName: string;
  status: string;
  input: string;
  output: string | null;
  duration: number;
  error: string | null;
}

function computeReachable(entries: FlowNode[], edgesBySource: Map<string, FlowEdge[]>): Set<string> {
  const reachable = new Set<string>();
  const stack = entries.map((node) => node.id);
  while (stack.length) {
    const id = stack.pop() as string;
    if (reachable.has(id)) continue;
    reachable.add(id);
    for (const edge of edgesBySource.get(id) || []) stack.push(edge.target);
  }
  return reachable;
}

function resolveNodeInput(
  node: FlowNode,
  nodeOutputs: Record<string, any>,
  byTarget: Map<string, FlowEdge[]>,
  inputData: string,
): Record<string, any> {
  const incoming = byTarget.get(node.id) || [];
  if (!incoming.length) return { input: inputData };
  const resolved: Record<string, any> = {};
  for (const edge of incoming) {
    const output = nodeOutputs[edge.source];
    if (output) Object.assign(resolved, output);
  }
  if (!Object.keys(resolved).length) return { input: inputData };
  return resolved;
}

/**
 * 用 LangGraph 状态图执行工作流：
 * - 每个工作流节点注册为图节点
 * - 普通连线用 addEdge 表达（支持并行分支）
 * - condition 节点用 addConditionalEdges 按 sourceHandle 路由
 * - 同一节点的多路输入在执行前按入边合并，保持与 DAG 引擎一致的取数语义
 */
export async function runWorkflowGraph(
  config: FlowConfig,
  inputData: string,
  executors: ExecutorRegistry,
  onEvent?: GraphEventCallback,
): Promise<GraphRunResult> {
  const sorted = topologicalSort(config.nodes, config.edges);
  const { bySource, byTarget } = buildEdgeIndexes(config.edges);
  const nodeById = new Map(sorted.map((node) => [node.id, node]));
  const targets = new Set(config.edges.map((edge) => edge.target));
  const entries = sorted.filter((node) => !targets.has(node.id));
  if (!entries.length) {
    return { status: 'SUCCESS', errorMessage: null, nodeResults: [], finalOutput: { input: inputData } };
  }

  const reachable = computeReachable(entries, bySource);
  const nodes = sorted.filter((node) => reachable.has(node.id));
  const results: NodeRunRecord[] = [];
  let failure: string | null = null;

  const graph: any = new StateGraph(WorkflowState);

  for (const node of nodes) {
    graph.addNode(node.id, async (state: any) => {
      const startedAt = Date.now();
      let nodeInput = resolveNodeInput(node, state.nodeOutputs || {}, byTarget, inputData);
      if (node.type === 'output') nodeInput = { ...nodeInput, __nodeOutputs__: state.nodeOutputs };
      if (onEvent) onEvent(events.nodeStart(node.id, node.type));

      const progress: Progress | undefined = onEvent
        ? (message, data) => onEvent(events.nodeProgress(node.id, node.type, message, data))
        : undefined;

      try {
        const rawOutput = await executors.get(node.type)(node, nodeInput, progress);
        const output = stripRuntime(rawOutput) as Record<string, any>;
        const duration = Date.now() - startedAt;
        results.push({
          nodeId: node.id,
          nodeName: node.type,
          status: 'SUCCESS',
          input: jdump(stripRuntime(nodeInput)),
          output: jdump(output),
          duration,
          error: null,
        });
        if (onEvent) onEvent(events.nodeSuccess(node.id, node.type, { input: stripRuntime(nodeInput), output, duration }, duration));
        return { nodeOutputs: { [node.id]: output }, currentInput: output };
      } catch (error: any) {
        const message = String(error?.message || error);
        const duration = Date.now() - startedAt;
        failure = `节点 ${node.id} 执行失败: ${message}`;
        results.push({
          nodeId: node.id,
          nodeName: node.type,
          status: 'FAILED',
          input: jdump(stripRuntime(nodeInput)),
          output: null,
          duration,
          error: message,
        });
        if (onEvent) onEvent(events.nodeError(node.id, node.type, message));
        throw error;
      }
    });
  }

  for (const node of nodes) {
    const outgoing = (bySource.get(node.id) || []).filter((edge) => reachable.has(edge.target));
    if (node.type === 'condition' && outgoing.some((edge) => edge.sourceHandle)) {
      // LangGraph 的 pathMap 值是单个目标节点；多目标用路由函数返回多个 key 实现扇出。
      const branches: Record<string, string[]> = {};
      const pathMap: Record<string, any> = { __stop__: END };
      for (const edge of outgoing) {
        const key = edge.sourceHandle || 'default';
        if (!branches[key]) branches[key] = [];
        branches[key].push(edge.target);
        pathMap[edge.target] = edge.target;
      }
      graph.addConditionalEdges(
        node.id,
        (state: any) => {
          const output = state.nodeOutputs?.[node.id] || {};
          const branch = typeof output.__selectedBranch__ === 'string' ? output.__selectedBranch__ : 'default';
          return branches[branch]?.length ? branches[branch] : ['__stop__'];
        },
        pathMap,
      );
    } else if (outgoing.length) {
      for (const edge of outgoing) graph.addEdge(node.id, edge.target);
    } else {
      graph.addEdge(node.id, END);
    }
  }

  if (entries.length === 1) {
    graph.addEdge(START, entries[0].id);
  } else {
    graph.addEdge(START, entries.map((node) => node.id));
  }

  const app = graph.compile();
  let finalState: any = { nodeOutputs: {}, currentInput: { input: inputData } };
  let status: 'SUCCESS' | 'FAILED' = 'SUCCESS';
  let errorMessage: string | null = null;

  try {
    finalState = await app.invoke(
      { currentInput: { input: inputData }, nodeOutputs: {} },
      { recursionLimit: Math.max(50, nodes.length * 2 + 10) },
    );
  } catch (error: any) {
    status = 'FAILED';
    errorMessage = failure || String(error?.message || error);
  }

  const nodeOutputs: Record<string, any> = finalState?.nodeOutputs || {};
  const outputNode = nodes.find((node) => node.type === 'output' && nodeOutputs[node.id]);
  const lastNode = [...nodes].reverse().find((node) => nodeOutputs[node.id]);
  const finalOutput = outputNode
    ? nodeOutputs[outputNode.id]
    : lastNode
      ? nodeOutputs[lastNode.id]
      : finalState?.currentInput || {};

  return {
    status,
    errorMessage,
    nodeResults: results,
    finalOutput: stripRuntime(finalOutput) as Record<string, any>,
  };
}