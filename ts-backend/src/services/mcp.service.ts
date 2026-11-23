import { Injectable } from '@nestjs/common';
import { spawn, ChildProcess } from 'child_process';
import readline from 'readline';
import { AppDataSource } from '../database/data-source';
import { McpToolConfig } from '../database/entities';
import { config } from '../config';
import { firstText, formatDate, jdump, jload, text, toInt } from '../common';

const SEARCH_PACKAGE = 'git+https://github.com/volcengine/mcp-server#subdirectory=server/mcp_server_askecho_search_infinity';
const SEARCH_COMMAND = 'mcp-server-askecho-search-infinity';
const SEARCH_ENV = 'ASK_ECHO_SEARCH_INFINITY_API_KEY';

function parseArgs(configRow: McpToolConfig): string[] {
  const value = jload(configRow.args, []);
  return Array.isArray(value) ? value.map(String) : [];
}

function parseEnv(configRow: McpToolConfig): Record<string, string> {
  const value = jload(configRow.env, {});
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const result: Record<string, string> = {};
  Object.entries(value).forEach(([key, item]) => (result[key] = item === null || item === undefined ? '' : String(item)));
  return result;
}

function safeMap(row: McpToolConfig): any {
  const env = parseEnv(row);
  const masked: Record<string, string> = {};
  for (const [key, value] of Object.entries(env)) {
    masked[key] = /KEY|SECRET|TOKEN|PASSWORD/i.test(key) ? '******' : value;
  }
  return {
    id: row.id,
    name: row.name,
    description: row.description,
    toolType: row.toolType,
    toolName: row.toolName,
    transport: row.transport,
    command: row.command,
    args: parseArgs(row),
    env: masked,
    enabled: row.enabled,
    preset: row.preset,
    createdAt: formatDate(row.createdAt),
    updatedAt: formatDate(row.updatedAt),
  };
}

class McpSession {
  private child: ChildProcess;
  private id = 0;
  private pending = new Map<number, { resolve: (value: any) => void; reject: (error: Error) => void }>();

  constructor(command: string, args: string[], env: Record<string, string>) {
    const commandLine = [command, ...args];
    this.child = spawn(commandLine[0], commandLine.slice(1), {
      env: { ...process.env, ...env },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const reader = readline.createInterface({ input: this.child.stdout! });
    reader.on('line', (line) => {
      if (!line.trim()) return;
      try {
        const message = JSON.parse(line);
        if (message.id !== undefined && this.pending.has(Number(message.id))) {
          const entry = this.pending.get(Number(message.id))!;
          this.pending.delete(Number(message.id));
          if (message.error) entry.reject(new Error(JSON.stringify(message.error)));
          else entry.resolve(message.result || {});
        }
      } catch {
        // ignore malformed lines
      }
    });
  }

  request(method: string, params: any, timeoutMs: number): Promise<any> {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`MCP ${method} 超时`));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (value) => { clearTimeout(timer); resolve(value); },
        reject: (error) => { clearTimeout(timer); reject(error); },
      });
      this.child.stdin!.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    });
  }

  notify(method: string, params: any): void {
    this.child.stdin!.write(JSON.stringify({ jsonrpc: '2.0', method, params }) + '\n');
  }

  close(): void {
    try { this.child.stdin?.end(); } catch { /* ignore */ }
    this.child.kill();
  }
}

@Injectable()
export class McpService {
  private repo() { return AppDataSource.getRepository(McpToolConfig); }

  async list(): Promise<any[]> {
    const rows = await this.repo().find({ where: { deleted: 0 } as any, order: { updatedAt: 'DESC' } });
    return rows.map(safeMap);
  }

  async create(payload: any, preset = false): Promise<any> {
    const row = new McpToolConfig();
    Object.assign(row, {
      name: text(payload?.name),
      description: text(payload?.description),
      toolType: firstText(payload?.toolType, 'custom'),
      toolName: text(payload?.toolName),
      transport: firstText(payload?.transport, 'stdio'),
      command: text(payload?.command),
      args: jdump(payload?.args || []),
      env: jdump(payload?.env || {}),
      enabled: payload?.enabled === undefined || toInt(payload.enabled, 1) === 1 ? 1 : 0,
      preset: preset ? 1 : 0,
      deleted: 0,
    });
    if (!row.name) throw new Error('MCP 名称不能为空');
    if (!row.toolName) throw new Error('工具名不能为空');
    if (!row.command) throw new Error('启动命令不能为空');
    await this.repo().save(row);
    return safeMap(row);
  }

  async createWebSearch(payload: any): Promise<any> {
    const apiKey = text(payload?.apiKey);
    if (!apiKey) throw new Error('联网搜索 API Key 不能为空');
    return this.create({
      name: firstText(payload?.name, 'Agent Plan 联网搜索'),
      description: firstText(payload?.description, '通过火山 Agent Plan Harness MCP 使用联网搜索额度'),
      toolType: 'agent_plan_web_search',
      toolName: 'web_search',
      transport: 'stdio',
      command: config.uvxPath,
      args: ['--from', SEARCH_PACKAGE, SEARCH_COMMAND],
      env: { [SEARCH_ENV]: apiKey },
      enabled: 1,
    }, true);
  }

  async update(id: number, payload: any): Promise<any> {
    const row = await this.repo().findOne({ where: { id, deleted: 0 } as any });
    if (!row) throw new Error('MCP 工具不存在');
    const updated = await this.create({ ...payload, preset: row.preset }, Number(row.preset) === 1);
    await this.repo().update({ id }, {
      name: updated.name,
      description: updated.description,
      toolType: updated.toolType,
      toolName: updated.toolName,
      transport: updated.transport,
      command: updated.command,
      args: jdump(updated.args),
      env: jdump(updated.env),
      enabled: updated.enabled,
      updatedAt: new Date(),
    } as any);
    return this.repo().findOne({ where: { id } as any });
  }

  async delete(id: number): Promise<void> {
    await this.repo().update({ id }, { deleted: 1, updatedAt: new Date() } as any);
  }

  async firstEnabledWebSearch(rawIds: any): Promise<McpToolConfig | null> {
    const ids = (Array.isArray(rawIds) ? rawIds : String(rawIds || '').split(','))
      .map((value) => toInt(value))
      .filter((value): value is number => value !== null);
    if (!ids.length) return null;
    const rows = await this.repo().find({ where: { id: require('typeorm').In(ids), deleted: 0 } as any });
    return rows.find((row) => row.toolName === 'web_search' && Number(row.enabled) === 1) || null;
  }

  async webSearch(row: McpToolConfig, query: string, count: number, timeRange: string | null, searchType: string): Promise<any> {
    if (!query) throw new Error('联网搜索缺少 query');
    const session = new McpSession(row.command, parseArgs(row), parseEnv(row));
    try {
      await session.request('initialize', {
        protocolVersion: '2024-11-05',
        capabilities: {},
        clientInfo: { name: 'AgentFlow', version: '1.0.0' },
      }, 90000);
      session.notify('notifications/initialized', {});
      const arguments_: any = {
        Query: query,
        Count: Math.max(1, Math.min(count, searchType.toLowerCase() === 'image' ? 5 : 50)),
        SearchType: searchType || 'web',
      };
      if (timeRange) arguments_.TimeRange = timeRange;
      const result = await session.request('tools/call', { name: 'web_search', arguments: arguments_ }, 120000);
      const content = Array.isArray(result?.content) ? result.content : [];
      const summary = content.map((item: any) => item?.text || '').filter(Boolean).join('\n');
      let parsed: any[] = [];
      for (const item of content) {
        if (!item?.text) continue;
        try { parsed.push(JSON.parse(item.text)); } catch { parsed.push({ text: item.text }); }
      }
      const webResults: any[] = [];
      const collect = (value: any): void => {
        if (!value || typeof value !== 'object') return;
        if (Array.isArray(value)) { value.forEach(collect); return; }
        const found = value.WebResults || value.webResults;
        if (Array.isArray(found)) found.forEach((item: any) => webResults.push({
          id: item?.Id ?? item?.id,
          title: item?.Title ?? item?.title,
          siteName: item?.SiteName ?? item?.siteName,
          url: item?.Url ?? item?.url,
          snippet: item?.Snippet ?? item?.snippet,
          summary: item?.Summary ?? item?.summary,
        }));
        Object.values(value).forEach(collect);
      };
      parsed.forEach(collect);
      const formatted = webResults.map((item, index) =>
        `${index + 1}. ${item.title || ''}${item.siteName ? ` - ${item.siteName}` : ''}\n${item.summary || item.snippet || ''}`,
      ).join('\n').trim();
      return {
        summary: formatted || summary,
        rawSummary: summary,
        webResults,
        results: parsed,
        citations: webResults.filter((item) => /^https?:\/\//i.test(item.url || '')).map((item) => ({
          url: item.url,
          title: item.title || item.url,
          siteName: item.siteName || '',
        })),
        content,
        isError: false,
        raw: result,
      };
    } finally {
      session.close();
    }
  }

  async test(id: number, query: string | null): Promise<any> {
    const row = await this.repo().findOne({ where: { id, deleted: 0 } as any });
    if (!row) throw new Error('MCP 工具不存在');
    if (row.toolName !== 'web_search') throw new Error('当前只支持测试 web_search MCP 工具');
    return this.webSearch(row, text(query) || '今天的科技新闻', 3, null, 'web');
  }
}
