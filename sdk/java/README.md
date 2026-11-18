# AgentFlow Java SDK

适用于 Java 17+。使用 JDK HttpClient，Jackson 解包 JSON；SSE 每个事件到达后立即回调，不等待整个响应结束。

## 本地安装

```bash
# 在仓库根目录执行（需要 Maven）
mvn -f sdk/java/pom.xml test install
```

调用方添加依赖（当前通过本地 Maven 仓库或自行发布的私服获取，不假定已发布 Maven Central）：

```xml
<dependency>
  <groupId>com.agentflow</groupId>
  <artifactId>agentflow-sdk</artifactId>
  <version>0.1.0</version>
</dependency>
```

## 调用示例

```java
import com.agentflow.sdk.AgentFlowClient;
import java.util.Map;

AgentFlowClient client = new AgentFlowClient(
    "http://127.0.0.1:8084", System.getenv("AGENTFLOW_API_KEY"));
long workflowId = 1L; // 替换为已有可执行工作流 ID
var result = client.runWorkflow(workflowId, Map.of("topic", "LangGraph"));
System.out.println(result.path("status").asText());
client.executeWorkflowStream(workflowId, Map.of(), event -> {
    System.out.println(event.name() + " " + event.data());
});
```

JWT 认证使用 `new AgentFlowClient(baseUrl, null, token)`。HTTP 错误或非零业务码通过 `ApiException` 返回；网络与 JSON 解析错误的 `code` 为 0。工作流自身失败需检查结果 `status` 或 `run_failed` 事件。

SSE 支持 LF/CRLF/CR、UTF-8、注释、默认 `message`、多行 JSON及无末尾空行；响应体在完成或异常时关闭。回调在读取流的调用线程执行，请避免耗时操作。当前 Java SDK 未暴露可配置超时，建议调用方增加请求期限与资源保护后再用于生产。

## MCP 与 Skills 管理

```java
import com.agentflow.sdk.AgentFlowClient;
import com.agentflow.sdk.McpServerSettings;
import java.util.List;

AgentFlowClient client = new AgentFlowClient(
    "http://127.0.0.1:8084", System.getenv("AGENTFLOW_API_KEY"));
var server = client.createMcpServer(new McpServerSettings(
    "文档工具", System.getenv("MCP_URL"), List.of(), 15000, false));
long serverId = server.path("id").asLong();
var probe = client.discoverMcpTools(serverId);
if (!probe.path("ok").asBoolean()) throw new IllegalStateException(probe.path("message").asText());
String tool = "echo"; // 替换为自己明确允许的工具
boolean available = false;
for (var item : probe.path("tools")) if (tool.equals(item.path("name").asText())) available = true;
if (!available) throw new IllegalStateException("目标工具不存在");
client.updateMcpServer(serverId, new McpServerSettings(
    server.path("name").asText(), server.path("url").asText(), List.of(tool),
    server.path("timeoutMs").asInt(), true));
System.out.println(client.listMcpTools(serverId));

// 保存 / 删除 / 重载 Skills 需要管理员权限。
client.saveSkill("report-helper", "---\nname: report-helper\ndescription: 报告指令\n---\n不编造数据。\n");
System.out.println(client.getSkill("report-helper").path("content").asText());
```

`McpServerSettings` 是完整更新配置，集合会复制为不可变快照，`toString()` 不打印 URL 和认证请求头。需要替换认证时使用七参数构造器传 `headers`；省略 / 传 null 表示保留已有认证，`clearHeaders=true` 才会明确清除。改变地址会在平台清除旧地址的凭据和工具发现结果。

`timeoutMs` 是平台 MCP 操作期限，不是 Java SDK 自身的 HTTP 超时。`discoverMcpTools()` 要检查 `ok`；HTTP / 权限错误仍通过 `ApiException` 表示。完整方法对照见 [SDK 接入说明](../../docs/sdk-integrations.md)。
