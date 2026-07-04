# Multi-Email-Provider Pool — Design

**Status**: Draft, awaiting user review
**Date**: 2026-07-04
**Scope**: Backend (DB + provider abstraction + REST API); frontend (provider management UI + customer entry update). Desktop-client untouched.
**Related**:
- Brainstorming: see this conversation for context
- Research findings: ~10 cloud-mail API endpoints, JWT auth flow (HS256, 30d expiry), account/email entity schemas

## 1. Background & Goals

### Problem
The system today only supports one email provider: **MoEmail**. Every customer created by the system gets a randomly-generated email address from one MoEmail deployment:

- All emails share the same **domain suffix** (e.g. `@681218.xyz`)
- If the user runs multiple giffgaff activations per day, every giffgaff registration lands on the same domain
- giffgaff's anti-fraud system can correlate these as a batch-registration pattern
- MoEmail's pricing/availability is also a single point of failure

There are now two candidate providers the user wants to mix:
1. **MoEmail** (existing) — hosted service
2. **cloud-mail** (github.com/maillab/cloud-mail) — self-hosted alternative

The user wants to **pool multiple providers**, auto-rotate selection per customer, **avoid a single domain suffix across all customers**.

### Goals
1. Pool N providers (N = 2-5, likely 2-3 MoEmail + 1-2 cloud-mail)
2. Add a new customer via a **round-robin policy** by default (least-recently-used)
3. Allow per-customer **manual override** (pin to specific provider) via UI
4. Backward-compatible: existing customers using MoEmail keep working
5. Frontend gets a **provider management UI** in system settings

### Out of Scope
- Desktop-client changes (NOT touched)
- Smart/weighted rotation (e.g. error-based health scoring) — only round-robin for v1
- Per-provider domain selection UI (advanced config) — provider is the atomic unit
- Migrating existing customers from MoEmail to other providers

## 2. Architecture

**Pool** = small (2-5) set of registered `email_providers` rows in DB.

**Provider** = one row with:
- `provider_type` ∈ {`moemail`, `cloudmail`}
- `config_json` (URL + credentials)
- `last_used_at`, `last_error` (round-robin tracking + health)

**Selection policy**:
- Default = round-robin via `last_used_at ASC` (excluding providers with `last_error` set within last 5 min — soft cooldown)
- Manual override = `customer.email_provider_id` set to non-null

**Provider abstraction**:
- New package `backend/email_providers/`
- `base.py` defines `EmailProvider` abstract class
- `moemail.py` wraps existing `MoEmailClient` (refactor, not rewrite)
- `cloudmail.py` new class implementing JWT auto-login + 10 API calls

**JWT management (cloud-mail only)**:
- System settings stores `cloudmail_email` + `cloudmail_password` in provider's `config_json`
- On every operation, if `last_jwt_token` is missing or >25 days old, re-login via `POST /login`
- TTL kept conservative (5-day safety margin vs 30-day token expiry)

## 3. Component Changes

### 3.1 `backend/database.py`

#### 3.1.1 Add `email_providers` table

```sql
CREATE TABLE email_providers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,           -- 'moemail_main', 'cloudmail_eu', etc.
    provider_type       TEXT NOT NULL,                  -- 'moemail' | 'cloudmail'
    config_json         TEXT NOT NULL,                  -- see §3.1.2
    last_used_at        TEXT,                           -- ISO datetime, nullable
    last_error          TEXT,                           -- error message, nullable
    last_error_at       TEXT,                           -- ISO datetime, nullable
    last_jwt_token      TEXT,                           -- cloud-mail only
    last_jwt_at         TEXT,                           -- ISO datetime, nullable
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
```

#### 3.1.2 `config_json` shape per provider_type

**MoEmail**:
```json
{
  "url": "https://moemail.681218.xyz",
  "api_key": "..."
}
```

**cloud-mail**:
```json
{
  "url": "https://mail.example.com",
  "email": "admin@example.com",
  "password": "..."
}
```

#### 3.1.3 Add columns to `customers` table

```sql
ALTER TABLE customers ADD COLUMN email_provider_id INTEGER REFERENCES email_providers(id);
ALTER TABLE customers ADD COLUMN email_account_id TEXT;       -- provider-specific account ID
```

Via `_ensure_column` (existing helper). Old `moemail_id` / `moemail_address` columns **kept** for backward compatibility; application code reads new columns first, falls back to old columns for legacy customers.

### 3.2 `backend/email_providers/` (new package)

```
backend/email_providers/
├── __init__.py            # exports pick_provider()
├── base.py                # EmailProvider abstract class
├── moemail.py             # MoEmailProvider (wraps MoEmailClient)
├── cloudmail.py           # CloudMailProvider (NEW)
├── auth.py                # JWT cache helpers
└── pool.py                # round-robin selection + manual override logic
```

### 3.3 `backend/email_providers/base.py`

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class GeneratedEmail:
    provider_account_id: str   # provider-specific, stored as text
    address: str               # the email address
    share_link: str | None     # if provider supports public viewing


@dataclass
class InboxMessage:
    id: str
    subject: str
    text: str                   # plain text body (most providers populate this)
    received_at: str           # ISO datetime


class EmailProvider(ABC):
    provider_type: str = ""    # subclass overrides

    @abstractmethod
    def generate_email(self) -> GeneratedEmail:
        """Create a new email account on this provider. Returns its identifier + address."""

    @abstractmethod
    def fetch_latest_messages(
        self, provider_account_id: str, *, after_message_id: str = ""
    ) -> list[InboxMessage]:
        """Return messages received since the given cursor (exclusive).
        Returned list must be ordered newest-first.
        """

    @abstractmethod
    def extract_verification_code(self, message: InboxMessage) -> str | None:
        """Pull a 6-digit verification code from the message body."""

    @abstractmethod
    def ping(self) -> bool:
        """Verify the provider is reachable and credentials are valid."""

    def share_link(self, provider_account_id: str) -> str | None:
        """Optional: URL the user can open to view the inbox in a browser."""
        return None
```

### 3.4 `backend/email_providers/moemail.py`

Refactor the existing `MoEmailClient` to fit `EmailProvider`:

```python
class MoEmailProvider(EmailProvider):
    provider_type = "moemail"

    def __init__(self, url: str, api_key: str):
        self._client = MoEmailClient(url, api_key)  # existing class

    def generate_email(self) -> GeneratedEmail:
        # random name via existing generate_email_name()
        # call self._client.generate_email(name=...)
        data = self._client.generate_email(name=generate_email_name(), expiry_time=0)
        share = self._client.create_share_link(data["id"])["link"]  # may 404; tolerate
        return GeneratedEmail(
            provider_account_id=str(data["id"]),
            address=data["email"],
            share_link=share,
        )

    def fetch_latest_messages(
        self, provider_account_id: str, *, after_message_id: str = ""
    ) -> list[InboxMessage]:
        data = self._client.get_email_messages(provider_account_id)
        msgs = []
        for m in data.get("messages", []):
            if after_message_id and str(m["id"]) <= after_message_id:
                continue
            body = self._client.get_message(provider_account_id, m["id"])
            msgs.append(InboxMessage(
                id=str(m["id"]),
                subject=m.get("subject", ""),
                text=body.get("text") or body.get("content") or "",
                received_at=m.get("receivedAt") or m.get("createdAt") or "",
            ))
        return msgs

    def extract_verification_code(self, message: InboxMessage) -> str | None:
        match = re.search(r"\b\d{6}\b", message.text)
        return match.group(0) if match else None

    def ping(self) -> bool:
        try:
            self._client.get_config()
            return True
        except Exception:
            return False
```

### 3.5 `backend/email_providers/cloudmail.py`

```python
import httpx


class CloudMailProvider(EmailProvider):
    provider_type = "cloudmail"

    def __init__(self, url: str, email: str, password: str, *, jwt_token: str | None = None,
                 jwt_acquired_at: str | None = None):
        self.base_url = url.rstrip("/")
        self._email = email
        self._password = password
        self._jwt = jwt_token
        self._jwt_at = jwt_acquired_at  # ISO string

    # ---------- Auth ----------
    def _ensure_jwt(self) -> None:
        """Re-login if no token or token > 25 days old."""
        from datetime import datetime, timedelta, timezone
        if self._jwt and self._jwt_at:
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(self._jwt_at)
                if age < timedelta(days=25):
                    return
            except ValueError:
                pass  # bad timestamp; re-login
        # POST /login
        r = httpx.post(
            f"{self.base_url}/login",
            json={"email": self._email, "password": self._password},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        token = data.get("data", {}).get("token") or data.get("token")
        if not token:
            raise RuntimeError("cloud-mail /login: missing token in response")
        self._jwt = token
        self._jwt_at = datetime.now(timezone.utc).isoformat()

    def _headers(self) -> dict:
        self._ensure_jwt()
        return {"Authorization": f"Bearer {self._jwt}"}

    @property
    def jwt(self) -> str | None: return self._jwt
    @property
    def jwt_acquired_at(self) -> str | None: return self._jwt_at

    # ---------- Provider methods ----------
    def generate_email(self) -> GeneratedEmail:
        # Random 10-char prefix (cloud-mail requires email param)
        prefix = generate_email_name()
        # For cloud-mail we need domain from config to construct full email
        # Domain comes from settings (or probed via ping) — see note below
        domain = self._domain  # supplied at construction
        email = f"{prefix}@{domain}"
        r = httpx.post(
            f"{self.base_url}/account/add",
            json={"email": email},
            headers=self._headers(),
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("data", {})
        return GeneratedEmail(
            provider_account_id=str(data["accountId"]),
            address=data["email"],
            share_link=None,  # cloud-mail has no share_link concept
        )

    def fetch_latest_messages(
        self, provider_account_id: str, *, after_message_id: str = ""
    ) -> list[InboxMessage]:
        r = httpx.get(
            f"{self.base_url}/email/latest",
            params={"accountId": provider_account_id, "emailId": after_message_id or 0},
            headers=self._headers(),
            timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("data", [])
        msgs = []
        for m in items:
            msgs.append(InboxMessage(
                id=str(m["emailId"]),
                subject=m.get("subject", ""),
                text=m.get("text", ""),
                received_at=m.get("createTime", ""),
            ))
        return msgs

    def extract_verification_code(self, message: InboxMessage) -> str | None:
        match = re.search(r"\b\d{6}\b", message.text)
        return match.group(0) if match else None

    def ping(self) -> bool:
        try:
            self._ensure_jwt()
            r = httpx.get(f"{self.base_url}/my/loginUserInfo", headers=self._headers(), timeout=10)
            return r.status_code == 200
        except Exception:
            return False
```

**Note on `domain`**: cloud-mail requires the deployment's configured domain. We either:
- (a) Store in `config_json` under `"domain"` key; or
- (b) Probe via `/account/list` (no — there's no GET-config endpoint)
- (c) Read from `my/loginUserInfo` (returns user.email, derives domain via split)

Spec uses **(a)** — store `"domain"` in `config_json`. System settings UI will surface a "default domain" input field for cloud-mail.

### 3.6 `backend/email_providers/pool.py`

```python
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Iterable

from .base import EmailProvider
from .moemail import MoEmailProvider
from .cloudmail import CloudMailProvider


def _construct_provider(row: sqlite3.Row) -> EmailProvider:
    config = json.loads(row["config_json"])
    typ = row["provider_type"]
    if typ == "moemail":
        return MoEmailProvider(url=config["url"], api_key=config["api_key"])
    elif typ == "cloudmail":
        return CloudMailProvider(
            url=config["url"],
            email=config["email"],
            password=config["password"],
            domain=config.get("domain", ""),
            jwt_token=row["last_jwt_token"],
            jwt_acquired_at=row["last_jwt_at"],
        )
    raise ValueError(f"unknown provider_type: {typ}")


def list_providers(db_path: str) -> list[dict]:
    """Return {id, name, type, config, last_used_at, last_error, ...} rows for the management UI."""
    ...


def pick_provider(db_path: str, *, manual_provider_id: int | None = None) -> tuple[int, EmailProvider]:
    """Return (provider_id, provider) following round-robin policy.

    If manual_provider_id is non-null and exists, return it.
    Otherwise: pick provider with oldest last_used_at (NULL sorts first).
    Excludes providers whose last_error_at is within last 5 minutes (soft cooldown).
    """
    ...


def record_provider_use(db_path: str, provider_id: int, error: str | None = None) -> None:
    """Update last_used_at; if error, also update last_error / last_error_at."""
    ...


def persist_provider_jwt(db_path: str, provider_id: int, jwt: str, when_iso: str) -> None:
    """Called by CloudMailProvider after a fresh JWT acquisition."""
    ...
```

### 3.7 `backend/email_providers/auth.py`

Helper to extract JWT cache during operations:

```python
def hydrate_provider(provider: EmailProvider, row: sqlite3.Row) -> None:
    """If provider is a CloudMailProvider, push cached JWT into its in-memory state."""
    if isinstance(provider, CloudMailProvider) and row["last_jwt_token"]:
        provider._jwt = row["last_jwt_token"]
        provider._jwt_at = row["last_jwt_at"]

def extract_jwt_for_persist(provider: EmailProvider) -> tuple[str, str] | tuple[None, None]:
    """After a CloudMailProvider call, return (jwt, jwt_at) to persist."""
    if isinstance(provider, CloudMailProvider) and provider.jwt:
        return provider.jwt, provider.jwt_acquired_at
    return None, None
```

### 3.8 `backend/main.py`

#### 3.8.1 Replace `_generate_moemail_account`

The current `_generate_moemail_account` is called from:
- `add_customer` (line ~675 area)
- `_create_and_claim_task_from_sim_code` (around line 1244)

Refactor to a unified `_generate_email_account`:

```python
async def _generate_email_account(
    *, manual_provider_id: int | None = None
) -> dict:
    """Pool-backed replacement for _generate_moemail_account.

    Returns {email, email_account_id, email_provider_id, share_link?, is_email_auto=True}.
    Raises HTTPException(503) if no usable provider is in the pool.
    """
    from email_providers.pool import pick_provider, record_provider_use, persist_provider_jwt, extract_jwt_for_persist
    provider_id, provider = email_providers.pool.pick_provider(
        DATABASE_PATH, manual_provider_id=manual_provider_id,
    )
    try:
        gen = provider.generate_email()
    except Exception as exc:
        record_provider_use(DATABASE_PATH, provider_id, error=str(exc))
        raise
    record_provider_use(DATABASE_PATH, provider_id)
    # Persist JWT for cloud-mail
    jwt, jwt_at = extract_jwt_for_persist(provider)
    if jwt:
        persist_provider_jwt(DATABASE_PATH, provider_id, jwt, jwt_at)
    return {
        "email": gen.address,
        "email_account_id": gen.provider_account_id,
        "email_provider_id": provider_id,
        "share_link": gen.share_link,
        "is_email_auto": True,
    }
```

**Behavior change**: old function returned hardcoded `is_email_auto=True`. New function keeps that. Behavior is preserved; only data source of provider changes.

#### 3.8.2 New REST API: `email_providers` resource

| Method | Path | Body | Purpose |
|---|---|---|---|
| `GET` | `/api/email-providers` | — | List all configured providers (id, name, type, last_used_at, last_error) |
| `POST` | `/api/email-providers` | `{name, type, config}` | Add new provider; calls `provider.ping()` once; on success persists |
| `PATCH` | `/api/email-providers/{id}` | partial `{name?, config?, last_error?}` | Edit name or config |
| `POST` | `/api/email-providers/{id}/test` | — | Force `provider.ping()`; update last_error |
| `DELETE` | `/api/email-providers/{id}` | — | Remove provider (must have 0 customers; 409 otherwise) |

#### 3.8.3 Frontend integration

In `frontend/index.html`:
1. **System settings**: new tab 「邮箱服务商」 with provider list + add/edit/test/delete buttons
2. **Add customer form** (`renderMoemailBox` area): add toggle 「使用自动轮换」(default on) + provider dropdown (visible only when toggle off)
3. **Customer detail**: replace hardcoded `c.share_link` etc. with `c.email_provider_name`, `c.email_address`

#### 3.8.4 Frontend HTML samples

**Provider management**:
```html
<button class="tab" data-tab="email-providers">邮箱服务商</button>
<section id="tab-email-providers" class="tab-content">
  <button id="ep-add-btn">添加</button>
  <table id="ep-table"></table>
</section>
```

**Add/edit dialog**:
```html
<div class="dialog" id="ep-dialog">
  <label>名称<input id="ep-name"></label>
  <label>类型<select id="ep-type">
    <option value="moemail">MoEmail</option>
    <option value="cloudmail">Cloud-Mail</option>
  </select></label>
  <!-- Dynamic fields per type -->
  <div data-type="moemail">
    <label>URL<input id="ep-url-m"></label>
    <label>API Key<input id="ep-key-m"></label>
  </div>
  <div data-type="cloudmail" hidden>
    <label>URL<input id="ep-url-c"></label>
    <label>邮箱<input id="ep-email-c"></label>
    <label>密码<input type="password" id="ep-pass-c"></label>
    <label>默认域名<input id="ep-domain-c"></label>
  </div>
</div>
```

**Add customer form**:
```html
<label class="checkbox"><input type="checkbox" id="auto-rotate" checked> 使用自动轮换</label>
<select id="provider-pick" hidden>
  <!-- populated from GET /api/email-providers -->
</select>
```

On submit:
- If `auto-rotate`: pass `manual_provider_id=null` to `_generate_email_account`
- Else: pass the selected provider id

#### 3.8.5 Frontend JS

New file functions:
- `loadEmailProviders()` → fetch list, render table
- `openEpDialog(existing?)` → open add/edit modal
- `saveEp()` → POST or PATCH
- `testEp(id)` → POST test
- `deleteEp(id)` → DELETE
- `renderAddCustomerProviderPicker()` → toggle visibility based on auto-rotate checkbox

## 4. State Machines

### 4.1 Round-robin selection

```
[Ask for email_provider_id]
    │
    ├── manual_provider_id provided? → use that (verify exists)
    │
    ├── query: providers WHERE last_error_at IS NULL OR last_error_at < now() - 5min
    │
    ├── if 0 providers:
    │   raise 503 "no usable provider"
    │
    └── ORDER BY last_used_at ASC NULLS FIRST, id ASC LIMIT 1
        (NULL last_used_at sorts before any timestamp)
```

`nulls_first` semantics: SQLite `ORDER BY x ASC` puts NULL first, which is what we want — never-used providers are picked first.

### 4.2 Provider health

```
last_error_at
    │
    └─ if now() - last_error_at < 5min → skip this provider in round-robin
       else include it (could have recovered)
```

For manual selection (manual_provider_id), **ignore cooldown** — user explicitly chose it.

### 4.3 JWT lifecycle (cloud-mail only)

```
last_jwt_at = NULL or absent
    ↓ (any cloud-mail operation triggers _ensure_jwt)
[POST /login]
    ↓ (success)
last_jwt = <new JWT>
last_jwt_at = now()
    ↓ (any subsequent call within 25 days)
[reuse JWT]
    ↓ (after 25 days)
[POST /login again]
```

If `POST /login` fails, mark `last_error` and propagate 503 to caller.

## 5. API Surface (final)

| Method | Path | Purpose | Spec |
|---|---|---|---|
| `GET` | `/api/email-providers` | List provider configs | New |
| `POST` | `/api/email-providers` | Add provider | New |
| `PATCH` | `/api/email-providers/{id}` | Update name/config | New |
| `POST` | `/api/email-providers/{id}/test` | Test connectivity | New |
| `DELETE` | `/api/email-providers/{id}` | Remove provider | New |
| (existing) | `/api/customers` | `email_provider_id` field added | Modified |
| (existing) | `/api/customers/{id}` | Returns `email_provider_name`, etc. | Modified |
| (existing desktop-client) | Uses customer data as-is | Unchanged | Unchanged |

## 6. Data Migration

Existing customers retain existing data:
- `moemail_id`, `moemail_address`, `share_link`, `is_moemail_auto` columns unchanged
- These rows continue to be readable by old code paths if any exist

Application logic prefers new columns first, then falls back:
```python
email_address = customer.get("email_address") or customer.get("moemail_address")
```

A small one-time backfill is included: for each existing customer with `moemail_id IS NOT NULL` and `email_provider_id IS NULL`, set `email_provider_id` to a special "legacy moemail" provider. The seeded "legacy" provider points at the existing system-wide MoEmail config (a synthetic entry created on first start if `moemail_*` settings are populated).

Actually, simpler: don't backfill. Old customers keep working via legacy fallback, new customers go through pool. Application logic handles this in `_generate_email_account` only — old customers' `add_customer_status` etc. don't change.

## 7. Testing

### 7.1 Unit tests (`backend/tests/test_email_providers.py`)

- `test_round_robin_picks_oldest_first`
- `test_round_robin_prefers_never_used`
- `test_round_robin_skips_recent_error`
- `test_round_robin_manual_provider_overrides`
- `test_round_robin_503_when_no_providers`
- `test_moemail_extract_verification_code`
- `test_moemail_ping_returns_true`
- `test_cloudmail_ping_returns_true` (mocked httpx)
- `test_cloudmail_ping_returns_false_on_401`
- `test_cloudmail_jwt_refresh_after_25_days`
- `test_cloudmail_jwt_kept_under_25_days`

### 7.2 Endpoint tests

- `test_get_email_providers_returns_list`
- `test_post_email_providers_creates_moemail`
- `test_post_email_providers_rejects_invalid_type`
- `test_post_email_providers_pings_on_create`
- `test_delete_email_providers_rejects_when_customers_attached`

### 7.3 Manual

1. Add a MoEmail provider via UI
2. Add a cloud-mail provider via UI (need at least 1 deployment)
3. Add 5 customers, observe round-robin picks different providers
4. View a customer's detail, verify `email_provider_name` shows correct provider
5. Pin a customer to a specific provider via UI toggle, re-add, verify they get that provider
6. Wait 30+ days (or fast-forward) and verify cloud-mail JWT auto-refreshes

## 8. Risks

| Risk | Mitigation |
|---|---|
| cloud-mail deployment unavailable | Round-robin skips providers with recent errors; pool of 2-5 means single failure degrades but doesn't break |
| JWT leaks to logs | Provider class masks JWT in `__repr__`; log lines use redacted token |
| Existing customer decode broken | Backward compat: app reads `email_address OR moemail_address` |
| cloud-mail `domain` field requires config UI but might be wrong | `ping()` also validates by attempting a probe; if invalid, `last_error` gets set |
| Account reuse across customers | Each task still creates a new account per customer (via pool); no sharing |
| Pool all errored out | 503 response; UI shows "no available providers, check settings" |
| Round-robin frequency oscillation | Soft cooldown (5 min) prevents thrashing |
| Hot provider gets hammered | Cooldown + round-robin ensures even distribution; cooldown window softens spikes |
| Self-signed/invalid HTTPS cert | httpx default doesn't validate; documented as known issue (use real cert) |

## 9. Files Changed

| File | Change |
|---|---|
| `backend/database.py` | Modify: add email_providers table + 2 customer columns |
| `backend/email_providers/__init__.py` | New |
| `backend/email_providers/base.py` | New |
| `backend/email_providers/moemail.py` | New (refactor existing logic) |
| `backend/email_providers/cloudmail.py` | New |
| `backend/email_providers/auth.py` | New |
| `backend/email_providers/pool.py` | New |
| `backend/main.py` | Modify: replace `_generate_moemail_account`, add 5 endpoints |
| `backend/models.py` | Add `EmailProvider*` Pydantic models |
| `frontend/index.html` | Modify: add provider management UI |
| `frontend/index.html` | Modify: add auto-rotate / provider picker in add-customer form |
| `backend/tests/test_email_providers.py` | New |
| `backend/tests/test_email_api.py` | New |
| `docs/superpowers/specs/...` | This file |
| `docs/superpowers/plans/...` | TBD |

**Estimated lines**: ~700 backend + ~200 frontend + ~250 tests = **~1150 lines**

## 10. Implementation Order (for plan)

1. DB schema + migration
2. Abstract base + dataclasses
3. Refactor MoEmail into provider class
4. New CloudMailProvider with auth
5. Pool (round-robin + cooldown + manual override)
6. Replace `_generate_moemail_account` in main.py
7. REST endpoints (GET/POST/PATCH/DELETE/test)
8. Pydantic models
9. Frontend: provider management tab
10. Frontend: add-customer form (auto-rotate toggle + picker)
11. Frontend: customer detail rendering
12. Manual E2E against running backend
13. Update README

## 11. Success Criteria

- User can add N providers via UI
- Round-robin distributes new customers across providers
- Manual override works
- Pool survives provider failures (auto-skips errored providers)
- JWT auto-refresh works on cloud-mail
- All existing customer flows still work (no regression)
- Test coverage: ≥80% on new code paths
