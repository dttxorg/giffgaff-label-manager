import base64
import datetime
import hashlib
import hmac
import json
import re
from typing import Any

import httpx


DEFAULT_ENDPOINT = "https://eco.taobao.com/router/rest"
DEFAULT_ORDER_CHANNEL = "OTHERS"
DEFAULT_GOODS_NAME = "giffgaff SIM"
DEFAULT_WEIGHT_GRAMS = 100
WAYBILL_METHOD = "cainiao.waybill.ii.get"


class CainiaoConfigError(ValueError):
    pass


def _text(value: Any) -> str:
    return str(value or "").strip()


def _required(settings: dict, key: str, label: str) -> str:
    value = _text(settings.get(key))
    if not value:
        raise CainiaoConfigError(f"菜鸟配置缺少：{label}")
    return value


def _top_sign(params: dict[str, Any], secret: str, sign_method: str = "md5") -> str:
    sign_params = {
        key: value
        for key, value in params.items()
        if key != "sign" and value is not None and str(value) != ""
    }
    raw = "".join(f"{key}{sign_params[key]}" for key in sorted(sign_params))
    if sign_method == "hmac-sha256":
        digest = hmac.new(secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")
    return hashlib.md5(f"{secret}{raw}{secret}".encode("utf-8")).hexdigest().upper()


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_int(value: Any, default: int) -> int:
    try:
        parsed = int(_text(value))
        return parsed if parsed > 0 else default
    except ValueError:
        return default


def _build_sender(settings: dict) -> dict[str, Any]:
    mobile = _text(settings.get("sender_mobile"))
    phone = _text(settings.get("sender_phone"))
    if not mobile and not phone:
        raise CainiaoConfigError("菜鸟配置缺少：发件人手机或固话")
    return {
        "name": _required(settings, "sender_name", "发件人姓名"),
        "mobile": mobile,
        "phone": phone,
        "address": {
            "province": _required(settings, "sender_province", "发件省份"),
            "city": _required(settings, "sender_city", "发件城市"),
            "district": _text(settings.get("sender_district")),
            "town": _text(settings.get("sender_town")),
            "detail": _required(settings, "sender_detail", "发件详细地址"),
        },
    }


PROVINCES = (
    "北京市", "天津市", "上海市", "重庆市",
    "河北省", "山西省", "辽宁省", "吉林省", "黑龙江省", "江苏省", "浙江省",
    "安徽省", "福建省", "江西省", "山东省", "河南省", "湖北省", "湖南省",
    "广东省", "海南省", "四川省", "贵州省", "云南省", "陕西省", "甘肃省",
    "青海省", "台湾省", "内蒙古自治区", "广西壮族自治区", "西藏自治区",
    "宁夏回族自治区", "新疆维吾尔自治区", "香港特别行政区", "澳门特别行政区",
)
MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}


def _find_province(text: str) -> str:
    for province in PROVINCES:
        if province in text:
            return province
    short_map = {
        "北京": "北京市",
        "天津": "天津市",
        "上海": "上海市",
        "重庆": "重庆市",
        "内蒙古": "内蒙古自治区",
        "广西": "广西壮族自治区",
        "西藏": "西藏自治区",
        "宁夏": "宁夏回族自治区",
        "新疆": "新疆维吾尔自治区",
        "香港": "香港特别行政区",
        "澳门": "澳门特别行政区",
    }
    for short, province in short_map.items():
        if short in text:
            return province
    for province in PROVINCES:
        short = province.removesuffix("省").removesuffix("市")
        if short and short in text:
            return province
    return ""


def _find_city(text: str, province: str) -> str:
    if province in MUNICIPALITIES:
        return province
    city_match = re.search(r"([\u4e00-\u9fa5]{2,12}(?:市|地区|自治州|盟))", text)
    if city_match:
        return city_match.group(1)
    return ""


def _find_district(text: str, province: str = "", city: str = "") -> str:
    if province:
        text = text.replace(province, "", 1)
    if city:
        text = text.replace(city, "", 1)
    district_match = re.search(r"([\u4e00-\u9fa5]{2,12}(?:区|县|市|旗))", text)
    return district_match.group(1) if district_match else ""


def parse_recipient_address(raw_address: str) -> dict[str, Any]:
    raw = _text(raw_address)
    if not raw:
        raise CainiaoConfigError("客户缺少收货地址")

    normalized = re.sub(r"[\n\r\t，,]+", " ", raw)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    mobile_match = re.search(r"1[3-9]\d{9}", normalized)
    phone_match = re.search(r"(?:\d{3,4}-?)?\d{7,8}", normalized)
    contact_match = mobile_match or phone_match
    if not contact_match:
        raise CainiaoConfigError("收货地址里没有识别到手机号，请按“姓名 手机号 省市区详细地址”录入")

    before_contact = normalized[:contact_match.start()].strip()
    after_contact = normalized[contact_match.end():].strip()
    name = before_contact.split()[-1] if before_contact else ""
    if not name:
        raise CainiaoConfigError("收货地址里没有识别到收件人姓名，请按“姓名 手机号 省市区详细地址”录入")

    detail = after_contact or normalized.replace(name, "", 1).replace(contact_match.group(0), "", 1).strip()
    province = _find_province(detail)
    if not province:
        raise CainiaoConfigError("收货地址里没有识别到省份，请补充完整省市区地址")
    city = _find_city(detail, province)
    district = _find_district(detail, province, city)

    contact_value = contact_match.group(0)
    is_mobile = bool(mobile_match and contact_match.start() == mobile_match.start())
    return {
        "name": name,
        "mobile": contact_value if is_mobile else "",
        "phone": "" if is_mobile else contact_value,
        "address": {
            "province": province,
            "city": city,
            "district": district,
            "town": "",
            "detail": detail,
        },
    }


def build_waybill_request(settings: dict, customer: dict) -> tuple[dict[str, Any], str]:
    cp_code = _required(settings, "cainiao_cp_code", "物流公司编码")
    template_url = _required(settings, "cainiao_template_url", "云打印模板 URL")
    user_id = _required(settings, "cainiao_user_id", "菜鸟使用者 ID")
    order_code = _text(customer.get("courier_order_code")) or f"GG{customer['id']}{datetime.datetime.now():%Y%m%d%H%M%S}"
    weight_grams = _parse_int(settings.get("cainiao_weight_grams"), DEFAULT_WEIGHT_GRAMS)
    goods_name = _text(settings.get("cainiao_goods_name")) or DEFAULT_GOODS_NAME

    payload = {
        "cp_code": cp_code,
        "sender": _build_sender(settings),
        "trade_order_info_dtos": [
            {
                "object_id": order_code,
                "order_info": {
                    "order_channels_type": _text(settings.get("cainiao_order_channel")) or DEFAULT_ORDER_CHANNEL,
                    "trade_order_list": [order_code],
                },
                "package_info": {
                    "id": "1",
                    "items": [{"name": goods_name, "count": 1}],
                    "weight": weight_grams,
                },
                "recipient": parse_recipient_address(_text(customer.get("shipping_address"))),
                "template_url": template_url,
                "user_id": user_id,
            }
        ],
    }
    return payload, order_code


def _find_first(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and item not in (None, ""):
                return item
        for item in value.values():
            found = _find_first(item, keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_first(item, keys)
            if found not in (None, ""):
                return found
    return None


def parse_waybill_response(data: dict[str, Any]) -> dict[str, Any]:
    if "error_response" in data:
        err = data["error_response"]
        message = err.get("sub_msg") or err.get("msg") or json.dumps(err, ensure_ascii=False)
        raise CainiaoConfigError(f"菜鸟接口返回错误：{message}")

    tracking_number = _find_first(data, {"waybill_code", "mail_no", "mailNo", "logistic_code"})
    print_data = _find_first(data, {"print_data", "printData"})
    if not tracking_number:
        raise CainiaoConfigError("菜鸟接口没有返回快递单号")
    return {
        "tracking_number": str(tracking_number),
        "courier_print_data": print_data if isinstance(print_data, str) else json.dumps(print_data, ensure_ascii=False) if print_data else "",
        "raw_response": data,
    }


async def create_waybill(settings: dict, customer: dict, dry_run: bool = False) -> dict[str, Any]:
    app_key = _required(settings, "cainiao_app_key", "菜鸟 AppKey")
    app_secret = _required(settings, "cainiao_app_secret", "菜鸟 AppSecret")
    session = _required(settings, "cainiao_session", "菜鸟授权 Session")
    endpoint = _text(settings.get("cainiao_endpoint")) or DEFAULT_ENDPOINT
    business_payload, order_code = build_waybill_request(settings, customer)
    payload_json = json.dumps(business_payload, ensure_ascii=False, separators=(",", ":"))

    params: dict[str, Any] = {
        "method": WAYBILL_METHOD,
        "app_key": app_key,
        "session": session,
        "timestamp": _timestamp(),
        "format": "json",
        "v": "2.0",
        "sign_method": "md5",
        "param_waybill_cloud_print_apply_new_request": payload_json,
    }
    params["sign"] = _top_sign(params, app_secret, params["sign_method"])

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "order_code": order_code,
            "request": business_payload,
        }

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(endpoint, data=params)
        response.raise_for_status()
        data = response.json()
    parsed = parse_waybill_response(data)
    return {
        "ok": True,
        "dry_run": False,
        "order_code": order_code,
        "request": business_payload,
        **parsed,
    }
