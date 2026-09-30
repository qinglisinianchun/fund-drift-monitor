#!/usr/bin/env bash
# 基金漂移监控 —— Linux/云电脑 每周例行报告入口
# 用法：bash weekly.sh
# 定时：每周日上午 9 点（无论是否漂移都推送上周/本交易周情况）
# 说明：先刷新数据（含补跑兜底），再强制推送周报，最后刷新看板。

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

LOG_DIR="$HERE/日志"
mkdir -p "$LOG_DIR"

# ---------- 选 Python ----------
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "[$(date '+%F %T')] ❌ 未找到 python3，请先安装：apt install -y python3" | tee -a "$LOG_DIR/cron.log"
    exit 127
fi

STAMP="$(date '+%F %T')"
{
    echo ""
    echo "================================================================"
    echo "[$STAMP] 开始每周周报（$PY）"
} >> "$LOG_DIR/cron.log"

# 刷新数据（周末通常无新净值，此步主要为补跑兜底）→ 强制推周报 → 刷新看板
"$PY" monitor.py        >> "$LOG_DIR/cron.log" 2>&1
"$PY" notify.py weekly  >> "$LOG_DIR/cron.log" 2>&1
"$PY" "生成看板.py"      >> "$LOG_DIR/cron.log" 2>&1

echo "[$(date '+%F %T')] 周报流程完成" >> "$LOG_DIR/cron.log"
exit 0
