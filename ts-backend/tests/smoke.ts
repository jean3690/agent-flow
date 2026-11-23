import { spawn, ChildProcess } from 'child_process';
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

  try {
    await waitForServer(child);

    const nodeTypes = await request('GET', '/api/node-types');
    const types = (nodeTypes.json?.data || []).map((item: any) => item.nodeType);
    check('node-types no auth', nodeTypes.status === 200 && nodeTypes.json.code === 200);
    check('node-types hides react_agent', !types.includes('react_agent'));
    check('node-types has llm', types.includes('llm'));

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

    const deleted = await request('DELETE', `/api/workflows/${workflowId}`, undefined, token);
    check('delete workflow', deleted.json?.code === 200);
    const hidden = await request('GET', `/api/workflows/${workflowId}`, undefined, token);
    check('deleted workflow hidden', hidden.json?.code === 500);
  } finally {
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
