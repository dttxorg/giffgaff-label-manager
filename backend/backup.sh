#!/bin/bash
# 备份脚本：导出客户、标签模板和安全设置到本地/飞牛 NAS 目录。
#
# 使用方法：
#   BACKUP_DIR="/vol1/1000/backups/giffgaff-label-manager" ./backup.sh
#
# 加入 crontab 示例：
#   0 10 * * * BACKUP_DIR="/vol1/1000/backups/giffgaff-label-manager" /path/to/backend/backup.sh >> /path/to/backup.log 2>&1

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$SCRIPT_DIR/backups}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/giffgaff_backup_$TIMESTAMP.json"

mkdir -p "$BACKUP_DIR"

echo "[$(date)] 开始备份..."
echo "[$(date)] 备份目录: $BACKUP_DIR"

cd "$SCRIPT_DIR"
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
fi

CUSTOMER_COUNT=$(python3 - "$BACKUP_FILE" <<'PY'
import asyncio
import json
import sys

from database import init_db
from main import _export_backup_payload


async def export():
    await init_db()
    data = await _export_backup_payload()
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(len(data["customers"]))


asyncio.run(export())
PY
)

echo "[$(date)] 导出完成，共 $CUSTOMER_COUNT 条客户记录"

find "$BACKUP_DIR" -type f -name 'giffgaff_backup_*.json' -mtime +"$BACKUP_KEEP_DAYS" -print | while IFS= read -r old; do
    rm -f "$old"
    echo "[$(date)] 删除过期备份: $old"
done

echo "[$(date)] 备份完成: $BACKUP_FILE"
