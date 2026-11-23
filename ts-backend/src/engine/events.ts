export interface FlowEvent {
  eventType: string;
  nodeId?: string | null;
  nodeName?: string | null;
  status?: string | null;
  message?: string | null;
  data?: any;
  timestamp: number;
}

function event(eventType: string, fields: Partial<FlowEvent> = {}): FlowEvent {
  return {
    eventType,
    nodeId: fields.nodeId ?? null,
    nodeName: fields.nodeName ?? null,
    status: fields.status ?? null,
    message: fields.message ?? null,
    data: fields.data ?? null,
    timestamp: Date.now(),
  };
}

export const workflowStart = (executionId: number | null) => event('WORKFLOW_START', { message: '工作流开始执行', data: executionId });
export const nodeStart = (id: string, name: string) => event('NODE_START', { nodeId: id, nodeName: name, status: 'RUNNING', message: '节点开始执行' });
export const nodeSuccess = (id: string, name: string, data: any, duration: number) => event('NODE_SUCCESS', { nodeId: id, nodeName: name, status: 'SUCCESS', message: `节点执行成功,耗时 ${duration}ms`, data });
export const nodeError = (id: string, name: string, message: string) => event('NODE_ERROR', { nodeId: id, nodeName: name, status: 'FAILED', message });
export const nodeProgress = (id: string, name: string, message: string, data: any) => event('NODE_PROGRESS', { nodeId: id, nodeName: name, status: 'RUNNING', message, data });
export const workflowComplete = (status: string, data: any, duration: number) => event('WORKFLOW_COMPLETE', { status, message: `工作流执行完成,总耗时 ${duration}ms`, data });
