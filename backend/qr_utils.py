"""ESIM QR generation utilities."""
from __future__ import annotations

import io
import re


# Matches: 1$SM-DP+$ACTIVATION_CODE  (optionally with leading "LPA:" prefix)
_RAW_PATTERN = re.compile(r"^(?:LPA:\s*)?1\$(.+?)\$(.+)$", re.IGNORECASE)


def parse_esim_raw(raw: str | None) -> tuple[str, str] | None:
    """Parse a raw string like '1$smdp$code' (optionally prefixed by 'LPA:').

    Returns (smdp, code) on success, None on parse failure or empty input.
    """
    if not raw or not raw.strip():
        return None
    m = _RAW_PATTERN.match(raw.strip())
    if not m:
        return None
    return m.group(1), m.group(2)


def build_lpa_string(smdp: str, code: str) -> str:
    """Construct the LPA string that gets encoded into the QR."""
    return f"LPA:1${smdp}${code}"


def generate_esim_qr_png(lpa: str) -> bytes:
    """Render the LPA string as a PNG image. Returns raw PNG bytes."""
    import qrcode

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=8,
        border=2,
    )
    qr.add_data(lpa)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
