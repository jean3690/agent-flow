import { AgentFlowClient } from "../src/index.js";

function buildFlow(): any {
  return {
    nodes: [
      { id: "in", type: "input", name: "input", position: { x: 0, y: 0 }, config: { variables: ["topic"] } },
      {
        id: "llm",
        type: "llm",
        name: "llm",
        position: { x: 1, y: 0 },
        config: { provider: "mock", model: "agentflow-mock", prompt: "introduce {{input.topic}}" }
      },
      { id: "out", type: "output", name: "output", position: { x: 2, y: 0 }, config: {} }
    ],
    edges: [
      { id: "e1", source: "in", target: "llm" },
      { id: "e2", source: "llm", target: "out" }
    ]
  };
}

async function main(): Promise<void> {
  const baseUrl = process.env.AGENTFLOW_BASE_URL || "http://127.0.0.1:8084";
  const apiKey = process.env.AGENTFLOW_API_KEY;
  const client = new AgentFlowClient(baseUrl, { apiKey });
  const created = await client.workflows.create("sdk-demo", buildFlow());
  const workflowId = created.id;
  console.log("created workflow id=" + workflowId);
  const result = await client.workflows.run(workflowId, { topic: "LangGraph" });
  console.log("run status: " + result.status);
  console.log("outputs: " + JSON.stringify(result.outputs));
  await client.workflows.delete(workflowId);
  console.log("deleted workflow");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
