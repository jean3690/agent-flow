import { AgentFlowClient } from "../client.js";

export class KnowledgeResource {
  constructor(private client: AgentFlowClient) {}

  list(): Promise<any> {
    return this.client.request("GET", "/api/knowledge-bases");
  }

  get(id: number): Promise<any> {
    return this.client.request("GET", "/api/knowledge-bases/" + id);
  }

  create(name: string, opts?: Record<string, any>): Promise<any> {
    const payload: any = {
      name,
      description: opts && opts.description ? opts.description : "",
      embeddingProvider: opts && opts.embeddingProvider ? opts.embeddingProvider : "mock",
      embeddingModel: opts && opts.embeddingModel ? opts.embeddingModel : "text-embedding-3-small",
      chunkSize: opts && opts.chunkSize ? opts.chunkSize : 600,
      chunkOverlap: opts && opts.chunkOverlap ? opts.chunkOverlap : 80,
    };
    return this.client.request("POST", "/api/knowledge-bases", { json: payload });
  }

  delete(id: number): Promise<any> {
    return this.client.request("DELETE", "/api/knowledge-bases/" + id);
  }

  addText(id: number, title: string, content: string, sourceType = "TEXT"): Promise<any> {
    return this.client.request("POST", "/api/knowledge-bases/" + id + "/documents/text", {
      json: { title, content, sourceType },
    });
  }

  index(id: number, documentId: number): Promise<any> {
    return this.client.request(
      "POST",
      "/api/knowledge-bases/" + id + "/documents/" + documentId + "/index"
    );
  }

  search(id: number, query: string, topK = 3): Promise<any> {
    return this.client.request("POST", "/api/knowledge-bases/" + id + "/search", {
      json: { query, topK },
    });
  }
}
