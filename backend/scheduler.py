import os
import asyncio
import aiosqlite
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

DAYS_PER_CYCLE = 170
MAX_CYCLES = 43  # ~20 years

DB_PATH = os.path.join(os.path.dirname(__file__), "giffgaff.db")


def calculate_cycles(activation_date: date):
    """返回从开通日起往后推 MAX_CYCLES 个 170 天到期日列表"""
    cycles = []
    for i in range(1, MAX_CYCLES + 1):
        due = activation_date + timedelta(days=DAYS_PER_CYCLE * i)
        cycles.append(due)
    return cycles


def build_email_subject(phone_number: str, due_date: date, cycle: int):
    return f"【giffgaff 续费提醒】您的卡 {phone_number} 第 {cycle} 次到期提醒"


def build_email_html(phone_number: str, email: str, activation_date: date,
                     due_date: date, cycle: int, share_link: str = ""):
    days_until = (due_date - date.today()).days
    share_section = f"""
  <p style="margin-top:20px;">📬 MoEmail 收件箱：<a href="{share_link}" style="color:#5f4b8b;">{share_link}</a></p>
""" if share_link else ""

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 40px auto; padding: 20px;">
  <h2 style="color:#5f4b8b;">🌟 giffgaff 卡到期提醒</h2>
  <p>您好，</p>
  <p>您的 <strong>giffgaff SIM 卡</strong>（手机号：<strong>{phone_number}</strong>）有以下到期安排：</p>
  <table style="border-collapse: collapse; width: 100%; margin: 20px 0;">
    <tr style="background:#5f4b8b; color:white;">
      <th style="padding:10px; text-align:left;">项目</th>
      <th style="padding:10px; text-align:left;">详情</th>
    </tr>
    <tr style="background:#f5f3ff;">
      <td style="padding:10px;">开通日期</td>
      <td style="padding:10px;">{activation_date.isoformat()}</td>
    </tr>
    <tr style="background:#fff;">
      <td style="padding:10px;">第 N 次到期</td>
      <td style="padding:10px;">第 {cycle} 次（共 {MAX_CYCLES} 次）</td>
    </tr>
    <tr style="background:#f5f3ff;">
      <td style="padding:10px;">到期日期</td>
      <td style="padding:10px; font-weight:bold; color:#d32f2f;">{due_date.isoformat()}</td>
    </tr>
    <tr style="background:#fff;">
      <td style="padding:10px;">剩余天数</td>
      <td style="padding:10px;">{'还有 ' + str(days_until) + ' 天' if days_until > 0 else '已到期，请尽快续费！'}</td>
    </tr>
  </table>
  {share_section}
  <p style="color:#666; font-size:13px;">此邮件由系统自动发送，共 {MAX_CYCLES} 次到期提醒。</p>
  <p style="color:#888; font-size:12px;">发送至：{email}</p>
</body>
</html>
"""


async def create_reminders_for_customer(customer_id: int, phone_number: str, email: str,
                                       activation_date: date):
    """在数据库中创建所有 43 个提醒记录（不立即发送）"""
    cycles = calculate_cycles(activation_date)
    async with aiosqlite.connect(DB_PATH) as db:
        for i, due_date in enumerate(cycles, start=1):
            await db.execute(
                """INSERT INTO reminders (customer_id, cycle_number, due_date, sent)
                   VALUES (?, ?, ?, 0)""",
                (customer_id, i, due_date.isoformat()),
            )
        await db.commit()


async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await db.execute_fetchone(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        return row["value"] if row else default


async def check_and_send_due_reminders():
    """
    每天运行：查所有 due_date <= 今天 AND sent=0 的记录，立即发送并标记。
    通过 MoEmail 的 Resend 集成发送（fromAddress 使用客户的 MoEmail 邮箱）。
    """
    moemail_url = await get_setting("moemail_url")
    moemail_key = await get_setting("moemail_api_key")
    if not moemail_url or not moemail_key:
        print("[WARN] MoEmail 未配置，跳过发送")
        return

    from moemail import MoEmailClient
    client = MoEmailClient(moemail_url, moemail_key)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            """SELECT r.id, r.customer_id, r.cycle_number, r.due_date,
                      c.phone_number, c.email, c.activation_date, c.share_link,
                      c.moemail_address
               FROM reminders r
               JOIN customers c ON r.customer_id = c.id
               WHERE r.sent = 0 AND r.due_date <= date('now')
               ORDER BY r.due_date ASC"""
        )

    sent_count = 0
    for row in rows:
        if not row["moemail_address"]:
            print(f"[SKIP] {row['phone_number']} 无 MoEmail 邮箱，跳过")
            continue
        try:
            due_date = date.fromisoformat(row["due_date"])
            subject = build_email_subject(row["phone_number"], due_date, row["cycle_number"])
            html = build_email_html(
                row["phone_number"], row["email"],
                date.fromisoformat(row["activation_date"]),
                due_date, row["cycle_number"],
                row.get("share_link") or ""
            )
            r = client.send_email(
                email_id=row["moemail_address"],
                to_address=row["email"],
                subject=subject,
                html=html,
            )
            email_id = r.get("id", "unknown")

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE reminders SET sent = 1, sent_at = ?, resend_email_id = ? WHERE id = ?",
                    (datetime.now().isoformat(), email_id, row["id"])
                )
                await db.commit()

            print(f"[SENT] {row['phone_number']} 第{row['cycle_number']}次 {row['due_date']} → {row['email']}")
            sent_count += 1

        except Exception as e:
            print(f"[ERROR] Failed to send reminder {row['id']}: {e}")

    print(f"[DONE] 今日共发送 {sent_count} 封邮件")


if __name__ == "__main__":
    asyncio.run(check_and_send_due_reminders())