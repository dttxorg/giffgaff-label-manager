"""公开页面路由：扫码后展示已激活号码资料或未激活卡教程。
路径前缀 /p/，不挂在 /api/* 下，自动绕过后台口令鉴权。
"""
import html
import os
import re
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

import crud

router = APIRouter()

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "public_card.html")
_ACTIVATION_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "templates", "activation_card.html"
)
ACTIVATION_GUIDE_PUBLIC_TOKEN = "activation-guide-public-page"
DEFAULT_ACTIVATION_TUTORIAL_URL = "https://gg.681218.xyz/activation.html"

# 扫码页运营内容固定在代码中，避免后台自由排版导致视觉失控。
ACTIVATION_PAGE_CONTENT = """# 📱 giffgaff 英国电话卡使用说明

:::tip giffgaff 套餐充值服务
无需海外支付方式，支持 **giffgaff 账户代充值**。
续费套餐、充值余额都可以联系客服办理。
:::

:::promo AI 服务推荐
本站同时提供 **ChatGPT Plus / Pro 订阅服务**。
✨ ChatGPT Plus　⚡ ChatGPT 5x Pro　🔥 ChatGPT 20x Pro
适用于学习、办公、编程和 AI 创作，如需服务可联系客服咨询。
:::

---

## ⚠️ 插卡前重要提醒

如果您准备将 giffgaff 作为手机主卡使用，请在插卡前关闭手机的 **短信增强功能**，避免手机自动发送验证短信，导致异常扣费或影响号码使用。

## 🍎 iPhone 用户

请关闭 **iMessage**：

1. 设置 → 信息 → iMessage → 关闭
2. 设置 → 信息 → RCS 信息 → 关闭（如有）

避免手机自动进行号码验证或启用增强通信服务。

## 🤖 安卓手机用户

不同品牌名称可能不同，请关闭以下短信增强功能：

- 智能短信 / 增强短信
- RCS 聊天 / 聊天功能
- 高级短信 / 富媒体消息

常见路径：**短信 App → 设置 → 聊天功能 / RCS → 关闭**

> 华为、小米、OPPO、vivo、三星等手机的设置名称可能有所不同。

---

## 🌐 官方网站

[访问 giffgaff 官方网站](https://www.giffgaff.com)

:::warning 请认准官方地址
请避免进入非官方网站，不要向陌生人提供验证码或账户密码。
:::

## 💬 售后咨询

如遇到以下问题，请联系卡片上的客服微信：

- 无网络
- 套餐问题
- 账户问题
- 使用疑问

:::warning 售后渠道提醒
请勿在京东咨询海外卡激活、网络配置等问题。京东客服无法处理 giffgaff 海外账户相关服务。
:::

## ⭐ 售后福利

1. 完成使用后给出五星好评 ⭐⭐⭐⭐⭐
2. 截图发送客服
3. 免费领取 **号码保号提醒服务**

帮助您定期维护号码状态，避免因长期闲置导致号码失效。

:::info 一站式全球数字服务
📱 giffgaff 英国电话卡
💳 giffgaff 套餐充值服务
🤖 ChatGPT AI 订阅服务
感谢支持 ❤️
:::
"""

ACTIVATED_PAGE_CONTENT = """# 📱 giffgaff 已激活号码使用说明

:::tip giffgaff 套餐充值服务
无需海外支付方式，可联系客服办理 **套餐续费、余额充值和账户代充值**。
:::

:::promo AI 服务推荐
本站提供 **ChatGPT Plus / Pro 订阅服务**，适用于学习、办公、编程、写作和图片创作。
✨ ChatGPT Plus　⚡ ChatGPT 5x Pro　🔥 ChatGPT 20x Pro
如需 AI 服务，可联系客服咨询。
:::

---

## 🌐 官方网站

[访问 giffgaff 官方网站](https://www.giffgaff.com)

:::warning 请认准官方地址
请避免进入非官方网站，不要向陌生人提供验证码或账户密码。
:::

## 🔐 账号登录信息

- **账号：您的 giffgaff 手机号码**
- **密码：注册邮箱密码**

登录官网后即可：

- 查看余额
- 充值套餐
- 修改邮箱绑定
- 修改账户密码

## 💬 售后咨询

如遇到激活、网络设置或账户使用问题，请联系卡片上的客服微信。

:::warning 售后渠道提醒
请勿在京东咨询海外卡激活、网络配置等问题。京东客服无法处理 giffgaff 海外账户相关服务。
:::

## ⭐ 售后福利

1. 完成使用后给出五星好评 ⭐⭐⭐⭐⭐
2. 截图发送客服
3. 免费领取 **号码保号提醒服务**

帮助您定期维护号码状态，避免因长期闲置导致号码失效。

---

## 🤖 ChatGPT 订阅服务

### ⭐ ChatGPT Plus

- 学习辅助
- 办公提效
- AI 写作
- 图片创作

### ⚡ 5x Pro

- 更复杂任务处理
- 编程辅助
- 高频内容创作

### 🔥 20x Pro

- 长时间使用
- 专业创作
- 高强度任务

:::info 一站式全球数字服务
📱 giffgaff 英国电话卡
💳 giffgaff 套餐充值服务
🤖 ChatGPT AI 服务
感谢支持 ❤️
:::
"""


def _load_template() -> str:
    # 不缓存：模板小（<10KB），且开发期间常改；测试也用同一个 main.app 实例，
    # 模块级缓存会一直返回第一次的版本。
    with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _load_activation_template() -> str:
    with open(_ACTIVATION_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _security_headers() -> dict:
    return {
        "Cache-Control": "no-store, max-age=0",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": (
            "default-src 'none'; "
            "style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; "
            "img-src data:; "
            "form-action 'none'; "
            "base-uri 'none'; "
            "frame-ancestors 'none'"
        ),
    }


# Markdown 里的 {var_name} 占位符，没有的留空。
def _substitute_variables(text: str, vars: dict) -> str:
    if not text or "{" not in text:
        return text
    def _repl(m):
        key = m.group(1).strip()
        if key not in vars:
            return ""  # 未知变量留空（不显示 {xxx}）
        v = vars[key]
        return str(v) if v is not None else ""
    return re.sub(r"\{([a-zA-Z0-9_]+)\}", _repl, text)


def _markdown_inline(text: str) -> str:
    """安全渲染行内 Markdown；输入中的原始 HTML 永远先实体化。"""
    line = html.escape(text)
    line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
    line = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", line)

    def _link_repl(match):
        label = match.group(1)
        url = html.unescape(match.group(2)).strip()
        if re.match(r"^(https?://|mailto:)", url, re.I):
            return (
                f'<a href="{html.escape(url, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer">{label}</a>'
            )
        return label

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link_repl, line)


def _markdown_to_safe_html(text: str) -> str:
    """安全的富文本子集：标题、列表、引用、分隔线、链接与四种内容卡片。

    内容卡片语法：`:::tip 标题` / `:::warning` / `:::promo` / `:::info`，
    以单独一行的 `:::` 结束。所有原始 HTML 都会被转义。
    """
    if not text or not text.strip():
        return '<div class="empty"><strong>内容正在整理</strong><span>请先保存上方资料，稍后再回来看看。</span></div>'

    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    callout_labels = {
        "tip": "重点",
        "warning": "注意",
        "promo": "推荐",
        "info": "说明",
    }
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        stripped = raw_line.strip()
        if not stripped:
            index += 1
            continue

        callout_match = re.match(r"^:::(tip|warning|promo|info)(?:\s+(.+))?$", stripped, re.I)
        if callout_match:
            kind = callout_match.group(1).lower()
            title = callout_match.group(2) or callout_labels[kind]
            index += 1
            content_lines = []
            while index < len(lines) and lines[index].strip() != ":::":
                if lines[index].strip():
                    content_lines.append(_markdown_inline(lines[index].strip()))
                index += 1
            if index < len(lines):
                index += 1
            content = "<br>".join(content_lines)
            out.append(
                f'<aside class="callout callout-{kind}">'
                f'<span class="callout-label">{_markdown_inline(title)}</span>'
                f'<div class="callout-body">{content}</div>'
                f'</aside>'
            )
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", raw_line)
        if heading:
            level = min(len(heading.group(1)) + 1, 4)
            out.append(f"<h{level}>{_markdown_inline(heading.group(2))}</h{level}>")
            index += 1
            continue

        if re.fullmatch(r"\s*([-*_])(?:\s*\1){2,}\s*", raw_line):
            out.append('<hr class="content-rule">')
            index += 1
            continue

        quote = re.match(r"^>\s*(.+)$", raw_line)
        if quote:
            out.append(f"<blockquote>{_markdown_inline(quote.group(1))}</blockquote>")
            index += 1
            continue

        unordered = re.match(r"^\s*[-*]\s+(.+)$", raw_line)
        if unordered:
            items = []
            while index < len(lines):
                item = re.match(r"^\s*[-*]\s+(.+)$", lines[index])
                if not item:
                    break
                items.append(f"<li>{_markdown_inline(item.group(1))}</li>")
                index += 1
            out.append(f'<ul class="content-list">{"".join(items)}</ul>')
            continue

        ordered = re.match(r"^\s*\d+[.)]\s+(.+)$", raw_line)
        if ordered:
            items = []
            while index < len(lines):
                item = re.match(r"^\s*\d+[.)]\s+(.+)$", lines[index])
                if not item:
                    break
                items.append(f"<li>{_markdown_inline(item.group(1))}</li>")
                index += 1
            out.append(f'<ol class="content-list content-steps">{"".join(items)}</ol>')
            continue

        out.append(f"<p>{_markdown_inline(raw_line)}</p>")
        index += 1

    return "".join(out)


def _build_substitution_vars(customer_row: dict) -> dict:
    """从客户行组装公开页显示所需字段。"""
    return {
        "phone_number": customer_row.get("phone_number") or "",
        "email": customer_row.get("email") or "",
        "moemail_address": customer_row.get("moemail_address") or "",
        "first_name": customer_row.get("first_name") or "",
        "last_name": customer_row.get("last_name") or "",
        "full_name": (
            f"{customer_row.get('last_name') or ''} "
            f"{customer_row.get('first_name') or ''}"
        ).strip(),
        "address": customer_row.get("address") or "",
        "city": customer_row.get("city") or "",
        "postcode": customer_row.get("postcode") or "",
        "full_address": ", ".join(
            filter(None, [
                customer_row.get("address") or "",
                customer_row.get("city") or "",
                customer_row.get("postcode") or "",
            ])
        ),
        "sim_activation_code": customer_row.get("sim_activation_code") or "",
        "initial_password": customer_row.get("initial_password") or "",
        "share_link": customer_row.get("share_link") or "",
        "activation_date": customer_row.get("activation_date") or "",
        "phone_status": customer_row.get("phone_status") or "激活",
        "shipping_address": customer_row.get("shipping_address") or "",
    }


def _render_card(email: Optional[str], hint_markdown: str, vars_: dict) -> str:
    tpl = _load_template()
    phone = (vars_ or {}).get("phone_number") or ""
    safe_email = html.escape(email) if email else ""
    if email:
        display = html.escape(email)
    else:
        display = '<span class="empty">（暂未配置）</span>'
    # 1) 变量替换（先于 markdown 渲染）
    hint_md = _substitute_variables(hint_markdown, vars_)
    # 2) markdown → html
    hint_html = _markdown_to_safe_html(hint_md)
    # 3) 手机号：有值才显示整行（替换时已经做了安全转义）
    if phone:
        phone_row = (
            f'<div class="contact-row" id="phone-row">'
            f'<span class="contact-label">giffgaff 手机号码</span>'
            f'<code id="phone" data-phone="{html.escape(phone)}" class="contact-val">{html.escape(phone)}</code>'
            f'<button class="copy-btn" type="button" '
            f'onclick="copyFromEl(\'phone\', \'已复制手机号码\')" id="phone-copy-btn">复制</button>'
            f'</div>'
        )
    else:
        phone_row = ''  # 模板里默认 hidden，赋空字符串让占位符消失
    return (
        tpl
        .replace("__EMAIL__", safe_email)
        .replace("__EMAIL_DISPLAY__", display)
        .replace("__PHONE_ROW__", phone_row)
        .replace("__HINT_HTML__", hint_html)
    )


def _render_activation_card(tutorial_url: str, hint_markdown: str) -> str:
    safe_url = html.escape(tutorial_url)
    hint_md = _substitute_variables(
        hint_markdown,
        {"activation_tutorial_url": tutorial_url},
    )
    hint_html = _markdown_to_safe_html(hint_md)
    return (
        _load_activation_template()
        .replace("__TUTORIAL_URL__", safe_url)
        .replace("__TUTORIAL_URL_DISPLAY__", safe_url)
        .replace("__HINT_HTML__", hint_html)
    )


@router.get("/p/{token}", response_class=HTMLResponse)
async def public_card_page(token: str):
    if token == ACTIVATION_GUIDE_PUBLIC_TOKEN:
        settings = await crud.get_settings()
        tutorial_url = (
            settings.get("activation_tutorial_url") or DEFAULT_ACTIVATION_TUTORIAL_URL
        )
        hint_md = ACTIVATION_PAGE_CONTENT
        try:
            version = max(1, int(settings.get("activation_page_version") or 1))
        except (TypeError, ValueError):
            version = 1
        headers = _security_headers()
        headers["X-Cache-Version"] = str(version)
        return HTMLResponse(
            _render_activation_card(tutorial_url, hint_md),
            headers=headers,
        )
    if not token or len(token) > 128:
        return HTMLResponse(
            _render_card(None, "", {}),
            status_code=404,
            headers=_security_headers(),
        )
    card = await crud.get_public_card(token)
    if not card:
        return HTMLResponse(
            _render_card(None, "", {}),
            status_code=404,
            headers=_security_headers(),
        )
    # 号码与初始邮箱来自客户记录；下方运营说明固定在代码中。
    hint_md = ACTIVATED_PAGE_CONTENT
    vars_ = _build_substitution_vars(card)
    headers = _security_headers()
    headers["X-Cache-Version"] = str(card["public_version"])
    return HTMLResponse(_render_card(card["email"], hint_md, vars_), headers=headers)


@router.get("/api/public/{token}/version")
async def public_token_version(token: str):
    """返回 {public_version} 或 404。供 Worker 做版本化缓存 key，避免重新生成后
    旧 URL 的 HTML 仍被缓存命中。完全不返回 email 等敏感字段。"""
    if token == ACTIVATION_GUIDE_PUBLIC_TOKEN:
        settings = await crud.get_settings()
        try:
            version = max(1, int(settings.get("activation_page_version") or 1))
        except (TypeError, ValueError):
            version = 1
    else:
        version = await crud.get_public_version(token)
    if version is None:
        return JSONResponse({"detail": "invalid"}, status_code=404)
    return JSONResponse(
        {"public_version": version},
        headers={
            "Cache-Control": "no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
        },
    )
