# 实用数据与工具节点

新增八种内置节点，均不需要模型 Key 或外部服务，可直接通过画布、REST / SDK 使用。动作相关字段会按所选操作显示，切换操作不会丢失已填参数。

## 节点清单

| 节点 | 类型 | 典型用途 | 主要输出 |
| --- | --- | --- | --- |
| JSON 解析 | `json_parse` | 将模型 / HTTP 响应转换成结构化值，去除 JSON 代码块，提取嵌套字段 | `data`、`value`、`text`、`type` |
| 字段映射 | `data_map` | 重命名字段、组装请求对象、汇总多节点结果 | `data`、`value`、`text`、`keys` |
| 列表处理 | `list_process` | 筛选、稳定去重、排序、字段提取、截取、展开一层 | `items`、`count`、`inputCount` |
| 文本处理 | `text_process` | 清除首尾空白、字面替换、拆分 / 拼接、大小写、截断 | `value`、`text`、`items`、`truncated` |
| CSV 转换 | `csv` | 文件文本转对象数组，筛选后导出 CSV | `rows`、`text`、`columns`、`count` |
| 日期时间 | `date_time` | 当前日期、Unix 时间戳、时区转换、时间偏移、差值 | `iso`、`text`、`timestamp`、`differenceSeconds` |
| 数据校验 | `validate` | 检查必填、类型、枚举、范围与长度，阻断坏数据或进入条件分支 | `valid`、`errors`、`errorCount`、`data` |
| 编码与摘要 | `encode` | UTF-8 文本 Base64、URL 百分号编解码，SHA-256 / SHA-512 摘要 | `value`、`text`、`action` |

## 共通输入与引用

- `source` 支持模板、原生 JSON 值或文本。留空时取最后一条已产生输出的**直接入边**的值，不会误取其他并行分支；无直接上游时取运行时输入。多个来源应先用合并节点，或显式填写引用。
- JSON、映射、列表、CSV 导出、校验接受 JSON 文本 / 原生 JSON；文本操作与编码要求字符串（文本拼接要求数组）。
- 直接模板 `{{input.items}}` 保留数组、数字、布尔等类型；字段映射里可使用 `source`，例如 `{"title":"{{source.name}}","count":"{{len(source.items)}}"}`。混合模板出错会使节点失败，不会把错误提示嵌入数据后继续运行。
- 输出带 `value`，因此引用完整输出字段时推荐 `{{outputs["节点ID"].items}}`，而不是 `{{节点ID.items}}`。配置抽屉会自动提供安全引用。
- 映射 / 列表等 JSON 源中若需传入字符串标量，应使用 JSON 字符串形式（例如 `"hello"`）；`json_parse` 能解析 `0`、`false`、`null` 等标量。
- 所有节点沿用重试、失败继续和输出别名机制。同步的本地转换有数据大小限制，但现有异步节点超时不是严格的 CPU 抢占沙箱。

## 常用组合

### 1. 模型 / API 结果筛选与导出

```text
开始 → JSON 解析 → 列表筛选 → 列表排序 → CSV 导出 → 字段映射 → 数据校验 → 结束
```

可运行工作流定义：[examples/data-export.flow.json](examples/data-export.flow.json)。通过 `POST /api/workflows` 的 `flow` 字段或 SDK 的创建接口保存，随后执行即可；当前没有新增“导入文件”页面按钮。

输入示例：

```json
{
  "raw": "[{\"name\":\"张三\",\"score\":92},{\"name\":\"李四\",\"score\":60},{\"name\":\"王五\",\"score\":85}]"
}
```

输出包含 `count: 2`、按评分降序的 `rows` 和 CSV 文本。需要落盘时，可再接文件写入节点，内容引用 `{{outputs.csv.text}}`。

### 2. CSV 联系人清洗

```text
文件读取 → CSV 解析 → 列表去重（field=email）→ 列表提取（field=email）→ 文本拼接
```

CSV 支持 BOM、引号、逗号字段和多行字段，保留单元格为字符串。无表头可配置列名或自动生成 `column_1` 等名称。重复表头、行列不齐和未闭合引号会报错。导出默认防止危险字符串被 Excel 等工具作为公式执行；可能在表头 / 单元格前增加单引号，不修改数值。若需要精确原文往返，可显式关闭保护，但不要直接用电子表格打开不可信导出。

### 3. 调用外部 API 前校验参数

数据校验的 `rules` 示例：

```json
{
  "email": {"required": true, "type": "string", "minLength": 1},
  "age": {"type": "integer", "min": 0, "max": 120},
  "status": {"enum": ["active", "inactive"]}
}
```

`required` 检查字段是否存在；非空字符串需另加 `minLength: 1`。布尔不是数字。规则支持点路径和 JSON Pointer，不是完整 JSON Schema，也不隐式验证邮箱格式。关闭 `stopOnError` 后，可用条件表达式 `outputs.check.valid` 进入不同分支；默认校验失败直接失败。

### 4. 时间与内容编码

- 日期输入默认支持 ISO 8601 或 **秒级** Unix 时间戳，`0` 不会被当作未配置。无时区的日期按所选时区解释。
- `add` 的一天按 24 小时计算，跨夏令时按实际经过的时间偏移；`diff` 是结束时间减开始时间的秒数。不存在的夏令时本地时间会被拒绝；重叠时间建议明确提供 UTC 偏移。
- `base64_decode` 仅支持能解码为 UTF-8 的文本，不用于二进制文件；URL 编码针对单个参数值，不是整条 URL。
- SHA 摘要不是加密、密码存储或 HMAC 签名。需要这些能力时请使用专用安全组件。

## 生效与限制

1. AI 服务更新依赖：`ai-service/.venv/bin/pip install -e './ai-service[dev]'`（仓库根目录执行）。新增 `tzdata` 是官方时区数据兜底，避免容器或 Windows 缺少 IANA 时区库。
2. 重启 AI 与 Java 服务；Java 启动时自动同步新增节点，不需要修改数据库表结构。
3. 刷新浏览器，重新加载节点目录。

单次转换的数据总大小 / 文本最多 1,000,000 个序列化字符，数组 / 对象最多 10,000 项，嵌套最多 32 层；展开、拆分、替换和拼接也检查产物限制。CSV 最多 10,000 行，单字段还受 Python CSV 默认大小限制。列表排序要求同一字段全为数字或全为字符串，空值与缺失值始终排最后。

## 本轮验证

- 新增 **100 项 AI 节点测试**：动作分支、类型保持、路径缺失、模板错误、CSV 特殊字段与公式保护、时区 / 夏令时、坏输入、大小限制、容错与输出别名。
- 用真实 LangGraph 串联全部八种新节点，另对本文提供的导出示例执行回归，确认文档示例可运行。
- 新增 **9 项浏览器测试**：八种节点的面板入口、默认配置、输出声明和保存，以及动作切换后的字段显示 / 参数保留。
- `make check` 通过：AI 196、Java 57、前端 SSE 13、Python SDK 12、TypeScript SDK 14、Java SDK 10，共 **302 项测试**，类型检查和构建通过。
- `make test-ui` 的 **28 项隔离 Chromium 回归通过**；新增 Python 文件与改动目录声明的 Ruff 检查通过。
- 浏览器 API 使用 mock，本轮没有改动本地业务数据，也没有重新进行真实三端联调、模型调用或性能压测。
