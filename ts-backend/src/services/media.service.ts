import { Injectable } from '@nestjs/common';
import axios from 'axios';
import { AppDataSource } from '../database/data-source';
import { LLMGlobalConfig } from '../database/entities';
import { AgentPlanService, PlanConfig } from './agent-plan.service';
import { config } from '../config';
import { canonicalizeProvider, firstText, text, toFloat, toInt } from '../common';

function normalizeStepUrl(apiUrl: string | null): string {
  let value = text(apiUrl) || 'https://api.stepfun.com/v1';
  value = value.replace(/\/+$/, '');
  if (value.endsWith('/audio/speech')) return value;
  if (value.endsWith('/v1') || value.endsWith('/step_plan/v1')) return `${value}/audio/speech`;
  return `${value}/v1/audio/speech`;
}

function normalizeDashScopeUrl(apiUrl: string | null): string {
  let value = text(apiUrl) || '';
  value = value.replace(/\/+$/, '');
  value = value.replace('/services/aigc/multimodal-generation/generation', '');
  value = value.replace('/compatible-mode/v1', '/api/v1').replace('/compatible-mode', '/api/v1');
  if (!value.endsWith('/api/v1')) value += '/api/v1';
  return value + '/services/aigc/multimodal-generation/generation';
}

function splitText(value: string, maxLength: number, maxBytes: number): string[] {
  const chunks: string[] = [];
  let start = 0;
  while (start < value.length) {
    let end = Math.min(start + maxLength, value.length);
    while (end > start) {
      const candidate = value.slice(start, end);
      if (Buffer.byteLength(candidate, 'utf8') <= maxBytes) {
        if (end < value.length) {
          for (let i = end - 1; i > start; i--) {
            if ('。！？；,.!?;'.includes(value[i])) { end = i + 1; break; }
          }
        }
        chunks.push(value.slice(start, end));
        start = end;
        break;
      }
      end -= 10;
    }
    if (end <= start) {
      end = start + 1;
      while (end <= value.length) {
        if (Buffer.byteLength(value.slice(start, end), 'utf8') > maxBytes) {
          if (end - 1 > start) {
            chunks.push(value.slice(start, end - 1));
            start = end - 1;
          } else throw new Error('单个字符超过 600 字节,无法处理');
          break;
        }
        end++;
      }
    }
  }
  return chunks;
}

function mergeWav(chunks: Buffer[]): Buffer {
  if (!chunks.length) throw new Error('音频片段列表为空');
  if (chunks.length === 1) return chunks[0];
  if (chunks[0].length < 44) throw new Error('无效的 WAV 文件格式');
  const merged = Buffer.concat([chunks[0].subarray(0, 44), ...chunks.slice(1).map((chunk) => chunk.subarray(44))]);
  merged.writeUInt32LE(merged.length - 8, 4);
  merged.writeUInt32LE(merged.length - 44, 40);
  return merged;
}

interface TtsConfig {
  provider: string;
  apiUrl: string | null;
  apiKey: string | null;
  model: string | null;
  voice: string;
  languageType: string;
  instruction: string | null;
  speed: number;
  volume: number;
  sampleRate: number;
}

@Injectable()
export class MediaService {
  constructor(private readonly plan: AgentPlanService) {}

  private repo() { return AppDataSource.getRepository(LLMGlobalConfig); }

  private resolveTtsConfig(data: Record<string, any>): TtsConfig {
    const globalId = toInt(data.configId);
    let provider: string | null = null;
    let apiUrl: string | null = null;
    let apiKey: string | null = null;
    let model: string | null = null;
    let explicitTtsModel = false;
    const global = globalId !== null ? // synchronous lookup not possible; caller awaits
      null : null;

    return {
      provider: provider || '',
      apiUrl,
      apiKey,
      model,
      voice: '',
      languageType: 'Auto',
      instruction: null,
      speed: 1,
      volume: 1,
      sampleRate: 24000,
    };
  }

  async tts(data: Record<string, any>, input: Record<string, any>, progress?: (message: string, data: any) => void): Promise<any> {
    let textValue = firstText(data.text, input.output, input.input, input.text);
    const inputParams = Array.isArray(data.inputParams) ? data.inputParams : [];
    for (const param of inputParams) {
      if (param?.name !== 'text') continue;
      if (param.type === 'input') { textValue = firstText(param.value); break; }
      if (param.type === 'reference') {
        const key = String(param.referenceNode || '').split('.').pop();
        textValue = firstText(input[key || ''], key === 'user_input' ? input.input : null);
        break;
      }
    }
    if (!textValue) throw new Error('输入文本不能为空');

    let provider: string | null = null;
    let apiUrl: string | null = null;
    let apiKey: string | null = null;
    let model: string | null = null;
    let explicit = false;
    const configId = toInt(data.configId);
    if (configId !== null) {
      const global = await this.repo().findOne({ where: { id: configId, deleted: 0 } as any });
      if (global) {
        provider = canonicalizeProvider(global.provider);
        apiUrl = text(global.apiUrl);
        apiKey = text(global.apiKey);
        model = text(global.ttsModel);
        explicit = Boolean(model);
        if (!explicit) model = text(global.model);
      }
    }
    apiKey = apiKey || text(data.apiKey);
    apiUrl = apiUrl || text(data.apiUrl);
    model = model || text(data.model);
    provider = provider || canonicalizeProvider(data.provider);
    if (!provider) provider = /step/i.test(model || '') ? 'step' : 'qwen';
    if (!explicit) {
      if (provider === 'step' && !(model || '').includes('tts')) model = 'stepaudio-2.5-tts';
      if (provider === 'qwen' && !(model || '').includes('tts')) model = 'qwen3-tts-flash';
    }
    if (!apiKey) throw new Error('TTS API Key 不能为空，请选择全局配置或在节点配置中设置');
    if (!model) throw new Error('TTS 模型名称不能为空');
    if (provider !== 'qwen' && provider !== 'step') throw new Error(`TTS 暂不支持的供应商: ${provider}`);

    const voice = text(data.voice) || (provider === 'step' ? 'cixingnansheng' : 'Cherry');
    const languageType = text(data.languageType) || 'Auto';
    const instruction = text(data.instruction);
    const speed = toFloat(data.speed, 1) ?? 1;
    const volume = toFloat(data.volume, 1) ?? 1;
    const sampleRate = toInt(data.sampleRate, 24000) ?? 24000;
    const maxLength = provider === 'step' ? 1000 : 400;
    const maxBytes = provider === 'step' ? Number.MAX_SAFE_INTEGER : 600;
    const chunks = splitText(textValue, maxLength, maxBytes);
    if (progress) progress(`文本已分割为 ${chunks.length} 个片段`, { totalChunks: chunks.length, currentChunk: 0 });

    const audios: Buffer[] = [];
    for (let i = 0; i < chunks.length; i++) {
      if (progress) progress(`正在处理第 ${i + 1}/${chunks.length} 个片段`, { totalChunks: chunks.length, currentChunk: i + 1 });
      let audio: Buffer;
      if (provider === 'step') {
        const response = await axios.post(normalizeStepUrl(apiUrl), {
          model, input: chunks[i], voice, response_format: 'wav', speed, volume, sample_rate: sampleRate,
          ...(instruction ? { instruction } : {}),
        }, { headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json', Accept: 'audio/wav,application/json' }, responseType: 'arraybuffer', timeout: 180000 });
        audio = Buffer.from(response.data);
      } else {
        const response = await axios.post(normalizeDashScopeUrl(apiUrl), {
          model, input: { text: chunks[i], voice, language_type: languageType },
        }, { headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' }, timeout: 180000 });
        const url = response.data?.output?.audio?.url;
        if (!url) throw new Error('阿里百炼 TTS 返回的音频URL为空');
        const download = await axios.get<ArrayBuffer>(url, { responseType: 'arraybuffer', timeout: 60000 });
        audio = Buffer.from(download.data);
      }
      audios.push(audio);
      if (progress) progress(`已完成第 ${i + 1}/${chunks.length} 个片段`, { totalChunks: chunks.length, currentChunk: i + 1, completedChunks: i + 1 });
    }
    if (progress) progress(`正在合并 ${audios.length} 个音频片段...`, null);
    const fileName = `audio_${require('crypto').randomUUID()}.wav`;
    const url = await this.plan.uploadBytes(mergeWav(audios), `audio/${fileName}`, 'audio/wav');
    return { audioUrl: url, fileName, output: url, chunks: chunks.length };
  }

  async generateImage(config: PlanConfig, prompt: string, reference: string | null, size: string | null): Promise<{ imageUrls: string[]; metadata: any }> {
    if (config.provider === 'volcengine_agent_plan') return this.plan.generateImage(config, prompt, reference, size);
    let endpoint = text(config.apiUrl) || 'https://api.openai.com/v1';
    endpoint = endpoint.replace(/\/+$/, '');
    if (endpoint.endsWith('/images/generations')) {
      // already the full endpoint
    } else {
      if (endpoint.includes('/v1')) endpoint = endpoint.slice(0, endpoint.toLowerCase().indexOf('/v1'));
      endpoint = `${endpoint}/v1/images/generations`;
    }
    const body: any = { model: config.model, prompt, response_format: 'url', n: 1 };
    if (size) body.size = size;
    if (reference) body.image = reference;
    const response = await axios.post(endpoint, body, {
      headers: { Authorization: `Bearer ${config.apiKey}`, 'Content-Type': 'application/json' }, timeout: 180000,
      transformResponse: [(data) => data],
    });
    const payload = typeof response.data === 'string' ? JSON.parse(response.data) : response.data;
    const urls = (payload?.data || []).map((item: any) => item?.url || (item?.b64_json ? `data:image/png;base64,${item.b64_json}` : null)).filter(Boolean);
    return { imageUrls: urls, metadata: payload };
  }

  async persistImage(url: string, objectName: string): Promise<string> {
    if (!url) return url;
    try {
      if (url.startsWith('data:image/')) {
        const comma = url.indexOf(',');
        if (comma > 0) return this.plan.uploadBytes(Buffer.from(url.slice(comma + 1), 'base64'), objectName, 'image/png');
      }
      return this.plan.uploadUrl(url, objectName, 'image/png');
    } catch {
      return url;
    }
  }

  async persistVideo(url: string, objectName: string): Promise<string> {
    try { return this.plan.uploadUrl(url, objectName, 'video/mp4'); } catch { return url; }
  }
}
