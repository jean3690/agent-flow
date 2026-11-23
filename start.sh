#!/usr/bin/env bash
# AgentFlow 本地一键启动：AI(Python) + 平台服务(Python) + 前端
# 用法:
#   ./start.sh               启动三端，Ctrl+C 全部停止
#   ./start.sh ai|platform|web  只启动某一端
#   ./start.sh status        查看端口与健康状态
#   ./start.sh stop          停止由本脚本启动的进程

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/logs"
PID_DIR="$LOG_DIR/pids"
AI_PORT=8000
PLATFORM_PORT=8084
WEB_PORT=5173

mkdir -p "$PID_DIR"

color() { printf '\033[%sm%s\033[0m\n' "$1" "$2"; }
info()  { color "36" "==> $*"; }
ok()    { color "32" "✓ $*"; }
warn()  { color "33" "! $*"; }
fail()  { color "31" "✗ $*"; }

port_open() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

wait_http() { # name url timeout_seconds
  local name=$1 url=$2 timeout=${3:-120} waited=0
  while [ "$waited" -lt "$timeout" ]; do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
    if [ $((waited % 10)) -eq 0 ]; then
      info "等待 $name 就绪… ${waited}s"
    fi
  done
  return 1
}

kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child"
  done
  kill -TERM "$pid" 2>/dev/null
}

start_service() { # name dir command port url [timeout]
  local name=$1 dir=$2 cmd=$3 port=$4 url=$5 timeout=${6:-90}
  local pid_file="$PID_DIR/$name.pid"

  if port_open "$port"; then
    fail "$name 端口 $port 已被占用，先执行 ./start.sh stop 或释放端口"
    return 1
  fi

  info "启动 $name（端口 $port），日志: logs/$name.log"
  ( cd "$dir" && exec bash -c "$cmd" ) > "$LOG_DIR/$name.log" 2>&1 &
  local pid=$!
  echo "$pid" > "$pid_file"

  if ! wait_http "$name" "$url" "$timeout"; then
    fail "$name 启动失败，最后 20 行日志："
    tail -n 20 "$LOG_DIR/$name.log" | sed 's/^/    /'
    kill_tree "$pid"
    rm -f "$pid_file"
    return 1
  fi
  ok "$name 就绪 (pid $pid)"
}

stop_service() { # name
  local name=$1
  local pid_file="$PID_DIR/$name.pid"
  local pid
  [ -f "$pid_file" ] || return 0
  pid=$(cat "$pid_file")
  if kill -0 "$pid" 2>/dev/null; then
    kill_tree "$pid"
    ok "已停止 $name (pid $pid)"
  fi
  rm -f "$pid_file"
}

stop_all() {
  info "停止服务…"
  stop_service web
  stop_service platform
  stop_service ai
}

show_status() {
  for entry in "ai:$AI_PORT:http://127.0.0.1:$AI_PORT/health" \
               "platform:$PLATFORM_PORT:http://127.0.0.1:$PLATFORM_PORT/api/system/health" \
               "web:$WEB_PORT:http://127.0.0.1:$WEB_PORT/"; do
    local name=${entry%%:*} rest=${entry#*:}
    local port=${rest%%:*} url=${rest#*:}
    if port_open "$port" && curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      ok "$name 运行中  :$port"
    elif port_open "$port"; then
      warn "$name 端口占用但健康检查未通过  :$port"
    else
      warn "$name 未运行  :$port"
    fi
  done
  echo "日志目录: $LOG_DIR"
}

require_ai() {
  if [ ! -x "$ROOT/ai-service/.venv/bin/uvicorn" ]; then
    fail "缺少 ai-service/.venv，先执行: make install"
    exit 1
  fi
}

require_platform() {
  if [ ! -x "$ROOT/platform-service/.venv/bin/uvicorn" ]; then
    fail "缺少 platform-service/.venv，先执行: make install"
    exit 1
  fi
}

require_web() {
  if [ ! -d "$ROOT/frontend/node_modules" ]; then
    fail "缺少 frontend/node_modules，先执行: cd frontend && npm install"
    exit 1
  fi
  command -v npm >/dev/null 2>&1 || { fail "未找到 npm"; exit 1; }
}

start_ai() {
  require_ai
  start_service ai "$ROOT/ai-service" ".venv/bin/uvicorn app.main:app --port $AI_PORT" \
    "$AI_PORT" "http://127.0.0.1:$AI_PORT/health"
}

start_platform() {
  require_platform
  start_service platform "$ROOT/platform-service" ".venv/bin/uvicorn app.main:app --port $PLATFORM_PORT" \
    "$PLATFORM_PORT" "http://127.0.0.1:$PLATFORM_PORT/api/system/health"
}

start_web() {
  require_web
  start_service web "$ROOT/frontend" "npm run dev -- --port $WEB_PORT" \
    "$WEB_PORT" "http://127.0.0.1:$WEB_PORT/"
}

on_interrupt() {
  echo
  stop_all
  exit 130
}

case "${1:-all}" in
  all)
    trap on_interrupt INT TERM
    info "启动 AgentFlow 三端（Ctrl+C 停止全部）"
    start_ai || { stop_all; exit 1; }
    start_platform || { stop_all; exit 1; }
    start_web || { stop_all; exit 1; }
    echo
    ok "全部就绪 → http://localhost:$WEB_PORT  (admin / admin123)"
    echo "  AI       http://127.0.0.1:$AI_PORT/health"
    echo "  平台服务 http://127.0.0.1:$PLATFORM_PORT/api/system/health"
    echo "  日志     $LOG_DIR"
    echo
    info "按 Ctrl+C 停止全部服务"
    wait
    ;;
  ai)
    trap on_interrupt INT TERM
    start_ai || exit 1
    wait
    ;;
  platform)
    trap on_interrupt INT TERM
    start_platform || exit 1
    wait
    ;;
  web)
    trap on_interrupt INT TERM
    start_web || exit 1
    wait
    ;;
  stop)
    stop_all
    ;;
  status)
    show_status
    ;;
  *)
    echo "用法: $0 [all|ai|platform|web|stop|status]"
    exit 1
    ;;
esac
