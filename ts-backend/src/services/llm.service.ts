import { Injectable } from '@nestjs/common';
import axios from 'axios';
import { canonicalizeProvider, firstText, text } from '../common';

const PLACEHOLDER_RE = /\{\{(.*?)\}\}/g;

function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, '');
}

function stripSuffixIgnoreCase(value: string, suffix: string): string {
  return value.toLowerCase().endsWith(suffix.toLowerCase()) ? value.slice(0, -suffix.length) : value;
}

export function normalizeChatBase(apiUrl: string | null): string {
  let value = stripTrailingSlash((apiUrl || '').trim());
  value = stripSuffixIgnoreCase(value, '/v1/chat/completions');
  value = stripSuffixIgnoreCase(value, '/v1');
  return stripTrailingSlash(value);
}

export function normalizeAgentPlanBase(apiUrl: string | null): string {
  let value = stripTrailingSlash((apiUrl || '').trim());
  value = stripSuffixIgnoreCase(value, '/api/plan/v3/chat/completions');
  value = stripSuffixIgnoreCase(value, '/api/plan/v3');
  return stripTrailingSlash(value);
}

export function chatEndpoint(provider: string, apiUrl: string | null): string {
  if (provider === 'volcengine_agent_plan') {
    return normalizeAgentPlanBase(apiUrl) + '/api/plan/v3/chat/completions';
  }
  return normalizeChatBase(apiUrl) + '/v1/chat/completions';
}

export interface ChatResult {
  content: string;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

@Injectable()
export class LlmService {
  async chat(
    provider: string,
    apiUrl: string,
    apiKey: string,
    model: string,
    temperature: number,
    messages: Array<{ role: string; content: string }>,
    onChunk?: (chunk: string, accumulated: string) => void,
  ): Promise<ChatResult> {
    let normalizedProvider = canonicalizeProvider(provider) || provider;
    let normalizedModel = model.trim();
    if (normalizedProvider === 'apifree') {
      const aliases: Record<string, string> = {
        skyclaw: 'skywork-ai/skyclaw-v1',
        'skyclaw-v1': 'skywork-ai/skyclaw-v1',
        'skyclaw-v1.0': 'skywork-ai/skyclaw-v1',
        'skyclaw-lite': 'skywork-ai/skyclaw-v1-lite',
        'skyclaw-v1-lite': 'skywork-ai/skyclaw-v1-lite',
        'skyclaw-v1.0-lite': 'skywork-ai/skyclaw-v1-lite',
      };
      normalizedModel = aliases[normalizedModel.toLowerCase()] || normalizedModel;
    }
    const endpoint = chatEndpoint(normalizedProvider, apiUrl);
    const headers = { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' };

    if (onChunk) {
      let accumulated = '';
      const response = await axios.post(
        endpoint,
        { model: normalizedModel, messages, temperature, stream: true },
        { headers, responseType: 'stream', timeout: 180000 },
      );
      await new Promise<void>((resolve, reject) => {
        let buffer = '';
        response.data.on('data', (chunk: Buffer) => {
          buffer += chunk.toString('utf8');
          let index: number;
          while ((index = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0, index).trim();
            buffer = buffer.slice(index + 1);
            if (!line.startsWith('data:')) continue;
            const payload = line.slice(5).trim();
            if (payload === '[DONE]') continue;
            try {
              const json = JSON.parse(payload);
              const delta = json.choices?.[0]?.delta?.content;
              if (delta) {
                accumulated += delta;
                onChunk(delta, accumulated);
              }
            } catch {
              // ignore malformed chunk
            }
          }
        });
        response.data.on('end', resolve);
        response.data.on('error', reject);
      });
      return { content: accumulated, inputTokens: 0, outputTokens: 0, totalTokens: 0 };
    }

    const response = await axios.post(
      endpoint,
      { model: normalizedModel, messages, temperature, stream: false },
      { headers, timeout: 180000, transformResponse: [(data) => data] },
    );
    let payload: any;
    try {
      payload = typeof response.data === 'string' ? JSON.parse(response.data) : response.data;
    } catch {
      throw new Error(`LLM 返回内容无法解析: ${String(response.data).slice(0, 300)}`);
    }
    const rawContent = payload?.choices?.[0]?.message?.content;
    let content = '';
    if (typeof rawContent === 'string') content = rawContent;
    else if (Array.isArray(rawContent)) content = rawContent.map((item) => item?.text || '').join('');
    const usage = payload?.usage || {};
    const inputTokens = Number(usage.prompt_tokens ?? usage.input_tokens ?? 0) || 0;
    const outputTokens = Number(usage.completion_tokens ?? usage.output_tokens ?? 0) || 0;
    const totalTokens = Number(usage.total_tokens ?? inputTokens + outputTokens) || 0;
    return { content, inputTokens, outputTokens, totalTokens };
  }

  processTemplate(template: string | null | undefined, inputParams: any[], input: Record<string, any>): string {
    if (template === null || template === undefined) return '';
    const values: Record<string, string> = {};
    for (const param of inputParams || []) {
      const name = text(param?.name);
      if (!name) continue;
      if (param.type === 'input') {
        if (param.value !== null && param.value !== undefined) values[name] = String(param.value);
      } else if (param.type === 'reference') {
        const reference = text(param.referenceNode);
        if (!reference || !reference.includes('.')) continue;
        const key = reference.split('.').pop() as string;
        let value = input[key];
        if (value === undefined && key === 'user_input') value = input.input;
        if (value !== undefined) values[name] = String(value);
      }
    }
    return template.replace(PLACEHOLDER_RE, (_match, rawName: string) => values[rawName.trim()] ?? '');
  }
}
