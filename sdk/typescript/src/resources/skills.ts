import type { AgentFlowClient } from "../client.js";

export interface SkillSummary {
  name: string;
  title: string;
  description: string;
  version: string;
  tags: string[];
  editable: boolean;
}

export interface SkillDetail extends SkillSummary {
  content: string;
  rawContent: string;
  references: Array<{ name: string; file: string; size: number }>;
}

function skillPath(name: string): string {
  if (!/^[a-z][a-z0-9_-]{0,63}$/.test(name)) throw new RangeError("invalid skill identifier");
  return "/api/skills/" + encodeURIComponent(name);
}

export class SkillResource {
  constructor(private client: AgentFlowClient) {}

  list(): Promise<SkillSummary[]> {
    return this.client.request("GET", "/api/skills");
  }

  get(name: string): Promise<SkillDetail> {
    return this.client.request("GET", skillPath(name));
  }

  reload(): Promise<SkillSummary[]> {
    return this.client.request("POST", "/api/skills/reload");
  }

  save(name: string, content: string): Promise<SkillDetail> {
    return this.client.request("PUT", skillPath(name), { json: { content } });
  }

  delete(name: string): Promise<void> {
    return this.client.request("DELETE", skillPath(name));
  }

  reference(name: string, file: string): Promise<{ name: string; content: string }> {
    if (!/^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}\.md$/.test(file)) {
      throw new RangeError("invalid Markdown reference filename");
    }
    return this.client.request("GET", skillPath(name) + "/references/" + encodeURIComponent(file));
  }
}
