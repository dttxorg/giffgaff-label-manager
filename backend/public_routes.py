"""公开页面路由：扫码后展示的邮箱复制页。
路径前缀 /p/，不挂在 /api/* 下，自动绕过后台口令鉴权。
"""
import html
import json
import os
import re
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

import crud
from database import DATABASE_PATH

router = APIRouter()

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "public_card.html")


def _load_template() -> str:
    # 不缓存：模板小（<10KB），且开发期间常改；测试也用同一个 main.app 实例，
    # 模块级缓存会一直返回第一次的版本。
    with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
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


# Markdown 里的 {var_name} 占位符。客户字段优先，没有的留空。
# 用户也可以在 system_settings.custom_public_vars 里定义全局变量（JSON 格式），
# 优先级低于客户字段（防止全局变量覆盖客户数据）。
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


def _markdown_to_safe_html(text: str) -> str:
    """极简 Markdown 渲染：段落 / 行内 code / **加粗** / ## 标题 / [text](url)。
    全部 HTML 实体先转义，再做白名单替换，避免 XSS。"""
    if not text or not text.strip():
        return '<p class="empty">（运营尚未填写提示内容）</p>'
    out = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = html.escape(raw_line)
        # 标题：## xxx / ### xxx → h3 / h4
        h_match = re.match(r"^(#{1,3})\s+(.+)$", raw_line)
        if h_match:
            level = min(len(h_match.group(1)) + 1, 6)
            content = html.escape(h_match.group(2))
            tag = f"h{level}"
            out.append(f"<{tag}>{content}</{tag}>")
            prev_empty = False
            continue
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", line)

        def _link_repl(m):
            label = m.group(1)
            url = m.group(2)
            if re.match(r"^(https?://|mailto:)", url):
                return (
                    f'<a href="{html.escape(url)}" target="_blank" '
                    f'rel="noopener noreferrer">{label}</a>'
                )
            return html.escape(label)

        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link_repl, line)
        if line.strip() == "":
            out.append("")
        else:
            out.append(f"<p>{line}</p>")
    # 合并连续空行
    merged = []
    prev_empty = False
    for item in out:
        is_empty = item == ""
        if is_empty and prev_empty:
            continue
        merged.append(item)
        prev_empty = is_empty
    body = "".join(p for p in merged if p)
    return body or '<p class="empty">（运营尚未填写提示内容）</p>'


def _build_substitution_vars(customer_row: dict) -> dict:
    """从客户行 + 系统设置里组装变量字典（供 markdown 替换用）。"""
    # 客户字段
    vars_ = {
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
    # 全局自定义变量（来自 system_settings.custom_public_vars，JSON 格式）
    # 优先级低于客户字段（不覆盖客户数据）
    import sqlite3 as _sqlite3
    from database import DATABASE_PATH as DB_PATH
    # 全局自定义变量（来自 system_settings.custom_public_vars，JSON 格式）
    # 优先级低于客户字段（不覆盖客户数据）
    try:
        with _sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'custom_public_vars'"
            ).fetchone()
        custom_raw = row[0] if row and row[0] else ""
        if custom_raw.strip():
            parsed = json.loads(custom_raw)
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    if k not in vars_ or not vars_[k]:
                        vars_[k] = str(v) if v is not None else ""
    except Exception:
        pass
    return vars_


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
            f'<span class="contact-label">📱 手机</span>'
            f'<code id="phone" data-phone="{html.escape(phone)}" class="contact-val">{html.escape(phone)}</code>'
            f'<button class="copy-btn" type="button" '
            f'onclick="copyFromEl(\'phone\', \'已复制手机号\')" id="phone-copy-btn">复制</button>'
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


@router.get("/p/{token}", response_class=HTMLResponse)
async def public_card_page(token: str):
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
    # 读取设置 + 组装变量
    settings_rows = await crud.get_settings()
    hint_md = settings_rows.get("public_page_markdown", "") or ""
    vars_ = _build_substitution_vars(card)
    headers = _security_headers()
    headers["X-Cache-Version"] = str(card["public_version"])
    return HTMLResponse(_render_card(card["email"], hint_md, vars_), headers=headers)


@router.get("/api/public/{token}/version")
async def public_token_version(token: str):
    """返回 {public_version} 或 404。供 Worker 做版本化缓存 key，避免重新生成后
    旧 URL 的 HTML 仍被缓存命中。完全不返回 email 等敏感字段。"""
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
