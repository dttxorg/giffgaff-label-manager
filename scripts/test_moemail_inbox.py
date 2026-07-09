"""Live E2E smoke-test for the beilunyang/moemail inbox path the desktop
client uses to read verification codes.

Run this script on the VPS (or anywhere with network access to
https://681218.xyz) with the real MoEmail API key in MOEMAIL_API_KEY.
It will:

  1. POST /api/emails/generate to provision a fresh inbox.
  2. Wait up to N seconds for the user to send a test email
     (instructions printed to stderr).
  3. GET /api/emails/{id} to list the messages.
  4. GET /api/emails/{id}/{messageId} for the first message.
  5. Run _extract_verification_code on the body.
  6. Print the result.

This is the same code path `main.py:get_customer_verification_code`
takes after a customer is bound to a moemail provider — so a green
run here means the production flow works.

Usage:
  MOEMAIL_API_KEY=<your-key> \
  MOEMAIL_BASE_URL=https://681218.xyz \
  python scripts/test_moemail_inbox.py

Optional env vars:
  MOEMAIL_BASE_URL   default https://681218.xyz
  MOEMAIL_API_KEY    no default (required)
  MOEMAIL_DOMAIN     default the first domain from GET /api/config
  POLL_TIMEOUT_S     default 60
  POLL_INTERVAL_S    default 3

The script does NOT clean up the generated email (it lives for the
provider's expiry window, default 永久 = year 9999). Delete it from
the MoEmail admin UI when done.
"""
from __future__ import annotations

import json
import os
import sys
import time
import re
from typing import Any

import httpx

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)


VERIFICATION_CODE_RE = re.compile(r"\b\d{6}\b")


def _first_text(data: dict, *keys: str) -> str:
    for key in keys:
        v = data.get(key)
        if v is not None:
            return str(v)
    return ""


def _plain_text_from_html(value: str) -> str:
    import html
    import re as _re
    text = html.unescape(value or "")
    text = _re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = _re.sub(r"(?s)<br\s*/?>", "\n", text)
    text = _re.sub(r"(?s)</p\s*>", "\n", text)
    text = _re.sub(r"(?s)<[^>]+>", " ", text)
    return _re.sub(r"[ \t]+", " ", text)


def extract_verification_code(message: dict) -> str | None:
    """Same logic as backend.main._extract_verification_code."""
    subject = _first_text(message, "subject")
    content = _first_text(message, "content", "text", "body", "plainText", "plain_text")
    html_content = _plain_text_from_html(_first_text(message, "html", "htmlContent", "html_content"))
    text = "\n".join(part for part in (subject, content, html_content) if part)
    if not text:
        return None
    m = VERIFICATION_CODE_RE.search(text)
    return m.group(0) if m else None


def main() -> int:
    base_url = os.environ.get("MOEMAIL_BASE_URL", "https://681218.xyz").rstrip("/")
    api_key = os.environ.get("MOEMAIL_API_KEY", "")
    if not api_key:
        print("ERROR: set MOEMAIL_API_KEY in the environment.", file=sys.stderr)
        return 2
    poll_timeout = int(os.environ.get("POLL_TIMEOUT_S", "60"))
    poll_interval = float(os.environ.get("POLL_INTERVAL_S", "3"))
    domain_override = os.environ.get("MOEMAIL_DOMAIN") or None

    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    with httpx.Client(base_url=base_url, headers=headers, timeout=15) as client:
        # 1) pick a domain (server-recommended)
        if not domain_override:
            cfg = client.get("/api/config").json()
            domain_override = (cfg.get("emailDomains") or "").split(",")[0].strip()
        if not domain_override:
            print("ERROR: no domain available on the server; set MOEMAIL_DOMAIN", file=sys.stderr)
            return 2
        # 2) generate email
        import secrets
        local_part = "probeverify" + secrets.token_hex(2)  # 8 hex chars
        # (intentionally NOT using our generate_email_name so we can
        # independently verify the moemail-server whitelist accepts the value
        # 0; we set expiryTime: 0 = 永久)
        body = {"name": local_part, "expiryTime": 0, "domain": domain_override}
        r = client.post("/api/emails/generate", json=body)
        r.raise_for_status()
        account = r.json()
        email = account.get("email") or f"{local_part}@{domain_override}"
        account_id = account.get("id")
        print(f"[ok] generated email: {email}  (id={account_id})", file=sys.stderr)
        print(f"\n*** Send a verification email to: {email} ***\n", file=sys.stderr)

        # 3) poll for messages
        deadline = time.time() + poll_timeout
        last_messages: list[dict[str, Any]] = []
        message_id: str | None = None
        attempt = 0
        while time.time() < deadline and message_id is None:
            attempt += 1
            listing = client.get(f"/api/emails/{account_id}")
            listing.raise_for_status()
            payload = listing.json()
            messages = (payload.get("messages") if isinstance(payload, dict) else payload) or []
            last_messages = messages if isinstance(messages, list) else []
            if last_messages:
                message_id = last_messages[0].get("id")
                if message_id is not None:
                    break
            print(f"[poll] attempt {attempt}: {len(last_messages)} message(s) so far", file=sys.stderr)
            time.sleep(poll_interval)

        if not last_messages:
            print(f"ERROR: no message arrived in {poll_timeout}s. Did you send the email?", file=sys.stderr)
            return 1
        print(f"[ok] got {len(last_messages)} message(s); first id={message_id}", file=sys.stderr)

        # 4) fetch first message body
        msg_resp = client.get(f"/api/emails/{account_id}/{message_id}")
        msg_resp.raise_for_status()
        msg_envelope = msg_resp.json()
        # beilunyang/moemail wraps the body in {"message": {...}}
        msg = msg_envelope.get("message") if isinstance(msg_envelope, dict) else None
        if not isinstance(msg, dict):
            msg = msg_envelope if isinstance(msg_envelope, dict) else {}
        print(f"[ok] message body fetched: subject={msg.get('subject')!r}", file=sys.stderr)

        # 5) extract verification code
        code = extract_verification_code(msg)
        if code:
            print(f"\nSUCCESS: extracted verification code {code}", file=sys.stderr)
            print(json.dumps({
                "ok": True,
                "email": email,
                "subject": msg.get("subject"),
                "content": (msg.get("content") or "")[:200],
                "verification_code": code,
            }, ensure_ascii=False, indent=2))
            return 0
        print(f"ERROR: could not extract a 6-digit code from the message", file=sys.stderr)
        print(json.dumps({
            "ok": False,
            "email": email,
            "subject": msg.get("subject"),
            "content": (msg.get("content") or "")[:500],
            "html_snippet": (msg.get("html") or "")[:500],
        }, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
