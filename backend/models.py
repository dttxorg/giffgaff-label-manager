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
    courier_order_code: Optional[str] = None
    courier_print_data: Optional[str] = None
    activation_date: date


class CustomerUpdate(BaseModel):
    phone_number: Optional[str] = None
    email: Optional[str] = None
    shipping_address: Optional[str] = None
    shipping_status: Optional[ShippingStatus] = None
    courier_company: Optional[str] = None
    tracking_number: Optional[str] = None
    courier_order_code: Optional[str] = None
    courier_print_data: Optional[str] = None
    activation_date: Optional[date] = None


class CustomerOut(BaseModel):
    id: int
    phone_number: Optional[str]
    email: str
    shipping_address: Optional[str]
    shipping_status: ShippingStatus
    courier_company: Optional[str]
    tracking_number: Optional[str]
    courier_order_code: Optional[str]
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
    courier_order_code: Optional[str]
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
    cainiao_endpoint: Optional[str] = None
    cainiao_app_key: Optional[str] = None
    cainiao_app_secret: Optional[str] = None
    cainiao_session: Optional[str] = None
    cainiao_cp_code: Optional[str] = None
    cainiao_cp_name: Optional[str] = None
    cainiao_template_url: Optional[str] = None
    cainiao_user_id: Optional[str] = None
    cainiao_order_channel: Optional[str] = None
    cainiao_goods_name: Optional[str] = None
    cainiao_weight_grams: Optional[str] = None
    sender_name: Optional[str] = None
    sender_mobile: Optional[str] = None
    sender_phone: Optional[str] = None
    sender_province: Optional[str] = None
    sender_city: Optional[str] = None
    sender_district: Optional[str] = None
    sender_town: Optional[str] = None
    sender_detail: Optional[str] = None


class AuthLoginRequest(BaseModel):
    password: str


class MoEmailCreateRequest(BaseModel):
    domain: Optional[str] = None


class CainiaoWaybillRequest(BaseModel):
    dry_run: bool = False


class DomainInfo(BaseModel):
    domains: list[str]


class LabelConfig(BaseModel):
    giffgaff_download_url: str
    templates: list[dict[str, Any]]
