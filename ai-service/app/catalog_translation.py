def translation_catalog() -> list[dict]:
    return [{
        "type": "image_translate", "name": "图片翻译", "category": "AI", "icon": "Picture",
        "color": "#56c8d8", "sort": 29,
        "description": "百炼图片翻译：保留排版，输出翻译后的 JPG 图片（不是视觉问答）",
        "configSchema": [
            {"key": "provider", "label": "服务商", "type": "select", "default": "qwen", "options": [
                {"label": "阿里百炼 / 通义", "value": "qwen"}, {"label": "Mock（不翻译原图）", "value": "mock"}]},
            {"key": "model", "label": "模型", "type": "input", "default": "qwen-mt-image-2.0"},
            {"key": "apiHost", "label": "业务空间 API Host", "type": "input", "default": "",
             "placeholder": "<WorkspaceId>.cn-beijing.maas.aliyuncs.com",
             "help": "不含协议或路径；留空使用 AI_DASHSCOPE_API_HOST 或服务商 Base URL 的域名"},
            {"key": "imageUrl", "label": "图片地址 / 文件", "type": "file", "default": "",
             "help": "支持公网 URL、文件中心路径或 {{上游节点.imageUrl}}；留空取上游图片。真实调用会上传所选本地图片到百炼临时存储。"},
            {"key": "sourceLang", "label": "源语种", "type": "input", "default": "auto", "help": "auto 自动识别，或 zh / en / ja 等语种编码"},
            {"key": "targetLang", "label": "目标语种", "type": "input", "default": "en", "help": "如 zh / en / ja，不能填写 auto"},
            {"key": "domainHint", "label": "领域提示（英文）", "type": "textarea", "default": "", "rows": 2},
            {"key": "terminologies", "label": "术语对照（JSON）", "type": "textarea", "default": "[]", "rows": 3,
             "help": '[{"src":"人工智能","tgt":"Artificial Intelligence"}]，最多 50 项'},
            {"key": "imageSegment", "label": "跳过主体上的文字", "type": "switch", "default": False},
            {"key": "asyncMode", "label": "异步提交并等待结果", "type": "switch", "default": False,
             "help": "大图可开启；最多等待 5 分钟。工作流取消不会自动撤销百炼已受理的任务。"},
        ],
    }]
