import { Injectable } from '@nestjs/common';
import axios from 'axios';
import { Client as MinioClient } from 'minio';
import { AppDataSource } from '../database/data-source';
import { LLMGlobalConfig } from '../database/entities';
import { config } from '../config';
import { canonicalizeProvider, cosine, firstText, jdump, text, toInt } from '../common';

export interface PlanConfig {
  configId: number | null;
  provider: string;
  apiUrl: string | null;
  apiKey: string | null;
  model: string | null;
  embeddingModel: string | null;
  imageModel: string | null;
  videoModel: string | null;
  memoryEnabled: boolean;
}

const DEFAULT_EMBEDDING = 'doubao-embedding-vision';

@Injectable()
export class AgentPlanService {
  private readonly minio: MinioClient;
  private readonly memories: any[] = [];

  constructor() {
    const endpoint = new URL(config.minioEndpoint);
    this.minio = new MinioClient({
      endPoint: endpoint.hostname,
      port: Number(endpoint.port) || (endpoint.protocol === 'https:' ? 443 : 80),
      useSSL: endpoint.protocol === 'https:',
      accessKey: config.minioAccessKey,
      secretKey: config.minioSecretKey,
    });
  }

  private repo() {
    return AppDataSource.getRepository(LLMGlobalConfig);
  }

  private async byId(id: any): Promise<LLMGlobalConfig | null> {
    const value = toInt(id);
    if (value === null) return null;
    return this.repo().findOne({ where: { id: value, deleted: 0 } as any });
  }

  private async defaultConfig(provider: string): Promise<LLMGlobalConfig | null> {
    return this.repo().findOne({ where: { provider, isDefault: 1, deleted: 0 } as any });
  }

  async resolve(data: Record<string, any>, capability: string): Promise<PlanConfig> {
    const nodeConfig = await this.byId(data.configId);
    const explicit = await this.byId(data.agentPlanConfigId);
    const globalConfig = explicit || nodeConfig || (await this.defaultConfig('volcengine_agent_plan'));

    const nodeModel = text(data.model);
    const languageModel = firstText(nodeModel, globalConfig?.model);
    const embeddingModel = firstText(capability === 'embedding' ? nodeModel : null, globalConfig?.embeddingModel, DEFAULT_EMBEDDING);
    const imageModel = firstText(capability === 'image' ? nodeModel : null, globalConfig?.imageModel, languageModel);
    const videoModel = firstText(capability === 'video' ? nodeModel : null, globalConfig?.videoModel, languageModel);
    const effective = ['embedding', 'memory', 'knowledge'].includes(capability)
      ? embeddingModel
      : capability === 'image'
        ? imageModel
        : capability === 'video'
          ? videoModel
          : languageModel;

    return {
      configId: globalConfig?.id ?? null,
      provider: canonicalizeProvider(firstText(globalConfig?.provider, data.provider, 'volcengine_agent_plan')) || 'volcengine_agent_plan',
      apiUrl: firstText(globalConfig?.apiUrl, data.apiUrl),
      apiKey: firstText(globalConfig?.apiKey, data.apiKey),
      model: effective,
      embeddingModel,
      imageModel,
      videoModel,
      memoryEnabled: Number(globalConfig?.memoryEnabled ?? 0) === 1,
    };
  }

  async resolveImage(data: Record<string, any>): Promise<PlanConfig> {
    const nodeConfig = await this.byId(data.configId);
    const configuredProvider = canonicalizeProvider(data.provider);
    let globalConfig = nodeConfig;
    if (!globalConfig) {
      globalConfig =
        (configuredProvider ? await this.defaultConfig(configuredProvider) : null) ||
        (await this.defaultConfig('volcengine_agent_plan')) ||
        (await this.defaultConfig('step'));
    }
    const nodeModel = text(data.model);
    const languageModel = firstText(nodeModel, globalConfig?.model);
    const imageModel = firstText(nodeModel, globalConfig?.imageModel, languageModel);
    return {
      configId: globalConfig?.id ?? null,
      provider: canonicalizeProvider(firstText(globalConfig?.provider, configuredProvider, 'volcengine_agent_plan')) || 'volcengine_agent_plan',
      apiUrl: firstText(globalConfig?.apiUrl, data.apiUrl),
      apiKey: firstText(globalConfig?.apiKey, data.apiKey),
      model: imageModel,
      embeddingModel: globalConfig?.embeddingModel ?? null,
      imageModel,
      videoModel: globalConfig?.videoModel ?? null,
      memoryEnabled: Number(globalConfig?.memoryEnabled ?? 0) === 1,
    };
  }

  async resolveKnowledge(configId: any, modelOverride: string | null): Promise<PlanConfig> {
    const globalConfig = await this.byId(configId);
    const embeddingModel = firstText(modelOverride, globalConfig?.embeddingModel, DEFAULT_EMBEDDING) as string;
    return {
      configId: toInt(configId),
      provider: canonicalizeProvider(firstText(globalConfig?.provider, 'volcengine_agent_plan')) || 'volcengine_agent_plan',
      apiUrl: globalConfig?.apiUrl ?? null,
      apiKey: globalConfig?.apiKey ?? null,
      model: embeddingModel,
      embeddingModel,
      imageModel: globalConfig?.imageModel ?? null,
      videoModel: globalConfig?.videoModel ?? null,
      memoryEnabled: Number(globalConfig?.memoryEnabled ?? 0) === 1,
    };
  }

  validate(config: PlanConfig, nodeName: string): void {
    if (!config.apiUrl || !config.apiKey || !config.model) {
      throw new Error(`${nodeName} 节点缺少有效的 Agent Plan 配置，请选择全局配置或填写 API 信息`);
    }
  }

  private baseUrl(apiUrl: string | null): string {
    let base = (apiUrl || '').trim().replace(/\/+$/, '');
    if (base.endsWith('/v1')) base = base.slice(0, -3);
    return base;
  }

  private async post(config: PlanConfig, endpoint: string, body: any): Promise<any> {
    const response = await axios.post(this.baseUrl(config.apiUrl) + endpoint, body, {
      headers: { Authorization: `Bearer ${config.apiKey}`, 'Content-Type': 'application/json' },
      timeout: 180000,
      transformResponse: [(data) => data],
    });
    const payload = typeof response.data === 'string' ? JSON.parse(response.data) : response.data;
    if (response.status < 200 || response.status >= 300) throw new Error(`Agent Plan 调用失败: HTTP ${response.status}`);
    return payload;
  }

  async embedding(config: PlanConfig, input: string): Promise<number[]> {
    const payload = await this.post(config, '/embeddings', { model: config.model, input });
    const data = payload?.data?.[0]?.embedding;
    return Array.isArray(data) ? data.map(Number).filter((value) => Number.isFinite(value)) : [];
  }

  async generateImage(config: PlanConfig, prompt: string, reference: string | null, size: string | null): Promise<{ imageUrls: string[]; metadata: any }> {
    const body: any = {
      model: config.model,
      prompt,
      response_format: 'url',
      output_format: 'png',
      watermark: false,
      stream: false,
    };
    if (size) body.size = size;
    if (reference) body.image = reference;
    const payload = await this.post(config, '/images/generations', body);
    return {
      imageUrls: (payload?.data || []).map((item: any) => item?.url).filter(Boolean),
      metadata: payload,
    };
  }

  async createVideoTask(config: PlanConfig, prompt: string, reference: string | null, duration: number, resolution: string | null, ratio: string | null): Promise<string | null> {
    const content: any[] = [{ type: 'text', text: prompt }];
    if (reference) content.push({ type: 'image_url', image_url: { url: reference } });
    const body: any = { model: config.model, content, generate_audio: true, duration, watermark: false };
    if (resolution) body.resolution = resolution;
    if (ratio) body.ratio = ratio;
    const payload = await this.post(config, '/contents/generations/tasks', body);
    return firstText(payload?.id, payload?.task_id, payload?.taskId);
  }

  async getVideoTask(config: PlanConfig, taskId: string): Promise<any> {
    const response = await axios.get(this.baseUrl(config.apiUrl) + `/contents/generations/tasks/${taskId}`, {
      headers: { Authorization: `Bearer ${config.apiKey}` },
      timeout: 180000,
      transformResponse: [(data) => data],
    });
    const payload = typeof response.data === 'string' ? JSON.parse(response.data) : response.data;
    return {
      status: firstText(payload?.status, payload?.task_status, 'running'),
      videoUrl: payload?.video_url || payload?.videoUrl || payload?.url || null,
      coverUrl: payload?.last_frame_url || payload?.cover_url || payload?.coverUrl || payload?.poster_url || null,
      raw: payload,
    };
  }

  writeMemory(content: string, memoryType: string, scope: string, tags: string[], source: string, embedding: number[], embeddingModel: string | null): any {
    const record = {
      id: require('crypto').randomUUID(),
      scope: scope || 'workflow',
      memoryType: memoryType || 'fact',
      content,
      tags,
      source,
      embedding,
      embeddingModel,
    };
    this.memories.push(record);
    return { memoryId: record.id, scope: record.scope, stored: true };
  }

  retrieveMemory(query: string, scope: string, tags: string[], embedding: number[], topK: number): any {
    const matches = this.memories
      .filter((memory) => !scope || memory.scope === scope)
      .filter((memory) => !tags.length || tags.every((tag) => memory.tags.includes(tag)))
      .map((memory) => {
        let score = cosine(embedding, memory.embedding);
        if (!score && query && memory.content.includes(query)) score = 0.5;
        return { ...memory, score };
      })
      .filter((match) => match.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, Math.max(1, topK));
    return {
      memories: matches,
      context: matches.map((match) => `- ${match.content}`).join('\n'),
      citations: matches.map((match) => match.memoryId),
    };
  }

  splitTags(value: string | null | undefined): string[] {
    if (!value) return [];
    return value.split(/[,，\s]+/).map((item) => item.trim()).filter(Boolean);
  }

  async ensureBucket(): Promise<void> {
    if (!(await this.minio.bucketExists(config.minioBucket))) {
      await this.minio.makeBucket(config.minioBucket);
    }
  }

  async uploadBytes(data: Buffer, objectName: string, contentType: string): Promise<string> {
    await this.ensureBucket();
    await this.minio.putObject(config.minioBucket, objectName, data, data.length, { 'Content-Type': contentType });
    return `${config.minioPublicUrl}/${config.minioBucket}/${objectName}`;
  }

  async uploadUrl(url: string, objectName: string, contentType: string): Promise<string> {
    const response = await axios.get<ArrayBuffer>(url, { responseType: 'arraybuffer', timeout: 180000 });
    return this.uploadBytes(Buffer.from(response.data), objectName, contentType);
  }
}
