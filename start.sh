#!/usr/bin/env bash
# AgentFlow 本地一键启动：前端 Vite + 任意一套后端（ts / python / java）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/logs"
BACKEND="${1:-ts}"
START_FRONTEND=1
API_PORT="${SERVER_PORT:-8084}"
WEB_PORT="${WEB_PORT:-5173}"

for arg in "$@"; do
  case "$arg" in
    -h|--help) usage_flag=1 ;;
    --no-frontend) START_FRONTEND=0 ;;
  esac
done

usage() {
  cat <<'EOF'
用法: ./start.sh [backend] [--no-frontend]

  backend        ts（默认，NestJS） | python（FastAPI） | java（Spring Boot） | none（只启前端）
  --no-frontend  只启动后端

示例:
  ./start.sh                # 前端 + TS 后端
  ./start.sh java           # 前端 + Java 后端
  ./start.sh python --no-frontend
EOF
}

if [[ "${usage_flag:-0}" == "1" ]]; then usage; exit 0; fi

case "$BACKEND" in
  ts|python|java|none) ;;
  *) echo "未知后端: $BACKEND"; usage; exit 1 ;;
esac

mkdir -p "$LOG_DIR"

# 1. 环境变量：三套后端都读 backend/.env
if [[ ! -f "$ROOT/backend/.env" ]]; then
  cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
  echo "[env] 已从 .env.example 生成 backend/.env，请填写 MYSQL_PASSWORD 与 JWT_SECRET"
fi
if ! grep -qE '^MYSQL_PASSWORD=.+' "$ROOT/backend/.env"; then
  echo "[warn] backend/.env 中 MYSQL_PASSWORD 为空（改用 sqljs/SQLite 模式可忽略）"
fi

PIDS=()
CLEANED=0
cleanup() {
  [[ "$CLEANED" == "1" ]] && return
  CLEANED=1
  echo ""
  echo "[stop] 正在停止服务..."
  for pid in "${PIDS[@]:-}"; do
    [[ -n "${pid:-}" ]] || continue
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "[stop] 已退出"
}
trap cleanup INT TERM EXIT

# 2. 前端
if [[ "$START_FRONTEND" == "1" ]]; then
  if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
    echo "[frontend] 安装依赖..."
    ( cd "$ROOT/frontend" && npm install )
  fi
  echo "[frontend] 启动 Vite -> http://localhost:$WEB_PORT"
  ( cd "$ROOT/frontend" && exec npm run dev -- --port "$WEB_PORT" --strictPort ) \
    >"$LOG_DIR/frontend.log" 2>&1 &
  PIDS+=($!)
fi

# 3. 后端
case "$BACKEND" in
  ts)
    if [[ ! -f "$ROOT/ts-backend/dist/src/main.js" ]]; then
      echo "[backend] 编译 TypeScript..."
      ( cd "$ROOT/ts-backend" && npm run build )
    fi
    echo "[backend] 启动 NestJS -> http://localhost:$API_PORT"
    ( cd "$ROOT/ts-backend" && exec npm start ) >"$LOG_DIR/backend.log" 2>&1 &
    PIDS+=($!)
    ;;
  python)
    if [[ -x "$ROOT/python-backend/.venv/bin/python" ]]; then
      PY="$ROOT/python-backend/.venv/bin/python"
    else
      PY="python3"
    fi
    echo "[backend] 启动 FastAPI -> http://localhost:$API_PORT"
    ( cd "$ROOT/python-backend" && exec "$PY" run.py ) >"$LOG_DIR/backend.log" 2>&1 &
    PIDS+=($!)
    ;;
  java)
    echo "[backend] 启动 Spring Boot -> http://localhost:$API_PORT"
    ( cd "$ROOT/backend" && exec mvn -q spring-boot:run ) >"$LOG_DIR/backend.log" 2>&1 &
    PIDS+=($!)
    ;;
  none)
    echo "[backend] 跳过（仅前端）"
    ;;
esac

echo ""
echo "日志: $LOG_DIR/frontend.log $LOG_DIR/backend.log"
echo "跟踪日志: tail -f $LOG_DIR/*.log"
echo "按 Ctrl+C 停止全部服务"
echo ""

wait
