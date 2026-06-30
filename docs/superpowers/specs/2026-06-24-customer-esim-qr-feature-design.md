# Customer ESIM QR Feature — Design

**Status**: Draft, awaiting user review
**Date**: 2026-06-24
**Scope**: Backend (DB column + API) + frontend (detail page UI). NO desktop-client changes.

## 1. Background & Goals

### Problem
After a giffgaff activation is complete, the operator receives an eSIM activation code from giffgaff (via email or out-of-band). They want to convert it to a scannable QR code and save it on the customer record so the customer can install eSIM by scanning.

Reference site: https://gg.681218.xyz/esim-qr.html already implements this conversion. The frontend there:
- Accepts either the full `1$cel.prod.ondemandconnectivity.com$ACTIVATIONCODE` string, or splits SM-DP+ and code into two fields
- Auto-prefixes `LPA:1$` to construct the final `LPA:1$smdp$code` string
- Renders the LPA string as a QR code (256×256, error correction L)
- Shows the full LPA string with a "copy" button

User wants the same workflow **embedded in the customer detail page** of the management UI, with the code **persisted to the customer record** so they don't have to re-paste next time.

### Goal
In the customer detail page, add a section with:
1. A multi-line text input that accepts `1$cel.prod.ondemandconnectivity.com$ACTIVATIONCODE`
2. A **"生成二维码"** button — generates QR (purely client-side temporary preview, calls backend API)
3. A **"保存到客户"** button — saves the raw string to the customer record
4. The generated QR image (PNG) and the full `LPA:1$...` string shown below
5. After saving, the QR remains visible whenever the detail page is opened for that customer

## 2. Out of Scope

- Desktop-client changes (NOT touched)
- eSIM QR used as a label template variable (future work)
- Editing/deleting the saved code via the UI (we only support save and re-generate)
- Multi-customer bulk eSIM import
- Encrypted storage of activation codes (giffgaff eSIM codes are not high-sensitivity; same security level as `sim_activation_code`)

## 3. Component Changes

### 3.1 Backend: `backend/database.py`

Add column `esim_raw_code TEXT` to `customers` table. Startup migration uses the existing `_ensure_column` helper:

```python
await _ensure_column(db, "customers", "esim_raw_code", "TEXT")
```

Existing rows: `esim_raw_code IS NULL`. Backward-compatible (no default value needed).

### 3.2 Backend: `backend/models.py`

`CustomerDetail` and `CustomerOut` both get `esim_raw_code: Optional[str] = None`.

### 3.3 Backend: `backend/requirements.txt`

Add `qrcode[pil]>=7.0` line. The `[pil]` extra uses PIL for PNG generation. Spec minimum is 7.0 because PIL support changed in 7.x.

### 3.4 Backend: `backend/qr_utils.py` (new)

```python
"""ESIM QR generation utilities."""
from __future__ import annotations

import io
import re

DEFAULT_SMDP = "cel.prod.ondemandconnectivity.com"

# 1$SM-DP+$ACTIVATION_CODE  (or with leading LPA:)
_RAW_PATTERN = re.compile(r"^(?:LPA:\s*)?1\$(.+?)\$(.+)$", re.IGNORECASE)


def parse_esim_raw(raw: str) -> tuple[str, str] | None:
    """Parse a raw string like '1$smdp$code' (optionally prefixed by 'LPA:').

    Returns (smdp, code) on success, None on parse failure.
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
        version=None,  # auto-pick smallest version that fits
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

**Note on default SM-DP+**: The frontend will default the input field to `1$cel.prod.ondemandconnectivity.com$<empty>` so the user only types the activation code. The backend parser doesn't enforce a default — it only normalizes whatever the user typed.

### 3.5 Backend: `backend/main.py` — endpoint

```python
@app.get("/api/customers/{customer_id}/esim-qr.png")
async def get_customer_esim_qr(customer_id: int):
    c = await get_customer(customer_id)
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

Notes:
- Returns **404** if customer has no `esim_raw_code` (lets frontend show "请先保存激活码" message)
- Returns **400** if the saved value is unparseable (corrupt data; user can re-save)
- Custom header `X-LPA-String` carries the full LPA so frontend doesn't need a second request

### 3.6 Backend: `backend/main.py` — save endpoint

```python
@app.put("/api/customers/{customer_id}/esim-code")
async def save_customer_esim_code(customer_id: int, data: EsimCodeUpdate):
    c = await get_customer(customer_id)
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

`EsimCodeUpdate` is a Pydantic model: `code: str`. Empty string clears the code (sets NULL).

### 3.7 Frontend: `frontend/index.html`

#### 3.7.1 New section in the customer detail panel

Inside the existing customer-detail section (where `customerDetail` is rendered), append:

```html
<fieldset id="esimSection">
  <legend>eSIM 激活码</legend>
  <textarea id="esimRawCode" rows="3"
            placeholder="1$cel.prod.ondemandconnectivity.com$..."></textarea>
  <div>
    <button id="esimPreviewBtn">生成二维码</button>
    <button id="esimSaveBtn">保存到客户</button>
  </div>
  <div id="esimQrContainer" hidden>
    <img id="esimQrImg" alt="eSIM QR" />
    <p>完整 LPA：</p>
    <code id="esimLpaText"></code>
    <button id="esimCopyBtn">复制</button>
  </div>
  <p id="esimSavedIndicator" hidden>已保存到客户</p>
</fieldset>
```

#### 3.7.2 Wiring script (vanilla JS, no framework)

```js
async function refreshEsimSection(customer) {
  const raw = customer.esim_raw_code || "";
  const textarea = document.getElementById('esimRawCode');
  textarea.value = raw;
  document.getElementById('esimSavedIndicator').hidden = !raw;
  if (raw) {
    document.getElementById('esimQrContainer').hidden = false;
    document.getElementById('esimQrImg').src =
      `/api/customers/${customer.id}/esim-qr.png?ts=${Date.now()}`;
  } else {
    document.getElementById('esimQrContainer').hidden = true;
  }
}

document.getElementById('esimPreviewBtn').onclick = async () => {
  const customer = currentCustomer;
  if (!customer) return;
  const raw = document.getElementById('esimRawCode').value.trim();
  if (!raw) return alert('请先粘入激活码');
  // POST to save (preview requires save to work via /esim-qr.png endpoint)
  const form = { code: raw };
  const res = await fetch(`/api/customers/${customer.id}/esim-code`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(form),
  });
  if (!res.ok) return alert('保存失败：' + (await res.text()));
  // After save, fetch QR via GET endpoint (returns PNG bytes + X-LPA-String header)
  const qrRes = await fetch(`/api/customers/${customer.id}/esim-qr.png`);
  if (!qrRes.ok) return alert('生成失败：' + (await qrRes.text()));
  const lpa = qrRes.headers.get('X-LPA-String');
  const blob = await qrRes.blob();
  document.getElementById('esimQrImg').src = URL.createObjectURL(blob);
  document.getElementById('esimLpaText').textContent = lpa;
  document.getElementById('esimQrContainer').hidden = false;
  document.getElementById('esimSavedIndicator').hidden = false;
  // Update in-memory customer so subsequent edits don't overwrite
  customer.esim_raw_code = raw;
};

document.getElementById('esimCopyBtn').onclick = () => {
  const t = document.getElementById('esimLpaText').textContent;
  navigator.clipboard.writeText(t);
};

// When customerDetail is opened (existing hook), call refreshEsimSection(customer).
```

Note: the **"生成二维码"** button does **save** as well (because the QR endpoint reads from DB). This avoids needing a separate "preview without save" endpoint and keeps the spec simple. The button is labelled to imply preview but functionally it also saves. If user wants to delete the code, they can clear the textarea and click again (empty string clears).

## 4. API Surface (new)

| Method | Path | Purpose | Status codes |
|---|---|---|---|
| `PUT` | `/api/customers/{id}/esim-code` | Save raw eSIM string | 200, 400 (bad format), 404 (no customer) |
| `GET` | `/api/customers/{id}/esim-qr.png` | Fetch QR image | 200 PNG, 400 (corrupt), 404 (no code / no customer) |

No changes to existing API endpoints.

## 5. Testing Strategy

### 5.1 Backend unit tests

`backend/tests/test_qr_utils.py` (new):
- `parse_esim_raw` matches `1$smdp$code` → returns (smdp, code)
- `parse_esim_raw` matches `LPA:1$smdp$code` (case-insensitive) → returns (smdp, code)
- `parse_esim_raw` returns None on empty input
- `parse_esim_raw` returns None on wrong-format input (e.g. just `1$smdp`)
- `build_lpa_string` returns `LPA:1$smdp$code`
- `generate_esim_qr_png` returns non-empty PNG bytes; signature starts with `\x89PNG`

### 5.2 Backend integration test

`backend/tests/test_esim_api.py` (new):
- `GET .../esim-qr.png` on customer with no code → 404
- `PUT .../esim-code` with valid string → 200
- `GET .../esim-qr.png` after save → 200 PNG
- `PUT .../esim-code` with invalid format → 400
- Custom `X-LPA-String` header contains `LPA:1$cel.prod.ondemandconnectivity.com$CODE`

### 5.3 Manual

- Open a real customer detail page
- Paste `1$cel.prod.ondemandconnectivity.com$ABC123...` (any valid-looking code)
- Click "生成二维码"
- Verify QR displays
- Reload page — saved code and QR re-render

## 6. Risks

| Risk | Mitigation |
|---|---|
| giffgaff might use a different default SM-DP+ for a member | Input is free-form; user can edit the smdp part |
| `qrcode` PIL dependency adds ~5MB install | Optional `[pil]` extra; if user objects, swap to `segno` library |
| iOS / Android QR scanner sensitivity | Use 256×256, error correction L (matches reference site) |
| Activation code leaked via export JSON | Acceptable risk — same level as `sim_activation_code`. Not flagged as high-sensitivity in spec |
| Frontend updates `customer` object after save; subsequent list refresh resets it | Use only `customer.esim_raw_code = raw;` in-memory; don't rerender full card unless refetched |
| Multiple customers share the same activation code (impossible but defended) | Backend doesn't care; each customer row has its own `esim_raw_code` |

## 7. Files Changed (scope)

| File | Change type | Lines |
|---|---|---|
| `backend/database.py` | modify | +3 |
| `backend/models.py` | modify | +2 |
| `backend/qr_utils.py` | new | +60 |
| `backend/main.py` | modify | +50 |
| `backend/requirements.txt` | modify | +1 |
| `backend/tests/test_qr_utils.py` | new | +60 |
| `backend/tests/test_esim_api.py` | new | +80 |
| `frontend/index.html` | modify | +50 |

## 8. Implementation Order (for the writing-plans phase)

1. Add `qrcode[pil]>=7.0` to requirements
2. Add `esim_raw_code` column migration
3. Add `qr_utils.py` with tests
4. Add Pydantic model `EsimCodeUpdate`
5. Add `PUT .../esim-code` endpoint with tests
6. Add `GET .../esim-qr.png` endpoint with tests
7. Add `esim_raw_code` to `CustomerDetail` / `CustomerOut` so frontend gets it on detail load
8. Frontend: add HTML section + JS wiring
9. Manual end-to-end against running backend

## 9. Success Criteria

- Detail page shows eSIM section for every customer
- Typing a raw string and clicking "生成二维码" produces a scannable QR
- Saving once, reloading the page, the saved QR re-renders without re-typing
- QR encodes `LPA:1$SM-DP+$CODE` exactly (verifiable via backend `X-LPA-String` response header)
- Wrong-format input rejected with 400 + frontend alert
