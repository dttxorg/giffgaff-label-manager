"""公开页面路由：扫码后展示的邮箱复制页。
路径前缀 /p/，不挂在 /api/* 下，自动绕过后台口令鉴权。
"""
import html
import os
import re
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from fastapi.responses import JSONResponse
import crud
from database import DATABASE_PATH

router = APIRouter()

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "public_card.html")
_template_cache: Optional[str] = None


def _load_template() -> str:
    global _template_cache
    if _template_cache is None:
        with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            _template_cache = f.read()
    return _template_cache


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


def _markdown_to_safe_html(text: str) -> str:
    """极简 Markdown 渲染：段落 / 行内 code / **加粗** / [text](url)。
    全部 HTML 实体先转义，再做白名单替换，避免 XSS。"""
    if not text or not text.strip():
        return '<p class="empty">（运营尚未填写提示内容）</p>'
    out = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = html.escape(raw_line)
        # 标题：## xxx / ### xxx → h3 / h4（不暴露 h1/h2，避免与页面主标题竞争）
        h_match = re.match(r"^(#{1,3})\s+(.+)$", raw_line)
        if h_match:
            level = min(len(h_match.group(1)) + 1, 6)  # #->h2, ##->h3, ###->h4
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
            # 非法 scheme：丢弃 URL，只保留 label 作为纯文本（防钓鱼）
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


def _render_card(email: Optional[str], hint_markdown: str) -> str:
    tpl = _load_template()
    safe_email = html.escape(email) if email else ""
    display = html.escape(email) if email else '<span class="empty">（暂未配置）</span>'
    hint_html = _markdown_to_safe_html(hint_markdown)
    return (
        tpl
        .replace("__EMAIL__", safe_email)
        .replace("__EMAIL_DISPLAY__", display)
        .replace("__HINT_HTML__", hint_html)
    )


@router.get("/p/{token}", response_class=HTMLResponse)
async def public_card_page(token: str):
    if not token or len(token) > 128:
        return HTMLResponse(
            _render_card(None, ""),
            status_code=404,
            headers=_security_headers(),
        )
    card = await crud.get_public_card(token)
    if not card:
        return HTMLResponse(
            _render_card(None, ""),
            status_code=404,
            headers=_security_headers(),
        )
    settings_rows = await crud.get_settings()
    hint_md = settings_rows.get("public_page_markdown", "") or ""
    headers = _security_headers()
    # 给 Worker / CDN 提供版本号，方便做版本化缓存（token 重新生成时自动失效）
    headers["X-Cache-Version"] = str(card["public_version"])
    return HTMLResponse(_render_card(card["email"], hint_md), headers=headers)


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
