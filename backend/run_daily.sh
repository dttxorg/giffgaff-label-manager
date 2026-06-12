#!/bin/bash
# 每日定时任务：
#   - 09:00 检查并发送到期的 giffgaff 提醒邮件
#   - 10:00 备份数据库到阿里云盘（如果配置了 rclone）
#
# crontab 示例：
# 0 9 * * * /path/to/run_daily.sh send >> /path/to/cron.log 2>&1
# 0 10 * * * /path/to/run_daily.sh backup >> /path/to/cron.log 2>&1
#
# 或一次性运行全部：./run_daily.sh all

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-all}"

echo "[$(date)] === run_daily.sh started (mode=$MODE) ==="

if [ "$MODE" = "send" ] || [ "$MODE" = "all" ]; then
    echo "[$(date)] [1/2] 检查到期邮件..."
    source venv/bin/activate
    python3 scheduler.py
    echo "[$(date)] [1/2] 完成"
fi

if [ "$MODE" = "backup" ] || [ "$MODE" = "all" ]; then
    echo "[$(date)] [2/2] 备份数据库到阿里云盘..."
    if command -v rclone &> /dev/null; then
        bash "$SCRIPT_DIR/backup.sh"
    else
        echo "[WARN] rclone 未安装，跳过备份"
    fi
    echo "[$(date)] [2/2] 完成"
fi

echo "[$(date)] === run_daily.sh done ==="