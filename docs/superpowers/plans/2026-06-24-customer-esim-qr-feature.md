# Customer eSIM QR Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "eSIM 激活码" section to the customer detail panel that lets operators paste a raw eSIM activation code (`1$cel.prod.ondemandconnectivity.com$...`), generate a scannable QR code (PNG, encoded as `LPA:1$smdp$code`), and persist it back to the customer record.

**Architecture:** Backend adds `esim_raw_code` column + `qr_utils.py` (`qrcode` PIL lib) + two endpoints (`PUT /api/customers/{id}/esim-code`, `GET /api/customers/{id}/esim-qr.png`). Frontend detail page gets an HTML section wired via vanilla JS. The "生成二维码" button saves + fetches PNG in one round trip.

**Tech Stack:** FastAPI, aiosqlite, qrcode[pil] (Python), pytest, plain HTML/CSS/JS. No changes to desktop-client.

**Spec:** `docs/superpowers/specs/2026-06-24-customer-esim-qr-feature-design.md`

---

## File Structure

| File | Role |
|---|---|
| `backend/requirements.txt` | Add `qrcode[pil]>=7.0` |
| `backend/database.py` | Add `esim_raw_code` column via existing `_ensure_column` |
| `backend/qr_utils.py` | New: `parse_esim_raw`, `build_lpa_string`, `generate_esim_qr_png` |
| `backend/models.py` | Add `esim_raw_code` to `CustomerDetail` & `CustomerOut`; add `EsimCodeUpdate` |
| `backend/main.py` | Add `PUT /esim-code` endpoint, add `GET /esim-qr.png` endpoint |
| `backend/tests/test_qr_utils.py` | New: parser, builder, PNG bytes tests |
| `backend/tests/test_esim_api.py` | New: 404/200/400 lifecycle tests for both endpoints |
| `frontend/index.html` | New eSIM section + JS wiring |

---

## Task 1: Install qrcode library and add to requirements

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add `qrcode[pil]>=7.0` to requirements**

Append `qrcode[pil]>=7.0` to `backend/requirements.txt` (after `httpx>=0.27.0`).

- [ ] **Step 2: Install**

Run: `cd backend && ../desktop-client/.venv/bin/pip install -r requirements.txt 2>&1 | tail -3`

Expected: `Successfully installed qrcode-7.x.x Pillow-x.x.x ...`

- [ ] **Step 3: Smoke test**

Run: `cd backend && ../desktop-client/.venv/bin/python -c "import qrcode; from PIL import Image; print('qrcode', qrcode.__version__); print('PIL', Image.__version__)"`

Expected: prints both versions.

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt
git commit -m "deps: add qrcode[pil]>=7.0 for eSIM QR generation"
```

---

## Task 2: Add `esim_raw_code` column via existing `_ensure_column` helper

**Files:**
- Modify: `backend/database.py` (in the `_ensure_column` block for customers)

- [ ] **Step 1: Locate the customer migration block**

In `backend/database.py`, find the block that adds columns to `customers` (around lines 36-46). Add a new line.

- [ ] **Step 2: Add the new column**

Insert this line at the end of that block (after line 45):

```python
        await _ensure_column(db, "customers", "esim_raw_code", "TEXT")
```

- [ ] **Step 3: Verify migration runs without error**

Run: `cd backend && ../desktop-client/.venv/bin/python -c "
import asyncio
import database
database.DATABASE_PATH = ':memory:'
async def run():
    await database.init_db()
    async with __import__('aiosqlite').connect(database.DATABASE_PATH) as db:
        cur = await db.execute(\"PRAGMA table_info(customers)\")
        cols = [r[1] async for r in cur]
    print('esim_raw_code' in cols)
asyncio.run(run())
"`

Expected: `True`

- [ ] **Step 4: Commit**

```bash
git add backend/database.py
git commit -m "feat(db): add esim_raw_code column to customers"
```

---

## Task 3: TDD `qr_utils.parse_esim_raw`

**Files:**
- Create: `backend/qr_utils.py`
- Create: `backend/tests/test_qr_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_qr_utils.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ../desktop-client/.venv/bin/python -m pytest tests/test_qr_utils.py -v 2>&1 | tail -10`

Expected: `ModuleNotFoundError: No module named 'qr_utils'` (or similar import error)

- [ ] **Step 3: Implement `qr_utils.py`**

```python
# backend/qr_utils.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ../desktop-client/.venv/bin/python -m pytest tests/test_qr_utils.py -v`

Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/qr_utils.py backend/tests/test_qr_utils.py
git commit -m "feat(backend): add qr_utils (parse, build_lpa, png)"
```

---

## Task 4: Add `EsimCodeUpdate` model and `esim_raw_code` to detail/out

**Files:**
- Modify: `backend/models.py`

- [ ] **Step 1: Add field to CustomerDetail**

Find `class CustomerDetail(BaseModel):` block in `backend/models.py`. Add `esim_raw_code: Optional[str] = None` after the existing `courier_print_data` field (or at the end of the typed fields group).

The model must look approximately like:

```python
class CustomerDetail(BaseModel):
    id: int
    phone_number: Optional[str]
    email: str
    shipping_address: Optional[str]
    shipping_status: ShippingStatus
    courier_company: Optional[str]
    tracking_number: Optional[str]
    courier_order_code: Optional[str]
    courier_print_data: Optional[str]
    activation_date: date
    created_at: str
    moemail_id: Optional[str]
    moemail_address: Optional[str]
    share_link: Optional[str]
    is_moemail_auto: bool
    sim_code_id: Optional[int] = None
    sim_activation_code: Optional[str] = None
    initial_password: Optional[str] = None
    esim_raw_code: Optional[str] = None        # <-- NEW
    activation_status: ActivationStatus = "未开始"
    activation_error: Optional[str] = None
    activated_at: Optional[str] = None
```

- [ ] **Step 2: Add field to CustomerOut**

Find `class CustomerOut(BaseModel):` and add `esim_raw_code: Optional[str] = None` similarly.

- [ ] **Step 3: Add `EsimCodeUpdate` model**

Add at the end of `backend/models.py`:

```python
class EsimCodeUpdate(BaseModel):
    code: str = ""
```

- [ ] **Step 4: Verify imports work**

Run: `cd backend && ../desktop-client/.venv/bin/python -c "from models import EsimCodeUpdate, CustomerDetail, CustomerOut; print('import ok'); c = CustomerDetail(id=1, email='x', shipping_status='未发货', activation_date='2026-01-01', created_at='', is_moemail_auto=False); print('esim_raw_code default:', c.esim_raw_code)"`

Expected: `import ok` and `esim_raw_code default: None`

- [ ] **Step 5: Commit**

```bash
git add backend/models.py
git commit -m "feat(models): add esim_raw_code + EsimCodeUpdate"
```

---

## Task 5: Update `get_customer_detail` and `list_customers` to return new column

**Files:**
- Modify: `backend/main.py` (two endpoints)

- [ ] **Step 1: Update `get_customer_detail` (around line 626)**

Find the dict construction in `get_customer_detail` and add `esim_raw_code=c.get("esim_raw_code")` to the `CustomerDetail(...)` call. The field list (around line 626-650) must include the new field.

Verify the result includes the new column from the DB row.

- [ ] **Step 2: Update `list_customers` (around line 599)**

In `list_customers`, add `esim_raw_code=r.get("esim_raw_code")` to the `CustomerOut(...)` construction.

- [ ] **Step 3: Verify**

Run: `cd backend && ../desktop-client/.venv/bin/python -c "
import sys, tempfile, asyncio
from pathlib import Path
sys.path.insert(0, '.')
import database, crud, main
from models import CustomerCreate
from datetime import date

async def run():
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / 'test.db')
        database.DATABASE_PATH = db_path
        crud.DATABASE_PATH = db_path
        main.DATABASE_PATH = db_path
        await database.init_db()
        # Direct DB insert (bypass MoEmail)
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            cur = await db.execute(\"INSERT INTO customers (email, activation_date, activation_status) VALUES ('x@y', '2026-01-01', '未开始')\")
            cid = cur.lastrowid
            await db.execute('UPDATE customers SET esim_raw_code = ? WHERE id = ?', ('1$a$b', cid))
            await db.commit()
        c = await crud.get_customer(cid)
        print('esim_raw_code in crud row:', c.get('esim_raw_code'))
asyncio.run(run())
"`

Expected: prints `esim_raw_code in crud row: 1$a$b`

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat(main): include esim_raw_code in detail+list responses"
```

---

## Task 6: TDD PUT endpoint for saving eSIM code

**Files:**
- Modify: `backend/main.py`
- Create: `backend/tests/test_esim_api.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_esim_api.py
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import aiosqlite

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import crud
import database
import main
from models import CustomerCreate


def _patch_db_paths(testcase, tmp_dir):
    db_path = str(Path(tmp_dir) / "test.db")
    testcase.original_paths = (
        database.DATABASE_PATH,
        crud.DATABASE_PATH,
        main.DATABASE_PATH,
    )
    database.DATABASE_PATH = db_path
    crud.DATABASE_PATH = db_path
    main.DATABASE_PATH = db_path


def _restore_db_paths(testcase):
    database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH = testcase.original_paths


class SaveEsimCodeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir_ctx = tempfile.TemporaryDirectory()
        _patch_db_paths(self, self.temp_dir_ctx.name)
        # Bypass MoEmail: monkey-patch generator
        self.original_gen = main._generate_moemail_account

        async def fake_gen(domain=None):
            return {"email": "x@y", "moemail_id": None, "moemail_address": "x@y",
                    "share_link": None, "is_moemail_auto": False}

        main._generate_moemail_account = fake_gen
        await database.init_db()
        # Create one customer
        result = await main.add_customer(
            CustomerCreate(
                email="x@y",
                activation_date=date(2026, 6, 24),
                use_sim_code=False,
            )
        )
        self.customer_id = result["customer_id"]

    async def asyncTearDown(self):
        _restore_db_paths(self)
        main._generate_moemail_account = self.original_gen
        self.temp_dir_ctx.cleanup()

    async def test_save_valid_code(self):
        result = await main.save_customer_esim_code(
            self.customer_id, main.EsimCodeUpdate.model_validate({"code": "1$smpd$CODE1"})
        )
        assert result["ok"] is True
        async with aiosqlite.connect(main.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT esim_raw_code FROM customers WHERE id = ?", (self.customer_id,))
            row = await cur.fetchone()
        assert row["esim_raw_code"] == "1$smpd$CODE1"

    async def test_save_invalid_format_raises_400(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            await main.save_customer_esim_code(
                self.customer_id, main.EsimCodeUpdate.model_validate({"code": "not-a-valid-code"})
            )
        assert ctx.exception.status_code == 400

    async def test_save_with_lpa_prefix(self):
        result = await main.save_customer_esim_code(
            self.customer_id, main.EsimCodeUpdate.model_validate({"code": "LPA:1$smpd$CODE"})
        )
        assert result["ok"] is True

    async def test_save_empty_clears_code(self):
        # First save something
        await main.save_customer_esim_code(
            self.customer_id, main.EsimCodeUpdate.model_validate({"code": "1$smpd$CODE"})
        )
        # Then clear
        result = await main.save_customer_esim_code(
            self.customer_id, main.EsimCodeUpdate.model_validate({"code": ""})
        )
        assert result["ok"] is True
        async with aiosqlite.connect(main.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT esim_raw_code FROM customers WHERE id = ?", (self.customer_id,))
            row = await cur.fetchone()
        assert row["esim_raw_code"] is None

    async def test_save_unknown_customer_404(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            await main.save_customer_esim_code(
                99999, main.EsimCodeUpdate.model_validate({"code": "1$smpd$CODE"})
            )
        assert ctx.exception.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ../desktop-client/.venv/bin/python -m pytest tests/test_esim_api.py -v 2>&1 | tail -10`

Expected: `AttributeError: module 'main' has no attribute 'save_customer_esim_code'`

- [ ] **Step 3: Add `EsimCodeUpdate` to main.py imports**

Find `from models import ...` in `backend/main.py`. Import `EsimCodeUpdate` (alongside the other models). Also ensure `from qr_utils import parse_esim_raw` is added.

- [ ] **Step 4: Add the endpoint**

In `backend/main.py`, add (near `save_customer` or other write endpoints, around line 700):

```python
@app.put("/api/customers/{customer_id}/esim-code")
async def save_customer_esim_code(customer_id: int, data: EsimCodeUpdate):
    c = await crud.get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    raw = (data.code or "").strip()
    if raw and not parse_esim_raw(raw):
        raise HTTPException(status_code=400, detail="eSIM 激活码格式无效，需为 1$SM-DP+$激活码")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE customers SET esim_raw_code = ? WHERE id = ?",
            (raw or None, customer_id),
        )
        await db.commit()
    return {"ok": True, "esim_raw_code": raw or None}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && ../desktop-client/.venv/bin/python -m pytest tests/test_esim_api.py -v`

Expected: `5 passed`

- [ ] **Step 6: Run all backend tests**

Run: `cd backend && ../desktop-client/.venv/bin/python -m pytest tests/ -v`

Expected: All test_add_customer tests still pass; 5 new test_esim_api tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/main.py backend/tests/test_esim_api.py
git commit -m "feat(api): add PUT /api/customers/{id}/esim-code"
```

---

## Task 7: TDD GET endpoint for QR PNG

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/test_esim_api.py` (add more tests)

- [ ] **Step 1: Add tests for GET endpoint to test_esim_api.py**

Append to `test_esim_api.py`:

```python
class GetEsimQrTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir_ctx = tempfile.TemporaryDirectory()
        _patch_db_paths(self, self.temp_dir_ctx.name)
        self.original_gen = main._generate_moemail_account

        async def fake_gen(domain=None):
            return {"email": "x@y", "moemail_id": None, "moemail_address": "x@y",
                    "share_link": None, "is_moemail_auto": False}

        main._generate_moemail_account = fake_gen
        await database.init_db()
        result = await main.add_customer(
            CustomerCreate(email="x@y", activation_date=date(2026, 6, 24), use_sim_code=False)
        )
        self.customer_id = result["customer_id"]

    async def asyncTearDown(self):
        _restore_db_paths(self)
        main._generate_moemail_account = self.original_gen
        self.temp_dir_ctx.cleanup()

    async def test_get_qr_returns_404_when_no_code_saved(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            await main.get_customer_esim_qr(self.customer_id)
        assert ctx.exception.status_code == 404
        assert "尚未保存" in str(ctx.exception.detail)

    async def test_get_qr_returns_png_after_save(self):
        await main.save_customer_esim_code(
            self.customer_id, main.EsimCodeUpdate.model_validate({"code": "1$smpd$CODE"})
        )
        result = await main.get_customer_esim_qr(self.customer_id)
        # result is a Response object
        assert result.media_type == "image/png"
        body = result.body
        assert isinstance(body, bytes)
        assert body[:4] == b"\x89PNG"
        # X-LPA-String header carries the full LPA
        lpa_header = result.headers.get("X-LPA-String")
        assert lpa_header == "LPA:1$smpd$CODE"

    async def test_get_qr_corrupt_data_raises_400(self):
        # Simulate corrupt data: directly inject bad value, bypassing parser
        async with aiosqlite.connect(main.DATABASE_PATH) as db:
            await db.execute(
                "UPDATE customers SET esim_raw_code = 'corrupted-no-dollars' WHERE id = ?",
                (self.customer_id,),
            )
            await db.commit()
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            await main.get_customer_esim_qr(self.customer_id)
        assert ctx.exception.status_code == 400

    async def test_get_qr_unknown_customer_404(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            await main.get_customer_esim_qr(99999)
        assert ctx.exception.status_code == 404
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `cd backend && ../desktop-client/.venv/bin/python -m pytest tests/test_esim_api.py::GetEsimQrTests -v 2>&1 | tail -10`

Expected: `AttributeError: module 'main' has no attribute 'get_customer_esim_qr'`

- [ ] **Step 3: Add GET endpoint**

```python
@app.get("/api/customers/{customer_id}/esim-qr.png")
async def get_customer_esim_qr(customer_id: int):
    c = await crud.get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    raw = (c.get("esim_raw_code") or "").strip()
    if not raw:
        raise HTTPException(status_code=404, detail="该客户尚未保存 eSIM 激活码")
    parsed = parse_esim_raw(raw)
    if not parsed:
        raise HTTPException(status_code=400, detail="保存的 eSIM 激活码格式无效")
    smdp, code = parsed
    lpa = build_lpa_string(smdp, code)
    png_bytes = generate_esim_qr_png(lpa)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-LPA-String": lpa},
    )
```

Make sure `Response` is imported at top of `main.py` from `fastapi`:

```python
from fastapi import FastAPI, HTTPException, Request, Response
```

(If `Response` is already in the import, no change needed.)

Also add: `from qr_utils import parse_esim_raw, build_lpa_string, generate_esim_qr_png`

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../desktop-client/.venv/bin/python -m pytest tests/test_esim_api.py -v`

Expected: All 9 tests pass (5 from save + 4 from get)

- [ ] **Step 5: Run full backend test suite**

Run: `cd backend && ../desktop-client/.venv/bin/python -m pytest tests/ -v`

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_esim_api.py
git commit -m "feat(api): add GET /api/customers/{id}/esim-qr.png"
```

---

## Task 8: Frontend eSIM section in customer detail

**Files:**
- Modify: `frontend/index.html`

This task does not have unit tests (frontend), but is verified by manual E2E (Task 9).

- [ ] **Step 1: Find the customer detail render site**

Open `frontend/index.html`. Find the function/section that renders the customer detail panel. It's typically tied to `renderCustomerDetail(c)` or similar — search for `customerDetail` or `customer.esim_raw_code` (it does NOT exist yet).

- [ ] **Step 2: Add the eSIM fieldset block to the detail panel**

Add this inside the customer detail panel section (where other fieldsets like 收货地址 / SIM 激活码 live):

```html
<fieldset id="esimSection">
  <legend>eSIM 激活码</legend>
  <p class="hint">格式：<code>1$cel.prod.ondemandconnectivity.com$激活码</code>（不含 LPA: 前缀也可，系统会自动补全）</p>
  <textarea id="esimRawCode" rows="3" placeholder="1$cel.prod.ondemandconnectivity.com$..."></textarea>
  <div class="esim-actions">
    <button type="button" id="esimPreviewBtn">生成二维码</button>
    <button type="button" id="esimSaveBtn">保存到客户</button>
    <span id="esimSavedIndicator" hidden>已保存到客户</span>
  </div>
  <div id="esimQrContainer" hidden>
    <p class="hint">完整 LPA 字符串：</p>
    <code id="esimLpaText"></code>
    <button type="button" id="esimCopyBtn">复制</button>
    <p class="hint">手机用相机/扫一扫对准二维码安装 eSIM</p>
    <img id="esimQrImg" alt="eSIM QR" />
  </div>
</fieldset>
```

(Adapt the surrounding HTML structure — keep fieldset ordering consistent with existing detail panel.)

- [ ] **Step 3: Wire up the JS handlers**

Add a JS block that:

```js
(function () {
  const baseUrl = ''; // same-origin

  function refreshEsimSection(c) {
    if (!c) return;
    const raw = c.esim_raw_code || '';
    document.getElementById('esimRawCode').value = raw;
    document.getElementById('esimSavedIndicator').hidden = !raw;
    if (raw) {
      document.getElementById('esimQrContainer').hidden = false;
      document.getElementById('esimQrImg').src =
        '/api/customers/' + c.id + '/esim-qr.png?ts=' + Date.now();
    } else {
      document.getElementById('esimQrContainer').hidden = true;
    }
  }

  // Hook into the existing renderCustomerDetail
  const origRender = window.renderCustomerDetail;
  window.renderCustomerDetail = function (c) {
    if (typeof origRender === 'function') origRender(c);
    refreshEsimSection(c);
  };

  document.getElementById('esimPreviewBtn').onclick = async function () {
    const c = window.currentCustomer;
    if (!c) return alert('请先选择客户');
    const raw = document.getElementById('esimRawCode').value.trim();
    if (!raw) return alert('请先粘入激活码');
    const saveRes = await fetch('/api/customers/' + c.id + '/esim-code', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: raw }),
    });
    if (!saveRes.ok) {
      const t = await saveRes.text();
      return alert('保存失败：' + t);
    }
    c.esim_raw_code = raw;
    const qrRes = await fetch('/api/customers/' + c.id + '/esim-qr.png');
    if (!qrRes.ok) {
      const t = await qrRes.text();
      return alert('生成失败：' + t);
    }
    const lpa = qrRes.headers.get('X-LPA-String');
    const blob = await qrRes.blob();
    document.getElementById('esimQrImg').src = URL.createObjectURL(blob);
    document.getElementById('esimLpaText').textContent = lpa;
    document.getElementById('esimQrContainer').hidden = false;
    document.getElementById('esimSavedIndicator').hidden = false;
  };

  document.getElementById('esimSaveBtn').onclick = async function () {
    // Same logic as preview (per spec: button saves too). Could split for stricter semantics.
    await document.getElementById('esimPreviewBtn').onclick();
  };

  document.getElementById('esimCopyBtn').onclick = function () {
    const t = document.getElementById('esimLpaText').textContent;
    if (t) navigator.clipboard.writeText(t);
  };
})();
```

Adjust variable names to match the existing frontend's customer-detail render function. The names `window.renderCustomerDetail` and `window.currentCustomer` are placeholders; inspect `frontend/index.html` for the actual names.

- [ ] **Step 4: Verify HTML loads without JS errors**

Open the page in a browser, open a customer's detail panel. Verify the eSIM section appears with: textarea, "生成二维码" button, and (if the customer has no saved code) no QR / LPA shown.

If no JS errors, move on. (No automated test for this — manual E2E in Task 9.)

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html
git commit -m "feat(ui): add eSIM section to customer detail panel"
```

---

## Task 9: Manual end-to-end verification

This task verifies the full flow works.

- [ ] **Step 1: Run backend tests**

Run: `cd backend && ../desktop-client/.venv/bin/python -m pytest tests/ -v`

Expected: All tests pass.

- [ ] **Step 2: Start the backend**

Run: `cd backend && ../desktop-client/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000`

Expected: Uvicorn starts; startup log shows `Initialized database` and QR-related imports succeed.

- [ ] **Step 3: Manual test against running backend**

1. Add or open a customer in the management UI
2. Find the new "eSIM 激活码" section
3. Paste `1$cel.prod.ondemandconnectivity.com$TESTCODE123`
4. Click "生成二维码"
5. **Expectations**:
   - QR image appears below the buttons
   - Text `LPA:1$cel.prod.ondemandconnectivity.com$TESTCODE123` shown next to QR
   - "已保存到客户" indicator visible
6. Reload the page, re-open the same customer's detail
7. **Expectations**:
   - Textarea pre-filled with the raw code
   - QR re-renders (browser caches, may need to force-reload with Ctrl+Shift+R)
8. Test invalid input:
   - Paste `not-a-valid-code`, click button
   - Backend should return 400, frontend should show alert
9. Test clearing:
   - Empty the textarea, click button
   - QR should disappear; "已保存" indicator hidden; backend esim_raw_code = NULL

- [ ] **Step 4: Final commit if any tweaks**

```bash
git status
# If dirty:
git add -A && git commit -m "polish: e2e tweaks"
```

---

## Self-Review

- **Spec coverage**:
  - §3.1 column migration → Task 2 ✓
  - §3.2 CustomerDetail/CustomerOut field → Task 4 ✓
  - §3.3 qrcode dependency → Task 1 ✓
  - §3.4 qr_utils.py with all 3 functions → Task 3 ✓
  - §3.5 GET endpoint → Task 7 ✓
  - §3.6 PUT endpoint → Task 6 ✓
  - §3.7 frontend HTML+JS → Task 8 ✓
  - §5 tests → Tasks 3, 6, 7 ✓
  - §8 implementation order aligns with these tasks ✓
  - §9 success criteria → Task 9 ✓

- **Placeholder scan**: No TBD. All code blocks are concrete.

- **Type / name consistency**:
  - `esim_raw_code` used in column, model, API ✓
  - `parse_esim_raw`, `build_lpa_string`, `generate_esim_qr_png` used consistently ✓
  - `EsimCodeUpdate` imported in main.py and tests ✓
  - `save_customer_esim_code`, `get_customer_esim_qr` function names align between tests and main.py ✓
  - `X-LPA-String` header used in both endpoint implementation and test assertion ✓

- **Backend tests use real DB** (via temp file), not mocked — so test isolation is via `setUp`/`tearDown`. All 9 backend tests + existing test_add_customer must pass.

- **Frontend has no automated tests** — Task 9 manual verification covers that. This is consistent with existing frontend (pure HTML/JS, no test framework).
