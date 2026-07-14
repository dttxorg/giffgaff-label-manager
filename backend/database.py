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
                sim_code_id INTEGER,
                sim_activation_code TEXT,
                initial_password TEXT,
                email_provider_id INTEGER,
                email_account_id TEXT,
                email_provider_domain TEXT,
                public_token TEXT,
                public_version INTEGER NOT NULL DEFAULT 1,
                payment_changed_at TEXT,
                payment_updated_at TEXT,
                payment_last_checked_at TEXT,
                activation_status TEXT NOT NULL DEFAULT '未开始',
                activation_error TEXT,
                activated_at TEXT,
                automation_lock_owner TEXT,
                automation_locked_at TEXT,
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
        await _ensure_column(db, "customers", "sim_code_id", "INTEGER")
        await _ensure_column(db, "customers", "sim_activation_code", "TEXT")
        await _ensure_column(db, "customers", "initial_password", "TEXT")
        await _ensure_column(db, "customers", "esim_raw_code", "TEXT")
        await _ensure_column(db, "customers", "email_provider_id", "INTEGER")
        await _ensure_column(db, "customers", "email_account_id", "TEXT")
        await _ensure_column(db, "customers", "email_provider_domain", "TEXT")
        await _ensure_column(db, "customers", "public_token", "TEXT")
        await _ensure_column(
            db, "customers", "public_version", "INTEGER NOT NULL DEFAULT 1"
        )
        await _ensure_column(db, "customers", "payment_changed_at", "TEXT")
        await _ensure_column(db, "customers", "payment_updated_at", "TEXT")
        await _ensure_column(db, "customers", "payment_last_checked_at", "TEXT")
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_customers_public_token "
            "ON customers(public_token) WHERE public_token IS NOT NULL"
        )
        await _ensure_column(db, "customers", "activation_status", "TEXT NOT NULL DEFAULT '未开始'")
        await _ensure_column(db, "customers", "activation_error", "TEXT")
        await _ensure_column(db, "customers", "activated_at", "TEXT")
        await _ensure_column(db, "customers", "automation_lock_owner", "TEXT")
        await _ensure_column(db, "customers", "automation_locked_at", "TEXT")
        await _ensure_shipping_status_values(db)
        await _ensure_activation_status_values(db)
        await _ensure_nullable_phone_number(db)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sim_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT '未分配',
                customer_id INTEGER,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await _ensure_column(db, "sim_codes", "last_validated_at", "TEXT")
        await _ensure_column(db, "sim_codes", "last_validation_result", "TEXT")
        await _ensure_column(db, "sim_codes", "last_validation_error", "TEXT")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS activation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                step TEXT,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sim_codes_status ON sim_codes(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_activation_logs_customer ON activation_logs(customer_id, created_at)")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS email_providers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                provider_type TEXT NOT NULL,
                config_json TEXT NOT NULL,
                domains_json TEXT,
                default_domain TEXT,
                disabled INTEGER NOT NULL DEFAULT 0,
                last_used_at TEXT,
                last_error TEXT,
                last_error_at TEXT,
                last_jwt_token TEXT,
                last_jwt_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await _ensure_column(db, "email_providers", "domains_json", "TEXT")
        await _ensure_column(db, "email_providers", "default_domain", "TEXT")
        await _ensure_column(db, "email_providers", "disabled", "INTEGER NOT NULL DEFAULT 0")
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
            sim_code_id INTEGER,
            sim_activation_code TEXT,
            initial_password TEXT,
            public_token TEXT,
            public_version INTEGER NOT NULL DEFAULT 1,
            payment_changed_at TEXT,
            payment_updated_at TEXT,
            payment_last_checked_at TEXT,
            activation_status TEXT NOT NULL DEFAULT '未开始',
            activation_error TEXT,
            activated_at TEXT,
            automation_lock_owner TEXT,
            automation_locked_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    await db.execute("""
        INSERT INTO customers
            (id, phone_number, email, shipping_address, shipping_status, courier_company, tracking_number,
             courier_order_code, courier_print_data, activation_date, moemail_id, moemail_address, share_link,
             is_moemail_auto, sim_code_id, sim_activation_code, initial_password, public_token, activation_status,
             public_version,
             payment_changed_at, payment_updated_at, payment_last_checked_at,
             activation_error, activated_at, automation_lock_owner, automation_locked_at, created_at)
        SELECT id, phone_number, email, shipping_address, shipping_status, courier_company, tracking_number,
               courier_order_code, courier_print_data, activation_date, moemail_id, moemail_address, share_link,
               is_moemail_auto, sim_code_id, sim_activation_code, initial_password, public_token, activation_status,
               public_version,
               payment_changed_at, payment_updated_at, payment_last_checked_at,
               activation_error, activated_at, automation_lock_owner, automation_locked_at, created_at
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


async def _ensure_activation_status_values(db: aiosqlite.Connection):
    await db.execute("""
        UPDATE customers
        SET activation_status = '未开始'
        WHERE activation_status IS NULL
           OR activation_status = ''
           OR activation_status NOT IN (
               '未开始', '已分配激活码', '等待客户端领取', '激活中',
               '等待人工支付', '等待转 eSIM', '已完成', '失败'
           )
    """)
