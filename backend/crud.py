import aiosqlite
from datetime import date
from models import CustomerCreate, CustomerUpdate
from database import DATABASE_PATH


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
        row = await db.execute_fetchone(
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
    fields = []
    values = []
    if data.phone_number is not None:
        fields.append("phone_number = ?")
        values.append(data.phone_number)
    if data.email is not None:
        fields.append("email = ?")
        values.append(data.email)
    if data.activation_date is not None:
        fields.append("activation_date = ?")
        values.append(data.activation_date.isoformat())
    if not fields:
        return True
    values.append(customer_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            f"UPDATE customers SET {', '.join(fields)} WHERE id = ?", values
        )
        await db.commit()
        return True


async def delete_customer(customer_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM reminders WHERE customer_id = ?", (customer_id,))
        await db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        await db.commit()
        return True


async def get_reminders(customer_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            """SELECT * FROM reminders
               WHERE customer_id = ? ORDER BY due_date ASC""",
            (customer_id,),
        )
        return [dict(r) for r in rows]


async def get_reminder_by_email_id(resend_email_id: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await db.execute_fetchone(
            "SELECT * FROM reminders WHERE resend_email_id = ?", (resend_email_id,)
        )
        return dict(row) if row else None


async def create_reminder(customer_id: int, cycle_number: int, due_date: date, resend_email_id: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO reminders (customer_id, cycle_number, due_date, resend_email_id, sent)
               VALUES (?, ?, ?, ?, 0)""",
            (customer_id, cycle_number, due_date.isoformat(), resend_email_id),
        )
        await db.commit()
        return cursor.lastrowid


async def mark_reminder_sent(reminder_id: int, sent_at: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE reminders SET sent = 1, sent_at = ? WHERE id = ?",
            (sent_at, reminder_id),
        )
        await db.commit()


async def get_pending_reminders():
    """返回所有未发送的提醒"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            """SELECT r.*, c.email, c.phone_number
               FROM reminders r
               JOIN customers c ON r.customer_id = c.id
               WHERE r.sent = 0 AND r.due_date <= date('now', '+3 days')
               ORDER BY r.due_date ASC"""
        )
        return [dict(r) for r in rows]