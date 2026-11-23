import { Injectable } from '@nestjs/common';
import { AppDataSource } from '../database/data-source';
import {
  KnowledgeBase,
  KnowledgeChunk,
  KnowledgeDocument,
  KnowledgeIndexTask,
} from '../database/entities';
import { AgentPlanService } from './agent-plan.service';
import { formatDate, firstText, jdump, jload, nowDate, text, toFloat, toInt, cosine } from '../common';

const DEFAULT_CHUNK_SIZE = 800;
const DEFAULT_OVERLAP = 100;
const STOP_TERMS = new Set(['应该', '怎么', '什么', '如何', '可以', '需要', '一个', '这个', '那个', '是否', '以及', 'the', 'and', 'for', 'with', 'what', 'how']);

function normalizeSize(value: any, fallback = DEFAULT_CHUNK_SIZE): number {
  const parsed = toInt(value, fallback) || fallback;
  return Math.max(100, Math.min(4000, parsed));
}

function normalizeOverlap(value: any, chunkSize: number, fallback = DEFAULT_OVERLAP): number {
  const parsed = toInt(value, fallback) ?? fallback;
  return Math.max(0, Math.min(Math.max(0, chunkSize - 1), parsed));
}

function splitContent(content: string | null, chunkSize: number, overlap: number): string[] {
  if (!content?.trim()) return [];
  const size = normalizeSize(chunkSize);
  const safeOverlap = normalizeOverlap(overlap, size);
  const step = Math.max(1, size - safeOverlap);
  const value = content.trim();
  const result: string[] = [];
  for (let start = 0; start < value.length; start += step) {
    result.push(value.slice(start, start + size));
    if (start + size >= value.length) break;
  }
  return result;
}

function normalizeSearchText(value: string | null): string {
  if (!value) return '';
  return value.toLowerCase().replace(/[^\u4e00-\u9fffA-Za-z0-9]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function searchTerms(query: string): Set<string> {
  const terms = new Set<string>();
  for (const part of query.split(/\s+/)) {
    if (!part) continue;
    if (/[\u4e00-\u9fff]/.test(part)) {
      if (part.length <= 4) {
        if (!STOP_TERMS.has(part)) terms.add(part);
      } else {
        for (let size = 2; size <= 4; size++) {
          for (let i = 0; i <= part.length - size; i++) {
            const term = part.slice(i, i + size);
            if (!STOP_TERMS.has(term)) terms.add(term);
          }
        }
      }
    } else if (part.length >= 2 && !STOP_TERMS.has(part)) {
      terms.add(part);
    }
  }
  return terms;
}

function textRelevance(query: string | null, content: string | null): number {
  const normalizedQuery = normalizeSearchText(query);
  const normalizedContent = normalizeSearchText(content);
  if (!normalizedQuery || !normalizedContent) return 0;
  if (normalizedContent.includes(normalizedQuery)) return 1;
  const terms = searchTerms(normalizedQuery);
  let total = 0;
  let matched = 0;
  for (const term of terms) {
    const weight = Math.min(4, Math.max(1, term.length - 1));
    total += weight;
    if (normalizedContent.includes(term)) matched += weight;
  }
  return total && matched ? Math.min(0.95, matched / total) : 0;
}

function tagsJson(value: string | null): string {
  if (!value) return jdump([]);
  const parsed = jload(value, null);
  if (Array.isArray(parsed)) return jdump(parsed.map(String).filter(Boolean));
  return jdump(value.split(/[,，\s]+/).map((item) => item.trim()).filter(Boolean));
}

@Injectable()
export class KnowledgeService {
  private baseRepo() { return AppDataSource.getRepository(KnowledgeBase); }
  private docRepo() { return AppDataSource.getRepository(KnowledgeDocument); }
  private chunkRepo() { return AppDataSource.getRepository(KnowledgeChunk); }
  private taskRepo() { return AppDataSource.getRepository(KnowledgeIndexTask); }

  private baseMap(base: KnowledgeBase): any {
    return {
      id: base.id,
      name: base.name,
      description: base.description,
      configId: base.configId ?? null,
      embeddingModel: base.embeddingModel,
      chunkSize: base.chunkSize,
      chunkOverlap: base.chunkOverlap,
      status: base.status,
      documentCount: base.documentCount,
      chunkCount: base.chunkCount,
      charCount: base.charCount,
      createdAt: formatDate(base.createdAt),
      updatedAt: formatDate(base.updatedAt),
    };
  }

  private docMap(document: KnowledgeDocument): any {
    return {
      id: document.id,
      knowledgeBaseId: document.knowledgeBaseId,
      title: document.title,
      sourceType: document.sourceType,
      sourceUrl: document.sourceUrl,
      fileName: document.fileName,
      tags: document.tags,
      status: document.status,
      charCount: document.charCount,
      errorMessage: document.errorMessage,
      createdAt: formatDate(document.createdAt),
      updatedAt: formatDate(document.updatedAt),
    };
  }

  private taskMap(task: KnowledgeIndexTask): any {
    return {
      id: task.id,
      knowledgeBaseId: task.knowledgeBaseId,
      documentId: task.documentId,
      status: task.status,
      progress: task.progress,
      totalChunks: task.totalChunks,
      finishedChunks: task.finishedChunks,
      errorMessage: task.errorMessage,
      createdAt: formatDate(task.createdAt),
      updatedAt: formatDate(task.updatedAt),
    };
  }

  async list(): Promise<any[]> {
    const rows = await this.baseRepo().find({ where: { deleted: 0 } as any, order: { updatedAt: 'DESC' } });
    return rows.map((row) => this.baseMap(row));
  }

  async get(id: number): Promise<any> {
    const base = await this.requireBase(id);
    const documents = await this.listDocuments(id);
    const tasks = await this.taskRepo().find({
      where: { knowledgeBaseId: id, deleted: 0 } as any,
      order: { updatedAt: 'DESC' },
      take: 10,
    });
    return { ...this.baseMap(base), documents, recentTasks: tasks.map((task) => this.taskMap(task)) };
  }

  async requireBase(id: number): Promise<KnowledgeBase> {
    const base = await this.baseRepo().findOne({ where: { id, deleted: 0 } as any });
    if (!base) throw new Error('知识库不存在');
    return base;
  }

  async requireDocument(baseId: number, documentId: number): Promise<KnowledgeDocument> {
    const document = await this.docRepo().findOne({ where: { id: documentId, deleted: 0 } as any });
    if (!document || document.knowledgeBaseId !== baseId) throw new Error('知识文档不存在');
    return document;
  }

  async create(payload: any): Promise<any> {
    const name = text(payload?.name);
    if (!name) throw new Error('知识库名称不能为空');
    const base = new KnowledgeBase();
    base.name = name;
    base.description = text(payload.description);
    base.configId = toInt(payload.configId);
    base.embeddingModel = firstText(payload.embeddingModel, 'doubao-embedding-vision');
    base.chunkSize = normalizeSize(payload.chunkSize);
    base.chunkOverlap = normalizeOverlap(payload.chunkOverlap, base.chunkSize ?? 800);
    base.status = 'DRAFT';
    base.documentCount = 0;
    base.chunkCount = 0;
    base.charCount = 0;
    base.deleted = 0;
    await this.baseRepo().save(base);
    return this.baseMap(base);
  }

  async delete(id: number): Promise<void> {
    await this.requireBase(id);
    await this.chunkRepo().update({ knowledgeBaseId: id, deleted: 0 } as any, { deleted: 1 });
    await this.taskRepo().update({ knowledgeBaseId: id, deleted: 0 } as any, { deleted: 1 });
    await this.docRepo().update({ knowledgeBaseId: id, deleted: 0 } as any, { deleted: 1 });
    await this.baseRepo().update({ id }, { deleted: 1, updatedAt: nowDate() });
  }

  async importText(baseId: number, payload: any): Promise<any> {
    const base = await this.requireBase(baseId);
    const content = payload?.content;
    if (content === undefined || content === null || !String(content).trim()) throw new Error('导入文本不能为空');
    const value = String(content);
    const document = new KnowledgeDocument();
    document.knowledgeBaseId = base.id;
    document.title = firstText(payload.title, '未命名文本');
    document.sourceType = 'TEXT';
    document.rawText = value;
    document.tags = text(payload.tags) ? tagsJson(text(payload.tags)) : null;
    document.status = 'IMPORTED';
    document.charCount = value.length;
    document.deleted = 0;
    await this.docRepo().save(document);
    await this.refreshStats(base.id, 'IMPORTED');
    return this.docMap(document);
  }

  async uploadTextFile(baseId: number, fileName: string, data: Buffer): Promise<any> {
    if (!data.length) throw new Error('上传文件不能为空');
    const name = text(fileName) || 'uploaded.txt';
    if (!/\.(txt|md|markdown)$/i.test(name)) throw new Error('当前版本仅支持 txt、md、markdown 文本文件');
    const output = await this.importText(baseId, { title: name, content: data.toString('utf8') });
    const document = await this.requireDocument(baseId, Number(output.id));
    document.fileName = name;
    await this.docRepo().save(document);
    return this.docMap(document);
  }

  async listDocuments(baseId: number): Promise<any[]> {
    const rows = await this.docRepo().find({
      where: { knowledgeBaseId: baseId, deleted: 0 } as any,
      order: { updatedAt: 'DESC' },
    });
    return rows.map((row) => this.docMap(row));
  }

  async preview(baseId: number, documentId: number, payload: any): Promise<any[]> {
    const base = await this.requireBase(baseId);
    const document = await this.requireDocument(baseId, documentId);
    const chunkSize = normalizeSize(payload?.chunkSize, base.chunkSize ?? 800);
    const overlap = normalizeOverlap(payload?.chunkOverlap, chunkSize, base.chunkOverlap ?? 100);
    return splitContent(document.rawText, chunkSize, overlap).map((content, index) => ({
      chunkIndex: index,
      content,
      charCount: content.length,
    }));
  }

  async indexDocument(baseId: number, documentId: number, plan: AgentPlanService): Promise<any> {
    const base = await this.requireBase(baseId);
    const document = await this.requireDocument(baseId, documentId);
    const task = new KnowledgeIndexTask();
    Object.assign(task, {
      knowledgeBaseId: base.id,
      documentId: document.id,
      status: 'RUNNING',
      progress: 0,
      totalChunks: 0,
      finishedChunks: 0,
      deleted: 0,
    });
    await this.taskRepo().save(task);
    try {
      const chunks = splitContent(document.rawText, base.chunkSize ?? 800, base.chunkOverlap ?? 100);
      await this.chunkRepo().update({ knowledgeBaseId: base.id, documentId: document.id, deleted: 0 } as any, { deleted: 1 });
      const planConfig = await plan.resolveKnowledge(base.configId, base.embeddingModel);
      const canEmbed = Boolean(planConfig.apiUrl && planConfig.apiKey && planConfig.model);
      for (let i = 0; i < chunks.length; i++) {
        const embedding = canEmbed ? await plan.embedding(planConfig, chunks[i]) : [];
        const chunk = new KnowledgeChunk();
        Object.assign(chunk, {
          knowledgeBaseId: base.id,
          documentId: document.id,
          chunkIndex: i,
          title: document.title,
          content: chunks[i],
          sourceUrl: document.sourceUrl,
          tags: tagsJson(document.tags),
          embeddingModel: planConfig.model,
          embedding: jdump(embedding),
          status: 'READY',
          charCount: chunks[i].length,
          deleted: 0,
        });
        await this.chunkRepo().save(chunk);
        task.finishedChunks = i + 1;
        task.totalChunks = chunks.length;
        task.progress = chunks.length ? Math.round(((i + 1) * 100) / chunks.length) : 100;
        await this.taskRepo().save(task);
      }
      document.status = 'READY';
      document.errorMessage = null;
      await this.docRepo().save(document);
      task.status = 'SUCCESS';
      task.progress = 100;
      await this.taskRepo().save(task);
      await this.refreshStats(base.id, 'READY');
    } catch (error: any) {
      document.status = 'FAILED';
      document.errorMessage = String(error?.message || error);
      await this.docRepo().save(document);
      task.status = 'FAILED';
      task.errorMessage = document.errorMessage;
      await this.taskRepo().save(task);
      await this.refreshStats(base.id, 'FAILED');
    }
    return this.taskMap(task);
  }

  async search(baseId: number, payload: any, plan: AgentPlanService): Promise<any> {
    const base = await this.requireBase(baseId);
    const query = payload?.query;
    if (!text(query)) throw new Error('检索问题不能为空');
    const config = await plan.resolveKnowledge(base.configId, base.embeddingModel);
    const embedding = config.apiUrl && config.apiKey && config.model ? await plan.embedding(config, String(query)) : [];
    return this.retrieve(String(base.id), String(query), embedding, toInt(payload.topK, 5) ?? 5, toFloat(payload.scoreThreshold, 0.2) ?? 0.2);
  }

  async searchRuntime(id: string | null, query: string, topK: number, threshold: number, plan: AgentPlanService): Promise<any> {
    const base = await this.resolveBaseForRuntime(id);
    const config = await plan.resolveKnowledge(base.configId, base.embeddingModel);
    const embedding = config.apiUrl && config.apiKey && config.model ? await plan.embedding(config, query) : [];
    return this.retrieve(String(base.id), query, embedding, topK, threshold);
  }

  async upsert(id: string | null, title: string | null, content: string, sourceUrl: string | null, tags: string[], embedding: number[], embeddingModel: string | null): Promise<any> {
    const base = await this.resolveBaseForRuntime(id);
    const documentMap = await this.importText(base.id, {
      title: firstText(title, '工作流写入'),
      content,
      tags: tags.length ? tags.join(',') : null,
    });
    const document = await this.requireDocument(base.id, Number(documentMap.id));
    const chunks = splitContent(content, base.chunkSize ?? 800, base.chunkOverlap ?? 100);
    await this.chunkRepo().update({ knowledgeBaseId: base.id, documentId: document.id, deleted: 0 } as any, { deleted: 1 });
    for (let i = 0; i < chunks.length; i++) {
      const chunk = new KnowledgeChunk();
      Object.assign(chunk, {
        knowledgeBaseId: base.id,
        documentId: document.id,
        chunkIndex: i,
        title: document.title,
        content: chunks[i],
        sourceUrl,
        tags: tagsJson(document.tags),
        embeddingModel,
        embedding: jdump(i === 0 && embedding.length ? embedding : []),
        status: 'READY',
        charCount: chunks[i].length,
        deleted: 0,
      });
      await this.chunkRepo().save(chunk);
    }
    document.status = 'READY';
    document.sourceUrl = sourceUrl;
    await this.docRepo().save(document);
    await this.refreshStats(base.id, 'READY');
    return { knowledgeBaseId: base.id, contentId: document.id, chunkCount: chunks.length, indexed: true };
  }

  async retrieve(id: string | null, query: string, queryEmbedding: number[], topK: number, threshold: number): Promise<any> {
    const base = await this.resolveBaseForRuntime(id);
    const effective = threshold <= 0 ? 0.000001 : threshold;
    const chunks = await this.chunkRepo().find({
      where: { knowledgeBaseId: base.id, status: 'READY', deleted: 0 } as any,
    });
    const matches = chunks
      .map((chunk) => {
        const vectorScore = cosine(queryEmbedding, jload(chunk.embedding, []) || []);
        const score = Math.max(vectorScore, textRelevance(query, chunk.content));
        return {
          chunkId: chunk.id,
          knowledgeBaseId: chunk.knowledgeBaseId,
          documentId: chunk.documentId,
          title: chunk.title,
          content: chunk.content,
          sourceUrl: chunk.sourceUrl,
          tags: chunk.tags,
          score,
        };
      })
      .filter((match) => match.score >= effective)
      .sort((a, b) => b.score - a.score)
      .slice(0, Math.max(1, topK));
    return {
      chunks: matches,
      citations: matches.map((match) => match.chunkId),
      context: matches.map((match) => `- ${match.content}`).join('\n'),
    };
  }

  private async resolveBaseForRuntime(id: string | null): Promise<KnowledgeBase> {
    if (id && id.trim().toLowerCase() !== 'default') {
      const value = id.trim();
      const numeric = toInt(value);
      if (numeric !== null) return this.requireBase(numeric);
      const named = await this.baseRepo().findOne({ where: { name: value, deleted: 0 } as any });
      if (named) return named;
    }
    const existing = await this.baseRepo().findOne({ where: { name: '默认知识库', deleted: 0 } as any });
    if (existing) return existing;
    return this.baseRepo().save(Object.assign(new KnowledgeBase(), {
      name: '默认知识库',
      description: '工作流运行时自动写入的默认知识库',
      embeddingModel: 'doubao-embedding-vision',
      chunkSize: 800,
      chunkOverlap: 100,
      status: 'DRAFT',
      documentCount: 0,
      chunkCount: 0,
      charCount: 0,
      deleted: 0,
    }));
  }

  private async refreshStats(baseId: number, status: string): Promise<void> {
    const base = await this.requireBase(baseId);
    base.documentCount = await this.docRepo().count({ where: { knowledgeBaseId: baseId, deleted: 0 } as any });
    base.chunkCount = await this.chunkRepo().count({ where: { knowledgeBaseId: baseId, status: 'READY', deleted: 0 } as any });
    const docs = await this.docRepo().find({ where: { knowledgeBaseId: baseId, deleted: 0 } as any });
    base.charCount = docs.reduce((sum, doc) => sum + Number(doc.charCount || 0), 0);
    base.status = status;
    await this.baseRepo().save(base);
  }
}
