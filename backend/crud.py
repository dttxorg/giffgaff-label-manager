import aiosqlite
from models import CustomerCreate, CustomerUpdate
from database import DATABASE_PATH
from typing import Optional


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


async def fetch_one(db: aiosqlite.Connection, query: str, params=()):
    async with db.execute(query, params) as cursor:
        return await cursor.fetchone()


async def get_all_customers():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            "SELECT * FROM customers ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]


async def search_customers(query: str):
    """模糊搜索：手机号 / 快递单号 / 快递公司 / 快递订单号 / 邮箱 任一字段含子串即匹配。
    大小写不敏感，按 created_at DESC 排序。空串返回全部。"""
    q = (query or "").strip().lower()
    if not q:
        return await get_all_customers()
    pattern = f"%{q}%"
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            """SELECT * FROM customers
               WHERE LOWER(COALESCE(phone_number, '')) LIKE ?
                  OR LOWER(COALESCE(tracking_number, '')) LIKE ?
                  OR LOWER(COALESCE(courier_company, '')) LIKE ?
                  OR LOWER(COALESCE(courier_order_code, '')) LIKE ?
                  OR LOWER(COALESCE(email, '')) LIKE ?
               ORDER BY created_at DESC""",
            (pattern, pattern, pattern, pattern, pattern),
        )
        return [dict(r) for r in rows] 


async def get_customer(customer_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await fetch_one(
            db,
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        )
        return dict(row) if row else None


async def create_customer(data: CustomerCreate):
    phone_number = normalize_optional_text(data.phone_number)
    shipping_address = normalize_optional_text(data.shipping_address)
    courier_company = normalize_optional_text(data.courier_company)
    tracking_number = normalize_optional_text(data.tracking_number)
    courier_order_code = normalize_optional_text(data.courier_order_code)
    courier_print_data = normalize_optional_text(data.courier_print_data)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO customers
               (phone_number, email, shipping_address, shipping_status, courier_company,
                tracking_number, courier_order_code, courier_print_data, activation_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (phone_number, data.email, shipping_address, data.shipping_status, courier_company, tracking_number,
             courier_order_code, courier_print_data, data.activation_date.isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def update_customer(customer_id: int, data: CustomerUpdate):
    fields, values = [], []
    if data.phone_number is not None:
        fields.append("phone_number = ?"); values.append(normalize_optional_text(data.phone_number))
    if data.email is not None:
        fields.append("email = ?"); values.append(data.email)
    if data.shipping_address is not None:
        fields.append("shipping_address = ?"); values.append(normalize_optional_text(data.shipping_address))
    if data.shipping_status is not None:
        fields.append("shipping_status = ?"); values.append(data.shipping_status)
    if data.courier_company is not None:
        fields.append("courier_company = ?"); values.append(normalize_optional_text(data.courier_company))
    if data.tracking_number is not None:
        fields.append("tracking_number = ?"); values.append(normalize_optional_text(data.tracking_number))
    if data.courier_order_code is not None:
        fields.append("courier_order_code = ?"); values.append(normalize_optional_text(data.courier_order_code))
    if data.courier_print_data is not None:
        fields.append("courier_print_data = ?"); values.append(normalize_optional_text(data.courier_print_data))
    if data.activation_date is not None:
        fields.append("activation_date = ?"); values.append(data.activation_date.isoformat())
    if data.activation_status is not None:
        fields.append("activation_status = ?"); values.append(data.activation_status)
    if data.activation_error is not None:
        fields.append("activation_error = ?"); values.append(normalize_optional_text(data.activation_error))
    if not fields:
        return True
    values.append(customer_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(f"UPDATE customers SET {', '.join(fields)} WHERE id = ?", values)
        await db.commit()
        return True


async def delete_customer(customer_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        await db.commit()
        return True


async def update_customer_moemail(customer_id: int, moemail_id: str,
                                    moemail_address: str, share_link: str,
                                    is_moemail_auto: bool):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """UPDATE customers SET
               email = ?, moemail_id = ?, moemail_address = ?, share_link = ?, is_moemail_auto = ?
               WHERE id = ?""",
            (moemail_address, moemail_id, moemail_address, share_link,
             1 if is_moemail_auto else 0, customer_id),
        )
        await db.commit()


# ── 系统设置 ──

async def get_settings() -> dict:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in rows}


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT INTO settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )
        await db.commit()
