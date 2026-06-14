from pydantic import BaseModel
from datetime import date
from typing import Any, Literal, Optional


ShippingStatus = Literal["未发货", "已发货", "已收货"]


class CustomerCreate(BaseModel):
    phone_number: Optional[str] = None
    email: str = ""
    shipping_address: Optional[str] = None
    shipping_status: ShippingStatus = "未发货"
    courier_company: Optional[str] = None
    tracking_number: Optional[str] = None
    activation_date: date


class CustomerUpdate(BaseModel):
    phone_number: Optional[str] = None
    email: Optional[str] = None
    shipping_address: Optional[str] = None
    shipping_status: Optional[ShippingStatus] = None
    courier_company: Optional[str] = None
    tracking_number: Optional[str] = None
    activation_date: Optional[date] = None


class CustomerOut(BaseModel):
    id: int
    phone_number: Optional[str]
    email: str
    shipping_address: Optional[str]
    shipping_status: ShippingStatus
    courier_company: Optional[str]
    tracking_number: Optional[str]
    activation_date: date
    moemail_id: Optional[str]
    moemail_address: Optional[str]
    share_link: Optional[str]
    is_moemail_auto: bool
    created_at: str


class CustomerDetail(BaseModel):
    id: int
    phone_number: Optional[str]
    email: str
    shipping_address: Optional[str]
    shipping_status: ShippingStatus
    courier_company: Optional[str]
    tracking_number: Optional[str]
    activation_date: date
    created_at: str
    moemail_id: Optional[str]
    moemail_address: Optional[str]
    share_link: Optional[str]
    is_moemail_auto: bool


class SystemSettings(BaseModel):
    moemail_url: Optional[str] = None
    moemail_api_key: Optional[str] = None
    giffgaff_download_url: Optional[str] = None


class AuthLoginRequest(BaseModel):
    password: str


class MoEmailCreateRequest(BaseModel):
    domain: Optional[str] = None


class DomainInfo(BaseModel):
    domains: list[str]


class LabelConfig(BaseModel):
    giffgaff_download_url: str
    templates: list[dict[str, Any]]
