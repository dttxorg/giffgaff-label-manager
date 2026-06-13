import aiosqlite
from models import CustomerCreate, CustomerUpdate
from database import DATABASE_PATH


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


async def get_customer(customer_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await fetch_one(
            db,
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        )
        return dict(row) if row else None


async def create_customer(data: CustomerCreate):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO customers (phone_number, email, activation_date)
               VALUES (?, ?, ?)""",
            (data.phone_number, data.email, data.activation_date.isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def update_customer(customer_id: int, data: CustomerUpdate):
    fields, values = [], []
    if data.phone_number is not None:
        fields.append("phone_number = ?"); values.append(data.phone_number)
    if data.email is not None:
        fields.append("email = ?"); values.append(data.email)
    if data.activation_date is not None:
        fields.append("activation_date = ?"); values.append(data.activation_date.isoformat())
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
