.PHONY: help ai java web install install-sdk test test-ai test-java test-web test-sdk typecheck check build compose e2e e2e-service e2e-ui test-ui coverage bench

PYTHON ?= $(CURDIR)/ai-service/.venv/bin/python

help:
	@echo "make install  安装三端依赖"
	@echo "make ai       AI 服务 (8000)"
	@echo "make java     Java 服务 (8084)"
	@echo "make web      前端 (5173)"
	@echo "make install-sdk 安装 SDK 开发依赖"
	@echo "make test     跑 AI + Java + 前端单元 + 三种 SDK 测试"
	@echo "make test-ui  前端隔离回归（mock API，不需后端）"
	@echo "make test-sdk 仅跑三种 SDK 测试"
	@echo "make coverage 生成 AI / Java 覆盖率报告"
	@echo "make bench    对运行中的整栈做并发压测（同步执行入口）"
	@echo "make check    完整测试、类型检查与构建"
	@echo "make build    构建前端与 Java 包"
	@echo "make e2e      对运行中的整栈跑后端冒烟（需先 ./start.sh 或 compose up）"
	@echo "make e2e-service 验证 API Key、同步执行与 OpenAPI"
	@echo "make e2e-ui   对运行中的整栈跑前端 UI 冒烟（Playwright，需先 ./start.sh 或 compose up）"
	@echo "make compose  docker compose up --build"

install:
	cd ai-service && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd frontend && npm install
	cd java-service && mvn -q -DskipTests compile

ai:
	cd ai-service && .venv/bin/uvicorn app.main:app --reload --port 8000

java:
	cd java-service && mvn spring-boot:run

web:
	cd frontend && npm run dev

install-sdk:
	$(PYTHON) -m pip install -e './sdk/python[dev]'
	cd sdk/typescript && npm ci

test: test-ai test-java test-web test-sdk

test-ai:
	cd ai-service && $(PYTHON) -m pytest -q

test-java:
	cd java-service && mvn -q test

test-web:
	cd frontend && npm test

test-ui:
	cd frontend && npm run test:ui

test-sdk:
	cd sdk/python && $(PYTHON) -m pytest -q
	cd sdk/typescript && npm test
	cd sdk/java && mvn -q test

typecheck:
	cd frontend && npm run typecheck
	cd sdk/typescript && npm run typecheck

check: test typecheck build

build:
	cd frontend && npm run build
	cd java-service && mvn -q -DskipTests package
	cd sdk/typescript && npm run build

compose:
	docker compose up --build

e2e:
	python3 e2e/smoke.py

e2e-service:
	python3 e2e/verify_service.py

coverage:
	cd ai-service && $(PYTHON) -m pytest -q --cov=app --cov-report=term --cov-report=html:../coverage/ai
	cd java-service && mvn -q test
	@echo "AI 覆盖率报告: coverage/ai/index.html"
	@echo "Java 覆盖率报告: java-service/target/site/jacoco/index.html"

bench:
	python3 e2e/bench.py --concurrency 20 --requests 400

e2e-ui:
	cd frontend && npm install && npm run test:e2e