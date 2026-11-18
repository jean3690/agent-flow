import type { AgentFlowClient } from "../client.js";

export interface McpTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

/** Safe configuration view: credentials and encrypted headers are not returned. */
export interface McpServer {
  id: number;
  name: string;
  url: string;
  timeoutMs: number;
  enabled: boolean;
  hasCredentials: boolean;
  allowedTools: string[];
  tools: McpTool[];
}

export interface McpCreateOptions {
  headers?: Record<string, string>;
  timeoutMs?: number;
  enabled?: boolean;
}

/** Full updates prevent accidental enabling, permission resets or secret deletion. */
export interface McpServerUpdate {
  name: string;
  url: string;
  allowedTools: readonly string[];
  timeoutMs: number;
  enabled: boolean;
  headers?: Record<string, string>;
  clearHeaders?: boolean;
}

export interface McpDiscoveryResult {
  ok: boolean;
  tools: McpTool[];
  message: string;
}

function serverPath(id: number): string {
  if (!Number.isSafeInteger(id) || id <= 0) {
    throw new RangeError("server id must be a positive safe integer");
  }
  return "/api/mcp-servers/" + id;
}

export class McpResource {
  constructor(private client: AgentFlowClient) {}

  list(): Promise<McpServer[]> {
    return this.client.request("GET", "/api/mcp-servers");
  }

  create(name: string, url: string, options: McpCreateOptions = {}): Promise<McpServer> {
    return this.client.request("POST", "/api/mcp-servers", { json: {
      name, url, allowedTools: [], headers: options.headers,
      timeoutMs: options.timeoutMs ?? 15000, enabled: options.enabled ?? true,
    } });
  }

  update(id: number, settings: McpServerUpdate): Promise<McpServer> {
    const path = serverPath(id);
    if (!Array.isArray(settings.allowedTools) || settings.allowedTools.some(
      tool => typeof tool !== "string" || !tool || tool.length > 128
    )) {
      throw new TypeError("allowedTools must be an array of tool names");
    }
    return this.client.request("PUT", path, { json: {
      name: settings.name, url: settings.url, allowedTools: [...settings.allowedTools],
      timeoutMs: settings.timeoutMs, enabled: settings.enabled,
      headers: settings.headers, clearHeaders: settings.clearHeaders ?? false,
    } });
  }

  discover(id: number): Promise<McpDiscoveryResult> {
    return this.client.request("POST", serverPath(id) + "/discover");
  }

  tools(id: number): Promise<McpTool[]> {
    return this.client.request("GET", serverPath(id) + "/tools");
  }

  delete(id: number): Promise<void> {
    return this.client.request("DELETE", serverPath(id));
  }
}
