import aiosqlite
import os

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "giffgaff.db")


async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT UNIQUE,
                email TEXT NOT NULL,
                shipping_address TEXT,
                shipping_status TEXT NOT NULL DEFAULT '未发货',
                courier_company TEXT,
                tracking_number TEXT,
                courier_order_code TEXT,
                courier_print_data TEXT,
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
        await _ensure_column(db, "customers", "shipping_address", "TEXT")
        await _ensure_column(db, "customers", "shipping_status", "TEXT NOT NULL DEFAULT '未发货'")
        await _ensure_column(db, "customers", "courier_company", "TEXT")
        await _ensure_column(db, "customers", "tracking_number", "TEXT")
        await _ensure_column(db, "customers", "courier_order_code", "TEXT")
        await _ensure_column(db, "customers", "courier_print_data", "TEXT")
        await _ensure_shipping_status_values(db)
        await _ensure_nullable_phone_number(db)
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


async def _ensure_nullable_phone_number(db: aiosqlite.Connection):
    rows = await db.execute_fetchall("PRAGMA table_info(customers)")
    phone_column = next((row for row in rows if row[1] == "phone_number"), None)
    if not phone_column or phone_column[3] == 0:
        return

    await db.execute("ALTER TABLE customers RENAME TO customers_old")
    await db.execute("""
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT UNIQUE,
            email TEXT NOT NULL,
            shipping_address TEXT,
            shipping_status TEXT NOT NULL DEFAULT '未发货',
            courier_company TEXT,
            tracking_number TEXT,
            courier_order_code TEXT,
            courier_print_data TEXT,
            activation_date TEXT NOT NULL,
            moemail_id TEXT,
            moemail_address TEXT,
            share_link TEXT,
            is_moemail_auto INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    await db.execute("""
        INSERT INTO customers
            (id, phone_number, email, shipping_address, shipping_status, courier_company, tracking_number,
             courier_order_code, courier_print_data, activation_date, moemail_id, moemail_address, share_link,
             is_moemail_auto, created_at)
        SELECT id, phone_number, email, shipping_address, shipping_status, courier_company, tracking_number,
               courier_order_code, courier_print_data, activation_date, moemail_id, moemail_address, share_link,
               is_moemail_auto, created_at
        FROM customers_old
    """)
    await db.execute("DROP TABLE customers_old")


async def _ensure_shipping_status_values(db: aiosqlite.Connection):
    await db.execute("""
        UPDATE customers
        SET shipping_status = '未发货'
        WHERE shipping_status IS NULL
           OR shipping_status = ''
           OR shipping_status NOT IN ('未发货', '已发货', '已收货')
    """)
