# ai-service

Python + FastAPI + LangGraph 的 AI 执行服务。接收工作流 JSON，编译成 LangGraph 状态图，执行并以 SSE 回传事件。

## 运行

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

没有配置任何 API Key 时，AI_MOCK_MODE=auto 会让模型节点返回 mock 内容，保证整条链路可跑通。

## 测试

```bash
pytest -q
```

## 目录

- app/graph  构图 + 运行器（LangGraph）
- app/nodes  节点执行器，加节点只需新增一个类并注册
- app/llm    OpenAI 兼容模型工厂
- app/skills SKILL.md 三级加载
- app/api    REST + SSE
