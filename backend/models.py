from pydantic import BaseModel
from datetime import date
from typing import Optional


class CustomerCreate(BaseModel):
    phone_number: str
    email: str
    activation_date: date
    auto_moemail: bool = False  # True = 自动生成 MoEmail 邮箱
    moemail_domain: Optional[str] = None  # 可选指定域名，不填则用第一个


class CustomerUpdate(BaseModel):
    phone_number: Optional[str] = None
    email: Optional[str] = None
    activation_date: Optional[date] = None


class CustomerOut(BaseModel):
    id: int
    phone_number: str
    email: str
    activation_date: date
    moemail_id: Optional[str]
    moemail_address: Optional[str]
    share_link: Optional[str]
    is_moemail_auto: bool
    created_at: str


class SystemSettings(BaseModel):
    moemail_url: Optional[str] = None
    moemail_api_key: Optional[str] = None
    resend_api_key: Optional[str] = None
    from_email: Optional[str] = None


class QuickSendRequest(BaseModel):
    to_address: str
    subject: str
    content: str  # HTML 内容


class DomainInfo(BaseModel):
    domains: list[str]


class ReminderOut(BaseModel):
    id: int
    customer_id: int
    cycle_number: int
    due_date: date
    resend_email_id: Optional[str]
    sent: bool
    sent_at: Optional[str]


class CustomerDetail(BaseModel):
    id: int
    phone_number: str
    email: str
    activation_date: date
    created_at: str
    reminders: list[ReminderOut]
    moemail_id: Optional[str]
    moemail_address: Optional[str]
    share_link: Optional[str]
    is_moemail_auto: bool