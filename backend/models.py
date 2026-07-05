from pydantic import BaseModel
from datetime import date
from typing import Any, Literal, Optional


ShippingStatus = Literal["未发货", "已发货", "已收货"]
ActivationStatus = Literal["未开始", "已分配激活码", "等待客户端领取", "激活中", "等待人工支付", "等待转 eSIM", "已完成", "失败"]
SimCodeStatus = Literal["未分配", "已分配", "激活中", "已使用", "失败", "作废"]


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
    use_sim_code: bool = True
    email_provider_id: Optional[int] = None  # None = pool round-robin
    email_provider_domain: Optional[str] = None  # explicit domain; None = provider default


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
    activation_status: Optional[ActivationStatus] = None
    activation_error: Optional[str] = None


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
    sim_code_id: Optional[int] = None
    sim_activation_code: Optional[str] = None
    esim_raw_code: Optional[str] = None
    activation_status: ActivationStatus = "未开始"
    activation_error: Optional[str] = None
    activated_at: Optional[str] = None
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
    sim_code_id: Optional[int] = None
    sim_activation_code: Optional[str] = None
    initial_password: Optional[str] = None
    esim_raw_code: Optional[str] = None
    activation_status: ActivationStatus = "未开始"
    activation_error: Optional[str] = None
    activated_at: Optional[str] = None


class SystemSettings(BaseModel):
    moemail_url: Optional[str] = None
    moemail_api_key: Optional[str] = None
    giffgaff_download_url: Optional[str] = None
    agent_api_token: Optional[str] = None
    agent_api_token_source: Optional[str] = None
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


class SimCodeImport(BaseModel):
    codes: Optional[list[str]] = None
    text: Optional[str] = None


class SimCodeUpdate(BaseModel):
    status: SimCodeStatus


class SimCodeOut(BaseModel):
    id: int
    code: str
    status: SimCodeStatus
    customer_id: Optional[int] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: str


class ActivationLogIn(BaseModel):
    level: str = "info"
    step: Optional[str] = None
    message: str


class ActivationStatusUpdate(BaseModel):
    status: ActivationStatus
    error: Optional[str] = None
    step: Optional[str] = None
    message: Optional[str] = None


class ActivationResultUpdate(BaseModel):
    phone_number: Optional[str] = None
    status: ActivationStatus = "等待转 eSIM"
    error: Optional[str] = None
    step: Optional[str] = None
    message: Optional[str] = None


class ActivationTaskOut(BaseModel):
    customer_id: int
    phone_number: Optional[str] = None
    email: str
    initial_password: str
    sim_activation_code: str
    activation_status: ActivationStatus
    activation_date: date
    moemail_id: Optional[str] = None
    moemail_address: Optional[str] = None
    share_link: Optional[str] = None
    shipping_address: Optional[str] = None


class VerificationCodeOut(BaseModel):
    found: bool
    code: Optional[str] = None
    email: str = ""
    message_id: Optional[str] = None
    subject: Optional[str] = None
    from_address: Optional[str] = None
    received_at: Optional[str] = None
    checked_count: int = 0
    detail: str = ""


class PaymentInfoEmailOut(BaseModel):
    found: bool = False
    updated_found: bool = False
    changed_found: bool = False
    updated_count: int = 0
    changed_count: int = 0
    email: str = ""
    checked_count: int = 0
    latest_updated_message_id: Optional[str] = None
    latest_updated_subject: Optional[str] = None
    latest_updated_received_at: Optional[str] = None
    latest_changed_message_id: Optional[str] = None
    latest_changed_subject: Optional[str] = None
    latest_changed_received_at: Optional[str] = None
    detail: str = ""


class DomainInfo(BaseModel):
    domains: list[str]


class LabelConfig(BaseModel):
    giffgaff_download_url: str
    templates: list[dict[str, Any]]


class EsimCodeUpdate(BaseModel):
    code: str = ""


class EmailProviderCreate(BaseModel):
    name: str
    provider_type: str  # 'moemail' | 'cloudmail'
    config: dict
    domains: list[str] = []
    default_domain: Optional[str] = None


class EmailProviderOut(BaseModel):
    id: int
    name: str
    provider_type: str
    config: dict
    domains: list[str] = []
    default_domain: Optional[str] = None
    last_used_at: Optional[str] = None
    last_error: Optional[str] = None
    last_error_at: Optional[str] = None
    last_jwt_acquired_at: Optional[str] = None
    created_at: str
    updated_at: str


class EmailProviderUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[dict] = None
    domains: Optional[list[str]] = None
    default_domain: Optional[str] = None


class ResetCustomerRequest(BaseModel):
    detach_sim_code: bool = True
    detach_email: bool = True
    reset_activation: bool = True


class EmailProviderDomainPick(BaseModel):
    domain: Optional[str] = None  # None -> use provider's default_domain
