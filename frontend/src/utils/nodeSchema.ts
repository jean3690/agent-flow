import type {
  ConfigField,
  NodeDefinition,
  NodeOutputFieldConfig,
  OutputFieldDef
} from '../types'

export interface ResolvedOutputField extends OutputFieldDef {
  alias?: string
  hidden: boolean
  refKey: string
}

/** configSchema 里的 outputSchema 是声明式元数据，不渲染成表单项，也不写进节点 config。 */
export function isMetaField(field: ConfigField): boolean {
  return field.type === 'outputSchema'
}

export function visibleSchema(
  definition: NodeDefinition | null | undefined,
  config?: Record<string, any>
): ConfigField[] {
  return (definition?.configSchema || []).filter((field) => {
    if (isMetaField(field)) return false
    if (!config || !field.visibleWhen) return true
    return Object.entries(field.visibleWhen).every(([key, allowed]) => {
      const value = config[key] ?? definition?.configSchema.find((item) => item.key === key)?.default
      return allowed.includes(value)
    })
  })
}

export function outputMetaOf(definition: NodeDefinition | null | undefined): ConfigField | undefined {
  return definition?.configSchema?.find((field) => field.type === 'outputSchema')
}

export function hasValueKeyOf(definition: NodeDefinition | null | undefined): boolean {
  return !!outputMetaOf(definition)?.hasValueKey
}

/** 声明的输出字段 + 用户配置的别名，过滤掉 hidden 后供引用面板展示。 */
export function outputFieldsOf(
  definition: NodeDefinition | null | undefined,
  config?: Record<string, any>
): ResolvedOutputField[] {
  const declared = outputMetaOf(definition)?.fields || []
  const overrides = (config?.outputFields || []) as NodeOutputFieldConfig[]
  const byKey = new Map(overrides.map((item) => [item.key, item]))
  const fields: ResolvedOutputField[] = []

  for (const field of declared) {
    const config = byKey.get(field.key)
    const hidden = !!config?.hidden
    fields.push({
      key: field.key,
      label: field.label,
      type: field.type,
      alias: config?.alias || '',
      hidden,
      refKey: field.key
    })
    if (config?.alias) {
      fields.push({
        key: config.alias,
        label: `${config.alias}（别名）`,
        type: field.type,
        alias: config.alias,
        hidden,
        refKey: config.alias
      })
    }
  }
  return fields.filter((field) => !field.hidden)
}

const SAFE_IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/

/**
 * 生成模板引用。节点 id 带连字符时 {{nodeId.field}} 会被 ast 解析成减法，
 * 且输出含 value 键时短引用取不到字段，因此默认一律用下标形式。
 */
export function buildRef(nodeId: string, fieldKey: string, hasValueKey: boolean): {
  safe: string
  short?: string
} {
  return {
    safe: `{{outputs["${nodeId}"].${fieldKey}}}`,
    short: SAFE_IDENTIFIER.test(nodeId) && !hasValueKey
      ? `{{${nodeId}.${fieldKey}}}`
      : undefined
  }
}
