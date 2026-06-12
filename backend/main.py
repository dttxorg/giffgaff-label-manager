from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from datetime import datetime
import os
import json
import tempfile

from database import init_db
from models import (
    CustomerCreate, CustomerUpdate, CustomerOut,
    CustomerDetail, ReminderOut
)
from crud import (
    get_all_customers, get_customer, create_customer,
    update_customer, delete_customer, get_reminders,
    get_pending_reminders
)
from scheduler import create_reminders_for_customer
from export_import import router as export_router

app = FastAPI(title="giffgaff-reminder API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(export_router)


@app.post("/api/import", status_code=200)
async def import_backup(file: UploadFile = File(...)):
    """上传备份 JSON 文件恢复数据"""
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="只支持 .json 文件")

    contents = await file.read()
    try:
        data = json.loads(contents)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="文件格式错误，不是有效的 JSON")

    if data.get("version") != "1.0":
        raise HTTPException(status_code=400, detail="不支持的备份文件版本")

    import aiosqlite
    from database import DATABASE_PATH

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM reminders")
        await db.execute("DELETE FROM customers")
        await db.commit()

        for c in data.get("customers", []):
            await db.execute(
                """INSERT INTO customers (id, phone_number, email, activation_date, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (c["id"], c["phone_number"], c["email"], c["activation_date"], c["created_at"]),
            )

        for r in data.get("reminders", []):
            await db.execute(
                """INSERT INTO reminders
                   (id, customer_id, cycle_number, due_date, resend_email_id, sent, sent_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["id"], r["customer_id"], r["cycle_number"], r["due_date"],
                 r.get("resend_email_id"), r["sent"], r.get("sent_at"), r["created_at"]),
            )
        await db.commit()

    return {
        "ok": True,
        "customers_restored": len(data.get("customers", [])),
        "reminders_restored": len(data.get("reminders", [])),
    }

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


@app.on_event("startup")
async def startup():
    await init_db()


# ---------- 客户管理 ----------

@app.get("/api/customers", response_model=list[CustomerOut])
async def list_customers():
    rows = await get_all_customers()
    return [
        CustomerOut(
            id=r["id"],
            phone_number=r["phone_number"],
            email=r["email"],
            activation_date=r["activation_date"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


@app.get("/api/customers/{customer_id}", response_model=CustomerDetail)
async def get_customer_detail(customer_id: int):
    c = await get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    reminders = await get_reminders(customer_id)
    return CustomerDetail(
        id=c["id"],
        phone_number=c["phone_number"],
        email=c["email"],
        activation_date=c["activation_date"],
        created_at=c["created_at"],
        reminders=[
            ReminderOut(
                id=r["id"],
                customer_id=r["customer_id"],
                cycle_number=r["cycle_number"],
                due_date=r["due_date"],
                resend_email_id=r["resend_email_id"],
                sent=bool(r["sent"]),
                sent_at=r["sent_at"],
            )
            for r in reminders
        ],
    )


@app.post("/api/customers", status_code=201)
async def add_customer(data: CustomerCreate):
    from database import DATABASE_PATH
    import aiosqlite

    # 检查手机号是否已存在
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        existing = await db.execute_fetchone(
            "SELECT id FROM customers WHERE phone_number = ?",
            (data.phone_number,),
        )
        if existing:
            raise HTTPException(status_code=409, detail="该手机号已录入")

    customer_id = await create_customer(data)

    # 在数据库中创建所有 43 个提醒记录（不立即发送）
    await create_reminders_for_customer(
        customer_id, data.phone_number, data.email, data.activation_date
    )

    return {
        "customer_id": customer_id,
        "reminders_created": 43,
        "message": "已录入客户，系统将在各到期日自动发送邮件提醒"
    }


@app.patch("/api/customers/{customer_id}", status_code=200)
async def edit_customer(customer_id: int, data: CustomerUpdate):
    c = await get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    await update_customer(customer_id, data)
    return {"ok": True}


@app.delete("/api/customers/{customer_id}", status_code=200)
async def remove_customer(customer_id: int):
    c = await get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    await delete_customer(customer_id)
    return {"ok": True}


# ---------- 前端静态页面 ----------

@app.get("/")
async def serve_index():
    return RedirectResponse(url="/index.html")


@app.get("/reminders/pending")
async def pending_reminders():
    rows = await get_pending_reminders()
    return rows


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")