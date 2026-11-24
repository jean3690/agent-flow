import { Injectable } from '@nestjs/common';
import { ChatOpenAI } from '@langchain/openai';
import { HumanMessage, SystemMessage, AIMessage, BaseMessage } from '@langchain/core/messages';
import { canonicalizeProvider, text } from '../common';

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

/**
 * ChatOpenAI 会把 /chat/completions 追加到 baseURL 后面，因此这里返回的是 baseURL。
 */
function resolveBaseUrl(provider: string, apiUrl: string | null): string {
  const base = provider === 'volcengine_agent_plan'
    ? normalizeAgentPlanBase(apiUrl) + '/api/plan/v3'
    : normalizeChatBase(apiUrl) + '/v1';
  if (!base || base === '/v1' || base === '/api/plan/v3') {
    return provider === 'volcengine_agent_plan' ? 'https://ark.cn-beijing.volces.com/api/plan/v3' : 'https://api.openai.com/v1';
  }
  return base;
}

/** 完整请求地址，仅用于日志/展示。 */
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

const APIFREE_MODEL_ALIASES: Record<string, string> = {
  skyclaw: 'skywork-ai/skyclaw-v1',
  'skyclaw-v1': 'skywork-ai/skyclaw-v1',
  'skyclaw-v1.0': 'skywork-ai/skyclaw-v1',
  'skyclaw-lite': 'skywork-ai/skyclaw-v1-lite',
  'skyclaw-v1-lite': 'skywork-ai/skyclaw-v1-lite',
  'skyclaw-v1.0-lite': 'skywork-ai/skyclaw-v1-lite',
};

function messageText(message: any): string {
  const content = message?.content;
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content.map((item: any) => (typeof item === 'string' ? item : item?.text || '')).join('');
  }
  return '';
}

@Injectable()
export class LlmService {
  private createClient(
    provider: string,
    apiUrl: string,
    apiKey: string,
    model: string,
    temperature: number,
  ): ChatOpenAI {
    return new ChatOpenAI({
      model,
      apiKey: apiKey || 'EMPTY',
      temperature,
      maxRetries: 1,
      timeout: 180000,
      streamUsage: false,
      configuration: { baseURL: resolveBaseUrl(provider, apiUrl) },
    });
  }

  private toMessages(messages: Array<{ role: string; content: string }>): BaseMessage[] {
    return messages.map((message) => {
      const content = message.content ?? '';
      if (message.role === 'system') return new SystemMessage(content);
      if (message.role === 'assistant') return new AIMessage(content);
      return new HumanMessage(content);
    });
  }

  async chat(
    provider: string,
    apiUrl: string,
    apiKey: string,
    model: string,
    temperature: number,
    messages: Array<{ role: string; content: string }>,
    onChunk?: (chunk: string, accumulated: string) => void,
  ): Promise<ChatResult> {
    const normalizedProvider = canonicalizeProvider(provider) || provider;
    let normalizedModel = model.trim();
    if (normalizedProvider === 'apifree') {
      normalizedModel = APIFREE_MODEL_ALIASES[normalizedModel.toLowerCase()] || normalizedModel;
    }

    const client = this.createClient(normalizedProvider, apiUrl, apiKey, normalizedModel, temperature);
    const lcMessages = this.toMessages(messages);

    if (onChunk) {
      let accumulated = '';
      const stream = await client.stream(lcMessages);
      for await (const chunk of stream) {
        const delta = chunk.text;
        if (!delta) continue;
        accumulated += delta;
        onChunk(delta, accumulated);
      }
      return { content: accumulated, inputTokens: 0, outputTokens: 0, totalTokens: 0 };
    }

    const response = await client.invoke(lcMessages);
    const usage: any = response.usage_metadata;
    const inputTokens = Number(usage?.input_tokens ?? 0) || 0;
    const outputTokens = Number(usage?.output_tokens ?? 0) || 0;
    const totalTokens = Number(usage?.total_tokens ?? inputTokens + outputTokens) || 0;
    return { content: messageText(response), inputTokens, outputTokens, totalTokens };
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