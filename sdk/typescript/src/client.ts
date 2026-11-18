import { ApiError } from "./errors.js";
import { WorkflowResource } from "./resources/workflows.js";
import { KnowledgeResource } from "./resources/knowledge.js";
import { SkillResource } from "./resources/skills.js";
import { McpResource } from "./resources/mcp.js";

export interface AgentFlowClientOptions {
  apiKey?: string;
  token?: string;
  timeout?: number;
}

export class AgentFlowClient {
  public readonly baseUrl: string;
  public readonly apiKey?: string;
  public readonly token?: string;
  /** Total request deadline, in milliseconds (including streaming consumption). */
  public readonly timeout: number;
  public readonly workflows: WorkflowResource;
  public readonly knowledge: KnowledgeResource;
  public readonly skills: SkillResource;
  public readonly mcp: McpResource;

  constructor(baseUrl: string, options: AgentFlowClientOptions = {}) {
    this.baseUrl = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
    this.apiKey = options.apiKey;
    this.token = options.token;
    this.timeout = options.timeout ?? 120_000;
    if (!Number.isSafeInteger(this.timeout) || this.timeout <= 0) {
      throw new RangeError("timeout must be a positive integer in milliseconds");
    }
    this.workflows = new WorkflowResource(this);
    this.knowledge = new KnowledgeResource(this);
    this.skills = new SkillResource(this);
    this.mcp = new McpResource(this);
  }

  async request(
    method: string,
    path: string,
    opts?: { json?: any; params?: Record<string, any> }
  ): Promise<any> {
    let url = this.baseUrl + path;
    const params = opts && opts.params;
    if (params) {
      const qs = new URLSearchParams(params).toString();
      if (qs) {
        url += "?" + qs;
      }
    }
    const headers: Record<string, string> = { Accept: "application/json" };
    if (this.apiKey) {
      headers["X-API-Key"] = this.apiKey;
    } else if (this.token) {
      headers["Authorization"] = "Bearer " + this.token;
    }
    let body: string | undefined;
    if (opts && opts.json !== undefined) {
      body = JSON.stringify(opts.json);
      headers["Content-Type"] = "application/json";
    }
    const resp = await fetch(url, { method, headers, body, signal: AbortSignal.timeout(this.timeout) });
    if (resp.status >= 400) {
      throw new ApiError(resp.status, await resp.text());
    }
    const data = (await resp.json()) as any;
    if (data.code !== 0) {
      throw new ApiError(data.code, data.message || "error", data);
    }
    return data.data;
  }
}
