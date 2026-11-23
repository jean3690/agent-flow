export interface FlowNode {
  id: string;
  type: string;
  data: Record<string, any>;
  position?: any;
}

export interface FlowEdge {
  id?: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

export interface FlowConfig {
  nodes: FlowNode[];
  edges: FlowEdge[];
}

export function parseWorkflow(flowData: string | null | undefined): FlowConfig {
  let root: any;
  if (flowData && typeof flowData === 'object') {
    root = flowData;
  } else {
    try {
      root = JSON.parse((flowData as string) || '{}');
    } catch {
      throw new Error('工作流配置不是合法 JSON');
    }
  }
  if (!root || typeof root !== 'object') throw new Error('工作流配置必须是 JSON 对象');

  const nodes: FlowNode[] = (Array.isArray(root.nodes) ? root.nodes : []).map((item: any) => {
    const data = item?.data && typeof item.data === 'object' ? item.data : {};
    let type = item?.type;
    if ((!type || type === 'workflow') && data.type) type = data.type;
    return { id: String(item?.id), type: String(type || ''), data, position: item.position };
  });

  const edges: FlowEdge[] = (Array.isArray(root.edges) ? root.edges : []).map((item: any) => ({
    id: item?.id,
    source: String(item?.source),
    target: String(item?.target),
    sourceHandle: item?.sourceHandle ?? null,
    targetHandle: item?.targetHandle ?? null,
  }));
  return { nodes, edges };
}

export function topologicalSort(nodes: FlowNode[], edges: FlowEdge[]): FlowNode[] {
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const dependencies = new Map<string, string[]>();
  const dependents = new Map<string, string[]>();
  nodes.forEach((node) => {
    dependencies.set(node.id, []);
    dependents.set(node.id, []);
  });
  for (const edge of edges) {
    if (!dependencies.has(edge.source) || !dependencies.has(edge.target)) continue;
    dependencies.get(edge.target)!.push(edge.source);
    dependents.get(edge.source)!.push(edge.target);
  }

  const visited = new Set<string>();
  const stack = new Set<string>();
  const visit = (id: string): void => {
    if (stack.has(id)) throw new Error(`工作流存在循环依赖,节点: ${id}`);
    if (visited.has(id)) return;
    visited.add(id);
    stack.add(id);
    for (const dependency of dependencies.get(id) || []) visit(dependency);
    stack.delete(id);
  };
  nodes.forEach((node) => visit(node.id));

  const inDegree = new Map<string, number>();
  nodes.forEach((node) => inDegree.set(node.id, (dependencies.get(node.id) || []).length));
  const queue = nodes.filter((node) => inDegree.get(node.id) === 0).map((node) => node.id);
  const result: FlowNode[] = [];
  for (let index = 0; index < queue.length; index++) {
    const id = queue[index];
    result.push(nodeMap.get(id)!);
    for (const next of dependents.get(id) || []) {
      inDegree.set(next, inDegree.get(next)! - 1);
      if (inDegree.get(next) === 0) queue.push(next);
    }
  }
  if (result.length !== nodeMap.size) throw new Error('工作流存在循环依赖,无法完成拓扑排序');
  return result;
}

export function buildEdgeIndexes(edges: FlowEdge[]): {
  bySource: Map<string, FlowEdge[]>;
  byTarget: Map<string, FlowEdge[]>;
} {
  const bySource = new Map<string, FlowEdge[]>();
  const byTarget = new Map<string, FlowEdge[]>();
  for (const edge of edges) {
    if (!bySource.has(edge.source)) bySource.set(edge.source, []);
    if (!byTarget.has(edge.target)) byTarget.set(edge.target, []);
    bySource.get(edge.source)!.push(edge);
    byTarget.get(edge.target)!.push(edge);
  }
  return { bySource, byTarget };
}

export function markSkipped(
  conditionNodeId: string,
  selectedBranch: string | null,
  bySource: Map<string, FlowEdge[]>,
  byTarget: Map<string, FlowEdge[]>,
  skipped: Set<string>,
): void {
  const out = bySource.get(conditionNodeId) || [];
  if (!out.some((edge) => edge.sourceHandle !== null && edge.sourceHandle !== undefined)) return;
  const active = new Set<string>();
  const inactive = new Set<string>();
  for (const edge of out) {
    if (edge.sourceHandle && edge.sourceHandle === selectedBranch) active.add(edge.target);
    else if (edge.sourceHandle === null && selectedBranch === 'default') active.add(edge.target);
    else inactive.add(edge.target);
  }
  for (const target of inactive) {
    if (!active.has(target)) markDownstream(target, bySource, byTarget, skipped);
  }
}

function markDownstream(
  nodeId: string,
  bySource: Map<string, FlowEdge[]>,
  byTarget: Map<string, FlowEdge[]>,
  skipped: Set<string>,
): void {
  if (skipped.has(nodeId)) return;
  const incoming = byTarget.get(nodeId) || [];
  if (incoming.length > 1) {
    for (const edge of incoming) if (!skipped.has(edge.source)) return;
  }
  skipped.add(nodeId);
  for (const edge of bySource.get(nodeId) || []) markDownstream(edge.target, bySource, byTarget, skipped);
}
