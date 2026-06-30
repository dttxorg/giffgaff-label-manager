import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from qr_utils import parse_esim_raw, build_lpa_string, generate_esim_qr_png


def test_parse_basic_format():
    assert parse_esim_raw("1$cel.prod.ondemandconnectivity.com$ABC123") == (
        "cel.prod.ondemandconnectivity.com",
        "ABC123",
    )


def test_parse_with_lpa_prefix():
    assert parse_esim_raw("LPA:1$cel.prod.ondemandconnectivity.com$XYZ999") == (
        "cel.prod.ondemandconnectivity.com",
        "XYZ999",
    )


def test_parse_case_insensitive_lpa_prefix():
    assert parse_esim_raw("lpa:1$smpdhost$CODE") == ("smpdhost", "CODE")


def test_parse_with_whitespace():
    assert parse_esim_raw("  1$host$CODE   ") == ("host", "CODE")


def test_parse_empty_returns_none():
    assert parse_esim_raw("") is None
    assert parse_esim_raw("   ") is None
    assert parse_esim_raw(None) is None


def test_parse_missing_first_dollar_returns_none():
    assert parse_esim_raw("cel.prod.ondemandconnectivity.com$ABC") is None


def test_parse_missing_last_dollar_returns_none():
    assert parse_esim_raw("1$cel.prod.ondemandconnectivity.com") is None


def test_build_lpa_string():
    assert build_lpa_string("smdp.example.com", "ABC123") == "LPA:1$smdp.example.com$ABC123"


def test_generate_esim_qr_png_returns_png_bytes():
    png = generate_esim_qr_png("LPA:1$smpd.example.com$ABC123")
    assert isinstance(png, bytes)
    assert len(png) > 100
    # PNG magic bytes: 0x89 0x50 0x4E 0x47
    assert png[:4] == b"\x89PNG"