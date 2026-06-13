#!/bin/bash
# 备份脚本：导出客户数据并上传到阿里云盘
# 依赖：rclone（https://rclone.org/install/）
#
# 使用方法：
#   1. 先配置 rclone（只需一次）：
#      rclone config
#      # 选择 aliyundrive, 填入 refresh_token
#      # remote 名称记下来（比如 aliyundrive）
#
#   2. 修改下面的 REMOTE 和 BACKUP_DIR 变量
#
#   3. 加入 crontab：
#      0 10 * * * /path/to/backup.sh >> /path/to/backup.log 2>&1

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$SCRIPT_DIR/backups"

# ---------- 配置 ----------
REMOTE="aliyundrive"              # rclone remote 名称
REMOTE_PATH="giffgaff-label-manager"   # 阿里云盘目标文件夹
# -------------------------

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/backup_$TIMESTAMP.json"

mkdir -p "$BACKUP_DIR"

echo "[$(date)] 开始备份..."

# --- 步骤1：导出数据库为 JSON ---
cd "$SCRIPT_DIR"
source venv/bin/activate
CUSTOMER_COUNT=$(python3 -c "
import asyncio, sys, json, os
sys.path.insert(0, '.')
from database import DATABASE_PATH, init_db
import aiosqlite, datetime

async def export():
    await init_db()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        customers = await db.execute_fetchall('SELECT * FROM customers ORDER BY id ASC')
    data = {
        'exported_at': datetime.datetime.now().isoformat(),
        'version': '1.0',
        'customers': [dict(r) for r in customers],
    }
    with open('$BACKUP_FILE', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(len(data['customers']))

asyncio.run(export())
")

echo "[$(date)] 导出完成，共 $CUSTOMER_COUNT 条客户记录"

# --- 步骤2：检查 rclone 是否配置 ---
if ! command -v rclone &> /dev/null; then
    echo "[ERROR] rclone 未安装，请运行: curl https://rclone.org/install.sh | sudo bash"
    exit 1
fi

# --- 步骤3：上传到阿里云盘 ---
# 创建带时间戳的文件夹
REMOTE_TARGET="$REMOTE:/$REMOTE_PATH/$(date +%Y%m%d)"

echo "[$(date)] 上传到阿里云盘: $REMOTE_TARGET"
rclone copy "$BACKUP_FILE" "$REMOTE_TARGET/" \
    --transfers 1 \
    --quiet

# --- 步骤4：保留最近 30 天备份，删除旧文件 ---
# 阿里云盘不需要手动清理，保留 30 天足够
CUTOFF=$(date -d "30 days ago" +%Y%m%d 2>/dev/null || date -v-30d +%Y%m%d)
for old in $(ls "$BACKUP_DIR"/backup_*.json 2>/dev/null); do
    fname=$(basename "$old" | sed 's/backup_\([0-9]*\).*/\1/')
    if [ "$fname" \< "$CUTOFF" ]; then
        rm -f "$old"
        echo "[$(date)] 删除过期备份: $old"
    fi
done

echo "[$(date)] 备份完成: $BACKUP_FILE"
echo "[$(date)] 已同步至: $REMOTE_TARGET/"
