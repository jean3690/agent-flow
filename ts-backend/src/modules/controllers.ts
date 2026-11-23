import {
  Body, Controller, Delete, Get, Param, Post, Put, Query, Headers, Res, UseInterceptors, UploadedFile,
} from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import { AppDataSource } from '../database/data-source';
import {
  ExecutionRecord, ExecutionSnapshot, ExecutionVariable, NodeDefinition, Workflow,
} from '../database/entities';
import { AuthService } from '../auth/auth.service';
import { EngineService } from '../engine/engine.service';
import { SkillsService } from '../services/skills.service';
import { KnowledgeService } from '../services/knowledge.service';
import { McpService } from '../services/mcp.service';
import { LlmConfigService } from '../services/llm-config.service';
import { MediaService } from '../services/media.service';
import { AgentPlanService } from '../services/agent-plan.service';
import { config } from '../config';
import { asJsonString, err, firstText, formatDate, jdump, jload, nowDate, ok, text, toInt } from '../common';

function workflowMap(workflow: Workflow): any {
  return {
    id: workflow.id,
    name: workflow.name,
    description: workflow.description,
    flowData: asJsonString(workflow.flowData),
    engineType: workflow.engineType,
    createdAt: formatDate(workflow.createdAt),
    updatedAt: formatDate(workflow.updatedAt),
  };
}

function nodeMap(node: NodeDefinition): any {
  return {
    id: node.id,
    nodeType: node.nodeType,
    displayName: node.displayName,
    category: node.category,
    icon: node.icon,
    inputSchema: node.inputSchema,
    outputSchema: node.outputSchema,
    configSchema: node.configSchema,
    createdAt: formatDate(node.createdAt),
    updatedAt: formatDate(node.updatedAt),
    deleted: node.deleted,
  };
}

@Controller('api/workflows')
export class WorkflowsController {
  private repo() { return AppDataSource.getRepository(Workflow); }

  @Post()
  async create(@Body() body: any) {
    if (!text(body?.name) || !text(body?.flowData)) return err('工作流名称和配置数据不能为空', 400);
    const workflow = this.repo().create({
      name: String(body.name),
      description: body.description ?? null,
      flowData: String(body.flowData),
      engineType: text(body.engineType) || 'dag',
      deleted: 0,
      createdAt: nowDate(),
      updatedAt: nowDate(),
    } as any) as unknown as Workflow;
    await this.repo().save(workflow);
    return ok(workflowMap(workflow));
  }

  @Get()
  async list() {
    const rows = await this.repo().find({ where: { deleted: 0 } as any, order: { updatedAt: 'DESC' } });
    return ok(rows.map(workflowMap));
  }

  @Get(':id')
  async get(@Param('id') id: string) {
    const workflow = await this.repo().findOne({ where: { id: Number(id), deleted: 0 } as any });
    return workflow ? ok(workflowMap(workflow)) : err('工作流不存在');
  }

  @Put(':id')
  async update(@Param('id') id: string, @Body() body: any) {
    if (!text(body?.name) || !text(body?.flowData)) return err('工作流名称和配置数据不能为空', 400);
    const workflow = await this.repo().findOne({ where: { id: Number(id), deleted: 0 } as any });
    if (!workflow) return err('工作流不存在');
    workflow.name = String(body.name);
    workflow.flowData = String(body.flowData);
    if (body.description !== undefined && body.description !== null) workflow.description = body.description;
    if (text(body.engineType)) workflow.engineType = text(body.engineType);
    workflow.updatedAt = nowDate();
    await this.repo().save(workflow);
    return ok(workflowMap(workflow));
  }

  @Delete(':id')
  async delete(@Param('id') id: string) {
    await this.repo().update({ id: Number(id) }, { deleted: 1, updatedAt: nowDate() } as any);
    return ok();
  }
}

@Controller('api/workflows')
export class ExecutionsController {
  private readonly recordRepo = AppDataSource.getRepository(ExecutionRecord);
  private readonly snapshotRepo = AppDataSource.getRepository(ExecutionSnapshot);
  private readonly variableRepo = AppDataSource.getRepository(ExecutionVariable);
  private readonly workflowRepo = AppDataSource.getRepository(Workflow);

  constructor(private readonly engine: EngineService) {}

  private async workflow(id: number): Promise<Workflow | null> {
    return this.workflowRepo.findOne({ where: { id, deleted: 0 } as any });
  }

  @Post(':id/execute')
  async execute(@Param('id') id: string, @Body() body: any) {
    const inputData = text(body?.inputData);
    if (!inputData) return err('输入数据不能为空', 400);
    const workflow = await this.workflow(Number(id));
    if (!workflow) return err('工作流不存在');
    try {
      return ok(await this.engine.execute(workflow, inputData));
    } catch (error: any) {
      return err(`工作流执行失败: ${error?.message || error}`);
    }
  }

  @Get(':id/executions/latest')
  async latest(@Param('id') id: string) {
    const workflow = await this.workflow(Number(id));
    if (!workflow) return err('工作流不存在');
    const record = await this.recordRepo.findOne({
      where: { flowId: Number(id), deleted: 0 } as any,
      order: { id: 'DESC' },
    });
    if (!record) return ok(null);
    return ok(this.executionResponse(record));
  }

  private executionResponse(record: ExecutionRecord): any {
    const nodeResults = jload(record.nodeResults, []);
    return {
      executionId: record.id,
      status: record.status,
      inputData: asJsonString(record.inputData),
      nodeResults: Array.isArray(nodeResults) ? nodeResults : [],
      outputData: asJsonString(record.outputData),
      duration: record.duration,
      errorMessage: record.errorMessage,
    };
  }

  @Get(':id/executions/:executionId/snapshots')
  async snapshots(@Param('id') id: string, @Param('executionId') executionId: string) {
    const record = await this.recordRepo.findOne({ where: { id: Number(executionId), deleted: 0 } as any });
    if (!record || record.flowId !== Number(id)) return err('执行记录不存在');
    const rows = await this.snapshotRepo.find({ where: { executionId: Number(executionId) } as any, order: { executionOrder: 'ASC' } });
    return ok(rows.map((row) => ({
      id: row.id,
      executionId: row.executionId,
      flowId: row.flowId,
      nodeId: row.nodeId,
      nodeType: row.nodeType,
      nodeName: row.nodeName,
      status: row.status,
      inputData: jload(row.inputData, {}) || {},
      outputData: jload(row.outputData, {}) || {},
      errorMessage: row.errorMessage,
      startedAt: formatDate(row.startedAt),
      completedAt: formatDate(row.completedAt),
      duration: row.duration,
      retryCount: row.retryCount,
      executionOrder: row.executionOrder,
      createdAt: formatDate(row.createdAt),
    })));
  }

  @Get(':id/executions/:executionId/variables')
  async variables(@Param('id') id: string, @Param('executionId') executionId: string) {
    const record = await this.recordRepo.findOne({ where: { id: Number(executionId), deleted: 0 } as any });
    if (!record || record.flowId !== Number(id)) return err('执行记录不存在');
    const rows = await this.variableRepo.find({ where: { executionId: Number(executionId) } as any, order: { variableName: 'ASC' } });
    return ok(rows.map((row) => ({
      id: row.id,
      executionId: row.executionId,
      variableName: row.variableName,
      variableType: row.variableType,
      variableValue: row.variableValue,
      isModified: Number(row.isModified) === 1,
      createdAt: formatDate(row.createdAt),
      updatedAt: formatDate(row.updatedAt),
    })));
  }

  @Post(':id/executions/:executionId/resume')
  async resume(@Param('id') id: string, @Param('executionId') executionId: string, @Body() body: any) {
    const workflow = await this.workflow(Number(id));
    if (!workflow) return err('工作流不存在');
    try {
      return ok(await this.engine.resume(workflow, Number(executionId), body || {}));
    } catch (error: any) {
      return err(`断点续执行失败: ${error?.message || error}`);
    }
  }

  @Get(':id/execute/stream')
  async stream(
    @Param('id') id: string,
    @Query('inputData') inputData: string,
    @Query('token') token: string,
    @Headers('authorization') authorization: string,
    @Res() response: any,
  ) {
    response.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
    response.setHeader('Cache-Control', 'no-cache');
    response.setHeader('Connection', 'keep-alive');
    response.setHeader('X-Accel-Buffering', 'no');
    response.flushHeaders();

    const emit = (event: any, eventName?: string) => {
      response.write(`event: ${eventName || event.eventType}\ndata: ${JSON.stringify(event)}\n\n`);
    };
    try {
      const workflow = await this.workflow(Number(id));
      if (!workflow) {
        emit(require('../engine/events').workflowComplete('FAILED', '工作流不存在', 0), 'ERROR');
      } else {
        await this.engine.execute(workflow, inputData || '', emit);
      }
    } catch (error: any) {
      emit(require('../engine/events').workflowComplete('FAILED', String(error?.message || error), 0), 'ERROR');
    }
    response.end();
  }
}

@Controller('api/node-types')
export class NodeTypesController {
  private repo() { return AppDataSource.getRepository(NodeDefinition); }

  @Get()
  async list() {
    const hidden = new Set(['react_agent', 'web_search', 'web_fetch', 'vision_analyze', 'memory_write', 'memory_retrieve', 'knowledge_upsert', 'knowledge_retrieve']);
    const map = new Map<string, NodeDefinition>();
    for (const row of await this.repo().find({ where: { deleted: 0 } as any, order: { id: 'ASC' } })) map.set(row.nodeType, row);
    const generic = (type: string, displayName: string, category: string, icon: string, input: string, output: string, config: string) => ({
      id: null, nodeType: type, displayName, category, icon, inputSchema: input, outputSchema: output, configSchema: config, createdAt: null, updatedAt: null, deleted: null,
    });
    const defaults: any[] = [
      generic('llm', '大模型', 'LLM', '🤖', '{"type":"object","properties":{"input":{"type":"string"}}}', '{"type":"object","properties":{"output":{"type":"string"}}}', '{"type":"object","properties":{}}'),
      generic('memory_write', '写入记忆', 'MEMORY', 'MW', '{}', '{}', '{}'),
      generic('memory_retrieve', '召回记忆', 'MEMORY', 'MR', '{}', '{}', '{}'),
      generic('knowledge_upsert', '写入知识库', 'KNOWLEDGE', 'KU', '{}', '{}', '{}'),
      generic('knowledge_retrieve', '检索知识库', 'KNOWLEDGE', 'KR', '{}', '{}', '{}'),
      generic('image_generate', '图片生成', 'TOOL', 'IMG', '{}', '{}', '{}'),
      generic('video_generate', '视频生成', 'TOOL', 'VID', '{}', '{}', '{}'),
    ];
    for (const node of defaults) if (!map.has(node.nodeType)) map.set(node.nodeType, node as any);
    const result = [...map.values()].filter((node) => !hidden.has(node.nodeType) && (node.category !== 'LLM' || node.nodeType === 'llm'));
    return ok(result.map((node) => nodeMap(node)));
  }
}

@Controller('api/llm-config')
export class LlmConfigController {
  constructor(private readonly service: LlmConfigService) {}

  @Get('detail/:id')
  async detail(@Param('id') id: string) {
    const config = await this.service.byId(id);
    return config ? ok(this.service.map(config)) : err('配置不存在');
  }

  @Get('default/:provider')
  async default(@Param('provider') provider: string) {
    const config = await this.service.defaultConfig(provider);
    return ok(config ? this.service.map(config) : null);
  }

  @Get(':provider')
  async byProvider(@Param('provider') provider: string) {
    return ok((await this.service.listByProvider(provider)).map((config) => this.service.map(config)));
  }

  @Get()
  async all() {
    return ok((await this.service.list()).map((config) => this.service.map(config)));
  }

  @Post()
  async save(@Body() body: any) {
    try {
      return ok(this.service.map(await this.service.save(body)));
    } catch (error: any) {
      return err(`保存配置失败: ${error?.message || error}`);
    }
  }

  @Delete(':id')
  async delete(@Param('id') id: string) {
    await this.service.delete(Number(id));
    return ok();
  }

  @Post(':id/default')
  async setDefault(@Param('id') id: string) {
    try {
      await this.service.setDefault(Number(id));
      return ok();
    } catch (error: any) {
      return err(`设置默认配置失败: ${error?.message || error}`);
    }
  }
}

@Controller('api/skills')
export class SkillsController {
  constructor(private readonly skills: SkillsService) {}

  @Get()
  list() { return ok(this.skills.summaries()); }

  @Get(':skillName/references/:referenceName')
  reference(@Param('skillName') skillName: string, @Param('referenceName') referenceName: string) {
    try {
      return ok(this.skills.loadReference(skillName, referenceName));
    } catch {
      return err(`Reference not found: ${skillName}/${referenceName}`, 404);
    }
  }

  @Get(':name')
  get(@Param('name') name: string) {
    const skill = this.skills.get(name);
    if (!skill) return err(`Skill not found: ${name}`, 404);
    return ok({ name: skill.name, description: skill.description, content: skill.content, references: skill.references });
  }
}

@Controller('api/knowledge-bases')
export class KnowledgeController {
  constructor(private readonly knowledge: KnowledgeService, private readonly plan: AgentPlanService) {}

  @Get()
  async list() { return ok(await this.knowledge.list()); }

  @Post()
  async create(@Body() body: any) {
    try { return ok(await this.knowledge.create(body)); }
    catch (error: any) { return err(error?.message || error); }
  }

  @Get(':id')
  async get(@Param('id') id: string) {
    try { return ok(await this.knowledge.get(Number(id))); }
    catch (error: any) { return err(error?.message || error); }
  }

  @Delete(':id')
  async delete(@Param('id') id: string) {
    await this.knowledge.delete(Number(id));
    return ok();
  }

  @Post(':id/documents/text')
  async importText(@Param('id') id: string, @Body() body: any) {
    try { return ok(await this.knowledge.importText(Number(id), body)); }
    catch (error: any) { return err(error?.message || error); }
  }

  @Post(':id/documents/upload')
  @UseInterceptors(FileInterceptor('file'))
  async upload(@Param('id') id: string, @UploadedFile() file: any) {
    try {
      if (!file) return err('上传文件不能为空');
      return ok(await this.knowledge.uploadTextFile(Number(id), file.originalname || 'uploaded.txt', file.buffer));
    } catch (error: any) { return err(error?.message || error); }
  }

  @Get(':id/documents')
  async documents(@Param('id') id: string) { return ok(await this.knowledge.listDocuments(Number(id))); }

  @Post(':id/documents/:documentId/preview-chunks')
  async preview(@Param('id') id: string, @Param('documentId') documentId: string, @Body() body: any) {
    try { return ok(await this.knowledge.preview(Number(id), Number(documentId), body || {})); }
    catch (error: any) { return err(error?.message || error); }
  }

  @Post(':id/documents/:documentId/index')
  async index(@Param('id') id: string, @Param('documentId') documentId: string) {
    try { return ok(await this.knowledge.indexDocument(Number(id), Number(documentId), this.plan)); }
    catch (error: any) { return err(error?.message || error); }
  }

  @Post(':id/search')
  async search(@Param('id') id: string, @Body() body: any) {
    try { return ok(await this.knowledge.search(Number(id), body || {}, this.plan)); }
    catch (error: any) { return err(error?.message || error); }
  }
}

@Controller('api/mcp-tools')
export class McpController {
  constructor(private readonly mcp: McpService) {}

  @Get()
  async list() { return ok(await this.mcp.list()); }

  @Post()
  async create(@Body() body: any) {
    try { return ok(await this.mcp.create(body)); }
    catch (error: any) { return err(error?.message || error); }
  }

  @Post('agent-plan-web-search')
  async createWebSearch(@Body() body: any) {
    try { return ok(await this.mcp.createWebSearch(body)); }
    catch (error: any) { return err(error?.message || error); }
  }

  @Put(':id')
  async update(@Param('id') id: string, @Body() body: any) {
    try { return ok(await this.mcp.update(Number(id), body)); }
    catch (error: any) { return err(error?.message || error); }
  }

  @Delete(':id')
  async delete(@Param('id') id: string) {
    await this.mcp.delete(Number(id));
    return ok();
  }

  @Post(':id/test')
  async test(@Param('id') id: string, @Body() body: any) {
    try { return ok(await this.mcp.test(Number(id), body?.query)); }
    catch (error: any) { return err(error?.message || error); }
  }
}

@Controller('api/media')
export class MediaController {
  constructor(private readonly media: MediaService, private readonly plan: AgentPlanService) {}

  @Post('images')
  @UseInterceptors(FileInterceptor('file'))
  async upload(@UploadedFile() file: any) {
    if (!file) return err('上传图片不能为空');
    const data: Buffer = file.buffer;
    const fileName = firstText(file.originalname, 'image.png') || 'image.png';
    const contentType = firstText(file.mimetype, 'image/png') || 'image/png';
    if (!data.length) return err('上传图片不能为空');
    if (data.length > 10 * 1024 * 1024) return err('图片大小不能超过 10MB');
    if (!contentType.toLowerCase().startsWith('image/') && !/\.(png|jpg|jpeg|webp|gif)$/i.test(fileName)) {
      return err('仅支持上传图片文件');
    }
    const extension = /\.(png|jpg|jpeg|webp|gif)$/i.exec(fileName.toLowerCase())?.[0] ||
      ({ 'image/jpeg': '.jpg', 'image/webp': '.webp', 'image/gif': '.gif' } as Record<string, string>)[contentType.toLowerCase()] || '.png';
    const objectName = `images/uploads/${require('crypto').randomUUID()}${extension}`;
    try {
      const url = await this.plan.uploadBytes(data, objectName, contentType);
      return ok({ url, fileName, contentType, size: data.length });
    } catch (error: any) {
      return err(`图片上传失败: ${error?.message || error}`);
    }
  }
}
