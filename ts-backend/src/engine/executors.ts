import { Injectable } from '@nestjs/common';
import axios from 'axios';
import { AppDataSource } from '../database/data-source';
import { LLMGlobalConfig } from '../database/entities';
import { LlmService, chatEndpoint } from '../services/llm.service';
import { AgentPlanService } from '../services/agent-plan.service';
import { KnowledgeService } from '../services/knowledge.service';
import { McpService } from '../services/mcp.service';
import { MediaService } from '../services/media.service';
import { SkillsService } from '../services/skills.service';
import { FlowNode } from './parser';
import { canonicalizeProvider, firstText, jdump, text, toFloat, toInt, truthy } from '../common';

export type Progress = (message: string, data: any) => void;
export type ExecuteResult = Record<string, any>;
export type Executor = (node: FlowNode, input: ExecuteResult, progress?: Progress) => Promise<ExecuteResult>;

function valueText(value: any): string | null {
  return text(value);
}

function agentText(nodeData: Record<string, any>, input: ExecuteResult, field: string, fallbackField?: string): string | null {
  const nodeValue = valueText(nodeData[field]);
  if (nodeValue) return nodeValue;
  const inputValue = valueText(input[field]);
  if (inputValue) return inputValue;
  if (fallbackField) {
    const fallback = valueText(input[fallbackField]);
    if (fallback) return fallback;
  }
  return valueText(input.output);
}

function configuredText(nodeData: Record<string, any>, input: ExecuteResult, paramName: string): string | null {
  const params = nodeData.inputParams;
  if (!Array.isArray(params)) return null;
  for (const param of params) {
    if (!param || param.name !== paramName) continue;
    if (param.type === 'input') return valueText(param.value);
    if (param.type === 'reference') {
      const key = String(param.referenceNode || '').split('.').pop() || '';
      const found = valueText(input[key]) || (key === 'user_input' ? valueText(input.input) : null);
      if (found) return found;
    }
  }
  return null;
}

function applyOutputParams(nodeData: Record<string, any>, output: ExecuteResult): void {
  const params = nodeData.outputParams;
  if (!Array.isArray(params)) return;
  for (const param of params) {
    const name = text(param?.name);
    if (!name) continue;
    const source = text(param.value);
    const value = source ? output[source] : output[name];
    if (value !== undefined) output[name] = value;
  }
}

function intData(data: Record<string, any>, field: string, fallback: number): number {
  return toInt(data[field], fallback) ?? fallback;
}

function doubleData(data: Record<string, any>, field: string, fallback: number): number {
  return toFloat(data[field], fallback) ?? fallback;
}

function stringData(data: Record<string, any>, field: string, fallback: string | null = null): string | null {
  return valueText(data[field]) || fallback;
}

function conditionEval(actual: any, operator: string | null, expected: any): boolean {
  if (!operator) return false;
  const numeric = (value: any) => value !== null && value !== undefined && !Number.isNaN(Number(value));
  const equal = actual !== null && actual !== undefined && expected !== null && expected !== undefined &&
    (numeric(actual) && numeric(expected) ? Number(actual) === Number(expected) : String(actual) === String(expected));
  switch (operator) {
    case 'eq': return equal;
    case 'neq': return !equal;
    case 'gt': return Number(actual) > Number(expected);
    case 'gte': return Number(actual) >= Number(expected);
    case 'lt': return Number(actual) < Number(expected);
    case 'lte': return Number(actual) <= Number(expected);
    case 'contains': return actual !== null && actual !== undefined && String(actual).includes(String(expected));
    case 'notContains': return !(actual !== null && actual !== undefined && String(actual).includes(String(expected)));
    case 'startsWith': return actual !== null && actual !== undefined && String(actual).startsWith(String(expected));
    case 'endsWith': return actual !== null && actual !== undefined && String(actual).endsWith(String(expected));
    case 'isEmpty': return actual === null || actual === undefined || actual === '' || (Array.isArray(actual) && !actual.length) || (typeof actual === 'object' && !Object.keys(actual).length);
    case 'isNotEmpty': return !(actual === null || actual === undefined || actual === '' || (Array.isArray(actual) && !actual.length));
    default: return false;
  }
}

@Injectable()
export class ExecutorRegistry {
  private readonly executors = new Map<string, Executor>();

  constructor(
    private readonly llm: LlmService,
    private readonly plan: AgentPlanService,
    private readonly knowledge: KnowledgeService,
    private readonly mcp: McpService,
    private readonly media: MediaService,
    private readonly skills: SkillsService,
  ) {
    this.build();
  }

  get(type: string): Executor {
    const executor = this.executors.get(type);
    if (!executor) throw new Error(`不支持的节点类型: ${type}`);
    return executor;
  }

  private register(type: string, executor: Executor): void {
    this.executors.set(type, executor);
  }

  private build(): void {
    this.register('input', async (_node, input) => ({ ...input }));

    this.register('output', async (node, input) => {
      const data = node.data || {};
      const responseContent = text(data.responseContent);
      if (!responseContent) {
        return { output: input.output !== undefined && input.output !== null ? input.output : input.input };
      }
      const values: Record<string, string> = {};
      for (const param of Array.isArray(data.outputParams) ? data.outputParams : []) {
        const name = text(param?.name);
        if (!name) continue;
        if (param.type === 'input') values[name] = param.value === null || param.value === undefined ? '' : String(param.value);
        if (param.type === 'reference') {
          const reference = text(param.referenceNode);
          if (!reference || !reference.includes('.')) continue;
          const parts = reference.split('.');
          const refNode = parts[0];
          const key = parts[parts.length - 1];
          let value = (input.__nodeOutputs__?.[refNode] || {})[key];
          if (value === undefined) value = input[key];
          if (value === undefined && key === 'user_input') value = input.input;
          if (value !== undefined) values[name] = String(value);
        }
      }
      return { output: responseContent.replace(/\{\{(.*?)\}\}/g, (_match, raw) => values[raw.trim()] ?? '') };
    });

    this.register('condition', async (node, input) => {
      const conditions = Array.isArray(node.data?.conditions) ? node.data.conditions : [];
      let selectedBranch = 'default';
      for (const condition of conditions) {
        let actual = input[condition?.field];
        if (actual === undefined && typeof input.input === 'string') {
          try {
            const parsed = JSON.parse(input.input);
            actual = parsed?.[condition.field];
          } catch {
            // not JSON
          }
        }
        if (conditionEval(actual, condition?.operator, condition?.value)) {
          selectedBranch = condition?.id;
          break;
        }
      }
      return { ...input, __selectedBranch__: selectedBranch, __conditionNodeId__: node.id };
    });

    const llmExecutor: Executor = async (node, input, progress) => this.runLlm(node, input, progress);
    for (const type of ['llm', 'openai', 'deepseek', 'qwen', 'step', 'zhipu', 'ai_ping']) {
      this.register(type, llmExecutor);
    }

    this.register('react_agent', async (node, input, progress) => this.runReAct(node, input, progress));

    this.register('tts', async (node, input, progress) => this.media.tts(node.data || {}, input, progress));

    this.register('image_generate', async (node, input) => {
      const data = node.data || {};
      const prompt = configuredText(data, input, 'prompt') || agentText(data, input, 'prompt', 'input');
      if (!prompt) throw new Error('图片生成节点缺少 prompt');
      const config = await this.plan.resolveImage(data);
      this.plan.validate(config, '图片生成');
      const result = await this.media.generateImage(config, prompt, stringData(data, 'referenceImageUrl'), stringData(data, 'size', '2K'));
      const timestamp = Date.now();
      const persisted: string[] = [];
      for (const url of result.imageUrls) persisted.push(await this.media.persistImage(url, `images/generated-${timestamp}.png`));
      const output: ExecuteResult = {
        imageUrl: persisted[0] || null,
        imageUrls: persisted,
        prompt,
        model: config.model,
        metadata: result.metadata,
        output: persisted[0] || null,
      };
      applyOutputParams(data, output);
      return output;
    });

    this.register('video_generate', async (node, input, progress) => {
      const data = node.data || {};
      const prompt = configuredText(data, input, 'prompt') || agentText(data, input, 'prompt', 'input');
      if (!prompt) throw new Error('视频生成节点缺少 prompt');
      const reference = configuredText(data, input, 'referenceImageUrl') || stringData(data, 'referenceImageUrl');
      const config = await this.plan.resolve(data, 'video');
      this.plan.validate(config, '视频生成');
      const duration = intData(data, 'duration', 5);
      const taskId = await this.plan.createVideoTask(config, prompt, reference, duration, stringData(data, 'resolution'), stringData(data, 'ratio'));
      if (!taskId) throw new Error('视频生成接口未返回 taskId');
      if (progress) progress(`视频任务已提交: taskId=${taskId}`, { taskId });
      let task: any = { status: 'running' };
      for (let i = 0; i < 60; i++) {
        await new Promise((resolve) => setTimeout(resolve, 5000));
        task = await this.plan.getVideoTask(config, taskId);
        if (progress) progress(`视频生成中: 第 ${i + 1}/60 次查询, 状态=${task.status}`, { taskId, poll: i + 1, status: task.status });
        if (/success|succeed|completed/i.test(task.status || '')) break;
        if (/fail|error|cancel/i.test(task.status || '')) throw new Error(`视频生成失败: ${JSON.stringify(task)}`);
      }
      if (!task.videoUrl) throw new Error(`视频生成超时或未返回 videoUrl: ${JSON.stringify(task)}`);
      const url = await this.media.persistVideo(task.videoUrl, `videos/generated-${taskId}.mp4`);
      const output: ExecuteResult = {
        taskId,
        status: 'succeeded',
        videoUrl: url,
        coverUrl: task.coverUrl,
        model: config.model,
        metadata: task.raw,
        output: url,
      };
      applyOutputParams(data, output);
      return output;
    });

    this.register('knowledge_upsert', async (node, input) => {
      const data = node.data || {};
      const content = agentText(data, input, 'content', 'output');
      if (!content) throw new Error('写入知识库节点缺少 content');
      const config = await this.plan.resolve(data, 'knowledge');
      const embedding = config.apiUrl && config.apiKey && config.model ? await this.plan.embedding(config, content) : [];
      const output = await this.knowledge.upsert(
        stringData(data, 'knowledgeBaseId', 'default'),
        stringData(data, 'title'),
        content,
        stringData(data, 'sourceUrl'),
        this.plan.splitTags(stringData(data, 'tags')),
        embedding,
        config.model,
      );
      output.output = output.contentId;
      return output;
    });

    this.register('knowledge_retrieve', async (node, input) => {
      const data = node.data || {};
      const query = agentText(data, input, 'query', 'input');
      if (!query) throw new Error('检索知识库节点缺少 query');
      const config = await this.plan.resolve(data, 'knowledge');
      const embedding = config.apiUrl && config.apiKey && config.model ? await this.plan.embedding(config, query) : [];
      const result = await this.knowledge.retrieve(
        stringData(data, 'knowledgeBaseId', 'default'),
        query,
        embedding,
        intData(data, 'topK', 5),
        doubleData(data, 'scoreThreshold', 0.2),
      );
      result.output = result.context;
      return result;
    });

    this.register('memory_write', async (node, input) => {
      const data = node.data || {};
      const content = agentText(data, input, 'content', 'output');
      if (!content) throw new Error('写入记忆节点缺少 content');
      const config = await this.plan.resolve(data, 'memory');
      const embedding = config.apiUrl && config.apiKey && config.model ? await this.plan.embedding(config, content) : [];
      return this.plan.writeMemory(
        content,
        stringData(data, 'memoryType', 'fact') || 'fact',
        stringData(data, 'scope', 'workflow') || 'workflow',
        this.plan.splitTags(stringData(data, 'tags')),
        node.id,
        embedding,
        config.model,
      );
    });

    this.register('memory_retrieve', async (node, input) => {
      const data = node.data || {};
      const query = agentText(data, input, 'query', 'input');
      if (!query) throw new Error('召回记忆节点缺少 query');
      const config = await this.plan.resolve(data, 'memory');
      const embedding = config.apiUrl && config.apiKey && config.model ? await this.plan.embedding(config, query) : [];
      const result = this.plan.retrieveMemory(
        query,
        stringData(data, 'scope', 'workflow') || 'workflow',
        this.plan.splitTags(stringData(data, 'tags')),
        embedding,
        intData(data, 'topK', 5),
      );
      result.output = result.context;
      return result;
    });

    this.register('web_search', async (node, input) => {
      const data = node.data || {};
      const query = agentText(data, input, 'query', 'input');
      if (!query) throw new Error('联网搜索节点缺少 query');
      const selected = await this.mcp.firstEnabledWebSearch(data.mcpToolIds);
      if (!selected) throw new Error('联网搜索节点未配置，请先在 MCP 工具中添加 Agent Plan 联网搜索，并在当前节点选择它');
      const freshness = stringData(data, 'freshness');
      const ranges: Record<string, string> = { day: 'OneDay', week: 'OneWeek', month: 'OneMonth', year: 'OneYear' };
      const searchType = (stringData(data, 'language', 'zh') || '').toLowerCase() === 'image' ? 'image' : 'web';
      const result = await this.mcp.webSearch(selected, query, intData(data, 'limit', 5), freshness ? ranges[freshness] || freshness : null, searchType);
      return {
        query,
        summary: result.summary,
        results: result.results,
        citations: result.citations,
        output: result.summary,
        metadata: result.raw,
      };
    });

    this.register('web_fetch', async (node, input) => {
      const data = node.data || {};
      const urls = agentText(data, input, 'urls', 'url');
      if (!urls) throw new Error('网页读取节点缺少 urls');
      const pages: any[] = [];
      for (const url of urls.split(/[,，\n\s]+/).filter(Boolean)) {
        const response = await axios.get<string>(url.trim(), { timeout: 30000, headers: { 'User-Agent': 'AgentFlow/1.0' }, responseType: 'text' });
        const content = String(response.data).slice(0, 8000);
        pages.push({ url: url.trim(), content });
      }
      const output = pages.map((page) => `URL: ${page.url}\n${page.content}\n\n`).join('').trim();
      return { pages, content: output, citations: pages.map((page) => page.url), output };
    });

    this.register('vision_analyze', async (node, input) => {
      const data = node.data || {};
      const imageUrl = agentText(data, input, 'imageUrl', 'imageUrl');
      const videoUrl = agentText(data, input, 'videoUrl', 'videoUrl');
      if (!imageUrl && !videoUrl) throw new Error('视觉质检节点缺少 imageUrl 或 videoUrl');
      const config = await this.plan.resolve(data, 'vision');
      this.plan.validate(config, '视觉质检');
      const criteria = stringData(data, 'criteria', '判断素材是否满足输入要求，给出问题列表和 0-100 分。');
      const prompt = `请对下面的视觉素材做质检。\n质检要求：${criteria}\n图片 URL：${imageUrl || ''}\n视频 URL：${videoUrl || ''}\n\n请用中文返回简洁结论，包含：描述、分数、问题列表、是否通过。`;
      const response = await this.llm.chat(config.provider, config.apiUrl!, config.apiKey!, config.model!, 0.2, [{ role: 'user', content: prompt }]);
      const score = response.content.includes('不通过') ? 60 : 85;
      const passed = score >= 80 && !response.content.includes('不通过');
      return { description: response.content, score, issues: passed ? [] : [response.content], pass: passed, output: response.content };
    });
  }

  private async llmConfig(node: FlowNode): Promise<any> {
    const data = node.data || {};
    const configId = toInt(data.configId);
    let provider: string | null = null;
    let apiUrl: string | null = null;
    let apiKey: string | null = null;
    let model: string | null = null;
    if (configId !== null) {
      const global = await AppDataSource.getRepository(LLMGlobalConfig).findOne({ where: { id: configId, deleted: 0 } as any });
      if (global) {
        apiUrl = text(global.apiUrl);
        apiKey = text(global.apiKey);
        model = text(global.model);
        provider = canonicalizeProvider(global.provider);
      } else {
        provider = canonicalizeProvider(data.provider);
        apiUrl = text(data.apiUrl);
        apiKey = text(data.apiKey);
        model = text(data.model);
      }
    } else {
      provider = canonicalizeProvider(data.provider);
      apiUrl = text(data.apiUrl);
      apiKey = text(data.apiKey);
      model = text(data.model);
    }
    if (!provider && node.type !== 'llm') provider = canonicalizeProvider(node.type);
    return {
      provider,
      apiUrl,
      apiKey,
      model,
      temperature: toFloat(data.temperature, 0.7) ?? 0.7,
      prompt: data.prompt,
      inputParams: Array.isArray(data.inputParams) ? data.inputParams : [],
      outputParams: Array.isArray(data.outputParams) ? data.outputParams : [],
      streaming: truthy(data.streaming),
      skillName: text(data.skillName),
    };
  }

  private validateLlm(config: any, nodeType: string): void {
    if (!config.provider) throw new Error('LLM 节点缺少有效的提供商配置，请先选择供应商或全局配置');
    if (!config.apiUrl || !config.apiKey || !config.model) {
      throw new Error(`${nodeType.toUpperCase()} 节点缺少有效的模型配置，请检查全局配置或节点配置`);
    }
  }

  private buildOutput(response: any, outputParams: any[]): ExecuteResult {
    const output: ExecuteResult = {};
    if (outputParams.length) {
      for (const param of outputParams) output[String(param?.name)] = response.content;
    } else {
      output.output = response.content;
    }
    output.inputTokens = response.inputTokens;
    output.outputTokens = response.outputTokens;
    output.totalTokens = response.totalTokens;
    output.tokens = response.totalTokens;
    return output;
  }

  private isReactEnabled(data: Record<string, any>): boolean {
    if (String(data.agentStrategy || '').trim().toLowerCase() === 'react') return true;
    const tools = data.tools;
    if (Array.isArray(tools)) return tools.length > 0;
    return typeof tools === 'string' && Boolean(tools.trim());
  }

  private async runLlm(node: FlowNode, input: ExecuteResult, progress?: Progress): Promise<ExecuteResult> {
    const data = node.data || {};
    if (this.isReactEnabled(data)) return this.runReAct(node, input, progress);
    const config = await this.llmConfig(node);
    this.validateLlm(config, node.type || 'llm');

    let systemPrompt = '';
    if (config.skillName) {
      const skill = this.skills.get(config.skillName);
      if (skill) systemPrompt = this.skillExecutionPrompt(skill, this.skills.allReferences(config.skillName)) + '\n\n---\n\n';
    }
    let userPrompt = this.llm.processTemplate(config.prompt, config.inputParams, input);
    const query = this.contextQuery(config.inputParams, input, userPrompt);
    const context = await this.contextPrompt(data, query);
    if (context) userPrompt = `${context}\n\n---\n\n用户任务:\n${userPrompt}`;

    const messages: Array<{ role: string; content: string }> = [];
    if (systemPrompt.trim()) messages.push({ role: 'system', content: systemPrompt });
    messages.push({ role: 'user', content: userPrompt });

    const onChunk = config.streaming && progress
      ? (chunk: string, accumulated: string) => progress('生成中...', { chunk, accumulated })
      : undefined;
    const response = await this.llm.chat(config.provider, config.apiUrl, config.apiKey, config.model, config.temperature, messages, onChunk);
    return this.buildOutput(response, config.outputParams);
  }

  private skillExecutionPrompt(skill: any, references: Record<string, string>): string {
    const parts = [`# 技能: ${skill.name}\n\n`, `${skill.description}\n\n`, '---\n\n', '## 技能指南\n\n', `${skill.content}\n\n`];
    if (Object.keys(references).length) {
      parts.push('## 参考文档\n\n');
      for (const [name, value] of Object.entries(references)) parts.push(`### ${name}\n\n${value}\n\n`);
    }
    return parts.join('');
  }

  private contextQuery(inputParams: any[], input: ExecuteResult, userPrompt: string): string {
    for (const param of inputParams || []) {
      if (param?.type !== 'reference' || !param.referenceNode) continue;
      const key = String(param.referenceNode).split('.').pop() || '';
      let value = input[key];
      if (value === undefined && key === 'user_input') value = input.input;
      if (value !== undefined && value !== null && String(value).trim()) return String(value).trim();
    }
    return input.input !== undefined && String(input.input).trim() ? String(input.input).trim() : userPrompt;
  }

  private async contextPrompt(data: Record<string, any>, query: string): Promise<string> {
    const parts: string[] = [];
    if (truthy(data.memoryEnabled)) {
      try {
        const config = await this.plan.resolve(data, 'memory');
        const embedding = config.apiUrl && config.apiKey && config.model ? await this.plan.embedding(config, query) : [];
        const result = this.plan.retrieveMemory(query, 'workflow', [], embedding, intData(data, 'memoryTopK', 5));
        if (result.context) parts.push(`相关记忆:\n${result.context}\n\n`);
      } catch {
        // ignore memory failures
      }
    }
    if (text(data.knowledgeBaseId)) {
      try {
        const result = await this.knowledge.searchRuntime(
          text(data.knowledgeBaseId),
          query,
          intData(data, 'knowledgeTopK', 5),
          doubleData(data, 'knowledgeScoreThreshold', 0.2),
          this.plan,
        );
        if (result.context) parts.push(`知识库上下文:\n${result.context}\n\n`);
      } catch {
        // ignore knowledge failures
      }
    }
    return parts.length
      ? `以下是可用于回答当前任务的上下文。若上下文与任务无关，请忽略；若相关，请优先依据上下文回答。\n\n${parts.join('').trim()}`
      : '';
  }

  private async runReAct(node: FlowNode, input: ExecuteResult, progress?: Progress): Promise<ExecuteResult> {
    const data = node.data || {};
    const config = await this.llmConfig(node);
    if (!config.provider) throw new Error('ReAct Agent 缺少有效的提供商配置');
    this.validateLlm(config, 'react_agent');
    if (!config.prompt) throw new Error('ReAct Agent 缺少任务提示词');

    const goal = this.llm.processTemplate(config.prompt, config.inputParams, input);
    const maxSteps = Math.max(1, Math.min(20, intData(data, 'maxSteps', 5)));
    let toolNames: string[] = Array.isArray(data.tools)
      ? data.tools.map(String).filter(Boolean)
      : typeof data.tools === 'string'
        ? data.tools.split(',').map((item) => item.trim()).filter(Boolean)
        : [];
    if (text(data.knowledgeBaseId) && !toolNames.includes('knowledge_retrieve')) toolNames.push('knowledge_retrieve');
    if (toolNames.includes('web_search') && !toolNames.includes('web_fetch')) toolNames.push('web_fetch');
    if (!toolNames.length) throw new Error('ReAct Agent 至少需要启用一个工具');

    const systemPrompt = this.reActSystemPrompt(data, config, toolNames);
    const trace: any[] = [];
    const totals = { inputTokens: 0, outputTokens: 0, totalTokens: 0 };
    for (let step = 1; step <= maxSteps; step++) {
      const userPrompt = jdump({ goal, currentInput: input, previousSteps: trace, step, maxSteps });
      const response = await this.llm.chat(config.provider, config.apiUrl, config.apiKey, config.model, config.temperature, [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userPrompt },
      ]);
      totals.inputTokens += response.inputTokens;
      totals.outputTokens += response.outputTokens;
      totals.totalTokens += response.totalTokens;
      const decision = this.parseDecision(response.content);
      const item: any = { step, action: decision.action, reasoningSummary: decision.reasoningSummary };
      if (decision.action === 'final_answer') {
        item.finalAnswer = decision.finalAnswer;
        trace.push(item);
        if (progress) progress('ReAct 完成', item);
        return this.reActOutput(decision.finalAnswer, trace, totals, false, null);
      }
      if (decision.action !== 'tool_call') {
        item.finalAnswer = response.content;
        trace.push(item);
        return this.reActOutput(response.content, trace, totals, false, null);
      }
      let observation: any;
      try {
        observation = await this.callTool(decision.toolName, decision.toolInput, node, data, input);
      } catch (error: any) {
        observation = { error: String(error?.message || error), recoverable: true };
      }
      item.toolName = decision.toolName;
      item.toolInput = decision.toolInput;
      item.observation = observation;
      trace.push(item);
      if (progress) progress(`ReAct 工具调用: ${decision.toolName}`, item);
    }
    const message = `达到最大 ReAct 步数限制: ${maxSteps}`;
    return this.reActOutput(message, trace, totals, true, message);
  }

  private reActSystemPrompt(data: Record<string, any>, config: any, toolNames: string[]): string {
    const parts = [
      '你是一个运行在 AgentFlow 工作流节点里的 ReAct Agent。\n',
      '你必须通过 JSON 决策进行工具调用或给出最终答案，不要输出 Markdown 代码块。\n',
      '不要暴露完整隐藏推理链，只在 reasoningSummary 字段给一句简短行动理由。\n\n',
    ];
    if (text(data.knowledgeBaseId)) parts.push('当前节点已配置知识库。回答项目资料或配置相关问题时，必须先调用 knowledge_retrieve 检索知识库。\n\n');
    if (config.skillName) {
      const skill = this.skills.get(config.skillName);
      if (skill) parts.push(`当前节点关联 Skill: ${skill.name}\n${skill.description}\n\n`);
    }
    parts.push('可用工具:\n');
    const descriptions: Record<string, [string, string]> = {
      knowledge_retrieve: ['从知识库检索相关内容', '{"query":"string"}'],
      memory_retrieve: ['召回长期记忆', '{"query":"string"}'],
      memory_write: ['写入长期记忆', '{"content":"string"}'],
      web_search: ['联网搜索', '{"query":"string"}'],
      web_fetch: ['抓取网页', '{"url":"string"}'],
      read_current_input: ['读取当前输入', '{}'],
      load_skill_detail: ['加载技能详情', '{"skill_name":"string"}'],
      load_skill_reference: ['加载技能参考文档', '{"skill_name":"string","reference_name":"string"}'],
    };
    for (const name of toolNames) {
      const [description, schema] = descriptions[name] || ['工具', '{}'];
      parts.push(`- name: ${name}\n  description: ${description}\n  inputSchema: ${schema}\n`);
    }
    parts.push('\n每次只返回下面两种 JSON 之一：\n');
    parts.push('{"action":"tool_call","reasoningSummary":"为什么需要这个工具","toolName":"工具名","toolInput":{}}\n');
    parts.push('{"action":"final_answer","reasoningSummary":"为什么可以结束","finalAnswer":"最终答案"}\n');
    return parts.join('');
  }

  private parseDecision(content: string): any {
    let cleaned = (content || '').trim();
    if (cleaned.startsWith('```')) {
      const firstNewline = cleaned.indexOf('\n');
      const lastFence = cleaned.lastIndexOf('```');
      if (firstNewline >= 0 && lastFence > firstNewline) cleaned = cleaned.slice(firstNewline + 1, lastFence).trim();
    }
    try {
      const json = JSON.parse(cleaned);
      let action = String(json.action || '').trim().toLowerCase() || 'final_answer';
      if (['tool', 'call_tool', 'function_call'].includes(action)) action = 'tool_call';
      if (['final', 'answer'].includes(action)) action = 'final_answer';
      return {
        action,
        reasoningSummary: String(json.reasoningSummary || ''),
        toolName: json.toolName || json.tool_name || null,
        toolInput: typeof (json.toolInput || json.tool_input || json.arguments) === 'object' ? (json.toolInput || json.tool_input || json.arguments) : {},
        finalAnswer: String(json.finalAnswer || json.final_answer || json.answer || json.content || ''),
      };
    } catch {
      return { action: 'final_answer', reasoningSummary: '模型直接返回了最终内容', toolName: null, toolInput: {}, finalAnswer: content };
    }
  }

  private reActOutput(answer: string, trace: any[], totals: any, reached: boolean, stopReason: string | null): ExecuteResult {
    const output: ExecuteResult = {
      output: answer,
      finalAnswer: answer,
      toolTrace: trace,
      steps: trace.length,
      maxStepsReached: reached,
      inputTokens: totals.inputTokens,
      outputTokens: totals.outputTokens,
      totalTokens: totals.totalTokens,
      tokens: totals.totalTokens,
    };
    if (stopReason) output.stopReason = stopReason;
    return output;
  }

  private async callTool(name: string, args: any, node: FlowNode, data: Record<string, any>, input: ExecuteResult): Promise<any> {
    const arguments_ = args && typeof args === 'object' ? args : {};
    switch (name) {
      case 'read_current_input': return { currentInput: input };
      case 'knowledge_retrieve': {
        const base = firstText(arguments_.knowledgeBaseId, data.knowledgeBaseId, 'default') || 'default';
        const config = await this.plan.resolveKnowledge(null, null);
        const query = String(arguments_.query || '');
        const embedding = config.apiUrl && config.apiKey && config.model ? await this.plan.embedding(config, query) : [];
        return this.knowledge.retrieve(base, query, embedding, Number(arguments_.topK || data.knowledgeTopK || 5), Number(arguments_.scoreThreshold || data.knowledgeScoreThreshold || 0.2));
      }
      case 'memory_retrieve': {
        const query = String(arguments_.query || '');
        const config = await this.plan.resolve(data, 'memory');
        const embedding = config.apiUrl && config.apiKey && config.model ? await this.plan.embedding(config, query) : [];
        return this.plan.retrieveMemory(query, String(arguments_.scope || 'workflow'), [], embedding, Number(arguments_.topK || 5));
      }
      case 'memory_write': {
        const content = String(arguments_.content || '');
        const config = await this.plan.resolve(data, 'memory');
        const embedding = config.apiUrl && config.apiKey && config.model ? await this.plan.embedding(config, content) : [];
        return this.plan.writeMemory(content, String(arguments_.memoryType || 'fact'), String(arguments_.scope || 'workflow'), this.plan.splitTags(String(arguments_.tags || '')), node.id, embedding, config.model);
      }
      case 'load_skill_detail': {
        const skillName = String(arguments_.skill_name || '');
        if (!skillName) return { error: '缺少 skill_name' };
        return this.skills.get(skillName) ? { skillName, content: this.skills.fullContent(skillName) } : { error: `未找到 Skill: ${skillName}` };
      }
      case 'load_skill_reference': {
        const skillName = String(arguments_.skill_name || '');
        const referenceName = String(arguments_.reference_name || '');
        if (!skillName) return { error: '缺少 skill_name' };
        if (!referenceName) return { error: '缺少 reference_name' };
        return { skillName, referenceName, content: this.skills.loadReference(skillName, referenceName) };
      }
      case 'web_search': {
        const row = await this.mcp.firstEnabledWebSearch(data.mcpToolIds);
        if (!row) throw new Error('联网搜索工具未配置');
        const result = await this.mcp.webSearch(row, String(arguments_.query || ''), Number(arguments_.limit || 5), null, 'web');
        return { summary: result.summary, results: result.results, citations: result.citations };
      }
      case 'web_fetch': {
        const urls = Array.isArray(arguments_.urls) ? arguments_.urls : [arguments_.url, ...String(arguments_.urls || '').split(/[,，\n\s]+/)].filter(Boolean);
        const pages: any[] = [];
        for (const url of urls.filter(Boolean)) {
          const response = await axios.get<string>(String(url), { timeout: 30000, headers: { 'User-Agent': 'AgentFlow/1.0' }, responseType: 'text' });
          pages.push({ url: String(url), content: String(response.data).slice(0, 8000) });
        }
        return { pages, content: pages.map((page) => `URL: ${page.url}\n${page.content}\n\n`).join('').trim(), citations: pages.map((page) => page.url) };
      }
      default: throw new Error(`不支持的 Agent 工具: ${name}`);
    }
  }
}
