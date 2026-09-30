#!/usr/bin/env bash
# 基金漂移监控 —— Linux/云电脑 一键运行入口
# 用法：bash run.sh
# 定时任务：见 crontab.txt

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

LOG_DIR="$HERE/日志"
mkdir -p "$LOG_DIR"

# ---------- 选 Python ----------
# 优先 python3，找不到再试 python
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
    echo "[$STAMP] 开始巡检（$PY）"
} >> "$LOG_DIR/cron.log"

# 三步流程；不因推送失败中断
"$PY" monitor.py  >> "$LOG_DIR/cron.log" 2>&1
"$PY" notify.py   >> "$LOG_DIR/cron.log" 2>&1
"$PY" "生成看板.py" >> "$LOG_DIR/cron.log" 2>&1

echo "[$(date '+%F %T')] 完成" >> "$LOG_DIR/cron.log"
exit 0
