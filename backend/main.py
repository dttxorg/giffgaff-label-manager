from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from datetime import datetime
import os
import json

from database import init_db
from models import CustomerCreate, CustomerUpdate, CustomerOut, CustomerDetail, ReminderOut, SystemSettings, QuickSendRequest, DomainInfo
from crud import (
    get_all_customers, get_customer, create_customer,
    update_customer, delete_customer, get_reminders,
    get_pending_reminders, update_customer_moemail,
    get_settings, set_setting
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

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


@app.on_event("startup")
async def startup():
    await init_db()


# ── 系统设置 ──

@app.get("/api/settings", response_model=SystemSettings)
async def get_sys_settings():
    """获取所有设置（敏感字段不返回明文）"""
    rows = await get_settings()
    return SystemSettings(
        moemail_url=rows.get("moemail_url", ""),
        moemail_api_key="***" if rows.get("moemail_api_key") else "",
        resend_api_key="***" if rows.get("resend_api_key") else "",
        from_email=rows.get("from_email", ""),
    )


@app.patch("/api/settings")
async def update_settings(data: SystemSettings):
    """更新系统设置"""
    if data.moemail_url is not None:
        await set_setting("moemail_url", data.moemail_url)
    if data.moemail_api_key not in (None, "***", ""):
        await set_setting("moemail_api_key", data.moemail_api_key)
    if data.resend_api_key not in (None, "***", ""):
        await set_setting("resend_api_key", data.resend_api_key)
    if data.from_email is not None:
        await set_setting("from_email", data.from_email)
    return {"ok": True}


# ── 客户管理 ──

@app.get("/api/customers", response_model=list[CustomerOut])
async def list_customers():
    rows = await get_all_customers()
    return [CustomerOut(
        id=r["id"],
        phone_number=r["phone_number"],
        email=r["email"],
        activation_date=r["activation_date"],
        moemail_id=r.get("moemail_id"),
        moemail_address=r.get("moemail_address"),
        share_link=r.get("share_link"),
        is_moemail_auto=bool(r.get("is_moemail_auto")),
        created_at=r["created_at"],
    ) for r in rows]


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
                resend_email_id=r.get("resend_email_id"),
                sent=bool(r["sent"]),
                sent_at=r.get("sent_at"),
            )
            for r in reminders
        ],
        moemail_id=c.get("moemail_id"),
        moemail_address=c.get("moemail_address"),
        share_link=c.get("share_link"),
        is_moemail_auto=bool(c.get("is_moemail_auto")),
    )


@app.post("/api/customers", status_code=201)
async def add_customer(data: CustomerCreate):
    from database import DATABASE_PATH
    import aiosqlite

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        existing = await db.execute_fetchone(
            "SELECT id FROM customers WHERE phone_number = ?",
            (data.phone_number,),
        )
        if existing:
            raise HTTPException(status_code=409, detail="该手机号已录入")

    customer_id = await create_customer(data)
    moemail_id = ""
    moemail_address = ""
    share_link = ""
    is_auto = False

    # 自动模式：调用 MoEmail API 生成邮箱 + 分享链接
    if data.auto_moemail:
        moemail_url = await _get_setting("moemail_url")
        moemail_key = await _get_setting("moemail_api_key")

        if moemail_url and moemail_key:
            from moemail import MoEmailClient, generate_email_name
            try:
                client = MoEmailClient(moemail_url, moemail_key)

                # 确定域名
                domain = data.moemail_domain
                if not domain:
                    domains = client.get_domains()
                    domain = domains[0] if domains else ""

                email_name = generate_email_name()
                email_resp = client.generate_email(
                    name=email_name,
                    expiry_time=0,  # 永久有效
                    domain=domain,
                )
                moemail_id = email_resp.get("id", "")
                moemail_address = email_resp.get("email", "")

                # 自动创建永久分享链接
                if moemail_id:
                    share_resp = client.create_share_link(moemail_id, expires_in=0)
                    share_link = f"{moemail_url}/shared/{share_resp.get('token', '')}"

                if moemail_id:
                    share_resp = client.create_share_link(moemail_id, expires_in=0)
                    share_link = f"{moemail_url}/shared/{share_resp.get('token', '')}"

                is_auto = True
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"MoEmail API 调用失败：{e}。请检查 MoEmail 配置。"
                )
        else:
            raise HTTPException(
                status_code=400,
                detail="MoEmail 未配置，请在设置页面填写 MoEmail URL 和 API Key"
            )

    # 更新 MoEmail 信息
    if moemail_id:
        await update_customer_moemail(customer_id, moemail_id, moemail_address,
                                      share_link, is_auto)

    # 创建 43 个到期提醒记录
    await create_reminders_for_customer(
        customer_id, data.phone_number, data.email, data.activation_date
    )

    return {
        "customer_id": customer_id,
        "reminders_created": 43,
        "moemail_address": moemail_address,
        "share_link": share_link,
        "message": "已录入客户，系统将在各到期日自动发送邮件提醒",
    }


async def _get_setting(key: str) -> str:
    rows = await get_settings()
    return rows.get(key, "")


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


@app.get("/reminders/pending")
async def pending_reminders():
    rows = await get_pending_reminders()
    return rows


# ── MoEmail 域名列表 ──

@app.get("/api/moemail/domains", response_model=DomainInfo)
async def list_moemail_domains():
    """从 MoEmail 获取可用域名列表"""
    moemail_url = await _get_setting("moemail_url")
    moemail_key = await _get_setting("moemail_api_key")
    if not moemail_url or not moemail_key:
        raise HTTPException(status_code=400, detail="MoEmail 未配置")
    from moemail import MoEmailClient
    client = MoEmailClient(moemail_url, moemail_key)
    try:
        domains = client.get_domains()
        return DomainInfo(domains=domains)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取域名失败：{e}")


# ── 快捷发送邮件 ──

@app.post("/api/quick-send")
async def quick_send(data: QuickSendRequest):
    """用 Resend API 发送邮件（快捷发送）"""
    resend_key = await _get_setting("resend_api_key")
    from_email = await _get_setting("from_email")
    if not resend_key:
        raise HTTPException(status_code=400, detail="Resend API Key 未配置，请在设置页面配置")
    if not from_email:
        raise HTTPException(status_code=400, detail="发件邮箱未配置，请在设置页面配置")

    import resend
    resend.api_key = resend_key
    try:
        r = resend.Emails.send({
            "from": from_email,
            "to": [data.to_address],
            "subject": data.subject,
            "html": data.content,
        })
        return {"ok": True, "email_id": r.get("id", "")}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"发送失败：{e}")


# ── 前端静态页面 ──

@app.get("/")
async def serve_index():
    return RedirectResponse(url="/index.html")


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")


# ── 导入 ──

@app.post("/api/import", status_code=200)
async def import_backup(file: UploadFile = File(...)):
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
                """INSERT INTO customers
                   (id, phone_number, email, activation_date, moemail_id, moemail_address,
                    share_link, is_moemail_auto, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (c["id"], c["phone_number"], c["email"], c["activation_date"],
                 c.get("moemail_id"), c.get("moemail_address"),
                 c.get("share_link"), c.get("is_moemail_auto", 0), c["created_at"]),
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