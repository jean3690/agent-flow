import { AgentFlowClient } from "../client.js";
import { ApiError } from "../errors.js";
import { parseEventStream } from "../sse.js";

export class WorkflowResource {
  constructor(private client: AgentFlowClient) {}

  list(page = 1, size = 10, keyword?: string): Promise<any> {
    const params: Record<string, any> = { page, size };
    if (keyword) {
      params.keyword = keyword;
    }
    return this.client.request("GET", "/api/workflows", { params });
  }

  get(id: number): Promise<any> {
    return this.client.request("GET", "/api/workflows/" + id);
  }

  create(
    name: string,
    flow: any,
    opts?: { description?: string; engineType?: string; status?: number }
  ): Promise<any> {
    const payload: any = {
      name,
      description: opts && opts.description ? opts.description : "",
      engineType: opts && opts.engineType ? opts.engineType : "langgraph",
      status: opts && opts.status !== undefined ? opts.status : 1,
      flow,
    };
    return this.client.request("POST", "/api/workflows", { json: payload });
  }

  update(id: number, fields: Record<string, any>): Promise<any> {
    return this.client.request("PUT", "/api/workflows/" + id, { json: fields });
  }

  delete(id: number): Promise<any> {
    return this.client.request("DELETE", "/api/workflows/" + id);
  }

  run(id: number, input?: Record<string, any>, opts?: Record<string, any>): Promise<any> {
    const payload: any = { input: input || {} };
    if (opts) {
      Object.assign(payload, opts);
    }
    return this.client.request("POST", "/api/workflows/" + id + "/run", { json: payload });
  }

  async *executeStream(
    id: number,
    input?: Record<string, any>,
    opts?: Record<string, any>
  ): AsyncGenerator<[string, any]> {
    const payload: any = { input: input || {} };
    if (opts) {
      Object.assign(payload, opts);
    }
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    };
    if (this.client.apiKey) {
      headers["X-API-Key"] = this.client.apiKey;
    } else if (this.client.token) {
      headers["Authorization"] = "Bearer " + this.client.token;
    }
    const resp = await fetch(this.client.baseUrl + "/api/workflows/" + id + "/execute", {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(this.client.timeout),
    });
    if (resp.status >= 400) {
      throw new ApiError(resp.status, await resp.text());
    }
    if (!resp.body) throw new ApiError(resp.status, "Missing SSE response body");
    yield* parseEventStream(resp.body);
  }
}
