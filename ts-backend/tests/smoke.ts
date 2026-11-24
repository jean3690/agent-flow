import { spawn, ChildProcess } from 'child_process';
import * as http from 'http';
import path from 'path';

const PORT = 18085;
const root = path.resolve(__dirname, '..', '..');
const base = `http://127.0.0.1:${PORT}`;
const failures: string[] = [];

function check(name: string, condition: boolean, detail = ''): void {
  if (condition) console.log(`PASS  ${name}`);
  else {
    failures.push(name);
    console.log(`FAIL  ${name} ${detail}`);
  }
}

async function waitForServer(child: ChildProcess): Promise<void> {
  for (let i = 0; i < 100; i++) {
    if (child.exitCode !== null) throw new Error(`server exited with ${child.exitCode}`);
    try {
      const response = await fetch(`${base}/api/node-types`);
      if (response.ok) return;
    } catch {
      // not ready
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error('server did not start');
}

async function request(method: string, url: string, body?: any, token?: string): Promise<any> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${base}${url}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let json: any = null;
  try { json = JSON.parse(text); } catch { /* plain text */ }
  return { status: response.status, json, text };
}

async function main(): Promise<void> {
  const child = spawn(process.execPath, ['dist/src/main.js'], {
    cwd: root,
    env: {
      ...process.env,
      DB_TYPE: 'sqljs',
      SERVER_PORT: String(PORT),
      AGENTFLOW_AUTO_MIGRATE: 'true',
      APP_AUTH_DEFAULT_USERNAME: 'admin',
      APP_AUTH_DEFAULT_PASSWORD: 'admin123',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stdout?.on('data', (chunk) => process.stdout.write(`[server] ${chunk}`));
  child.stderr?.on('data', (chunk) => process.stderr.write(`[server] ${chunk}`));

    const stub = http.createServer((req, res) => {
      req.resume();
      req.on('end', () => {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          id: 'stub', object: 'chat.completion', created: 1, model: 'stub',
          choices: [{ index: 0, message: { role: 'assistant', content: JSON.stringify({ action: 'final_answer', reasoningSummary: 'done', finalAnswer: 'agent-ok' }) }, finish_reason: 'stop' }],
          usage: { prompt_tokens: 5, completion_tokens: 6, total_tokens: 11 },
        }));
      });
    });

  try {
    await waitForServer(child);

    const nodeTypes = await request('GET', '/api/node-types');
    const types = (nodeTypes.json?.data || []).map((item: any) => item.nodeType);
    check('node-types no auth', nodeTypes.status === 200 && nodeTypes.json.code === 200);
    check('node-types has llm', types.includes('llm'));
    const agentType = (nodeTypes.json?.data || []).find((item: any) => item.nodeType === 'react_agent');
    check('node-types exposes agent', Boolean(agentType) && agentType.displayName === '智能体', JSON.stringify(agentType || null));

    await new Promise<void>((resolve) => stub.listen(0, '127.0.0.1', () => resolve()));
    const stubPort = (stub.address() as any).port;

    const unauthorized = await request('GET', '/api/workflows');
    check('workflows requires auth', unauthorized.status === 401);

    const login = await request('POST', '/api/auth/login', { username: 'admin', password: 'admin123' });
    const token = login.json?.data?.token;
    check('login', Boolean(token), login.text.slice(0, 200));

    const flow = {
      nodes: [
        { id: 'i', type: 'input', data: { type: 'input', label: '输入' } },
        { id: 'o', type: 'output', data: { type: 'output', label: '输出' } },
      ],
      edges: [{ id: 'e', source: 'i', target: 'o' }],
    };
    const created = await request('POST', '/api/workflows', { name: 'smoke', flowData: JSON.stringify(flow) }, token);
    const workflowId = created.json?.data?.id;
    check('create workflow', created.json?.code === 200 && workflowId > 0, created.text.slice(0, 300));

    const fetched = await request('GET', `/api/workflows/${workflowId}`, undefined, token);
    check('get workflow', fetched.json?.data?.name === 'smoke');

    const executed = await request('POST', `/api/workflows/${workflowId}/execute`, { inputData: 'hello' }, token);
    const result = executed.json?.data || {};
    check('execute workflow', executed.json?.code === 200 && result.status === 'SUCCESS', executed.text.slice(0, 400));
    check('execute output', JSON.parse(result.outputData || '{}').output === 'hello', String(result.outputData));
    check('execute node results', (result.nodeResults || []).length === 2);

    const graphFlow = {
      nodes: [
        { id: 'gi', type: 'input', data: { type: 'input', label: '输入' } },
        {
          id: 'gc',
          type: 'condition',
          data: { type: 'condition', label: '条件', conditions: [{ id: 'yes', field: 'input', operator: 'eq', value: 'hello' }] },
        },
        { id: 'gy', type: 'output', data: { type: 'output', label: '是' } },
        { id: 'gn', type: 'output', data: { type: 'output', label: '否' } },
      ],
      edges: [
        { id: 'ge1', source: 'gi', target: 'gc' },
        { id: 'ge2', source: 'gc', target: 'gy', sourceHandle: 'yes' },
        { id: 'ge3', source: 'gc', target: 'gn', sourceHandle: 'no' },
      ],
    };
    const graphCreated = await request('POST', '/api/workflows', {
      name: 'smoke-langgraph',
      flowData: JSON.stringify(graphFlow),
      engineType: 'langgraph',
    }, token);
    const graphId = graphCreated.json?.data?.id;
    check('create langgraph workflow', graphCreated.json?.code === 200 && graphId > 0, graphCreated.text.slice(0, 300));
    const graphExecuted = await request('POST', `/api/workflows/${graphId}/execute`, { inputData: 'hello' }, token);
    const graphResult = graphExecuted.json?.data || {};
    check('langgraph execute', graphResult.status === 'SUCCESS', graphExecuted.text.slice(0, 500));
    check('langgraph branch output', JSON.parse(graphResult.outputData || '{}').output === 'hello', String(graphResult.outputData));
    check('langgraph skips other branch', (graphResult.nodeResults || []).length === 3, String((graphResult.nodeResults || []).length));
    await request('DELETE', `/api/workflows/${graphId}`, undefined, token);

    const latest = await request('GET', `/api/workflows/${workflowId}/executions/latest`, undefined, token);
    check('latest execution', latest.json?.data?.executionId === result.executionId);

    const snapshots = await request('GET', `/api/workflows/${workflowId}/executions/${result.executionId}/snapshots`, undefined, token);
    check('snapshots', (snapshots.json?.data || []).length === 2, snapshots.text.slice(0, 300));

    const config = await request('POST', '/api/llm-config', {
      provider: 'deepseek',
      configName: 'smoke',
      apiUrl: 'https://api.deepseek.com',
      apiKey: 'sk-test',
      model: 'deepseek-chat',
      temperature: 0.5,
    }, token);
    check('save llm config', config.json?.code === 200 && config.json?.data?.isDefault === 1, config.text.slice(0, 300));
    const defaultConfig = await request('GET', '/api/llm-config/default/deepseek', undefined, token);
    check('default llm config', defaultConfig.json?.data?.configName === 'smoke');

    const skills = await request('GET', '/api/skills', undefined, token);
    check('skills loaded', (skills.json?.data || []).some((item: any) => item.name === 'ai-podcast'), skills.text.slice(0, 200));

    const kb = await request('POST', '/api/knowledge-bases', { name: 'smoke-kb', description: 'd' }, token);
    const kbId = kb.json?.data?.id;
    check('create knowledge base', kb.json?.code === 200 && kbId > 0);
    const doc = await request('POST', `/api/knowledge-bases/${kbId}/documents/text`, {
      title: 'doc', content: 'AgentFlow 是一个工作流编排平台。输入节点会把用户输入传给下游。',
    }, token);
    const docId = doc.json?.data?.id;
    check('import knowledge text', Boolean(docId), doc.text.slice(0, 300));
    const indexed = await request('POST', `/api/knowledge-bases/${kbId}/documents/${docId}/index`, undefined, token);
    check('index knowledge document', indexed.json?.data?.status === 'SUCCESS', indexed.text.slice(0, 300));
    const search = await request('POST', `/api/knowledge-bases/${kbId}/search`, { query: '工作流编排', topK: 3 }, token);
    check('knowledge search', (search.json?.data?.chunks || []).length > 0, search.text.slice(0, 300));

    const mcp = await request('GET', '/api/mcp-tools', undefined, token);
    check('mcp tools list', mcp.json?.code === 200);

    const stream = await fetch(`${base}/api/workflows/${workflowId}/execute/stream?inputData=sse&token=${token}`);
    const streamText = await stream.text();
    check('sse stream', streamText.includes('event: WORKFLOW_START') && streamText.includes('event: WORKFLOW_COMPLETE'), streamText.slice(0, 300));

    const agentFlow = {
      nodes: [
        { id: 'ai', type: 'input', data: { type: 'input' } },
        {
          id: 'ag',
          type: 'react_agent',
          data: {
            type: 'react_agent',
            provider: 'deepseek',
            apiUrl: `http://127.0.0.1:${stubPort}`,
            apiKey: 'stub-key',
            model: 'stub',
            prompt: '{{q}}',
            inputParams: [{ name: 'q', type: 'reference', referenceNode: 'ai.input' }],
            agentStrategy: 'react',
            maxSteps: 2,
            tools: [],
          },
        },
        { id: 'ao', type: 'output', data: { type: 'output' } },
      ],
      edges: [
        { id: 'ae1', source: 'ai', target: 'ag' },
        { id: 'ae2', source: 'ag', target: 'ao' },
      ],
    };
    const agentCreated = await request('POST', '/api/workflows', { name: 'smoke-agent', flowData: JSON.stringify(agentFlow) }, token);
    const agentId = agentCreated.json?.data?.id;
    const agentExecuted = await request('POST', `/api/workflows/${agentId}/execute`, { inputData: 'hello' }, token);
    const agentResult = agentExecuted.json?.data || {};
    check('agent node executes without tools', agentResult.status === 'SUCCESS' && JSON.parse(agentResult.outputData || '{}').output === 'agent-ok', agentExecuted.text.slice(0, 400));
    await request('DELETE', `/api/workflows/${agentId}`, undefined, token);

    const deleted = await request('DELETE', `/api/workflows/${workflowId}`, undefined, token);
    check('delete workflow', deleted.json?.code === 200);
    const hidden = await request('GET', `/api/workflows/${workflowId}`, undefined, token);
    check('deleted workflow hidden', hidden.json?.code === 500);
  } finally {
    stub.close();
    child.kill('SIGTERM');
  }

  if (failures.length) {
    console.log(`\nFAILURES: ${failures.join(', ')}`);
    process.exit(1);
  }
  console.log('\nALL SMOKE TESTS PASSED');
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});