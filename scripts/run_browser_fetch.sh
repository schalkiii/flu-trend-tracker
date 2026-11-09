#!/bin/bash
# 浏览器采集入口: 保证 daemon 存活(会话托管) + 扩展连接, 然后跑现役快速采集器
# 用法: bash run_browser_fetch.sh [--days N]   (days 默认 365, 必须 ≤365)
#       bash run_browser_fetch.sh 北京,上海 --days 30   (城市过滤)
# 原则: 绝不重启/强杀 Edge —— 扩展断连时先等自动重连(30s 周期), 再用新标签页温和唤醒
# 备用慢路线(UI 交互, ~40s/词, 仅 5 城): python scripts/fetch_baidu_via_browser.py
WB="$HOME/.kimi-webbridge/bin/kimi-webbridge.exe"
EDGE="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
"$WB" start >/dev/null 2>&1 || true
sleep 1

wait_connected() {
  local deadline=$((SECONDS + $1))
  while [ $SECONDS -lt $deadline ]; do
    if "$WB" status 2>/dev/null | grep -q '"extension_connected":true'; then
      return 0
    fi
    sleep 3
  done
  return 1
}

# 1. 等扩展自动重连(扩展每 30s reconcile 一次)
if wait_connected 75; then
  echo "(扩展已连接)"
else
  # 2. 温和唤醒: 开新标签页触发 tabs 事件唤醒 service worker(Edge 已运行时不杀进程)
  edge_running=$(tasklist 2>/dev/null | grep -cE "^msedge\.exe")
  echo "(扩展未连接, Edge 进程数=${edge_running}; 开新标签页温和唤醒...)"
  "$EDGE" "https://index.baidu.com/v2/index.html#/" >/dev/null 2>&1 &
  if ! wait_connected 60; then
    echo "(警告: 扩展仍未连接, 继续尝试采集)"
  fi
fi

python "C:/Users/qi.shao/WorkBuddy/2026-11-05-16-40-57/flu-trend-tracker/scripts/fetch_baidu_fast.py" "$@"
