import type {
  AgentFlowClient,
  McpServer,
  McpServerUpdate,
  McpDiscoveryResult,
  SkillDetail,
} from "../src/index.js";

// Compiled by the SDK test build: exported contracts remain available to callers.
function contracts(client: AgentFlowClient, server: McpServer): void {
  const settings: McpServerUpdate = {
    name: server.name, url: server.url, allowedTools: server.allowedTools,
    timeoutMs: server.timeoutMs, enabled: server.enabled,
  };
  const discovery: Promise<McpDiscoveryResult> = client.mcp.discover(server.id);
  const skill: Promise<SkillDetail> = client.skills.get("report-helper");
  void client.mcp.update(server.id, settings);
  void discovery;
  void skill;
  // @ts-expect-error A partial update must not reset service permissions/settings.
  void client.mcp.update(server.id, { name: server.name, url: server.url });
  // @ts-expect-error Safe server views never expose credential headers.
  void server.headers;
}
void contracts;
