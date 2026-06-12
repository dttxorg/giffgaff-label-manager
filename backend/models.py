from pydantic import BaseModel
from datetime import date
from typing import Optional


class CustomerCreate(BaseModel):
    phone_number: str
    email: str
    activation_date: date


class CustomerUpdate(BaseModel):
    phone_number: Optional[str] = None
    email: Optional[str] = None
    activation_date: Optional[date] = None


class CustomerOut(BaseModel):
    id: int
    phone_number: str
    email: str
    activation_date: date
    created_at: str


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