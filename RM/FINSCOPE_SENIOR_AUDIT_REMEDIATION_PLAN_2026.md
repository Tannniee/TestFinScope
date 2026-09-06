# FinScope Senior Code Audit & Remediation Implementation Plan

**Repository:** `Tannniee/TestFinScope`  
**Audited branch:** `main`  
**Audited snapshot:** `8e130bca8c4eb499cb35853517bc93734339708f`  
**Audit date:** 2026-09-06  
**Primary target:** Windows 10/11, Python 3.10+, PyWebView/WebView2, SQLite  
**Purpose:** Implementation-ready senior engineering audit covering correctness, data integrity, security, analytics semantics, forecasting, frontend/backend contracts, operability, and maintainability.

---

## 1. How to use this document

This is not only a list of observations. Each finding is intended to become an implementation ticket or a small pull request.

Recommended workflow:

1. Freeze feature work until **Critical** findings are fixed.
2. Land the CI/bootstrap work first so every later fix is automatically verified.
3. Fix data-safety and domain-invariant issues before UI polish or refactors.
4. Add the regression test described in each finding **before or in the same PR** as the production fix.
5. Do not mark a finding complete until its acceptance criteria pass.
6. After all Critical + High items are closed, run the full regression, migration, restore, import, security, and historical replay suites before tagging the next release.

### Evidence labels

- **Confirmed static defect**: a concrete code path demonstrably violates the stated contract.
- **High-risk design defect**: the code structure permits data loss/corruption/race behavior and needs stress/failure-injection validation.
- **Contract mismatch**: two first-party modules disagree on payload, state, or semantics.
- **Hardening**: not necessarily failing today, but materially lowers release risk.

### Audit limitation

The audit is grounded in the `main` source snapshot above. The repository could not be checked out into the execution runtime used for this review, so the complete `pytest` suite was **not executed here**. Where a finding is runtime-sensitive, this document explicitly asks for a regression or stress test. Static defects such as the missing `Optional` import, API payload mismatch, unsupported `daily` recurrence path, ignored comparison parameters, and account-filter loss are directly visible in the source.

---

# 2. Executive summary

## Release recommendation

**Do not tag the current snapshot as a broadly compatible production release yet.**

The architecture is strong for a local finance application: exact integer storage, soft-delete semantics, double-entry transfers, explicit local API routing/capabilities, WAL-safe SQLite backup, replay-based forecasting, and a substantial regression suite are all good foundations. The remaining risk is concentrated in a smaller number of boundary problems:

- Python-version compatibility is currently inconsistent with the documented `Python 3.10+` contract.
- A destructive schema migration is not explicitly atomic.
- Restore and demo-reset operations need stronger exclusivity/data-loss safeguards.
- Domain invariants are enforced inconsistently across manual transactions, imports, recurring rules, categories, budgets, and historical analytics.
- Several frontend/backend contracts are out of sync.
- Some analytics modules report more certainty than their underlying data sufficiency supports.
- A few untrusted-content rendering and export paths bypass the otherwise-good escaping model.

## Finding counts

| Severity | Count | Release policy |
|---|---:|---|
| Critical | 2 | Must fix before release |
| High | 15 | Must fix before production-ready tag |
| Medium | 24 | Fix in the same hardening milestone where practical |
| Low | 9 | Schedule after correctness gates, unless touched by adjacent work |

---

# 3. Immediate release gates

The next production-ready tag should require all of the following:

- [ ] Application imports and starts successfully on Python **3.10, 3.11, 3.12, 3.13, and 3.14**.
- [ ] All database migrations pass happy-path, upgrade-path, rollback/failure-injection, and `PRAGMA integrity_check`.
- [ ] Restore is exclusive with respect to live DB operations and cannot silently lose writes.
- [ ] Transaction/category/recurring/budget domain invariants are centrally enforced.
- [ ] CSV import produces the same canonical merchant/category semantics as manual entry.
- [ ] Future-month analytics/forecast behavior is explicitly defined and tested.
- [ ] Historical reports reconcile regardless of whether categories/accounts are archived.
- [ ] All user-controlled HTML sinks and backup metadata rendering are escaped or DOM-created.
- [ ] Export session token is no longer placed in a URL.
- [ ] Full test suite passes in CI, including migration, import, restore, XSS, and forecast replay tests.

---

# 4. Critical findings

## FSC-C01 — Python 3.10–3.13 startup failure from unresolved `Optional`

**Severity:** Critical  
**Evidence:** Confirmed static defect  
**Primary file:** `app/backend/services/budget_service.py`  
**Propagation:** `app/backend/api/handler.py` imports `BudgetService`, so the failure can prevent application startup.

### Problem

`budget_service.py` imports:

```python
from typing import Dict, Any, List
```

but declares:

```python
def get_monthly_budget_status(
    month: str,
    account_id: Optional[int] = None
) -> Dict[str, Any]:
```

with no `Optional` in scope.

On Python versions where annotations are evaluated at function definition time, importing the module raises:

```text
NameError: name 'Optional' is not defined
```

This is particularly serious because the README advertises Python **3.10+** while the repository notes testing on Python 3.14. A newer interpreter can mask an annotation-resolution compatibility bug that older supported interpreters expose.

### Fix

Minimal fix:

```python
# app/backend/services/budget_service.py
from typing import Dict, Any, List, Optional
```

Recommended defensive project-wide policy:

```python
from __future__ import annotations
```

at the top of first-party Python modules **plus** correct typing imports. Do not rely on deferred annotations to hide missing names.

### Tests

Add a smoke-import test:

```python
# tests/test_import_smoke.py
def test_all_backend_modules_import():
    import app.backend.services.budget_service
    import app.backend.api.handler
    import app.backend.server
```

In CI, run:

```yaml
strategy:
  matrix:
    python-version: ["3.10", "3.11", "3.12", "3.13", "3.14"]
```

Also run:

```bash
python -m compileall -q app tests
python -c "from app.backend.api.handler import ApiHandler; print(ApiHandler())"
```

### Acceptance criteria

- App imports on all documented Python versions.
- `run.bat` reaches server startup without annotation errors.
- CI fails if any first-party module has an unresolved annotation/import.

---

## FSC-C02 — Migration 005 rebuild is not explicitly atomic

**Severity:** Critical  
**Evidence:** High-risk data-safety defect  
**Primary file:** `app/backend/database/migrations_runner.py`  
**Related:** `app/backend/database/schema.sql`, `app/backend/database/connection.py`

### Problem

Migration 005 rebuilds the `transactions` table using `conn.executescript()`:

1. `PRAGMA foreign_keys = OFF`
2. create `transactions_new`
3. copy data
4. drop `active_transactions`
5. `DROP TABLE transactions`
6. rename new table
7. recreate indexes/view
8. `PRAGMA foreign_keys = ON`

`run_migrations()` calls `conn.rollback()` if the migration function throws, but the migration script itself does not establish a clear explicit transaction around the destructive DDL.

A failure after `DROP TABLE transactions` but before the new table/view/index state is complete must never leave a partially migrated database. For a finance application, migration rollback needs to be proven, not assumed.

### Fix direction

Do not execute the destructive rebuild as an implicit multi-statement script. Make transaction boundaries explicit.

Suggested structure:

```python
def migration_005_enforce_table_constraints(conn: sqlite3.Connection):
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")

    try:
        conn.execute("BEGIN IMMEDIATE")

        conn.execute("""
            CREATE TABLE transactions_new (
                ...
            )
        """)

        conn.execute("""
            INSERT INTO transactions_new (...)
            SELECT ...
            FROM transactions
        """)

        old_count = conn.execute(
            "SELECT COUNT(*) FROM transactions"
        ).fetchone()[0]
        new_count = conn.execute(
            "SELECT COUNT(*) FROM transactions_new"
        ).fetchone()[0]

        if old_count != new_count:
            raise RuntimeError(
                f"Migration row-count mismatch: {old_count} != {new_count}"
            )

        conn.execute("DROP VIEW IF EXISTS active_transactions")
        conn.execute("DROP TABLE transactions")
        conn.execute(
            "ALTER TABLE transactions_new RENAME TO transactions"
        )

        # Recreate indexes/view here.
        ...

        fk_issues = conn.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        if fk_issues:
            raise RuntimeError(
                f"Foreign-key violations after migration: {fk_issues}"
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
```

Before applying a destructive migration in a user-facing release, create an automatic pre-migration snapshot or use SQLite's backup API.

### Required failure-injection tests

Create a test helper that raises after each stage:

```text
after CREATE transactions_new
after COPY
after DROP VIEW
after DROP old table
after RENAME
after index creation
```

After each injected failure:

- old DB must still open;
- transaction count and monetary totals must match;
- `PRAGMA integrity_check` must be `ok`;
- `PRAGMA foreign_key_check` must return no violations;
- migration version must not be recorded as applied.

### Acceptance criteria

A forced exception at any migration stage cannot lose or silently mutate user finance data.

---

# 5. High findings

## FSC-H01 — Restore is not exclusive with live reads/writes

**Severity:** High  
**Evidence:** High-risk concurrency/data-loss design  
**Files:** `app/backend/services/backup_service.py`, `app/backend/server.py`, `app/backend/database/connection.py`

### Problem

`ThreadingHTTPServer` can serve multiple requests while `BackupService.restore_backup()` swaps a validated snapshot into the live DB. There is no process-level maintenance/exclusive lock spanning ordinary API operations and the restore swap.

A write that commits while restore is replacing the DB can be lost even though both operations individually succeed.

### Fix direction

Introduce an application maintenance coordinator.

```python
# app/backend/database/maintenance.py
import threading
from contextlib import contextmanager

class MaintenanceCoordinator:
    def __init__(self):
        self._condition = threading.Condition()
        self._active_ops = 0
        self._maintenance = False

    @contextmanager
    def operation(self):
        with self._condition:
            while self._maintenance:
                self._condition.wait()
            self._active_ops += 1
        try:
            yield
        finally:
            with self._condition:
                self._active_ops -= 1
                self._condition.notify_all()

    @contextmanager
    def exclusive(self):
        with self._condition:
            self._maintenance = True
            while self._active_ops:
                self._condition.wait()
        try:
            yield
        finally:
            with self._condition:
                self._maintenance = False
                self._condition.notify_all()
```

Wrap normal API execution in `operation()` and restore/destructive reset in `exclusive()`.

### Tests

- Start N writer threads, then request restore.
- Assert no write is acknowledged and later missing.
- Assert writes are blocked/rejected with a clear maintenance status.
- Test restore failure rollback while concurrent clients retry.

---

## FSC-H02 — Transaction type and category type can contradict each other

**Severity:** High  
**Evidence:** Confirmed domain-integrity defect  
**Files:** `app/backend/repositories/transaction_repo.py`, `app/backend/repositories/category_repo.py`, `app/backend/domain/validators.py`

### Problem

The current code allows:

```text
expense transaction -> income category
income transaction  -> expense category
```

because transaction creation validates transaction type and amount but not the referenced category's semantic type.

`CategoryRepository.update()` can also change `categories.type` after transactions/budgets already reference the category, retroactively altering reporting semantics.

### Fix

Centralize cross-entity validation:

```python
def validate_category_for_transaction(
    conn,
    category_id: Optional[int],
    tx_type: str,
) -> Optional[int]:
    if category_id is None:
        return None

    row = conn.execute(
        "SELECT id, type, is_archived FROM categories WHERE id = ?",
        (category_id,),
    ).fetchone()

    if not row:
        raise ValueError("Category does not exist.")

    expected = "expense" if tx_type == "refund" else tx_type

    if expected in ("expense", "income") and row["type"] != expected:
        raise ValueError(
            f"{tx_type} transactions require a {expected} category."
        )

    if row["is_archived"]:
        raise ValueError("Archived categories cannot be assigned to new transactions.")

    return category_id
```

Call it from transaction create/update, refund flows, recurring rules, CSV import, and budget creation.

For category type edits, block mutation once financial history or budgets exist unless a dedicated migration workflow is used.

### Tests

- expense → income category rejected;
- income → expense category rejected;
- refund → income category rejected;
- category type mutation blocked once history/budget exists;
- archived historical category remains queryable but not assignable.

---

## FSC-H03 — CSV import assigns unknown rows to the first expense category

**Severity:** High  
**Evidence:** Confirmed data-quality defect  
**File:** `app/backend/services/import_service.py`

### Problem

`commit_import()` chooses the first expense category by ID as the fallback. An unknown row can therefore be stored as a real category such as **Groceries** simply because it happens to have the lowest ID.

The same fallback can be applied to imported income, creating an income transaction linked to an expense category.

Although `needs_review=1` is set, the incorrect category already contaminates analytics before review.

### Fix

Use semantic fallbacks:

```python
def resolve_import_fallback_category(conn, tx_type: str) -> Optional[int]:
    if tx_type == "expense":
        row = conn.execute("""
            SELECT id FROM categories
            WHERE name = 'Uncategorized' AND type = 'expense'
            LIMIT 1
        """).fetchone()
        return row["id"] if row else None

    if tx_type == "income":
        row = conn.execute("""
            SELECT id FROM categories
            WHERE name = 'Other Income' AND type = 'income'
            LIMIT 1
        """).fetchone()
        return row["id"] if row else None

    return None
```

No imported row should be categorized by insertion order.

---

## FSC-H04 — CSV import bypasses canonical merchant normalization and merchant IDs

**Severity:** High  
**Evidence:** Confirmed semantic divergence  
**Files:** `app/backend/services/import_service.py`, `app/backend/services/merchant_service.py`, `app/backend/repositories/transaction_repo.py`

### Problem

Manual entry normalizes merchant names, resolves/creates a merchant row, stores `merchant_id`, and learns defaults. Import uses raw payee data and does not consistently produce the same merchant identity.

This splits merchant analytics and weakens autocomplete, categorization memory, anomaly baselines, and drilldowns.

### Fix

Refactor merchant resolution so import can perform it inside its existing DB transaction:

```python
@staticmethod
def get_or_create_merchant_in_conn(
    conn,
    raw_name: str,
    *,
    category_id=None,
    account_id=None,
    essentiality=None,
):
    canonical = normalize_merchant_name(raw_name)
    if not canonical:
        return None, ""

    conn.execute("""
        INSERT INTO merchants (
            name, default_category_id,
            preferred_account_id, default_essentiality
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO NOTHING
    """, (
        canonical,
        category_id,
        account_id,
        essentiality or "discretionary",
    ))

    row = conn.execute(
        "SELECT id FROM merchants WHERE name = ?",
        (canonical,),
    ).fetchone()

    return row["id"], canonical
```

Import should store canonical `merchant_name` and `merchant_id`.

---

## FSC-H05 — Payee autocomplete frontend/backend contract is broken

**Severity:** High  
**Evidence:** Confirmed contract mismatch  
**Files:** `app/frontend/assets/js/components/modals.js`, `app/frontend/assets/js/api.js`, `app/backend/api/handler.py`, `app/backend/services/merchant_service.py`

### Problem A: typed suggestions

Frontend expects:

```javascript
res?.suggestions
```

while the backend returns a list directly. Typed autocomplete therefore resolves to an empty array.

### Problem B: recent-payee property names

Frontend maps `default_category_id` / `default_essentiality`, while backend recent-payee data uses `category_id` / `essentiality`.

### Fix

Create one canonical DTO or compatibility normalizer:

```javascript
function normalizeSuggestion(s) {
  return {
    name: s.name || s.merchant_name || '',
    default_category_id:
      s.default_category_id ?? s.category_id ?? null,
    category_name: s.category_name ?? null,
    preferred_account_id:
      s.preferred_account_id ?? s.account_id ?? null,
    default_essentiality:
      s.default_essentiality ?? s.essentiality ?? 'discretionary',
    confidence: s.confidence ?? 'low',
    tx_count: s.transaction_count ?? 0,
  };
}

const raw = await api.getMerchantSuggestions(query, 6);
const rows = Array.isArray(raw) ? raw : (raw?.suggestions ?? []);
this.currentSuggestions = rows.map(normalizeSuggestion);
```

Add API contract tests for typed and recent suggestions.

---

## FSC-H06 — “Optional” unlinked refund path can never succeed

**Severity:** High  
**Evidence:** Confirmed contract mismatch  
**Files:** `app/frontend/index.html`, `app/frontend/assets/js/components/modals.js`, `app/backend/repositories/transaction_repo.py`

### Problem

UI says “Original Transaction ID (Optional)”. Without an ID, the frontend calls generic transaction creation with `transaction_type: 'refund'`, but `TransactionRepository.create()` explicitly rejects generic refunds.

### Fix decision

Recommended for v1: require linkage.

- Change the original transaction field to required.
- Prefer search/select over manual ID typing.
- Remove the generic refund creation branch.
- Keep cumulative refund enforcement.

If unlinked refunds are needed, add an explicit `create_unlinked_refund()` domain operation with separate audit semantics instead of bypassing the refund lifecycle.

---

## FSC-H07 — `daily` recurring rules are validated but executed as monthly

**Severity:** High  
**Evidence:** Confirmed logic defect  
**Files:** `app/backend/domain/validators.py`, `app/backend/analytics/recurring_schedule.py`, `app/backend/services/recurring_service.py`

Validator accepts `"daily"`, but the occurrence engine has no daily branch; unsupported values fall through to monthly behavior.

### Fix

```python
if freq in ("daily", "day"):
    return d + timedelta(days=step_idx)
elif freq in ("weekly", "week"):
    return d + timedelta(days=7 * step_idx)
...
else:
    raise ValueError(f"Unsupported recurring frequency: {frequency}")
```

Keep allowed frequencies in one shared definition and table-test every frequency across month/leap-year boundaries.

---

## FSC-H08 — Future months are marked “completed”; future forecast collapses

**Severity:** High  
**Evidence:** Confirmed temporal-semantics defect  
**Files:** `app/backend/analytics/context.py`, `app/backend/analytics/forecasting.py`, `app/frontend/assets/js/state.js`

### Problem

Every non-current month is marked completed, including future months. Forecasting then treats a future month like a completed historical month and defaults elapsed days to month-end, leaving zero remaining days.

### Fix

Model past/current/future explicitly:

```python
selected_start = date(year, m, 1)
today_start = ref_today.replace(day=1)

is_past = selected_start < today_start
is_current = selected_start == today_start
is_future = selected_start > today_start
is_completed = is_past
```

Prefer an explicit:

```python
period_state: Literal["past", "current", "future"]
```

For future forecast without an explicit cutoff:

```text
elapsed_day = 0
actual_to_date = 0
upcoming recurring = full target month
variable estimate = full target month
```

Test next month and year rollover.

---

## FSC-H09 — `comparison_month` and `max_day` parameters are effectively ignored

**Severity:** High  
**Evidence:** Confirmed API/analytics contract defect  
**Files:** `app/backend/services/analytics_service.py`, `app/backend/analytics/changes.py`, `app/backend/analytics/context.py`, `app/backend/api/handler.py`

### Problem

`analyze_changes()` accepts explicit comparison inputs but actual comparison boundaries are derived from the context's default comparison mode. Explicit inputs therefore do not reliably affect results.

### Fix

Either remove unsupported parameters or make them first-class inputs to `resolve_analytics_context()`.

Required tests:

- Sep 2026 vs Jul 2026;
- MTD day 10 vs prior month day 10;
- explicit `max_day`;
- previous-year same-period.

---

## FSC-H10 — Archiving a category can rewrite historical analytics

**Severity:** High  
**Evidence:** Confirmed reporting-consistency defect  
**Files:** `app/backend/analytics/changes.py`, `app/backend/analytics/forecasting.py`, `app/backend/repositories/category_repo.py`

### Problem

Historical category analytics filters `c.is_archived = 0`. Archiving a category leaves its transactions intact but removes the category from selected historical analytics.

Archiving should stop future selection, not erase past economic facts.

### Fix

Include archived categories whenever period data/budget/history references them.

Required exact-cent invariant:

```text
sum(category net spend) == overall net spend
```

for all archive states.

---

## FSC-H11 — Calendar drawer drops global account filter and refund semantics

**Severity:** High  
**Evidence:** Confirmed UI/data contract defect  
**File:** `app/frontend/assets/js/pages/calendar.js`

Calendar grid includes `state.accountId`; drawer transaction query does not. The drawer also totals only income/expense, while backend calendar logic treats refunds as expense offsets.

### Minimal fix

```javascript
const res = await api.getTransactions({
  start_date: dateStr,
  end_date: dateStr,
  account_id: state.accountId,
  limit: 100,
});
```

Better: backend `get_day_details()` returning canonical totals + rows so the frontend cannot reimplement P&L semantics differently.

---

## FSC-H12 — CSV export session token is placed in URL

**Severity:** High  
**Evidence:** Confirmed credential-exposure design  
**Files:** `app/frontend/assets/js/pages/reports.js`, `app/backend/server.py`

### Problem

Export navigates to `/api/export_csv?token=...`. The query token can appear in browser history and other URL-visible surfaces.

### Fix

Use `fetch()` with `X-FinScope-Token`, convert response to Blob, and download locally. Remove query-token fallback server-side.

```javascript
const token = await api.getSessionToken();
const response = await fetch('/api/export_csv?...', {
  headers: { 'X-FinScope-Token': token },
});
const blob = await response.blob();
```

Acceptance: no session token ever appears in export URL/history.

---

## FSC-H13 — Stored XSS sink in topbar account dropdown

**Severity:** High  
**Evidence:** Confirmed unescaped user-controlled HTML sink  
**File:** `app/frontend/index.html`

Account names are inserted into `innerHTML` without escaping.

### Fix

Use DOM options:

```javascript
accSelect.replaceChildren(new Option('All Accounts', ''));

for (const account of state.accounts) {
  accSelect.add(
    new Option(
      String(account.name ?? ''),
      String(account.id)
    )
  );
}
```

Regression payload:

```text
"></option><img src=x onerror="window.__xss=1">
```

must render as inert text.

---

## FSC-H14 — Backup metadata is rendered as trusted HTML

**Severity:** High  
**Evidence:** Confirmed untrusted-metadata sink  
**Files:** `app/frontend/assets/js/pages/settings.js`, `app/backend/services/backup_service.py`

`metadata.json` content from backup archives can flow into settings table template strings. Treat archive metadata as external input.

### Fix

Backend schema/type/length validation + frontend DOM `textContent`.

Never interpolate arbitrary filepath/metadata directly into HTML attributes.

Add a malicious backup metadata XSS regression test.

---

## FSC-H15 — `--seed` can wipe real transactions/budgets without a safety backup

**Severity:** High  
**Evidence:** Confirmed destructive CLI behavior  
**Files:** `app/main.py`, `app/backend/services/sample_data.py`, `run.bat`

`--seed` calls `seed_sample_data(clear_existing=True)`, which deletes transactions and budgets. CLI wording does not clearly communicate destructive reset and no backup is created.

### Fix

Split commands:

```text
--seed                 non-destructive / empty-profile only
--reset-demo-data      explicit destructive behavior
--yes-really-reset-data  required noninteractive confirmation
```

Always create a verified safety backup before destructive reset.

---

# 6. Medium findings

## FSC-M01 — Backup filenames/temp snapshots can collide under concurrent calls

**File:** `app/backend/services/backup_service.py`

Second-resolution timestamps can collide. Use UUID/tempfile names and add a concurrent backup test.

---

## FSC-M02 — Restore accepts oversized/zip-bomb members without an uncompressed-size cap

**File:** `app/backend/services/backup_service.py`

`zf.read("finance.db")` loads the entire uncompressed member into memory.

Use `ZipInfo.file_size`, a configured maximum, compression-ratio guard, and streamed extraction.

---

## FSC-M03 — CSV export allows spreadsheet formula injection

**File:** `app/backend/services/backup_service.py`

Text fields beginning with `=`, `+`, `-`, `@` can be interpreted as formulas by spreadsheet software.

```python
DANGEROUS_CSV_PREFIXES = ("=", "+", "-", "@")

def safe_csv_text(value):
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(DANGEROUS_CSV_PREFIXES) else text
```

Apply to textual export columns.

---

## FSC-M04 — Fingerprint reports availability despite insufficient data

**File:** `app/backend/analytics/fingerprint.py`

`check_data_sufficiency()` can return unavailable, but nonempty fingerprints later force `out["available"] = True`.

No consecutive-month data also defaults persistence to `1.0`, yielding artificial 100% consistency.

### Fix

```python
out["available"] = sufficiency.available

if len(ordered_m) < 2:
    persistence_score = None
    consistency_score = None
```

Use “Insufficient history” instead of invented certainty.

---

## FSC-M05 — Fingerprint current-month weekday averages include future calendar days

**File:** `app/backend/analytics/fingerprint.py`

Current-month calendar occurrence denominators extend through month-end, diluting average daily spend with future days. Recent months are also selected as distinct transaction months rather than contiguous calendar months.

Clamp to effective as-of date and use a dense contiguous month range.

---

## FSC-M06 — Rolling-metric sufficiency uses month count as transaction count

**File:** `app/backend/services/analytics_service.py`

`check_data_sufficiency("rolling_3m", len(hist), len(hist))` passes months for both sample size and history. Query real transaction sample count. Mark current month as partial in period series.

---

## FSC-M07 — Anomaly engine documents an overall fallback but never uses it

**File:** `app/backend/analytics/anomalies.py`

The code collects `overall_history` but baseline selection only uses merchant then category. Category monthly history also omits zero months and compares current MTD to historical full-month totals.

Implement overall baseline, dense zero months, and matched-period comparisons.

---

## FSC-M08 — Transfer update/validation tolerates corrupted group roles

**File:** `app/backend/services/transfer_service.py`

If transfer roles are invalid/missing, update falls back to positional legs. Validation does not strictly enforce deletion parity.

Create a strict `_load_transfer_pair()` requiring:

```text
exactly 2 rows
roles == {source, destination}
same group ID
same amount/date linkage contract
opposite linked IDs
same deletion state
transaction_type == transfer
```

Reject corruption instead of guessing.

---

## FSC-M09 — Review queue ignores selected account

**Files:** `app/frontend/assets/js/pages/transactions.js`, `app/backend/repositories/transaction_repo.py`, `app/backend/api/handler.py`

Add `account_id` to review queue API and propagate active filter.

---

## FSC-M10 — Transfer rows show the wrong sign and transfer edit lacks destination context

**Files:** `app/frontend/assets/js/pages/transactions.js`, `app/frontend/assets/js/components/modals.js`

Destination transfer legs currently use the generic negative sign.

```javascript
const positive =
  tx.transaction_type === 'income' ||
  tx.transaction_type === 'refund' ||
  (tx.transaction_type === 'transfer' &&
   tx.transfer_role === 'destination');
```

Add a `get_transfer_group` DTO for edit UI.

---

## FSC-M11 — Recurring paid-match can match any blank-description transaction

**File:** `app/backend/services/recurring_service.py`

`"" in rule_name` is true, so a blank payee/description can produce a false match.

```python
name_match = bool(rule_name and tx_desc) and (
    rule_name in tx_desc or tx_desc in rule_name
)
```

Prefer normalized merchant + amount + date tolerance.

---

## FSC-M12 — Recurring rules accept unsupported transaction types

**Files:** `app/backend/services/recurring_service.py`, `app/backend/domain/validators.py`, `app/backend/analytics/forecasting.py`

Generic transaction validation permits transfer/refund/adjustment recurring rules, while forecasting only has meaningful recurring expense/income handling.

Add `VALID_RECURRING_TRANSACTION_TYPES = {"expense", "income"}`.

---

## FSC-M13 — Editing an adjustment can incorrectly reject a negative amount

**File:** `app/backend/repositories/transaction_repo.py`

Amount validation uses only incoming `data.get("transaction_type")`. If persisted type is adjustment but edit payload omits type, negative amount is rejected.

Resolve `effective_type = incoming_type or existing_type`.

---

## FSC-M14 — Confirmed review does not reliably re-learn merchant defaults

**File:** `app/backend/services/merchant_service.py`

Merchant category defaults only update when empty. User correction through review should be an authoritative overwrite.

Separate merchant creation from `learn_defaults(..., overwrite=True)`.

---

## FSC-M15 — Merchant creation uses check-then-insert under a threaded server

**File:** `app/backend/services/merchant_service.py`

Concurrent first-use of the same merchant can race on unique name. Use `INSERT ... ON CONFLICT DO NOTHING` then select. Replace per-suggestion N+1 history queries with aggregation.

---

## FSC-M16 — Forecast replay caches are unbounded and failures can degrade silently

**Files:** `app/backend/analytics/forecast_replay.py`, `app/backend/analytics/forecasting.py`, `app/backend/analytics/insight_ranker.py`

Cache key includes revision/cutoff, so old heavy entries remain after mutations. Live replay errors can be swallowed and silently fall back.

Use bounded LRU, stale-revision cleanup, single-flight per key, logging, and explicit degraded-mode diagnostics.

---

## FSC-M17 — Money conversion is duplicated and non-finite values are not centrally rejected

**Files:** validators, transfer/account/repository/import paths

Centralize on `Decimal`, reject non-finite values, and enforce one rounding policy.

```python
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

def money_to_minor(value, *, allow_negative=False, scale=2):
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Amount must be a valid finite number.")

    if not dec.is_finite():
        raise ValueError("Amount must be finite.")

    if not allow_negative and dec <= 0:
        raise ValueError("Amount must be greater than zero.")

    factor = Decimal(10) ** scale
    return int((dec * factor).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    ))
```

---

## FSC-M18 — Budget API lacks canonical month/category validation

**Files:** `app/backend/repositories/budget_repo.py`, `app/backend/services/budget_service.py`, `app/frontend/assets/js/components/modals.js`

Validate `YYYY-MM`, expense-category type, existence, and archive state. Decide whether zero means delete or invalid; make frontend/backend agree.

---

## FSC-M19 — Month/date validation is inconsistent and sometimes silently falls back

**Files:** analytics context, forecast request, services accepting `month`

Add one `validate_month()` and return 422 for malformed client periods rather than silently changing periods.

---

## FSC-M20 — Account/category delete can report success for nonexistent IDs

**Files:** `account_repo.py`, `category_repo.py`

Return `rowcount > 0` or a structured `{changed, action}` result.

---

## FSC-M21 — Category breakdown uses lexical `MAX(essentiality)`

**File:** `app/backend/analytics/aggregates.py`

`MAX()` on string labels is not a meaningful dominant classification. Aggregate spend by essentiality or choose dominant class by explicit spend weight.

---

## FSC-M22 — Storage health count includes soft-deleted rows

**File:** `app/backend/services/backup_service.py`

Expose active, deleted, and total row counts separately so health UI matches analytics semantics.

---

## FSC-M23 — Demo reset leaves merchant/recurring/insight intelligence behind

**File:** `app/backend/services/sample_data.py`

A “clear” reset deletes transactions/budgets but can leave learned merchant defaults, recurring rules/versions, insight history, accounts, and categories.

Define reset scope explicitly or use a dedicated demo profile/data directory.

---

## FSC-M24 — No automated CI workflow at audited snapshot

**Repository root**

Given documented multi-version support and substantial tests, this is a release risk.

Minimum CI:

```yaml
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: windows-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13", "3.14"]

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m pip install -r requirements-dev.txt
      - run: python -m compileall -q app tests
      - run: pytest -q
```

---

# 7. Low findings / engineering debt

## FSC-L01 — README storage path is stale

README describes `data/finance.db`; runtime Windows storage is `%LOCALAPPDATA%\FinScope\finance.db`, with user-local share on non-Windows.

---

## FSC-L02 — Large frontend page modules are change-risk hotspots

Refactor `analytics.js`, `settings.js`, `overview.js`, and `modals.js` by responsibility, separating fetch/state transformation/rendering.

---

## FSC-L03 — Template-string `innerHTML` remains too easy to misuse

Even though `escapeHtml()` is mostly used well, the account dropdown and backup metadata bugs show the approach is fragile. Prefer DOM node creation for user-controlled content.

---

## FSC-L04 — Category icon values should be allowlisted

Color is validated, icon is arbitrary. Validate against supported Lucide icon names and fallback to `tag`.

---

## FSC-L05 — Merchant search should clamp `limit` and define LIKE wildcard behavior

Clamp user-provided limits and decide whether `%`/`_` are literals or wildcards.

---

## FSC-L06 — Privacy mode should be described as screen masking, not data security

It hides values visually but does not encrypt DB, backup, CSV, memory, or local API responses.

---

## FSC-L07 — Supported currencies use a fixed x100 internal scale

Current arithmetic is internally consistent, but “minor units” is ambiguous for currencies such as JPY/VND. Document fixed internal scale or move to ISO currency-specific scales.

---

## FSC-L08 — `reloadMetadata()` swallows bootstrap failures

**File:** `app/frontend/assets/js/state.js`

Propagate/bootstrap a retryable error state instead of continuing with empty metadata.

---

## FSC-L09 — Insight persistence failures are silently ignored

**File:** `app/backend/analytics/insight_ranker.py`

Keep display resilient, but log persistence failures so novelty/dismissal behavior can be diagnosed.

---

# 8. Cross-cutting patch architecture

Rather than fixing each symptom independently, introduce five small shared layers.

## 8.1 Canonical validation module

Extend `app/backend/domain/validators.py` with:

```text
validate_month
validate_time_hhmm
money_to_minor
validate_category_for_transaction
validate_budget_category
validate_recurring_transaction_type
validate_recurring_frequency
validate_account_exists
```

Rule: no repository/service independently reimplements basic date/money/category validation.

---

## 8.2 Canonical finance semantics DTO

Frontend should not infer signs/totals ad hoc.

Backend or shared JS should expose semantics such as:

```json
{
  "transaction_type": "transfer",
  "transfer_role": "destination",
  "display_sign": "+",
  "pnl_effect_minor": 0,
  "cash_effect_minor": 5000
}
```

This avoids calendar/transaction/report divergence.

---

## 8.3 Maintenance/exclusive-operation coordinator

Use one app-level coordinator for restore, destructive demo reset, future migration/maintenance operations, and any live DB replacement.

---

## 8.4 Canonical frontend API DTO adapters

Near `api.js`, normalize backend payloads once:

```text
normalizeMerchantSuggestion
normalizeTransaction
normalizeBackupMetadata
normalizeForecast
```

UI components should not know historical aliases.

---

## 8.5 Safe DOM rendering helpers

Example:

```javascript
export function replaceOptions(
  select,
  items,
  {
    includeBlank = null,
    value = x => x.id,
    label = x => x.name,
  } = {}
) {
  const nodes = [];

  if (includeBlank) {
    nodes.push(new Option(includeBlank, ''));
  }

  for (const item of items) {
    nodes.push(
      new Option(
        String(label(item) ?? ''),
        String(value(item) ?? '')
      )
    );
  }

  select.replaceChildren(...nodes);
}
```

Use text nodes for all user-controlled data.

---

# 9. Proposed implementation phases and PR order

## Phase 0 — Establish trustworthy build signal

### PR 0.1 — CI and smoke imports

Implements FSC-C01 and FSC-M24.

Do this first.

---

## Phase 1 — Protect user data

### PR 1.1 — Atomic migration framework

Implements FSC-C02 with pre-migration backup and failure injection.

### PR 1.2 — Maintenance lock + restore hardening

Implements FSC-H01, FSC-M01, FSC-M02.

### PR 1.3 — Destructive demo reset safety

Implements FSC-H15, FSC-M23.

**Exit criterion:** no migration/restore/reset operation can silently lose acknowledged user writes.

---

## Phase 2 — Enforce the financial domain

### PR 2.1 — Central validators and money conversion

Implements FSC-H02, FSC-M17, FSC-M18, FSC-M19.

### PR 2.2 — Transfer/refund invariants

Implements FSC-H06, FSC-M08, FSC-M10, FSC-M13.

### PR 2.3 — Recurring rule contract

Implements FSC-H07, FSC-M11, FSC-M12.

**Exit criterion:** impossible finance states are rejected before persistence.

---

## Phase 3 — Repair import and merchant intelligence

### PR 3.1 — Canonical import categories

Implements FSC-H03.

### PR 3.2 — Canonical merchant resolution

Implements FSC-H04, FSC-M14, FSC-M15.

### PR 3.3 — Autocomplete contract

Implements FSC-H05.

**Exit criterion:** manual and CSV entry of the same economic transaction produce equivalent canonical data.

---

## Phase 4 — Analytics correctness

### PR 4.1 — Canonical period states/comparisons

Implements FSC-H08, FSC-H09, FSC-M19.

### PR 4.2 — Historical archive invariance

Implements FSC-H10.

### PR 4.3 — Fingerprint/rolling sufficiency

Implements FSC-M04, FSC-M05, FSC-M06.

### PR 4.4 — Anomaly/replay correctness and observability

Implements FSC-M07, FSC-M16, FSC-L09.

**Exit criterion:** analytics expose honest sufficiency and reconcile to canonical finance totals.

---

## Phase 5 — Frontend/security hardening

### PR 5.1 — Calendar/review/transfer scope consistency

Implements FSC-H11, FSC-M09, FSC-M10.

### PR 5.2 — Safe export and CSV

Implements FSC-H12, FSC-M03.

### PR 5.3 — Stored-XSS cleanup

Implements FSC-H13, FSC-H14, FSC-L03, FSC-L04.

---

## Phase 6 — Maintenance/documentation

Implements FSC-L01, L02, L05, L06, L07, L08, and FSC-M20/M21/M22.

---

# 10. Required regression test plan

## 10.1 Startup/compatibility

Run on Python 3.10–3.14:

```bash
python -m compileall -q app tests
python -c "import app.main"
python -c "from app.backend.api.handler import ApiHandler"
pytest -q
```

---

## 10.2 Migration

For every supported historical schema version:

```text
old DB fixture
-> backup
-> migrate
-> integrity_check
-> foreign_key_check
-> financial reconciliation
-> close/reopen
```

Inject failure after every destructive migration stage.

---

## 10.3 Finance invariants

| Operation | Invariant |
|---|---|
| expense | positive amount, expense category |
| income | positive amount, income category |
| refund | linked expense, cumulative refund <= original |
| transfer | exactly two opposite roles, equal amount, different accounts |
| adjustment | explicitly signed |
| recurring expense | supported frequency + expense category |
| recurring income | supported frequency + income category |

---

## 10.4 Import equivalence

For the same transaction, manual entry and CSV import must agree on:

```text
transaction_type
amount_minor
canonical merchant_name
merchant_id
category semantic type
essentiality
account
review state
analytics contribution
```

Include duplicate detection and merchant name variants.

---

## 10.5 Security

Stored-XSS payloads in:

```text
account name
category name
merchant
note
backup metadata
CSV description
```

CSV formula payloads in export.

Export token must never appear in URL.

Test malformed and oversized backups.

---

## 10.6 Analytics reconciliation

For every month/account filter:

```text
total net spend
== sum category net spend
== report expense
== calendar daily net-expense sum
```

Transfers must be P&L-neutral.

Archive state must not change historical totals.

---

## 10.7 Forecast point-in-time

At replay origin `T`:

- no transaction after `T` influences features;
- no recurring rule version after `T` influences forecast;
- future target starts at elapsed day 0;
- daily/weekly/monthly schedules are exact;
- model selection uses only prior completed origins;
- stale cache revisions are not reused.

---

## 10.8 Concurrency

Stress:

```text
create transaction + backup
create transaction + restore
two simultaneous backups
two simultaneous merchant first-use creates
rapid frontend navigation/filter requests
```

No acknowledged write may disappear.

---

# 11. File-by-file audit coverage matrix

This matrix maps first-party runtime files to findings or “no new blocking defect identified” from this static pass. Vendor libraries and purely visual CSS assets were not re-audited as third-party source.

## Root / bootstrap

| File | Audit result |
|---|---|
| `README.md` | FSC-L01; runtime contract relevant to FSC-C01 |
| `requirements.txt` | Add CI compatibility validation |
| `requirements-dev.txt` | FSC-M24 |
| `run.bat` | FSC-H15 context |
| `app/main.py` | FSC-H15 |
| `.gitignore` | No blocking defect identified |

## Backend configuration / database

| File | Audit result |
|---|---|
| `app/backend/config.py` | FSC-L01 documentation drift |
| `app/backend/database/connection.py` | FSC-H01 maintenance coordination |
| `app/backend/database/migrations_runner.py` | FSC-C02 |
| `app/backend/database/schema.sql` | Align stronger domain constraints where possible |

## Domain / repositories

| File | Audit result |
|---|---|
| `app/backend/domain/validators.py` | H02, H07, M17, M18, M19 |
| `app/backend/repositories/account_repo.py` | M17, M20 |
| `app/backend/repositories/category_repo.py` | H02, M20, L04 |
| `app/backend/repositories/transaction_repo.py` | H02, H06, M13 |
| `app/backend/repositories/budget_repo.py` | M18 |

## Services

| File | Audit result |
|---|---|
| `app/backend/services/analytics_service.py` | M06; H09 comparison path |
| `app/backend/services/backup_service.py` | H01, M01, M02, M03, M22 |
| `app/backend/services/budget_service.py` | C01, M18 |
| `app/backend/services/import_service.py` | H03, H04 |
| `app/backend/services/merchant_service.py` | H04, M14, M15, L05 |
| `app/backend/services/recurring_service.py` | H07, M11, M12 |
| `app/backend/services/sample_data.py` | H15, M23 |
| `app/backend/services/settings_service.py` | No blocking defect identified; retain currency-change invariant tests |
| `app/backend/services/transfer_service.py` | M08, M17 |

## API / server

| File | Audit result |
|---|---|
| `app/backend/api/handler.py` | Contract surface for H05, H09, M09 |
| `app/backend/server.py` | Existing explicit route registry/Host/Origin/token controls are good; H01/H12 remain |

## Analytics core

| File | Audit result |
|---|---|
| `app/backend/analytics/aggregates.py` | M21 |
| `app/backend/analytics/anomalies.py` | M07 |
| `app/backend/analytics/backtesting.py` | No new blocking defect identified |
| `app/backend/analytics/changes.py` | H09, H10 |
| `app/backend/analytics/context.py` | H08, H09, M19 |
| `app/backend/analytics/fingerprint.py` | M04, M05 |
| `app/backend/analytics/forecast_replay.py` | M16 |
| `app/backend/analytics/forecasting.py` | H08, H10, M16 |
| `app/backend/analytics/insight_history.py` | No new blocking defect identified |
| `app/backend/analytics/insight_ranker.py` | L09 |
| `app/backend/analytics/insight_rules.py` | No new blocking defect; relies on corrected upstream analytics |
| `app/backend/analytics/period_series.py` | Good dense-series primitive; callers need correct coverage parameters |
| `app/backend/analytics/reconciliation.py` | Good invariant utility; expand use in regression gates |
| `app/backend/analytics/recurring_schedule.py` | H07 |
| `app/backend/analytics/rolling.py` | No blocking defect identified in math primitives |
| `app/backend/analytics/semantics.py` | Good canonical P&L primitives; frontend should reuse semantics |

## Forecast strategies

| File | Audit result |
|---|---|
| `forecast_strategies/base.py` | No blocking defect identified |
| `forecast_strategies/config.py` | No blocking defect identified |
| `forecast_strategies/context.py` | No blocking defect identified; depends on correct cutoff |
| `forecast_strategies/current_pace.py` | Future-period problem is upstream H08 |
| `forecast_strategies/recent_median.py` | No new blocking defect identified |
| `forecast_strategies/robust_weekly.py` | No new blocking defect identified |
| `forecast_strategies/seasonal_naive.py` | No new blocking defect identified |
| `forecast_strategies/weekday_hybrid.py` | No new blocking defect identified |
| `forecast_strategies/selector.py` | Selection guardrails sound in static pass |
| `forecast_strategies/series.py` | No blocking defect identified |
| `forecast_strategies/request.py` | M19 |
| `forecast_strategies/registry.py` | No blocking defect identified |
| `forecast_strategies/scoring.py` | No blocking defect identified in static pass |

## Frontend

| File | Audit result |
|---|---|
| `app/frontend/index.html` | H13 |
| `assets/js/api.js` | Contract normalization for H05/H12 |
| `assets/js/router.js` | Abort/generation stale-render protection is good |
| `assets/js/state.js` | L08; future navigation exposes H08 |
| `assets/js/utils.js` | `escapeHtml` implementation is good |
| `assets/js/components/modals.js` | H05, H06, M10, M18 |
| `assets/js/components/toast.js` | Good `textContent` usage |
| `assets/js/pages/transactions.js` | M09, M10 |
| `assets/js/pages/calendar.js` | H11 |
| `assets/js/pages/budget.js` | L03/L04; correctness depends on M18 |
| `assets/js/pages/reports.js` | H12 |
| `assets/js/pages/import.js` | Backend H03/H04; escaping in inspected path generally good |
| `assets/js/pages/settings.js` | H14, L03 |
| `assets/js/pages/overview.js` | No new blocking defect in inspected path |
| `assets/js/pages/analytics.js` | L02; correctness depends on upstream analytics |
| chart helper modules | No release-blocking defect identified in static architecture pass |

## Tests

The repository contains substantial core/analytics/safety/hardening/forecast tests. Add dedicated regressions:

```text
tests/test_import_smoke.py
tests/test_domain_invariants.py
tests/test_migration_failure_atomicity.py
tests/test_restore_concurrency.py
tests/test_import_equivalence.py
tests/test_recurring_contract.py
tests/test_future_periods.py
tests/test_archive_invariance.py
tests/test_frontend_api_contracts.py
tests/test_export_security.py
```

---

# 12. Suggested implementation tracker

| ID | Severity | Area | Dependency | Target PR | Status |
|---|---|---|---|---|---|
| FSC-C01 | Critical | Backend/CI | none | PR 0.1 | ☐ |
| FSC-C02 | Critical | Database | CI | PR 1.1 | ☐ |
| FSC-H01 | High | DB/Server | CI | PR 1.2 | ☐ |
| FSC-H02 | High | Domain | CI | PR 2.1 | ☐ |
| FSC-H03 | High | Import | H02 | PR 3.1 | ☐ |
| FSC-H04 | High | Import/Merchant | H02 | PR 3.2 | ☐ |
| FSC-H05 | High | Frontend/API | none | PR 3.3 | ☐ |
| FSC-H06 | High | Refund | H02 | PR 2.2 | ☐ |
| FSC-H07 | High | Recurring | validators | PR 2.3 | ☐ |
| FSC-H08 | High | Analytics/Forecast | validation | PR 4.1 | ☐ |
| FSC-H09 | High | Analytics | context | PR 4.1 | ☐ |
| FSC-H10 | High | Analytics | domain | PR 4.2 | ☐ |
| FSC-H11 | High | Frontend/API | semantics | PR 5.1 | ☐ |
| FSC-H12 | High | Security/Export | none | PR 5.2 | ☐ |
| FSC-H13 | High | Frontend Security | none | PR 5.3 | ☐ |
| FSC-H14 | High | Backup/UI Security | M02 | PR 5.3 | ☐ |
| FSC-H15 | High | Data Safety | backup | PR 1.3 | ☐ |
| FSC-M01 | Medium | Backup | H01 | PR 1.2 | ☐ |
| FSC-M02 | Medium | Backup | H01 | PR 1.2 | ☐ |
| FSC-M03 | Medium | Export | H12 | PR 5.2 | ☐ |
| FSC-M04 | Medium | Analytics | H08 | PR 4.3 | ☐ |
| FSC-M05 | Medium | Analytics | H08 | PR 4.3 | ☐ |
| FSC-M06 | Medium | Analytics | H08 | PR 4.3 | ☐ |
| FSC-M07 | Medium | Analytics | H08 | PR 4.4 | ☐ |
| FSC-M08 | Medium | Transfer | H02 | PR 2.2 | ☐ |
| FSC-M09 | Medium | Frontend/API | H11 | PR 5.1 | ☐ |
| FSC-M10 | Medium | Frontend/Transfer | M08 | PR 5.1 | ☐ |
| FSC-M11 | Medium | Recurring | H07 | PR 2.3 | ☐ |
| FSC-M12 | Medium | Recurring | H02 | PR 2.3 | ☐ |
| FSC-M13 | Medium | Transaction | H02 | PR 2.2 | ☐ |
| FSC-M14 | Medium | Merchant | H04 | PR 3.2 | ☐ |
| FSC-M15 | Medium | Merchant | H04 | PR 3.2 | ☐ |
| FSC-M16 | Medium | Forecast | H08 | PR 4.4 | ☐ |
| FSC-M17 | Medium | Domain | none | PR 2.1 | ☐ |
| FSC-M18 | Medium | Budget | H02 | PR 2.1 | ☐ |
| FSC-M19 | Medium | Domain/Analytics | none | PR 2.1/4.1 | ☐ |
| FSC-M20 | Medium | Repository | none | Phase 6 | ☐ |
| FSC-M21 | Medium | Analytics | none | Phase 6 | ☐ |
| FSC-M22 | Medium | Storage UI | none | Phase 6 | ☐ |
| FSC-M23 | Medium | Demo data | H15 | PR 1.3 | ☐ |
| FSC-M24 | Medium | CI | none | PR 0.1 | ☐ |

---

# 13. Definition of done

The remediation milestone is complete only when:

1. `main` is green on all supported Python versions.
2. No Critical or High finding remains open.
3. Every fixed finding has a regression test.
4. Migration failure injection proves rollback/data preservation.
5. Restore concurrency tests prove no acknowledged write loss.
6. Manual and CSV paths produce equivalent canonical records.
7. Transaction/category/budget/recurring invariants are centralized.
8. Analytics period states explicitly support past/current/future.
9. Archived configuration cannot alter historical finance totals.
10. Fingerprint/anomaly/rolling modules expose honest sufficiency.
11. Export token never appears in URLs.
12. XSS payload suite passes for account/category/merchant/backup metadata.
13. CSV formula-injection suite passes.
14. `PRAGMA integrity_check` and `PRAGMA foreign_key_check` pass after upgrade/restore tests.
15. README matches actual storage/runtime behavior.

---

# 14. What should not be rewritten

Do **not** perform a ground-up rewrite. Keep and build on:

- exact integer monetary storage;
- `active_transactions` soft-delete view;
- dedicated transfer/refund lifecycle logic;
- explicit server route registry/capability model;
- loopback Host/Origin/session-token controls;
- SQLite native backup API;
- point-in-time recurring rule versioning;
- replay-based model selection;
- forecast Strategy Pattern;
- exact-cent reconciliation helpers;
- router abort/generation protection.

The fastest route to a strong next release is to harden **boundaries and invariants**, not replace the core architecture.

---

# 15. Recommended first three PRs

### PR A — `ci: enforce supported Python runtime contract`

- fix FSC-C01;
- Python 3.10–3.14 CI;
- import smoke test;
- full existing test suite.

### PR B — `db: make destructive migrations atomic and failure-safe`

- fix FSC-C02;
- automatic pre-migration snapshot;
- failure-injection suite;
- integrity/FK/reconciliation verification.

### PR C — `data-safety: serialize restore and protect destructive demo reset`

- fix FSC-H01;
- FSC-H15;
- FSC-M01/M02/M23;
- concurrency tests.

Only after these should domain/import/analytics fixes be merged aggressively.

---

**End of audit plan.**
