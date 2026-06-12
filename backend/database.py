import aiosqlite
import os

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "giffgaff.db")


async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                activation_date TEXT NOT NULL,
                moemail_id TEXT,
                moemail_address TEXT,
                share_link TEXT,
                is_moemail_auto INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                cycle_number INTEGER NOT NULL,
                due_date TEXT NOT NULL,
                resend_email_id TEXT,
                sent INTEGER NOT NULL DEFAULT 0,
                sent_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.commit()