"""激活码有效性验证：使用 Playwright 无头浏览器访问 giffgaff.com/activate。
若激活码有效，页面会跳转到填邮箱的下一步；否则显示错误。

Playwright 是软依赖：没装的话，调用方会拿到 result='skipped'，
UI 上显示「未验证（缺依赖）」。装法：
    pip install playwright
    playwright install chromium
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_playwright_module = None


def _try_import_playwright():
    """懒加载：第一次调用时才尝试 import，避免没装也能正常启动。"""
    global _playwright_module
    if _playwright_module is not None:
        return _playwright_module
    try:
        from playwright.async_api import async_playwright  # type: ignore
        _playwright_module = async_playwright
        return async_playwright
    except ImportError:
        return None


async def validate_activation_code(
    code: str,
    *,
    timeout_ms: int = 30000,
    page_url: str = "https://www.giffgaff.com/activate",
) -> Dict[str, Any]:
    """返回 dict：
        result: 'valid' | 'invalid' | 'error' | 'skipped'
        error: str | None
        final_url: str | None
        checked_at: ISO 时间戳
    """
    result: Dict[str, Any] = {
        "result": "error",
        "error": None,
        "final_url": None,
        "checked_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    async_playwright = _try_import_playwright()
    if async_playwright is None:
        result["result"] = "skipped"
        result["error"] = "Playwright 未安装（pip install playwright && playwright install chromium）"
        return result

    browser = None
    try:
        async with async_playwright() as p:
            # Linux 服务端 / 容器环境常见问题修复：
            #   --no-sandbox：容器里以 root 跑必须关 sandbox
            #   --disable-dev-shm-usage：默认 /dev/shm 只有 64MB，Chromium 会爆
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            # 全新 context：无 cookie、无 cache、无 storage，确保不带缓存
            context = await browser.new_context(
                ignore_https_errors=False,
                java_script_enabled=True,
            )
            # 屏蔽所有缓存相关请求头（让服务器返回最新内容）
            await context.set_extra_http_headers({
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
            })
            page = await context.new_page()
            page.set_default_timeout(timeout_ms)

            await page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)

            # 定位激活码输入框：尝试多种 selector
            code_input = await _find_first_visible(
                page,
                [
                    'input[name="code"]',
                    'input[name="activationCode"]',
                    'input[name="activation_code"]',
                    'input[name="activation-code"]',
                    'input[id="code"]',
                    'input[id="activationCode"]',
                    'input[type="text"]',
                    'input[autocomplete="off"][type="text"]',
                ],
            )
            if not code_input:
                result["error"] = "未找到激活码输入框（页面结构可能已变更）"
                return result

            await code_input.fill(code)

            # 定位提交按钮
            submit = await _find_first_visible(
                page,
                [
                    'button[type="submit"]',
                    'button:has-text("Continue")',
                    'button:has-text("Next")',
                    'button:has-text("Activate")',
                    'button:has-text("激活")',
                    'button:has-text("开始")',
                    'input[type="submit"]',
                ],
            )
            if not submit:
                result["error"] = "未找到提交按钮"
                return result

            await submit.click()

            # 等跳转或 DOM 变化（最多 15 秒）
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(1500)

            result["final_url"] = page.url
            content = await page.content()
            content_lower = content.lower()

            email_patterns = [
                r"input[^>]*type=[\"']email[\"']",
                r"name=[\"']email[\"']",
                r"name=[\"']emailAddress[\"']",
                r"your\s+email",
                r"email\s+address",
                r"enter\s+your\s+email",
                r"邮箱",
                r"电子?邮件",
            ]
            has_email_step = any(re.search(p, content, re.I) for p in email_patterns)

            invalid_patterns = [
                r"\binvalid\b",
                r"not\s+recogni[sz]ed",
                r"not\s+valid",
                r"couldn['\u2019]?t\s+find",
                r"please\s+check",
                r"无效",
                r"不存在",
                r"已使用",
                r"已被",
            ]
            has_invalid_msg = any(re.search(p, content, re.I) for p in invalid_patterns)

            if has_email_step and not has_invalid_msg:
                result["result"] = "valid"
            elif has_invalid_msg and not has_email_step:
                result["result"] = "invalid"
                result["error"] = "激活码无效或已被使用"
            else:
                # 兜底：根据 URL 判断
                if "email" in (page.url or "").lower():
                    result["result"] = "valid"
                else:
                    result["result"] = "error"
                    result["error"] = f"无法判断页面状态（最终 URL：{page.url[:200]}）"

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        logger.exception("Activation code validation failed")
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass

    return result


async def _find_first_visible(page, selectors):
    """从 selector 列表里找第一个可见的元素。"""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                # 等一下让元素稳定可见
                try:
                    await el.wait_for(state="visible", timeout=2000)
                except Exception:
                    pass
                if await el.is_visible():
                    return el
        except Exception:
            continue
    return None


async def save_validation_result(
    db_path: str,
    sim_code_id: int,
    validation: Dict[str, Any],
) -> None:
    """把验证结果落库。"""
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """UPDATE sim_codes
               SET last_validated_at = ?, last_validation_result = ?, last_validation_error = ?
               WHERE id = ?""",
            (
                validation.get("checked_at"),
                validation.get("result"),
                validation.get("error"),
                sim_code_id,
            ),
        )
        await db.commit()
