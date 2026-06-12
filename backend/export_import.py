import aiosqlite
import json
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from database import DATABASE_PATH

router = APIRouter(prefix="/api", tags=["export-import"])


@router.get("/export")
async def export_all():
    """
    导出所有客户数据和提醒记录为 JSON 文件。
    用于备份迁移。
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        customers = await db.execute_fetchall("SELECT * FROM customers ORDER BY id ASC")
        reminders = await db.execute_fetchall("SELECT * FROM reminders ORDER BY customer_id, cycle_number ASC")

    data = {
        "exported_at": datetime.now().isoformat(),
        "version": "1.0",
        "customers": [dict(r) for r in customers],
        "reminders": [dict(r) for r in reminders],
    }

    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    filename = f"giffgaff_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    return StreamingResponse(
        iter([json_bytes]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import")
async def import_data():
    """
    从导出的 JSON 文件恢复数据。
    导入时会清空现有数据后重新导入。
    """
    # 前端会通过表单上传文件，这里由 caller 直接传 JSON body
    # 如果需要用文件上传，使用 multipart/form-data
    pass


async def import_from_file(filepath: str):
    """供管理命令调用的文件导入函数"""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("version") != "1.0":
        raise ValueError("不支持的备份文件版本")

    async with aiosqlite.connect(DATABASE_PATH) as db:
        # 清空现有数据
        await db.execute("DELETE FROM reminders")
        await db.execute("DELETE FROM customers")
        await db.commit()

        # 恢复客户
        for c in data["customers"]:
            await db.execute(
                """INSERT INTO customers (id, phone_number, email, activation_date, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (c["id"], c["phone_number"], c["email"], c["activation_date"], c["created_at"]),
            )

        # 恢复提醒记录
        for r in data["reminders"]:
            await db.execute(
                """INSERT INTO reminders
                   (id, customer_id, cycle_number, due_date, resend_email_id, sent, sent_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["id"], r["customer_id"], r["cycle_number"], r["due_date"],
                 r.get("resend_email_id"), r["sent"], r.get("sent_at"), r["created_at"]),
            )
        await db.commit()