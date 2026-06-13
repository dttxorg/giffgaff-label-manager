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
        await _ensure_column(db, "customers", "moemail_id", "TEXT")
        await _ensure_column(db, "customers", "moemail_address", "TEXT")
        await _ensure_column(db, "customers", "share_link", "TEXT")
        await _ensure_column(db, "customers", "is_moemail_auto", "INTEGER NOT NULL DEFAULT 0")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.commit()


async def _ensure_column(db: aiosqlite.Connection, table: str, column: str, definition: str):
    rows = await db.execute_fetchall(f"PRAGMA table_info({table})")
    existing_columns = {row[1] for row in rows}
    if column not in existing_columns:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
