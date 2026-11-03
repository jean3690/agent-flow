.PHONY: help ai java web install test build compose e2e e2e-ui

help:
	@echo "make install  安装三端依赖"
	@echo "make ai       AI 服务 (8000)"
	@echo "make java     Java 服务 (8084)"
	@echo "make web      前端 (5173)"
	@echo "make test     跑 Python + Java 测试"
	@echo "make build    构建前端与 Java 包"
	@echo "make e2e      对运行中的整栈跑后端冒烟（需先 ./start.sh 或 compose up）"
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

test:
	cd ai-service && .venv/bin/python -m pytest -q
	cd java-service && mvn -q test

build:
	cd frontend && npm run build
	cd java-service && mvn -q -DskipTests package

compose:
	docker compose up --build

e2e:
	python3 e2e/smoke.py

e2e-ui:
	cd frontend && npm install && npm run test:e2e
