import { Injectable } from '@nestjs/common';
import { AppDataSource } from '../database/data-source';
import { LLMGlobalConfig } from '../database/entities';
import { canonicalizeProvider, firstText, formatDate, text, toFloat, toInt } from '../common';

@Injectable()
export class LlmConfigService {
  private repo() { return AppDataSource.getRepository(LLMGlobalConfig); }

  map(config: LLMGlobalConfig): any {
    return {
      id: config.id,
      provider: config.provider,
      configName: config.configName,
      apiUrl: config.apiUrl,
      apiKey: config.apiKey,
      model: config.model,
      ttsModel: config.ttsModel,
      embeddingModel: config.embeddingModel,
      imageModel: config.imageModel,
      videoModel: config.videoModel,
      memoryEnabled: config.memoryEnabled ?? 0,
      temperature: config.temperature === null || config.temperature === undefined ? null : Number(config.temperature),
      isDefault: config.isDefault ?? 0,
      createdAt: formatDate(config.createdAt),
      updatedAt: formatDate(config.updatedAt),
    };
  }

  async byId(id: any): Promise<LLMGlobalConfig | null> {
    const value = toInt(id);
    if (value === null) return null;
    return this.repo().findOne({ where: { id: value, deleted: 0 } as any });
  }

  async list(): Promise<LLMGlobalConfig[]> {
    return this.repo().find({ where: { deleted: 0 } as any });
  }

  async listByProvider(provider: string): Promise<LLMGlobalConfig[]> {
    return this.repo().find({
      where: { provider, deleted: 0 } as any,
      order: { isDefault: 'DESC', updatedAt: 'DESC' },
    });
  }

  async defaultConfig(provider: string): Promise<LLMGlobalConfig | null> {
    return this.repo().findOne({ where: { provider, isDefault: 1, deleted: 0 } as any });
  }

  async setDefault(id: number): Promise<void> {
    const config = await this.byId(id);
    if (!config) throw new Error('配置不存在');
    await this.repo().update({ provider: config.provider, deleted: 0 } as any, { isDefault: 0 });
    config.isDefault = 1;
    await this.repo().save(config);
  }

  async save(payload: any): Promise<LLMGlobalConfig> {
    const configId = toInt(payload?.id);
    let config = configId !== null ? await this.byId(configId) : null;
    const isNew = !config;
    if (!config) {
      config = this.repo().create({ deleted: 0, isDefault: 0, memoryEnabled: 0, temperature: 0.7 } as any) as unknown as LLMGlobalConfig;
    }
    const fields: Array<[keyof LLMGlobalConfig, string]> = [
      ['provider', 'provider'],
      ['configName', 'configName'],
      ['apiUrl', 'apiUrl'],
      ['apiKey', 'apiKey'],
      ['model', 'model'],
      ['ttsModel', 'ttsModel'],
      ['embeddingModel', 'embeddingModel'],
      ['imageModel', 'imageModel'],
      ['videoModel', 'videoModel'],
    ];
    for (const [property, key] of fields) {
      if (isNew || key in (payload || {})) (config as any)[property] = text(payload?.[key]);
    }
    config.provider = canonicalizeProvider(config.provider);
    config.memoryEnabled = toInt(payload?.memoryEnabled, 0) === 1 ? 1 : 0;
    if (isNew) config.temperature = toFloat(payload?.temperature, 0.7) ?? 0.7;
    else if (payload?.temperature !== undefined && payload.temperature !== null) config.temperature = toFloat(payload.temperature, 0.7);
    if ('isDefault' in (payload || {})) config.isDefault = toInt(payload.isDefault, 0) === 1 ? 1 : 0;

    for (const [value, message] of [
      [config.provider, '供应商不能为空'],
      [config.configName, '配置别名不能为空'],
      [config.apiUrl, 'API 地址不能为空'],
      [config.apiKey, 'API 密钥不能为空'],
      [config.model, '模型名称不能为空'],
    ] as Array<[any, string]>) {
      if (!value) throw new Error(message);
    }

    const duplicate = await this.repo().findOne({
      where: { provider: config.provider, configName: config.configName, deleted: 0 } as any,
    });
    if (duplicate && duplicate.id !== config.id) throw new Error('同一供应商下的配置别名不能重复');

    if (isNew) {
      const count = await this.repo().count({ where: { provider: config.provider, deleted: 0 } as any });
      if (count === 0) config.isDefault = 1;
      else if (payload?.isDefault === undefined) config.isDefault = 0;
    }

    if (!isNew && config.isDefault === 1) {
      await this.repo().update({ provider: config.provider, deleted: 0 } as any, { isDefault: 0 });
    }
    await this.repo().save(config);
    return config;
  }

  async delete(id: number): Promise<void> {
    const config = await this.byId(id);
    if (!config) return;
    const wasDefault = config.isDefault === 1;
    await this.repo().delete({ id });
    if (wasDefault) {
      const remaining = await this.listByProvider(config.provider);
      if (remaining.length) {
        remaining[0].isDefault = 1;
        await this.repo().save(remaining[0]);
      }
    }
  }
}
