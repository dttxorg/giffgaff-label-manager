from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
import os
import json
import datetime
import aiosqlite
import hmac
import hashlib
import html
import re
import secrets
import string
from copy import deepcopy
from typing import Optional

from database import init_db, DATABASE_PATH
from models import (
    CustomerCreate, CustomerUpdate, CustomerOut, CustomerDetail,
    SystemSettings, AuthLoginRequest, MoEmailCreateRequest, CainiaoWaybillRequest,
    SimCodeImport, SimCodeOut, ActivationLogIn, ActivationStatusUpdate,
    ActivationResultUpdate, ActivationTaskOut, VerificationCodeOut, DomainInfo, LabelConfig
)
from crud import (
    get_all_customers, get_customer,
    update_customer, delete_customer,
    update_customer_moemail,
    get_settings, set_setting, fetch_one, normalize_optional_text
)

app = FastAPI(title="giffgaff-label-manager API")

APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
AGENT_API_TOKEN = os.getenv("AGENT_API_TOKEN", "").strip()
AUTH_COOKIE_NAME = "giffgaff_label_auth"
DEFAULT_GIFFGAFF_DOWNLOAD_URL = "https://www.giffgaff.com/mobile-app"
DEFAULT_SHIPPING_STATUS = "未发货"
SHIPPING_STATUSES = {"未发货", "已发货", "已收货"}
ACTIVATION_STATUSES = {
    "未开始", "已分配激活码", "等待客户端领取", "激活中",
    "等待人工支付", "等待转 eSIM", "已完成", "失败",
}
SIM_CODE_STATUSES = {"未分配", "已分配", "激活中", "已使用", "失败", "作废"}
DEFAULT_CAINIAO_ENDPOINT = "https://eco.taobao.com/router/rest"
CAINIAO_PLAIN_SETTINGS = (
    "cainiao_endpoint",
    "cainiao_app_key",
    "cainiao_cp_code",
    "cainiao_cp_name",
    "cainiao_template_url",
    "cainiao_user_id",
    "cainiao_order_channel",
    "cainiao_goods_name",
    "cainiao_weight_grams",
    "sender_name",
    "sender_mobile",
    "sender_phone",
    "sender_province",
    "sender_city",
    "sender_district",
    "sender_town",
    "sender_detail",
)
CAINIAO_SECRET_SETTINGS = ("cainiao_app_secret", "cainiao_session")
DEFAULT_LABEL_TEMPLATES = [
    {
        "id": "basic-50x30",
        "name": "基础标签 50x30",
        "width_mm": 50,
        "height_mm": 30,
        "elements": [
            {"id": "phone", "type": "text", "source": "手机号", "text": "", "x": 3, "y": 3, "w": 30, "h": 6, "fontSize": 12, "bold": True},
            {"id": "email", "type": "text", "source": "邮箱", "text": "", "x": 3, "y": 10, "w": 31, "h": 6, "fontSize": 6, "bold": False},
            {"id": "mailqr", "type": "qr", "source": "邮箱二维码", "text": "", "x": 36, "y": 3, "w": 11, "h": 11, "fontSize": 8, "bold": False},
            {"id": "appqr", "type": "qr", "source": "Giffgaff下载二维码", "text": "", "x": 37, "y": 17, "w": 9, "h": 9, "fontSize": 8, "bold": False},
            {"id": "apptext", "type": "text", "source": "固定文字", "text": "giffgaff app", "x": 34, "y": 26, "w": 14, "h": 3, "fontSize": 4, "bold": False},
        ],
    },
    {
        "id": "full-50x40",
        "name": "完整标签 50x40",
        "width_mm": 50,
        "height_mm": 40,
        "elements": [
            {"id": "title", "type": "text", "source": "固定文字", "text": "giffgaff SIM", "x": 3, "y": 3, "w": 27, "h": 5, "fontSize": 9, "bold": True},
            {"id": "phone", "type": "text", "source": "手机号", "text": "", "x": 3, "y": 9, "w": 30, "h": 6, "fontSize": 11, "bold": True},
            {"id": "email", "type": "text", "source": "邮箱", "text": "", "x": 3, "y": 17, "w": 31, "h": 7, "fontSize": 6, "bold": False},
            {"id": "date", "type": "text", "source": "开通日期", "text": "", "x": 3, "y": 26, "w": 24, "h": 4, "fontSize": 6, "bold": False},
            {"id": "mailqr", "type": "qr", "source": "邮箱二维码", "text": "", "x": 35, "y": 3, "w": 12, "h": 12, "fontSize": 8, "bold": False},
            {"id": "appqr", "type": "qr", "source": "Giffgaff下载二维码", "text": "", "x": 35, "y": 22, "w": 12, "h": 12, "fontSize": 8, "bold": False},
            {"id": "apptext", "type": "text", "source": "固定文字", "text": "下载 App", "x": 35, "y": 35, "w": 12, "h": 3, "fontSize": 5, "bold": False},
        ],
    },
    {
        "id": "qr-50x40",
        "name": "双码标签 50x40",
        "width_mm": 50,
        "height_mm": 40,
        "elements": [
            {"id": "mailtitle", "type": "text", "source": "固定文字", "text": "邮箱 / 收件箱", "x": 4, "y": 3, "w": 18, "h": 4, "fontSize": 6, "bold": True},
            {"id": "mailqr", "type": "qr", "source": "邮箱二维码", "text": "", "x": 5, "y": 8, "w": 16, "h": 16, "fontSize": 8, "bold": False},
            {"id": "apptitle", "type": "text", "source": "固定文字", "text": "giffgaff App", "x": 28, "y": 3, "w": 18, "h": 4, "fontSize": 6, "bold": True},
            {"id": "appqr", "type": "qr", "source": "Giffgaff下载二维码", "text": "", "x": 29, "y": 8, "w": 16, "h": 16, "fontSize": 8, "bold": False},
            {"id": "phone", "type": "text", "source": "手机号", "text": "", "x": 4, "y": 28, "w": 42, "h": 5, "fontSize": 9, "bold": True},
            {"id": "email", "type": "text", "source": "邮箱", "text": "", "x": 4, "y": 34, "w": 42, "h": 4, "fontSize": 5, "bold": False},
        ],
    },
    {
        "id": "courier-50x40",
        "name": "快递单 50x40",
        "width_mm": 50,
        "height_mm": 40,
        "elements": [
            {"id": "courier-title", "type": "text", "source": "固定文字", "text": "收件信息", "x": 3, "y": 3, "w": 18, "h": 5, "fontSize": 8, "bold": True},
            {"id": "courier-company", "type": "text", "source": "快递公司", "text": "", "x": 25, "y": 3, "w": 22, "h": 5, "fontSize": 7, "bold": True},
            {"id": "courier-tracking", "type": "text", "source": "快递单号", "text": "", "x": 3, "y": 9, "w": 44, "h": 6, "fontSize": 9, "bold": True},
            {"id": "courier-address", "type": "text", "source": "收货地址", "text": "", "x": 3, "y": 16, "w": 44, "h": 13, "fontSize": 7, "bold": True},
            {"id": "courier-phone-label", "type": "text", "source": "固定文字", "text": "SIM", "x": 3, "y": 30, "w": 7, "h": 4, "fontSize": 6, "bold": True},
            {"id": "courier-phone", "type": "text", "source": "手机号", "text": "", "x": 11, "y": 29, "w": 36, "h": 6, "fontSize": 9, "bold": True},
            {"id": "courier-status", "type": "text", "source": "发货状态", "text": "", "x": 3, "y": 35, "w": 18, "h": 4, "fontSize": 5, "bold": False},
            {"id": "courier-date", "type": "text", "source": "开通日期", "text": "", "x": 23, "y": 35, "w": 24, "h": 4, "fontSize": 5, "bold": False},
        ],
    },
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


def _auth_enabled() -> bool:
    return bool(APP_PASSWORD)


def _auth_token() -> str:
    return hmac.new(APP_PASSWORD.encode("utf-8"), b"giffgaff-label-manager", hashlib.sha256).hexdigest()


def _is_authenticated(request: Request) -> bool:
    if not _auth_enabled():
        return True
    cookie = request.cookies.get(AUTH_COOKIE_NAME, "")
    return hmac.compare_digest(cookie, _auth_token())


def _is_agent_authenticated(request: Request) -> bool:
    if not AGENT_API_TOKEN:
        return False
    auth_header = request.headers.get("authorization", "")
    prefix = "Bearer "
    if not auth_header.startswith(prefix):
        return False
    return hmac.compare_digest(auth_header[len(prefix):].strip(), AGENT_API_TOKEN)


def _require_agent_auth(request: Request):
    if not AGENT_API_TOKEN:
        raise HTTPException(status_code=503, detail="桌面客户端 API 未启用，请配置 AGENT_API_TOKEN")
    if not _is_agent_authenticated(request):
        raise HTTPException(status_code=401, detail="桌面客户端 Token 无效")


def _normalize_base_url(value: Optional[str]) -> str:
    return (value or "").strip().rstrip("/")


def _normalize_share_link(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    return value.strip().replace("//shared/", "/shared/")


def _customer_payload(row) -> dict:
    customer = dict(row)
    customer["share_link"] = _normalize_share_link(customer.get("share_link"))
    customer["shipping_status"] = _normalize_shipping_status(customer.get("shipping_status"))
    customer["activation_status"] = _normalize_activation_status(customer.get("activation_status"))
    customer.pop("initial_password", None)
    customer.pop("automation_lock_owner", None)
    customer.pop("automation_locked_at", None)
    return customer


def _normalize_shipping_status(value: Optional[str]) -> str:
    value = (value or "").strip()
    return value if value in SHIPPING_STATUSES else DEFAULT_SHIPPING_STATUS


def _normalize_activation_status(value: Optional[str]) -> str:
    value = (value or "").strip()
    return value if value in ACTIVATION_STATUSES else "未开始"


def _normalize_sim_code_status(value: Optional[str]) -> str:
    value = (value or "").strip()
    return value if value in SIM_CODE_STATUSES else "未分配"


def _normalize_sim_code(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _generate_initial_password() -> str:
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"Gg-{random_part}!"


def _utc_now() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _masked_setting(rows: dict, key: str) -> str:
    return "***" if rows.get(key) else ""


def _first_text(data: dict, *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return str(value)
    return ""


def _message_list(payload) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("messages", "data", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    email = payload.get("email")
    if isinstance(email, dict) and isinstance(email.get("messages"), list):
        return [item for item in email["messages"] if isinstance(item, dict)]
    return []


def _message_id(message: dict) -> str:
    return _first_text(message, "id", "messageId", "message_id")


def _message_received_at(message: dict) -> str:
    return _first_text(message, "receivedAt", "received_at", "createdAt", "created_at", "date")


def _message_detail_payload(payload) -> dict:
    if not isinstance(payload, dict):
        return {}
    for key in ("message", "data", "item"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def _plain_text_from_html(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<br\s*/?>", "\n", text)
    text = re.sub(r"(?s)</p\s*>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text)


def _extract_verification_code(message: dict) -> Optional[str]:
    subject = _first_text(message, "subject")
    content = _first_text(message, "content", "text", "body", "plainText", "plain_text")
    html_content = _plain_text_from_html(_first_text(message, "html", "htmlContent", "html_content"))
    text = "\n".join(part for part in (subject, content, html_content) if part)
    if not text:
        return None
    patterns = (
        r"(?is)verification\s+code\s*(?:is)?\s*[:：]?\s*(\d{6})",
        r"(?is)code\s*(?:is)?\s*[:：]?\s*(\d{6})",
        r"(?is)验证码\s*(?:是|为)?\s*[:：]?\s*(\d{6})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    match = re.search(r"(?<!\d)\d{6}(?!\d)", text)
    return match.group(0) if match else None


def _merge_default_label_templates(templates: list[dict]) -> list[dict]:
    merged = deepcopy(templates)
    existing_ids = {tpl.get("id") for tpl in merged if isinstance(tpl, dict)}
    for template in DEFAULT_LABEL_TEMPLATES:
        if template["id"] not in existing_ids:
            merged.append(deepcopy(template))
    return merged


@app.middleware("http")
async def require_app_password(request, call_next):
    public_paths = {"/api/auth/status", "/api/auth/login", "/api/auth/logout"}
    protected_prefixes = ("/api", "/docs", "/redoc", "/openapi.json")
    if request.url.path.startswith("/api/agent"):
        return await call_next(request)
    if _auth_enabled() and request.url.path not in public_paths and request.url.path.startswith(protected_prefixes):
        if not _is_authenticated(request):
            return JSONResponse({"detail": "需要登录"}, status_code=401)
    return await call_next(request)


@app.on_event("startup")
async def startup():
    await init_db()


# ── 访问口令 ──

@app.get("/api/auth/status")
async def auth_status(request: Request):
    return {
        "auth_required": _auth_enabled(),
        "authenticated": _is_authenticated(request),
    }


@app.post("/api/auth/login")
async def auth_login(data: AuthLoginRequest):
    if not _auth_enabled():
        return {"ok": True}
    if not hmac.compare_digest(data.password, APP_PASSWORD):
        raise HTTPException(status_code=401, detail="口令错误")
    response = JSONResponse({"ok": True})
    response.set_cookie(
        AUTH_COOKIE_NAME,
        _auth_token(),
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return response


@app.post("/api/auth/logout")
async def auth_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(AUTH_COOKIE_NAME)
    return response


# ── 系统设置 ──

@app.get("/api/settings", response_model=SystemSettings)
async def get_sys_settings():
    rows = await get_settings()
    return SystemSettings(
        moemail_url=rows.get("moemail_url", ""),
        moemail_api_key="***" if rows.get("moemail_api_key") else "",
        giffgaff_download_url=rows.get("giffgaff_download_url", DEFAULT_GIFFGAFF_DOWNLOAD_URL),
        cainiao_endpoint=rows.get("cainiao_endpoint", DEFAULT_CAINIAO_ENDPOINT),
        cainiao_app_key=rows.get("cainiao_app_key", ""),
        cainiao_app_secret=_masked_setting(rows, "cainiao_app_secret"),
        cainiao_session=_masked_setting(rows, "cainiao_session"),
        cainiao_cp_code=rows.get("cainiao_cp_code", ""),
        cainiao_cp_name=rows.get("cainiao_cp_name", ""),
        cainiao_template_url=rows.get("cainiao_template_url", ""),
        cainiao_user_id=rows.get("cainiao_user_id", ""),
        cainiao_order_channel=rows.get("cainiao_order_channel", "OTHERS"),
        cainiao_goods_name=rows.get("cainiao_goods_name", "giffgaff SIM"),
        cainiao_weight_grams=rows.get("cainiao_weight_grams", "100"),
        sender_name=rows.get("sender_name", ""),
        sender_mobile=rows.get("sender_mobile", ""),
        sender_phone=rows.get("sender_phone", ""),
        sender_province=rows.get("sender_province", ""),
        sender_city=rows.get("sender_city", ""),
        sender_district=rows.get("sender_district", ""),
        sender_town=rows.get("sender_town", ""),
        sender_detail=rows.get("sender_detail", ""),
    )


@app.patch("/api/settings")
async def update_settings(data: SystemSettings):
    if data.moemail_url is not None:
        await set_setting("moemail_url", _normalize_base_url(data.moemail_url))
    if data.moemail_api_key not in (None, "***", ""):
        await set_setting("moemail_api_key", data.moemail_api_key)
    if data.giffgaff_download_url is not None:
        await set_setting("giffgaff_download_url", data.giffgaff_download_url)
    for key in CAINIAO_PLAIN_SETTINGS:
        value = getattr(data, key)
        if value is not None:
            await set_setting(key, value.strip())
    for key in CAINIAO_SECRET_SETTINGS:
        value = getattr(data, key)
        if value not in (None, "***", ""):
            await set_setting(key, value.strip())
    return {"ok": True}


async def _get_setting(key: str) -> str:
    rows = await get_settings()
    return rows.get(key, "")


async def _generate_moemail_account(domain: Optional[str] = None) -> dict:
    moemail_url = _normalize_base_url(await _get_setting("moemail_url"))
    moemail_key = await _get_setting("moemail_api_key")
    if not moemail_url or not moemail_key:
        raise HTTPException(status_code=400, detail="MoEmail 未配置，请在设置页面配置")
    from moemail import MoEmailClient
    client = MoEmailClient(moemail_url, moemail_key)
    if not domain:
        domains = client.get_domains()
        domain = domains[0] if domains else ""
    email_resp = client.generate_email(expiry_time=0, domain=domain)
    moemail_id = email_resp.get("id", "")
    moemail_address = email_resp.get("email", "")
    if not moemail_id or not moemail_address:
        raise ValueError("MoEmail 未返回邮箱 ID 或地址")
    share_resp = client.create_share_link(moemail_id, expires_in=0)
    token = share_resp.get("token", "")
    return {
        "email": moemail_address,
        "moemail_id": moemail_id,
        "moemail_address": moemail_address,
        "share_link": f"{moemail_url}/shared/{token}" if token else "",
    }


async def _has_available_sim_code() -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        row = await fetch_one(db, "SELECT id FROM sim_codes WHERE status = '未分配' ORDER BY id ASC LIMIT 1")
        return bool(row)


async def _create_customer_with_activation(data: CustomerCreate, email_bundle: dict, initial_password: str) -> tuple[int, dict]:
    phone_number = normalize_optional_text(data.phone_number)
    shipping_address = normalize_optional_text(data.shipping_address)
    courier_company = normalize_optional_text(data.courier_company)
    tracking_number = normalize_optional_text(data.tracking_number)
    courier_order_code = normalize_optional_text(data.courier_order_code)
    courier_print_data = normalize_optional_text(data.courier_print_data)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        try:
            await db.execute("BEGIN IMMEDIATE")
            sim = await fetch_one(
                db,
                "SELECT id, code FROM sim_codes WHERE status = '未分配' ORDER BY id ASC LIMIT 1",
            )
            if not sim:
                raise HTTPException(status_code=400, detail="没有可用 SIM 激活码，请先导入激活码")
            cursor = await db.execute(
                """INSERT INTO customers
                   (phone_number, email, shipping_address, shipping_status, courier_company,
                    tracking_number, courier_order_code, courier_print_data, activation_date,
                    moemail_id, moemail_address, share_link, is_moemail_auto,
                    sim_code_id, sim_activation_code, initial_password, activation_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    phone_number,
                    email_bundle.get("email", ""),
                    shipping_address,
                    data.shipping_status,
                    courier_company,
                    tracking_number,
                    courier_order_code,
                    courier_print_data,
                    data.activation_date.isoformat(),
                    email_bundle.get("moemail_id"),
                    email_bundle.get("moemail_address"),
                    email_bundle.get("share_link"),
                    1 if email_bundle.get("is_moemail_auto") else 0,
                    sim["id"],
                    sim["code"],
                    initial_password,
                    "等待客户端领取",
                ),
            )
            customer_id = cursor.lastrowid
            await db.execute(
                "UPDATE sim_codes SET status = '已分配', customer_id = ?, updated_at = datetime('now') WHERE id = ?",
                (customer_id, sim["id"]),
            )
            await db.execute(
                """INSERT INTO activation_logs (customer_id, level, step, message)
                   VALUES (?, 'info', 'created', ?)""",
                (customer_id, f"已分配 SIM 激活码 {sim['code']}，等待桌面客户端领取"),
            )
            await db.commit()
            return customer_id, {"id": sim["id"], "code": sim["code"]}
        except Exception:
            await db.rollback()
            raise


# ── 客户管理 ──

@app.get("/api/customers", response_model=list[CustomerOut])
async def list_customers():
    rows = await get_all_customers()
    return [CustomerOut(
        id=r["id"],
        phone_number=r["phone_number"],
        email=r["email"],
        shipping_address=r.get("shipping_address"),
        shipping_status=_normalize_shipping_status(r.get("shipping_status")),
        courier_company=r.get("courier_company"),
        tracking_number=r.get("tracking_number"),
        courier_order_code=r.get("courier_order_code"),
        activation_date=r["activation_date"],
        moemail_id=r.get("moemail_id"),
        moemail_address=r.get("moemail_address"),
        share_link=_normalize_share_link(r.get("share_link")),
        is_moemail_auto=bool(r.get("is_moemail_auto")),
        sim_code_id=r.get("sim_code_id"),
        sim_activation_code=r.get("sim_activation_code"),
        activation_status=_normalize_activation_status(r.get("activation_status")),
        activation_error=r.get("activation_error"),
        activated_at=r.get("activated_at"),
        created_at=r["created_at"],
    ) for r in rows]


@app.get("/api/customers/{customer_id}", response_model=CustomerDetail)
async def get_customer_detail(customer_id: int):
    c = await get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    return CustomerDetail(
        id=c["id"],
        phone_number=c["phone_number"],
        email=c["email"],
        shipping_address=c.get("shipping_address"),
        shipping_status=_normalize_shipping_status(c.get("shipping_status")),
        courier_company=c.get("courier_company"),
        tracking_number=c.get("tracking_number"),
        courier_order_code=c.get("courier_order_code"),
        activation_date=c["activation_date"],
        created_at=c["created_at"],
        moemail_id=c.get("moemail_id"),
        moemail_address=c.get("moemail_address"),
        share_link=_normalize_share_link(c.get("share_link")),
        is_moemail_auto=bool(c.get("is_moemail_auto")),
        sim_code_id=c.get("sim_code_id"),
        sim_activation_code=c.get("sim_activation_code"),
        initial_password=c.get("initial_password"),
        activation_status=_normalize_activation_status(c.get("activation_status")),
        activation_error=c.get("activation_error"),
        activated_at=c.get("activated_at"),
    )


@app.post("/api/customers", status_code=201)
async def add_customer(data: CustomerCreate):
    phone_number = normalize_optional_text(data.phone_number)
    if phone_number:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            existing = await fetch_one(
                db,
                "SELECT id FROM customers WHERE phone_number = ?", (phone_number,)
            )
            if existing:
                raise HTTPException(status_code=409, detail="该手机号已录入")

    if not await _has_available_sim_code():
        raise HTTPException(status_code=400, detail="没有可用 SIM 激活码，请先导入激活码")

    try:
        email = (data.email or "").strip()
        if email:
            email_bundle = {"email": email, "is_moemail_auto": False}
        else:
            email_bundle = await _generate_moemail_account()
            email_bundle["is_moemail_auto"] = True
        initial_password = _generate_initial_password()
        customer_id, sim = await _create_customer_with_activation(data, email_bundle, initial_password)
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="该手机号已录入")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"自动建档失败：{exc}") from exc

    return {
        "customer_id": customer_id,
        "message": "客户已录入，已分配激活码并创建激活任务",
        "email": email_bundle.get("email", ""),
        "sim_activation_code": sim["code"],
        "initial_password": initial_password,
    }


@app.patch("/api/customers/{customer_id}", status_code=200)
async def edit_customer(customer_id: int, data: CustomerUpdate):
    c = await get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    phone_number = normalize_optional_text(data.phone_number)
    if phone_number:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            existing = await fetch_one(
                db,
                "SELECT id FROM customers WHERE phone_number = ? AND id != ?",
                (phone_number, customer_id),
            )
            if existing:
                raise HTTPException(status_code=409, detail="该手机号已录入")
    try:
        await update_customer(customer_id, data)
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="该手机号已录入") from None
    return {"ok": True}


@app.post("/api/customers/{customer_id}/cainiao-waybill", status_code=200)
async def create_cainiao_waybill(customer_id: int, data: CainiaoWaybillRequest):
    c = await get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    rows = await get_settings()
    from cainiao import CainiaoConfigError, create_waybill
    try:
        result = await create_waybill(rows, c, dry_run=data.dry_run)
    except CainiaoConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"菜鸟接口调用失败：{exc}") from exc

    if not data.dry_run:
        courier_company = rows.get("cainiao_cp_name") or rows.get("cainiao_cp_code") or c.get("courier_company")
        await update_customer(customer_id, CustomerUpdate(
            courier_company=courier_company,
            tracking_number=result.get("tracking_number", ""),
            courier_order_code=result.get("order_code", ""),
            courier_print_data=result.get("courier_print_data", ""),
        ))
    return {
        "ok": True,
        "dry_run": data.dry_run,
        "order_code": result.get("order_code", ""),
        "tracking_number": result.get("tracking_number", ""),
        "courier_company": rows.get("cainiao_cp_name") or rows.get("cainiao_cp_code", ""),
        "has_print_data": bool(result.get("courier_print_data")),
        "request": result.get("request") if data.dry_run else None,
    }


@app.delete("/api/customers/{customer_id}", status_code=200)
async def remove_customer(customer_id: int):
    c = await get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    sim_code_id = c.get("sim_code_id")
    if sim_code_id:
        status = _normalize_activation_status(c.get("activation_status"))
        sim_status = "已使用" if status in {"等待转 eSIM", "已完成"} else "未分配"
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """UPDATE sim_codes
                   SET status = ?, customer_id = NULL, updated_at = datetime('now')
                   WHERE id = ?""",
                (sim_status, sim_code_id),
            )
            await db.execute("DELETE FROM activation_logs WHERE customer_id = ?", (customer_id,))
            await db.commit()
    await delete_customer(customer_id)
    return {"ok": True}


@app.post("/api/customers/{customer_id}/moemail")
async def create_customer_moemail(customer_id: int, data: MoEmailCreateRequest):
    c = await get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    try:
        email_bundle = await _generate_moemail_account(data.domain)
        await update_customer_moemail(
            customer_id,
            email_bundle["moemail_id"],
            email_bundle["moemail_address"],
            email_bundle["share_link"],
            True,
        )
        return {
            "ok": True,
            "email": email_bundle["email"],
            "moemail_id": email_bundle["moemail_id"],
            "share_link": email_bundle["share_link"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MoEmail 调用失败：{e}") from e


@app.get("/api/customers/{customer_id}/verification-code", response_model=VerificationCodeOut)
async def get_customer_verification_code(customer_id: int):
    c = await get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    moemail_id = (c.get("moemail_id") or "").strip()
    if not moemail_id:
        raise HTTPException(status_code=400, detail="该客户没有 MoEmail 邮箱，手填邮箱无法自动接码")
    moemail_url = _normalize_base_url(await _get_setting("moemail_url"))
    moemail_key = await _get_setting("moemail_api_key")
    if not moemail_url or not moemail_key:
        raise HTTPException(status_code=400, detail="MoEmail 未配置，请在设置页面配置")

    from moemail import MoEmailClient
    client = MoEmailClient(moemail_url, moemail_key)
    email_address = c.get("moemail_address") or c.get("email") or ""
    try:
        mailbox = client.get_email_messages(moemail_id)
        messages = _message_list(mailbox)
        messages.sort(key=_message_received_at, reverse=True)
        checked_count = 0
        latest_meta = {}

        for summary in messages[:10]:
            message_id = _message_id(summary)
            detail = {}
            if message_id:
                detail = _message_detail_payload(client.get_message(moemail_id, message_id))
            message = {**summary, **detail}
            checked_count += 1
            if not latest_meta:
                latest_meta = message
            code = _extract_verification_code(message)
            if code:
                return VerificationCodeOut(
                    found=True,
                    code=code,
                    email=email_address,
                    message_id=_message_id(message) or message_id or None,
                    subject=_first_text(message, "subject") or None,
                    from_address=_first_text(message, "fromAddress", "from_address", "from") or None,
                    received_at=_message_received_at(message) or None,
                    checked_count=checked_count,
                    detail="已提取最新验证码",
                )

        return VerificationCodeOut(
            found=False,
            email=email_address,
            message_id=_message_id(latest_meta) or None,
            subject=_first_text(latest_meta, "subject") or None,
            from_address=_first_text(latest_meta, "fromAddress", "from_address", "from") or None,
            received_at=_message_received_at(latest_meta) or None,
            checked_count=checked_count,
            detail="没有找到可提取的 6 位验证码",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MoEmail 接码失败：{e}") from e


# ── MoEmail 域名列表 ──

@app.get("/api/moemail/domains", response_model=DomainInfo)
async def list_moemail_domains():
    moemail_url = _normalize_base_url(await _get_setting("moemail_url"))
    moemail_key = await _get_setting("moemail_api_key")
    if not moemail_url or not moemail_key:
        raise HTTPException(status_code=400, detail="MoEmail 未配置")
    from moemail import MoEmailClient
    client = MoEmailClient(moemail_url, moemail_key)
    try:
        return DomainInfo(domains=client.get_domains())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取域名失败：{e}")


# ── SIM 激活码库 ──

def _parse_sim_codes(data: SimCodeImport) -> list[str]:
    values = []
    if data.codes:
        values.extend(data.codes)
    if data.text:
        values.extend(re.split(r"[\s,;，；]+", data.text))
    seen = set()
    codes = []
    for value in values:
        code = _normalize_sim_code(value)
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


@app.get("/api/sim-codes", response_model=list[SimCodeOut])
async def list_sim_codes():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall("SELECT * FROM sim_codes ORDER BY id DESC LIMIT 1000")
    return [
        SimCodeOut(
            id=row["id"],
            code=row["code"],
            status=_normalize_sim_code_status(row["status"]),
            customer_id=row["customer_id"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


@app.post("/api/sim-codes/import", status_code=201)
async def import_sim_codes(data: SimCodeImport):
    codes = _parse_sim_codes(data)
    if not codes:
        raise HTTPException(status_code=400, detail="请粘贴或填写 SIM 激活码")
    imported = 0
    async with aiosqlite.connect(DATABASE_PATH) as db:
        for code in codes:
            cursor = await db.execute(
                "INSERT OR IGNORE INTO sim_codes (code, status) VALUES (?, '未分配')",
                (code,),
            )
            imported += cursor.rowcount
        await db.commit()
    return {
        "ok": True,
        "imported": imported,
        "duplicates": len(codes) - imported,
        "total": len(codes),
    }


# ── 桌面客户端 API ──

def _sim_status_for_activation(status: str) -> str:
    status = _normalize_activation_status(status)
    if status in {"未开始", "已分配激活码", "等待客户端领取"}:
        return "已分配"
    if status in {"激活中", "等待人工支付"}:
        return "激活中"
    if status in {"等待转 eSIM", "已完成"}:
        return "已使用"
    if status == "失败":
        return "失败"
    return "已分配"


async def _insert_activation_log(customer_id: int, level: str, step: Optional[str], message: str):
    if not message:
        return
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT INTO activation_logs (customer_id, level, step, message)
               VALUES (?, ?, ?, ?)""",
            (customer_id, (level or "info").strip() or "info", normalize_optional_text(step), message),
        )
        await db.commit()


async def _apply_activation_status(customer_id: int, status: str, error: Optional[str] = None):
    status = _normalize_activation_status(status)
    sim_status = _sim_status_for_activation(status)
    clear_lock = status != "激活中"
    activated_at_sql = ", activated_at = COALESCE(activated_at, ?)" if status in {"等待转 eSIM", "已完成"} else ""
    params = [status, normalize_optional_text(error)]
    if status in {"等待转 eSIM", "已完成"}:
        params.append(_utc_now())
    if clear_lock:
        lock_sql = ", automation_lock_owner = NULL, automation_locked_at = NULL"
    else:
        lock_sql = ""
    params.append(customer_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            f"""UPDATE customers
                SET activation_status = ?, activation_error = ?{activated_at_sql}{lock_sql}
                WHERE id = ?""",
            params,
        )
        await db.execute(
            """UPDATE sim_codes
               SET status = ?, updated_at = datetime('now')
               WHERE customer_id = ?""",
            (sim_status, customer_id),
        )
        await db.commit()


@app.get("/api/agent/activation-tasks/next")
async def get_next_activation_task(request: Request, agent_id: str = "desktop"):
    _require_agent_auth(request)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        row = await fetch_one(
            db,
            """SELECT * FROM customers
               WHERE activation_status = '等待客户端领取'
                 AND sim_activation_code IS NOT NULL
                 AND sim_activation_code != ''
                 AND email != ''
                 AND initial_password IS NOT NULL
                 AND initial_password != ''
               ORDER BY created_at ASC, id ASC
               LIMIT 1""",
        )
        if not row:
            await db.commit()
            return {"task": None}
        await db.execute(
            """UPDATE customers
               SET activation_status = '激活中',
                   automation_lock_owner = ?,
                   automation_locked_at = ?
               WHERE id = ?""",
            (agent_id, _utc_now(), row["id"]),
        )
        await db.execute(
            "UPDATE sim_codes SET status = '激活中', updated_at = datetime('now') WHERE customer_id = ?",
            (row["id"],),
        )
        await db.execute(
            """INSERT INTO activation_logs (customer_id, level, step, message)
               VALUES (?, 'info', 'claimed', ?)""",
            (row["id"], f"桌面客户端 {agent_id} 已领取任务"),
        )
        await db.commit()
        task = dict(row)
        task["activation_status"] = "激活中"
    task_out = ActivationTaskOut(
        customer_id=task["id"],
        phone_number=task.get("phone_number"),
        email=task["email"],
        initial_password=task["initial_password"],
        sim_activation_code=task["sim_activation_code"],
        activation_status=_normalize_activation_status(task.get("activation_status")),
        activation_date=task["activation_date"],
        moemail_id=task.get("moemail_id"),
        moemail_address=task.get("moemail_address"),
        share_link=_normalize_share_link(task.get("share_link")),
        shipping_address=task.get("shipping_address"),
    )
    return {"task": task_out.dict()}


@app.post("/api/agent/customers/{customer_id}/activation-log")
async def add_agent_activation_log(customer_id: int, data: ActivationLogIn, request: Request):
    _require_agent_auth(request)
    c = await get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    await _insert_activation_log(customer_id, data.level, data.step, data.message)
    return {"ok": True}


@app.patch("/api/agent/customers/{customer_id}/activation-status")
async def update_agent_activation_status(customer_id: int, data: ActivationStatusUpdate, request: Request):
    _require_agent_auth(request)
    c = await get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    await _apply_activation_status(customer_id, data.status, data.error)
    if data.message:
        await _insert_activation_log(customer_id, "info", data.step, data.message)
    elif data.error:
        await _insert_activation_log(customer_id, "error", data.step, data.error)
    return {"ok": True}


@app.patch("/api/agent/customers/{customer_id}/activation-result")
async def update_agent_activation_result(customer_id: int, data: ActivationResultUpdate, request: Request):
    _require_agent_auth(request)
    c = await get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    phone_number = normalize_optional_text(data.phone_number)
    if phone_number:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            existing = await fetch_one(
                db,
                "SELECT id FROM customers WHERE phone_number = ? AND id != ?",
                (phone_number, customer_id),
            )
            if existing:
                raise HTTPException(status_code=409, detail="该手机号已录入")
            await db.execute(
                "UPDATE customers SET phone_number = ? WHERE id = ?",
                (phone_number, customer_id),
            )
            await db.commit()
    await _apply_activation_status(customer_id, data.status, data.error)
    message = data.message or (f"桌面客户端回传手机号 {phone_number}" if phone_number else "")
    if message:
        await _insert_activation_log(customer_id, "info", data.step or "result", message)
    if data.error:
        await _insert_activation_log(customer_id, "error", data.step, data.error)
    return {"ok": True}


@app.get("/api/agent/customers/{customer_id}/verification-code", response_model=VerificationCodeOut)
async def get_agent_customer_verification_code(customer_id: int, request: Request):
    _require_agent_auth(request)
    return await get_customer_verification_code(customer_id)


# ── 标签模板 ──

def _load_label_templates(raw: str):
    if not raw:
        return deepcopy(DEFAULT_LABEL_TEMPLATES)
    try:
        templates = json.loads(raw)
        return _merge_default_label_templates(templates) if isinstance(templates, list) else deepcopy(DEFAULT_LABEL_TEMPLATES)
    except json.JSONDecodeError:
        return deepcopy(DEFAULT_LABEL_TEMPLATES)


@app.get("/api/label-config", response_model=LabelConfig)
async def get_label_config():
    rows = await get_settings()
    return LabelConfig(
        giffgaff_download_url=rows.get("giffgaff_download_url", DEFAULT_GIFFGAFF_DOWNLOAD_URL),
        templates=_load_label_templates(rows.get("label_templates", "")),
    )


@app.put("/api/label-config")
async def update_label_config(data: LabelConfig):
    await set_setting("giffgaff_download_url", data.giffgaff_download_url)
    await set_setting("label_templates", json.dumps(data.templates, ensure_ascii=False))
    return {"ok": True}


# ── 导出 / 导入 ──

def _backup_timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


async def _export_backup_payload() -> dict:
    rows = await get_settings()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        customers = await db.execute_fetchall("SELECT * FROM customers ORDER BY id ASC")
        sim_codes = await db.execute_fetchall("SELECT * FROM sim_codes ORDER BY id ASC")
    return {
        "exported_at": datetime.datetime.now().isoformat(),
        "version": "1.0",
        "customers": [_customer_payload(r) for r in customers],
        "sim_codes": [dict(r) for r in sim_codes],
        "settings": {
            "moemail_url": _normalize_base_url(rows.get("moemail_url", "")),
            "giffgaff_download_url": rows.get("giffgaff_download_url", DEFAULT_GIFFGAFF_DOWNLOAD_URL),
            "label_templates": _load_label_templates(rows.get("label_templates", "")),
            **{key: rows.get(key, "") for key in CAINIAO_PLAIN_SETTINGS},
        },
    }


def _validate_backup_payload(data: dict) -> list[dict]:
    if data.get("version") != "1.0":
        raise HTTPException(status_code=400, detail="不支持的备份文件版本")
    customers = data.get("customers", [])
    if not isinstance(customers, list):
        raise HTTPException(status_code=400, detail="备份文件缺少 customers 列表")
    required_fields = ("id", "phone_number", "email", "activation_date", "created_at")
    for index, customer in enumerate(customers, start=1):
        if not isinstance(customer, dict):
            raise HTTPException(status_code=400, detail=f"第 {index} 条客户数据格式错误")
        missing = [field for field in required_fields if field not in customer]
        if missing:
            raise HTTPException(status_code=400, detail=f"第 {index} 条客户缺少字段：{', '.join(missing)}")
    return customers


def _validate_sim_codes_payload(data: dict) -> list[dict]:
    sim_codes = data.get("sim_codes", [])
    if sim_codes is None:
        return []
    if not isinstance(sim_codes, list):
        raise HTTPException(status_code=400, detail="备份文件 sim_codes 格式错误")
    for index, item in enumerate(sim_codes, start=1):
        if not isinstance(item, dict) or not item.get("code"):
            raise HTTPException(status_code=400, detail=f"第 {index} 条 SIM 激活码数据格式错误")
    return sim_codes


async def _restore_backup_payload(data: dict) -> dict:
    customers = _validate_backup_payload(data)
    sim_codes = _validate_sim_codes_payload(data)
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    safe_settings = {}

    if isinstance(settings.get("moemail_url"), str):
        safe_settings["moemail_url"] = _normalize_base_url(settings["moemail_url"])
    if isinstance(settings.get("giffgaff_download_url"), str):
        safe_settings["giffgaff_download_url"] = settings["giffgaff_download_url"]
    for key in CAINIAO_PLAIN_SETTINGS:
        if isinstance(settings.get(key), str):
            safe_settings[key] = settings[key]
    if "label_templates" in settings:
        label_templates = settings["label_templates"]
        if not isinstance(label_templates, list):
            raise HTTPException(status_code=400, detail="标签模板数据格式错误")
        safe_settings["label_templates"] = json.dumps(label_templates, ensure_ascii=False)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute("BEGIN")
            await db.execute("DELETE FROM customers")
            await db.execute("DELETE FROM sim_codes")
            for sim in sim_codes:
                await db.execute(
                    """INSERT INTO sim_codes
                       (id, code, status, customer_id, notes, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sim.get("id"),
                        _normalize_sim_code(sim.get("code")),
                        _normalize_sim_code_status(sim.get("status")),
                        sim.get("customer_id"),
                        normalize_optional_text(sim.get("notes")),
                        sim.get("created_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        sim.get("updated_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
            for c in customers:
                await db.execute(
                    """INSERT INTO customers
                       (id, phone_number, email, shipping_address, shipping_status, courier_company,
                        tracking_number, courier_order_code, courier_print_data, activation_date,
                        moemail_id, moemail_address, share_link, is_moemail_auto,
                        sim_code_id, sim_activation_code, activation_status, activation_error, activated_at,
                        created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (c["id"], normalize_optional_text(c.get("phone_number")), c["email"],
                     normalize_optional_text(c.get("shipping_address")),
                     _normalize_shipping_status(c.get("shipping_status")),
                     normalize_optional_text(c.get("courier_company")),
                     normalize_optional_text(c.get("tracking_number")),
                     normalize_optional_text(c.get("courier_order_code")),
                     normalize_optional_text(c.get("courier_print_data")), c["activation_date"],
                     c.get("moemail_id"), c.get("moemail_address"),
                     _normalize_share_link(c.get("share_link")), c.get("is_moemail_auto", 0),
                     c.get("sim_code_id"), _normalize_sim_code(c.get("sim_activation_code")),
                     _normalize_activation_status(c.get("activation_status")),
                     normalize_optional_text(c.get("activation_error")), c.get("activated_at"),
                     c["created_at"]),
                )
            for key, value in safe_settings.items():
                await db.execute(
                    """INSERT INTO settings (key, value) VALUES (?, ?)
                       ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                    (key, value),
                )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=400, detail=f"恢复失败：{exc}") from exc
    return {"customers_restored": len(customers), "sim_codes_restored": len(sim_codes), "settings_restored": len(safe_settings)}


@app.get("/api/export")
async def export_all():
    data = await _export_backup_payload()
    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    filename = f"giffgaff_backup_{_backup_timestamp()}.json"
    return StreamingResponse(iter([json_bytes]), media_type="application/json",
                           headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.post("/api/import", status_code=200)
async def import_backup(file: UploadFile = File(...)):
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="只支持 .json 文件")
    contents = await file.read()
    try:
        data = json.loads(contents)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="文件格式错误")
    restored = await _restore_backup_payload(data)
    return {"ok": True, **restored}


# ── 前端静态页面 ──

@app.get("/")
async def serve_index():
    return RedirectResponse(url="/index.html")


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")
