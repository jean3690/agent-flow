# 百炼图片翻译与实时语音翻译

这两项能力走百炼原生接口，不复用 OpenAI `/images/generations`、视觉问答或 `/audio/speech`。

## 配置

先在「模型配置 → 通义千问（qwen）」保存百炼 API Key。若使用本地环境文件，`ai-service/.env` 中使用：

```dotenv
AI_DASHSCOPE_API_KEY=<新的百炼 Key>
AI_DASHSCOPE_API_HOST=<WorkspaceId>.cn-beijing.maas.aliyuncs.com
```

API Host 从百炼对应地域的业务空间设置复制，不含协议与路径。北京和新加坡分别是：

- `<WorkspaceId>.cn-beijing.maas.aliyuncs.com`
- `<WorkspaceId>.ap-southeast-1.maas.aliyuncs.com`

Key、业务空间和域名必须对应同一地域。实时页面和图片节点也可以单独填写 Host，覆盖环境设置；如果 qwen 的 Base URL 已是业务空间域名，可从中推导 Host。旧 `dashscope.aliyuncs.com` 地址可用于图片接口，但不能代替 3.8 实时模型要求的业务空间域名。

Docker Compose 使用根目录环境变量 `DASHSCOPE_API_KEY` / `DASHSCOPE_API_HOST`。不要将真实 Key 提交到 Git、写入浏览器代码或放进聊天记录。

## 图片翻译工作流

添加「图片翻译」节点，模型保持 `qwen-mt-image-2.0`：

```
开始 → 图片翻译 → 结束
```

- 图片可来自公网 URL、文件中心路径、`/files/...` 或上游节点 `imageUrl`。
- 本地文件会先上传到百炼临时 OSS，使用模型绑定的 `oss://` URL，并自动附带 `X-DashScope-OssResourceResolve: enable`。临时文件由百炼在 48 小时后清理；生产环境建议使用自己的稳定对象存储 URL。
- 本地图片验证格式、100 MB 大小、15–8192 像素宽高及 1:10–10:1 宽高比。当前文件中心上传上限仍为项目默认的 50 MB。
- 源语种可选 `auto`，目标语种填写 `en` / `zh` / `ja` 等百炼支持的语种编码。
- 支持英文领域提示、术语 JSON `[{"src":"人工智能","tgt":"Artificial Intelligence"}]`，以及跳过商品/人物主体上的文字。
- 默认同步调用；开启异步后只提交一次任务，每秒查询结果，最多等待 5 分钟。节点重试可能新建云任务，不宜对收费操作盲目开启重试。取消本地执行不会自动取消已受理的百炼异步任务。
- 工作流整体超时仍默认 120 秒。如需要完整等待较长的异步任务，调用执行接口时将 `options.timeoutMs` 设为大于 300000，并检查 Java 的 `AI_SERVICE_TIMEOUT_MS` 与反向代理超时；仅开启异步开关不会自动放宽整体执行限制。
- 成功后下载并验证 JPG，保存到媒体目录，下游引用 `{{translate.imageUrl}}`。输出包含 `originalImageUrl`、语种、百炼 `requestId`、`usage` 和提示信息。
- `No text detected for translation` 仍是百炼成功且收费的结果，提示信息会保留。
- Mock 输出明确标记为占位图，不宣称已翻译原图。

## 实时语音翻译

工作流列表点击「实时翻译」，或打开 `/#/live-translation`。这是独立的麦克风会话，不是会在 DAG 中一直占用执行器的无限时长节点。

1. 配置同地域业务空间 Host，选择目标语种与是否播放译音。
2. 点击「开始翻译」，允许麦克风。需要 HTTPS 或 localhost，以及支持 AudioWorklet 的现代浏览器。
3. 输入自动转换成 **16 kHz 单声道 PCM16 小端**，每 200 ms 发送一帧。页面展示分段原文与译文，译音按 **24 kHz PCM16** 顺序播放。
4. 点击「结束并收尾」停止录音并发送 `session.finish`；继续接收剩余字幕和音频，收到 `session.finished` 后才关闭连接。已排队的译音仍会播放完。
5. 「取消」、离开页面、网络积压或错误会停止麦克风并关闭会话。源语种由 3.8 模型自动识别；当前不提供声音克隆或视频输入。

建议戴耳机。单次最多 10 分钟；异常网络或闲置 60 秒会中断会话。会话和字幕不落数据库，刷新后不会恢复。Mock 必须显式选择，不会在缺少 Key 时悄悄假装翻译语音。

### 鉴权与协议

```
浏览器 --JWT/API Key REST--> Java --内部令牌+百炼凭据--> Python
浏览器 --一次性 ticket WS--> Java --内部令牌 WS--> Python --百炼 WS--> 云模型
```

- `POST /api/translations/realtime/sessions`：已登录用户创建会话。请求包含 `provider`、`targetLang`、`apiHost`、`outputAudio`、可选 `voice`（默认 Tina）；用户归属由 Java 注入，浏览器不能注入百炼凭据。
- 返回 `ticket`（60 秒有效、一次性消费）、采样率及 mock 标记，不返回厂商 Key。
- 连接 `/api/translations/realtime/ws`，首帧发送 `{"type":"connect","ticket":"..."}`。ticket 不在 URL 或访问日志中。
- 输入帧：`{"type":"audio","audio":"<base64 PCM16>"}`，每帧不超过 500 ms；收尾：`{"type":"finish"}`。
- 返回：`session.ready`、`transcript.delta/done`、`translation.delta/done`、`audio.delta`、`usage`、`session.finished`、`error`。每段字幕用 `itemId` 区分；`usage` 为累计值，以最后一次为准，不累加各轮用量。
- Python 仅在收到 `session.created` 后配置 3.8 的 `output_modalities`、`audio.input.turn_detection` 和 `translation.language`；收到 `session.updated` 后才允许采集输入。没有套用 Omni 的 `response.create`，也没有混用 3.5 的字段。
- Python 限制待连接 tickets、总并发和单用户并发；错误信息会遮蔽 Key。Vite 和 Nginx 均支持 WebSocket 转发，Java 检查配置的允许来源。
- 生产部署必须更换默认 `AI_INTERNAL_TOKEN`，并将 Python 服务限制在内部网络；只对外暴露 Java 与前端入口。

### 部署边界

当前会话与 ticket 存放在 Python 单实例内存中。多副本需对建会话请求和 WebSocket 连接做粘性路由；实例重启会使 ticket 和活跃会话失效。Java 横向扩容同样应保持 WebSocket 连接稳定。尚不提供跨实例会话恢复、持久化字幕或自动重连（避免重复送音频和重复收费）。

## 验证

```bash
make check
make test-ui
# 已启动整栈后：
make e2e-translations
```

自动化测试用 HTTP/WS 上游模拟覆盖请求结构、上传、同步/异步下载、鉴权、一次性票据、PCM 采集、错误收尾、字幕增量与累计用量。整栈冒烟显式使用 mock，不会调用收费模型。

真实验收需要未泄露的新 Key、正确业务空间 Host、模型权限，以及实际含文字的图片/有语音的音频。不能把模拟通过等同于云端真实翻译效果已验证。

## 百炼官方协议

- [图片翻译](https://help.aliyun.com/zh/model-studio/qwen-mt-image-api)
- [临时文件上传](https://help.aliyun.com/zh/model-studio/get-temporary-file-url)
- [LiveTranslate WebSocket 接入](https://help.aliyun.com/zh/model-studio/livetranslate-realtime-websocket-access)
- [客户端事件](https://help.aliyun.com/zh/model-studio/live-translator-client-events)
- [服务端事件](https://help.aliyun.com/zh/model-studio/live-translator-server-events)
