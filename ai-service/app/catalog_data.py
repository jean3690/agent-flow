"""Editor schemas for the deterministic data/utility node family."""


def _options(items: list[tuple[str, str]]) -> list[dict]:
    return [{"label": label, "value": value} for label, value in items]


def _source(**extra) -> dict:
    return {
        "key": "source", "label": "数据源", "type": "textarea", "rows": 3, "default": "",
        "help": '留空取直接上游的值；可写 {{input.items}} 或 {{outputs["节点ID"].text}}', **extra,
    }


def data_catalog() -> list[dict]:
    return [
        {
            "type": "mcp_tool", "name": "MCP 工具", "category": "工具", "icon": "Connection",
            "color": "#0891b2", "description": "调用已配置并授权的远程 MCP 工具", "sort": 88,
            "configSchema": [
                {"key": "serverId", "label": "MCP 服务", "type": "mcpServer", "default": ""},
                {"key": "toolName", "label": "工具", "type": "mcpTool", "default": ""},
                {"key": "arguments", "label": "参数（JSON）", "type": "textarea", "rows": 6, "default": "{}", "help": '例如 {"query":"{{input.topic}}"}，模板保留数字 / 数组类型'},
            ],
        },
        {
            "type": "json_parse", "name": "JSON 解析", "category": "数据", "icon": "DocumentChecked",
            "color": "#0891b2", "description": "解析 JSON / 模型代码块，按路径提取结构化数据", "sort": 80,
            "configSchema": [
                _source(),
                {"key": "path", "label": "提取路径", "type": "input", "default": "", "help": "留空返回全部；支持 items.0.name 或 /items/0/name（JSON Pointer）"},
                {"key": "stripCodeFence", "label": "去掉 Markdown 代码块", "type": "switch", "default": True},
            ],
        },
        {
            "type": "data_map", "name": "字段映射", "category": "数据", "icon": "SetUp",
            "color": "#0891b2", "description": "重命名 / 组装字段，保留数字、布尔和数组类型", "sort": 81,
            "configSchema": [
                _source(),
                {"key": "mapping", "label": "映射对象（JSON）", "type": "textarea", "rows": 6, "default": "{}", "help": '例如 {"title":"{{source.name}}", "count":"{{len(source.items)}}"}；也可引用 input / outputs'},
                {"key": "mergeSource", "label": "保留原对象字段", "type": "switch", "default": False},
                {"key": "dropNull", "label": "删除值为 null 的顶层字段", "type": "switch", "default": False},
            ],
        },
        {
            "type": "list_process", "name": "列表处理", "category": "数据", "icon": "List",
            "color": "#0891b2", "description": "数组筛选、排序、去重、字段提取、截取和展开", "sort": 82,
            "configSchema": [
                _source(),
                {"key": "action", "label": "操作", "type": "select", "default": "unique", "options": _options([("稳定去重", "unique"), ("筛选", "filter"), ("提取字段", "pluck"), ("排序", "sort"), ("截取", "slice"), ("展开一层", "flatten")])},
                {"key": "field", "label": "字段路径", "type": "input", "default": "", "help": "留空处理元素本身；例如 user.name", "visibleWhen": {"action": ["unique", "filter", "pluck", "sort"]}},
                {"key": "operator", "label": "筛选条件", "type": "select", "default": "eq", "options": _options([("等于", "eq"), ("不等于", "ne"), ("大于", "gt"), ("大于等于", "gte"), ("小于", "lt"), ("小于等于", "lte"), ("包含", "contains"), ("字段存在", "exists")]), "visibleWhen": {"action": ["filter"]}},
                {"key": "compareValue", "label": "比较值", "type": "textarea", "rows": 2, "default": "", "help": '支持模板或 JSON 值；数字填 80，字符串填 "active"', "visibleWhen": {"action": ["filter"]}},
                {"key": "missingPolicy", "label": "字段缺失时", "type": "select", "default": "null", "options": _options([("输出 null", "null"), ("跳过", "skip"), ("报错", "fail")]), "visibleWhen": {"action": ["pluck"]}},
                {"key": "descending", "label": "降序排列", "type": "switch", "default": False, "help": "空值和缺失字段始终排在最后", "visibleWhen": {"action": ["sort"]}},
                {"key": "start", "label": "起始下标（包含）", "type": "number", "min": -10000, "max": 10000, "default": 0, "visibleWhen": {"action": ["slice"]}},
                {"key": "end", "label": "结束下标（不包含）", "type": "number", "min": -10000, "max": 10000, "default": 10000, "visibleWhen": {"action": ["slice"]}},
            ],
        },
        {
            "type": "text_process", "name": "文本处理", "category": "文本", "icon": "EditPen",
            "color": "#0284c7", "description": "清理空白、字面替换、拆分拼接、大小写和截断", "sort": 83,
            "configSchema": [
                _source(),
                {"key": "action", "label": "操作", "type": "select", "default": "trim", "options": _options([("去除首尾空白", "trim"), ("字面替换", "replace"), ("拆分为数组", "split"), ("数组拼接", "join"), ("转小写", "lower"), ("转大写", "upper"), ("截断", "truncate")])},
                {"key": "search", "label": "查找文本", "type": "input", "default": "", "help": "仅字面匹配，不执行正则表达式", "visibleWhen": {"action": ["replace"]}},
                {"key": "replacement", "label": "替换为", "type": "textarea", "rows": 2, "default": "", "visibleWhen": {"action": ["replace"]}},
                {"key": "replaceCount", "label": "最多替换次数", "type": "number", "min": -1, "max": 10000, "default": -1, "help": "-1 替换全部，0 不替换", "visibleWhen": {"action": ["replace"]}},
                {"key": "separator", "label": "分隔符", "type": "textarea", "rows": 2, "default": "\n", "visibleWhen": {"action": ["split", "join"]}},
                {"key": "removeEmpty", "label": "拆分后移除空白项", "type": "switch", "default": False, "visibleWhen": {"action": ["split"]}},
                {"key": "maxLength", "label": "最多保留字符", "type": "number", "min": 0, "max": 1000000, "default": 1000, "visibleWhen": {"action": ["truncate"]}},
            ],
        },
        {
            "type": "csv", "name": "CSV 转换", "category": "数据", "icon": "Grid",
            "color": "#0891b2", "description": "CSV 文本与对象数组互转，可直接接文件读写节点", "sort": 84,
            "configSchema": [
                _source(),
                {"key": "action", "label": "操作", "type": "select", "default": "parse", "options": _options([("CSV → 对象数组", "parse"), ("对象数组 → CSV", "generate")])},
                {"key": "delimiter", "label": "分隔符", "type": "input", "default": ",", "help": "一个字符；默认逗号，也可填写分号或制表符"},
                {"key": "hasHeader", "label": "包含表头", "type": "switch", "default": True},
                {"key": "columns", "label": "列名 / 导出顺序", "type": "tags", "default": [], "help": "留空自动取表头或对象字段；无表头时自动生成 column_1 等列名"},
                {"key": "protectFormulas", "label": "防止表格公式注入", "type": "switch", "default": True, "help": "导出时在危险字符串前加单引号，不修改数值", "visibleWhen": {"action": ["generate"]}},
            ],
        },
        {
            "type": "date_time", "name": "日期时间", "category": "工具", "icon": "Calendar",
            "color": "#64748b", "description": "当前时间、格式化、时区转换、时间偏移与秒级差值", "sort": 85,
            "configSchema": [
                {"key": "action", "label": "操作", "type": "select", "default": "now", "options": _options([("当前时间", "now"), ("格式化 / 转时区", "format"), ("时间偏移", "add"), ("计算时间差", "diff")])},
                _source(visibleWhen={"action": ["format", "add", "diff"]}),
                {"key": "timezone", "label": "时区", "type": "input", "default": "Asia/Shanghai", "help": "IANA 时区，例如 Asia/Shanghai、UTC、America/New_York"},
                {"key": "inputFormat", "label": "输入格式", "type": "input", "default": "", "help": "留空支持 ISO 8601 或 Unix 秒级时间戳；自定义如 %Y/%m/%d", "visibleWhen": {"action": ["format", "add", "diff"]}},
                {"key": "outputFormat", "label": "输出文本格式", "type": "input", "default": "%Y-%m-%d %H:%M:%S", "visibleWhen": {"action": ["now", "format", "add"]}},
                {"key": "offset", "label": "偏移量", "type": "number", "min": -315360000, "max": 315360000, "default": 1, "help": "负数向过去偏移；最多十年，一天按 24 小时计算", "visibleWhen": {"action": ["add"]}},
                {"key": "unit", "label": "偏移单位", "type": "select", "default": "days", "options": _options([("秒", "seconds"), ("分钟", "minutes"), ("小时", "hours"), ("天（24 小时）", "days")]), "visibleWhen": {"action": ["add"]}},
                {"key": "end", "label": "结束时间", "type": "textarea", "rows": 2, "default": "{{input.end}}", "help": "差值为结束时间减数据源时间，单位秒", "visibleWhen": {"action": ["diff"]}},
            ],
        },
        {
            "type": "validate", "name": "数据校验", "category": "数据", "icon": "CircleCheck",
            "color": "#16a34a", "description": "检查必填、类型、枚举、数值与长度，失败终止或接条件分支", "sort": 86,
            "configSchema": [
                _source(),
                {"key": "rules", "label": "字段规则（JSON）", "type": "textarea", "rows": 6, "default": "{}", "help": '例如 {"email":{"required":true,"type":"string","minLength":1},"age":{"type":"integer","min":0}}；不是完整 JSON Schema'},
                {"key": "stopOnError", "label": "校验失败终止节点", "type": "switch", "default": True, "help": "关闭后查看 valid / errors，并可连接条件分支"},
            ],
        },
        {
            "type": "encode", "name": "编码与摘要", "category": "工具", "icon": "Key",
            "color": "#64748b", "description": "Base64 / URL 编解码与 SHA-256 / SHA-512 内容摘要", "sort": 87,
            "configSchema": [
                _source(),
                {"key": "action", "label": "操作", "type": "select", "default": "sha256", "options": _options([("SHA-256 摘要", "sha256"), ("SHA-512 摘要", "sha512"), ("Base64 编码", "base64_encode"), ("Base64 解码（UTF-8 文本）", "base64_decode"), ("URL 百分号编码", "url_encode"), ("URL 百分号解码", "url_decode")])},
            ],
        },
    ]
