import { Injectable } from '@nestjs/common';
import { AppDataSource } from '../database/data-source';
import { ExecutionRecord, ExecutionSnapshot, ExecutionVariable, Workflow } from '../database/entities';
import { FlowNode, parseWorkflow, topologicalSort, buildEdgeIndexes, markSkipped } from './parser';
import { ExecutorRegistry, Progress } from './executors';
import { GraphRunResult, runWorkflowGraph } from './graph';
import * as events from './events';
import { asJsonString, jdump, jload, nowDate, stripRuntime, text, toInt } from '../common';

export type EventCallback = (event: any) => void;

interface ResumeState {
  startNodeId: string | null;
  restoredNodeResults: any[];
  nodeOutputs: Record<string, any>;
  skippedNodes: Set<string>;
  latestOutput: Record<string, any>;
  modifiedVariables: Record<string, any>;
}

function emptyResumeState(): ResumeState {
  return {
    startNodeId: null,
    restoredNodeResults: [],
    nodeOutputs: {},
    skippedNodes: new Set(),
    latestOutput: {},
    modifiedVariables: {},
  };
}

@Injectable()
export class EngineService {
  private readonly recordRepo = AppDataSource.getRepository(ExecutionRecord);
  private readonly snapshotRepo = AppDataSource.getRepository(ExecutionSnapshot);
  private readonly variableRepo = AppDataSource.getRepository(ExecutionVariable);

  constructor(private readonly executors: ExecutorRegistry) {}

  selectEngine(workflow: Workflow): 'dag' | 'langgraph' {
    const value = (workflow.engineType || '').trim().toLowerCase();
    return value === 'langgraph' ? 'langgraph' : 'dag';
  }

  async execute(workflow: Workflow, inputData: string, onEvent?: EventCallback): Promise<any> {
    if (this.selectEngine(workflow) === 'langgraph') return this.langgraph(workflow, inputData, onEvent);
    const started = Date.now();
    const config = parseWorkflow(workflow.flowData);
    const sorted = topologicalSort(config.nodes, config.edges);
    const indexes = buildEdgeIndexes(config.edges);
    const record = this.recordRepo.create({
      flowId: workflow.id,
      inputData: jdump({ input: inputData }),
      status: 'RUNNING',
      nodeResults: '[]',
      duration: 0,
      executedAt: nowDate(),
      deleted: 0,
    } as any) as unknown as ExecutionRecord;
    await this.recordRepo.save(record);
    if (onEvent) onEvent(events.workflowStart(record.id));
    return this.executeNodes(record, workflow.id, inputData, sorted, indexes.bySource, indexes.byTarget, emptyResumeState(), started, onEvent);
  }

  async resume(workflow: Workflow, executionId: number, request: any, onEvent?: EventCallback): Promise<any> {
    const record = await this.recordRepo.findOne({ where: { id: executionId, deleted: 0 } as any });
    if (!record || record.flowId !== workflow.id) throw new Error('执行记录不存在或不属于当前工作流');
    if (this.selectEngine(workflow) !== 'dag') throw new Error('当前执行引擎暂不支持断点续执行');

    const payload = request || {};
    const config = parseWorkflow(workflow.flowData);
    const sorted = topologicalSort(config.nodes, config.edges);
    const indexes = buildEdgeIndexes(config.edges);
    const snapshots = await this.snapshotRepo.find({ where: { executionId } as any, order: { executionOrder: 'ASC' } });
    const byNode = new Map<string, ExecutionSnapshot>();
    snapshots.forEach((snapshot) => byNode.set(snapshot.nodeId, snapshot));

    const startNodeId = this.resolveStartNode(sorted, byNode, payload);
    if (!startNodeId) return this.responseFromRecord(record, snapshots);

    let inputData = '';
    const parsedInput = jload(record.inputData, {}) || {};
    if (parsedInput.input !== undefined && parsedInput.input !== null) inputData = String(parsedInput.input);

    const state = this.buildResumeState(
      sorted,
      byNode,
      indexes.bySource,
      indexes.byTarget,
      startNodeId,
      payload.skipSuccessNodes !== false,
    );
    state.modifiedVariables = payload.modifiedVariables && typeof payload.modifiedVariables === 'object' ? payload.modifiedVariables : {};
    await this.saveVariables(executionId, state.modifiedVariables);
    record.status = 'RUNNING';
    record.errorMessage = null;
    await this.recordRepo.save(record);

    const started = Date.now();
    if (onEvent) onEvent(events.workflowStart(record.id));
    return this.executeNodes(
      record,
      workflow.id,
      inputData,
      sorted,
      indexes.bySource,
      indexes.byTarget,
      state,
      started,
      onEvent,
    );
  }

  private resolveStartNode(sorted: FlowNode[], byNode: Map<string, ExecutionSnapshot>, request: any): string | null {
    if (text(request.startNodeId)) return text(request.startNodeId);
    for (const node of sorted) {
      if (byNode.get(node.id)?.status === 'FAILED') return node.id;
    }
    for (const node of sorted) {
      const snapshot = byNode.get(node.id);
      if (!snapshot || !['SUCCESS', 'SKIPPED'].includes(snapshot.status)) return node.id;
    }
    return null;
  }

  private buildResumeState(
    sorted: FlowNode[],
    byNode: Map<string, ExecutionSnapshot>,
    bySource: Map<string, any[]>,
    byTarget: Map<string, any[]>,
    startNodeId: string,
    skipSuccess: boolean,
  ): ResumeState {
    const state = emptyResumeState();
    state.startNodeId = startNodeId;
    if (!skipSuccess) return state;
    for (const node of sorted) {
      if (node.id === startNodeId) break;
      const snapshot = byNode.get(node.id);
      if (!snapshot || snapshot.status !== 'SUCCESS') continue;
      const output = jload(snapshot.outputData, {}) || {};
      state.nodeOutputs[node.id] = output;
      state.latestOutput = output;
      state.restoredNodeResults.push(this.snapshotResult(snapshot));
      if (node.type === 'condition') {
        const branch = typeof output.__selectedBranch__ === 'string' ? output.__selectedBranch__ : 'default';
        markSkipped(node.id, branch, bySource as any, byTarget as any, state.skippedNodes);
      }
    }
    return state;
  }

  private snapshotResult(snapshot: ExecutionSnapshot): any {
    return {
      nodeId: snapshot.nodeId,
      nodeName: snapshot.nodeType,
      status: snapshot.status,
      input: snapshot.inputData,
      output: snapshot.outputData,
      duration: snapshot.duration ?? 0,
      error: snapshot.errorMessage,
    };
  }

  private responseFromRecord(record: ExecutionRecord, snapshots: ExecutionSnapshot[]): any {
    const parsed = jload(record.nodeResults, null);
    const nodeResults = Array.isArray(parsed) ? parsed : snapshots.map((snapshot) => this.snapshotResult(snapshot));
    return {
      executionId: record.id,
      status: record.status,
      inputData: asJsonString(record.inputData),
      nodeResults,
      outputData: asJsonString(record.outputData),
      duration: record.duration,
      errorMessage: record.errorMessage,
    };
  }

  private async saveVariables(executionId: number, variables: Record<string, any>): Promise<void> {
    for (const [name, value] of Object.entries(variables || {})) {
      const existing = await this.variableRepo.findOne({ where: { executionId, variableName: name } as any });
      const variable = (existing || this.variableRepo.create({ executionId, variableName: name } as any)) as ExecutionVariable;
      variable.variableType = value === null ? 'NULL' : Array.isArray(value) || typeof value === 'object' ? 'JSON' : typeof value === 'number' ? 'NUMBER' : typeof value === 'boolean' ? 'BOOLEAN' : 'STRING';
      variable.variableValue = jdump(value);
      variable.isModified = 1;
      await this.variableRepo.save(variable as any);
    }
  }

  private resolveInput(node: FlowNode, nodeOutputs: Record<string, any>, byTarget: Map<string, any[]>, fallback: Record<string, any>): Record<string, any> {
    const incoming = byTarget.get(node.id) || [];
    if (!incoming.length) return fallback;
    const resolved: Record<string, any> = {};
    for (const edge of incoming) {
      const output = nodeOutputs[edge.source];
      if (output) Object.assign(resolved, output);
    }
    if (!Object.keys(resolved).length) return fallback;
    resolved.__nodeOutputs__ = nodeOutputs;
    return resolved;
  }

  private async startSnapshot(record: ExecutionRecord, flowId: number, node: FlowNode, nodeInput: any, order: number): Promise<ExecutionSnapshot | null> {
    if (!record.id) return null;
    let snapshot = await this.snapshotRepo.findOne({ where: { executionId: record.id, nodeId: node.id } as any });
    if (!snapshot) {
      snapshot = this.snapshotRepo.create({
        executionId: record.id,
        flowId,
        nodeId: node.id,
        nodeType: node.type,
        nodeName: text(node.data?.label) || node.type,
        retryCount: 0,
        executionOrder: order,
      } as any) as unknown as ExecutionSnapshot;
    } else {
      snapshot.retryCount = (snapshot.retryCount || 0) + 1;
    }
    Object.assign(snapshot, {
      nodeType: node.type,
      nodeName: text(node.data?.label) || node.type,
      executionOrder: order,
      status: 'RUNNING',
      inputData: jdump(stripRuntime(nodeInput)),
      outputData: null,
      errorMessage: null,
      startedAt: nowDate(),
      completedAt: null,
      duration: null,
      updatedAt: nowDate(),
    });
    await this.snapshotRepo.save(snapshot as any);
    return snapshot;
  }

  private async finishSnapshot(snapshot: ExecutionSnapshot | null, status: string, output: any, duration: number, error: string | null): Promise<void> {
    if (!snapshot?.id) return;
    snapshot.status = status;
    if (status === 'SUCCESS') {
      snapshot.outputData = jdump(output);
      snapshot.errorMessage = null;
    } else {
      snapshot.errorMessage = error;
    }
    snapshot.completedAt = nowDate();
    snapshot.duration = duration;
    await this.snapshotRepo.save(snapshot);
  }

  private async executeNodes(
    record: ExecutionRecord,
    flowId: number,
    inputData: string,
    sorted: FlowNode[],
    bySource: Map<string, any[]>,
    byTarget: Map<string, any[]>,
    resumeState: ResumeState,
    started: number,
    onEvent?: EventCallback,
  ): Promise<any> {
    const nodeResults: any[] = [...resumeState.restoredNodeResults];
    const nodeOutputs: Record<string, any> = { ...resumeState.nodeOutputs };
    const skipped = new Set(resumeState.skippedNodes);
    let currentInput: Record<string, any> = { input: inputData, ...resumeState.latestOutput, ...resumeState.modifiedVariables };
    let status = 'SUCCESS';
    let errorMessage: string | null = null;
    let outputData: string | null = null;
    let reached = resumeState.startNodeId === null;
    const orderMap = new Map(sorted.map((node, index) => [node.id, index]));

    try {
      for (const node of sorted) {
        if (!reached) {
          if (node.id === resumeState.startNodeId) reached = true;
          else continue;
        }
        if (skipped.has(node.id)) continue;

        let nodeInput = this.resolveInput(node, nodeOutputs, byTarget, currentInput);
        if (Object.keys(resumeState.modifiedVariables).length) nodeInput = { ...nodeInput, ...resumeState.modifiedVariables };

        const nodeStarted = Date.now();
        const snapshot = await this.startSnapshot(record, flowId, node, nodeInput, orderMap.get(node.id) || 0);
        if (onEvent) onEvent(events.nodeStart(node.id, node.type));

        const nodeResult: any = {
          nodeId: node.id,
          nodeName: node.type,
          status: null,
          input: jdump(stripRuntime(nodeInput)),
          output: null,
          duration: null,
          error: null,
        };
        try {
          const progress: Progress | undefined = onEvent
            ? (message, data) => onEvent(events.nodeProgress(node.id, node.type, message, data))
            : undefined;
          const rawOutput = await this.executors.get(node.type)(node, nodeInput, progress);
          const output = stripRuntime(rawOutput) as Record<string, any>;
          nodeOutputs[node.id] = output;
          const duration = Date.now() - nodeStarted;
          nodeResult.status = 'SUCCESS';
          nodeResult.output = jdump(output);
          nodeResult.duration = duration;
          await this.finishSnapshot(snapshot, 'SUCCESS', output, duration, null);
          if (onEvent) {
            onEvent(events.nodeSuccess(node.id, node.type, {
              input: stripRuntime(nodeInput),
              output,
              duration,
            }, duration));
          }
          currentInput = output;
          if (node.type === 'condition') {
            markSkipped(node.id, rawOutput.__selectedBranch__ ?? 'default', bySource, byTarget, skipped);
          }
        } catch (error: any) {
          nodeResult.status = 'FAILED';
          nodeResult.error = String(error?.message || error);
          status = 'FAILED';
          errorMessage = `节点 ${node.id} 执行失败: ${error?.message || error}`;
          await this.finishSnapshot(snapshot, 'FAILED', null, Date.now() - nodeStarted, String(error?.message || error));
          if (onEvent) onEvent(events.nodeError(node.id, node.type, String(error?.message || error)));
          throw error;
        } finally {
          nodeResult.duration = Date.now() - nodeStarted;
          nodeResults.push(nodeResult);
        }
      }
      outputData = jdump(stripRuntime(currentInput));
    } catch (error: any) {
      status = 'FAILED';
      if (!errorMessage) errorMessage = String(error?.message || error);
    }

    const duration = Date.now() - started;
    if (onEvent) onEvent(events.workflowComplete(status, currentInput, duration));

    record.inputData = jdump({ input: inputData });
    record.outputData = outputData;
    record.status = status;
    record.nodeResults = jdump(nodeResults);
    record.errorMessage = errorMessage;
    record.duration = duration;
    await this.recordRepo.save(record);

    return {
      executionId: record.id,
      status,
      inputData: asJsonString(record.inputData),
      nodeResults,
      outputData,
      duration,
      errorMessage,
    };
  }

  private async langgraph(workflow: Workflow, inputData: string, onEvent?: EventCallback): Promise<any> {
    const started = Date.now();
    if (onEvent) onEvent(events.workflowStart(null));

    let result: GraphRunResult;
    try {
      const config = parseWorkflow(workflow.flowData);
      result = await runWorkflowGraph(config, inputData, this.executors, onEvent);
    } catch (error: any) {
      result = {
        status: 'FAILED',
        errorMessage: String(error?.message || error),
        nodeResults: [],
        finalOutput: {},
      };
    }

    const duration = Date.now() - started;
    const outputData = jdump(stripRuntime(result.finalOutput));
    const record = this.recordRepo.create({
      flowId: workflow.id,
      inputData: jdump({ input: inputData }),
      outputData,
      status: result.status,
      nodeResults: jdump(result.nodeResults),
      errorMessage: result.errorMessage,
      duration,
      executedAt: nowDate(),
      deleted: 0,
    } as any) as unknown as ExecutionRecord;
    await this.recordRepo.save(record);

    if (onEvent) onEvent(events.workflowComplete(result.status, result.finalOutput, duration));
    return {
      executionId: record.id,
      status: result.status,
      inputData: record.inputData,
      nodeResults: result.nodeResults,
      outputData,
      duration,
      errorMessage: result.errorMessage,
    };
  }
}
