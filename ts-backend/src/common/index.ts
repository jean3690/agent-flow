export function ok(data: any = null): any {
  return { code: 200, message: '操作成功', data };
}

export function err(message: string, code = 500): any {
  return { code, message, data: null };
}

export function jdump(value: any): string {
  return JSON.stringify(stripRuntime(value));
}

export function asJsonString(value: any): string | null {
  if (value === null || value === undefined) return null;
  return typeof value === 'string' ? value : JSON.stringify(value);
}

export function jload(value: any, fallback: any = null): any {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'object') return value;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

export function stripRuntime(value: any, seen = new Set<any>()): any {
  if (value === null || ['string', 'number', 'boolean'].includes(typeof value)) return value;
  if (seen.has(value)) return '[Circular]';
  seen.add(value);
  if (Array.isArray(value)) {
    const result = value.map((item) => stripRuntime(item, seen));
    seen.delete(value);
    return result;
  }
  if (typeof value === 'object') {
    const result: Record<string, any> = {};
    for (const [key, item] of Object.entries(value)) {
      if (key === '__nodeOutputs__') continue;
      result[key] = stripRuntime(item, seen);
    }
    seen.delete(value);
    return result;
  }
  return value;
}

export function text(value: any): string | null {
  if (value === null || value === undefined) return null;
  const result = String(value).trim();
  return result || null;
}

export function firstText(...values: any[]): string | null {
  for (const value of values) {
    const candidate = text(value);
    if (candidate) return candidate;
  }
  return null;
}

export function toInt(value: any, fallback: number | null = null): number | null {
  if (value === null || value === undefined || value === '') return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback;
}

export function toFloat(value: any, fallback: number | null = null): number | null {
  if (value === null || value === undefined || value === '') return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function truthy(value: any): boolean {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  if (typeof value === 'string') return ['true', '1', 'yes', 'on'].includes(value.trim().toLowerCase());
  return false;
}

export function formatDate(value: any): string | null {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date).replace('T', ' ');
}

export function nowDate(): Date {
  return new Date();
}

export function nowMs(): number {
  return Date.now();
}

export function cosine(left: number[] | null | undefined, right: number[] | null | undefined): number {
  if (!left?.length || !right?.length) return 0;
  const size = Math.min(left.length, right.length);
  let dot = 0;
  let leftNorm = 0;
  let rightNorm = 0;
  for (let i = 0; i < size; i++) {
    dot += left[i] * right[i];
    leftNorm += left[i] * left[i];
    rightNorm += right[i] * right[i];
  }
  if (!leftNorm || !rightNorm) return 0;
  return dot / (Math.sqrt(leftNorm) * Math.sqrt(rightNorm));
}

export function canonicalizeProvider(provider: any): string | null {
  const value = text(provider);
  if (!value) return null;
  const aliases: Record<string, string> = {
    'open ai': 'openai',
    'deep seek': 'deepseek',
    '通义千问': 'qwen',
    dashscope: 'qwen',
    aliyun: 'qwen',
    stepfun: 'step',
    阶跃星辰: 'step',
    'ai ping': 'ai_ping',
    智谱: 'zhipu',
    agnes: 'agnes',
    'agnes ai': 'agnes',
    'api free': 'apifree',
    'apifree.ai': 'apifree',
    skyclaw: 'apifree',
    'skyclaw-v1': 'apifree',
    'skyclaw-v1.0': 'apifree',
    'skyclaw-v1-lite': 'apifree',
    'skyclaw-v1.0-lite': 'apifree',
    'skywork-ai/skyclaw-v1': 'apifree',
    'skywork-ai/skyclaw-v1-lite': 'apifree',
    volcengine: 'volcengine_agent_plan',
    ark: 'volcengine_agent_plan',
    agent_plan: 'volcengine_agent_plan',
    'agent plan': 'volcengine_agent_plan',
    火山方舟: 'volcengine_agent_plan',
  };
  const key = value.toLowerCase();
  return aliases[key] || key;
}
