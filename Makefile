.PHONY: help ai platform web install install-sdk test test-ai test-platform test-web test-ui test-sdk typecheck check build compose e2e e2e-service e2e-translations e2e-ui coverage bench

PYTHON ?= $(CURDIR)/ai-service/.venv/bin/python
PLATFORM_PYTHON ?= $(CURDIR)/platform-service/.venv/bin/python

help:
	@echo "make install      安装 AI / 平台 / 前端依赖"
	@echo "make ai           AI 服务 (8000)"
	@echo "make platform     平台服务 (8084)"
	@echo "make web          前端 (5173)"
	@echo "make install-sdk  安装 SDK 开发依赖"
	@echo "make test         跑 AI + 平台 + 前端单元 + 两种 SDK 测试"
	@echo "make test-ui      前端隔离回归（mock API，不需后端）"
	@echo "make test-sdk     仅跑两种 SDK 测试"
	@echo "make coverage     生成 AI / 平台覆盖率报告"
	@echo "make bench        对运行中的整栈做并发压测（同步执行入口）"
	@echo "make check        完整测试、类型检查与构建"
	@echo "make build        构建前端与 TypeScript SDK"
	@echo "make e2e          对运行中的整栈跑后端冒烟（需先 ./start.sh 或 compose up）"
	@echo "make e2e-service  验证 API Key、同步执行与 OpenAPI"
	@echo "make e2e-ui       对运行中的整栈跑前端 UI 冒烟（Playwright）"
	@echo "make compose      docker compose up --build"

install:
	cd ai-service && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd platform-service && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd frontend && npm install

ai:
	cd ai-service && .venv/bin/uvicorn app.main:app --reload --port 8000

platform:
	cd platform-service && .venv/bin/uvicorn app.main:app --reload --port 8084

web:
	cd frontend && npm run dev

install-sdk:
	$(PYTHON) -m pip install -e './sdk/python[dev]'
	cd sdk/typescript && npm ci

test: test-ai test-platform test-web test-sdk

test-ai:
	cd ai-service && $(PYTHON) -m pytest -q

test-platform:
	cd platform-service && $(PLATFORM_PYTHON) -m pytest -q

test-web:
	cd frontend && npm test

test-ui:
	cd frontend && npm run test:ui

test-sdk:
	cd sdk/python && $(PYTHON) -m pytest -q
	cd sdk/typescript && npm test

typecheck:
	cd frontend && npm run typecheck
	cd sdk/typescript && npm run typecheck

check: test typecheck build

build:
	cd frontend && npm run build
	cd sdk/typescript && npm run build

compose:
	docker compose up --build

e2e:
	python3 e2e/smoke.py

e2e-service:
	python3 e2e/verify_service.py

e2e-translations:
	$(PYTHON) e2e/verify_translations.py

coverage:
	cd ai-service && $(PYTHON) -m pytest -q --cov=app --cov-report=term --cov-report=html:../coverage/ai
	cd platform-service && $(PLATFORM_PYTHON) -m pytest -q --cov=app --cov-report=term --cov-report=html:../coverage/platform
	@echo "AI 覆盖率报告: coverage/ai/index.html"
	@echo "平台覆盖率报告: coverage/platform/index.html"

bench:
	python3 e2e/bench.py --concurrency 20 --requests 400

e2e-ui:
	cd frontend && npm install && npm run test:e2e
