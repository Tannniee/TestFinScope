# FinScope CORE V2 — FINAL MERGED Technical Hardening Roadmap

> **Status:** Final merged execution plan  
> **Audit basis:** Current-state CORE V2 audit supplied on 2026-09-04 + repository review findings discussed during the FinScope technical review  
> **Primary objective:** Make FinScope trustworthy before expanding feature breadth. Browser mode, Windows desktop mode, repositories, analytics, budgets, exports, backup/restore, and forecasting must all observe the **same financial truth**.
>
> **Release philosophy:** Correctness first. Prediction second. Feature breadth third.

---

# 0. Final Audit Verdict

The existing CORE V2 audit is fundamentally sound and should be used as the base plan.

Its strongest conclusions are correct:

- Business API transport should be unified.
- Raw `ApiHandler` reflection should not be exposed through HTTP or PyWebView.
- Browser and desktop must share one business API contract.
- Localhost is still a security boundary.
- Soft-deleted transactions must disappear from every active financial calculation.
- Tests must use isolated temporary databases and real automated server fixtures.
- Fake financial balances must never silently appear in real-user mode.
- Transfers and refunds require lifecycle-level invariants, not generic transaction CRUD.
- Exact monetary semantics must be enforced end-to-end.

This final merge keeps those conclusions and adds the remaining hardening items identified during review:

1. amount-only transaction update regression;
2. frontend stored-XSS / unsafe `innerHTML` handling;
3. account-filter parity across dashboard widgets such as Recent Activity;
4. stronger backup restore atomicity and migration recovery;
5. explicit financial invariant test matrix;
6. integration execution order;
7. forecasting/backtesting gates so prediction is built only on trusted financial data;
8. confidence and leakage rules for future prediction work.

---

# 1. Current-State Classification

Before implementation, separate findings into four buckets.

## 1.1 CLOSED — Do Not Reimplement Old Fixes

These issues were already fixed in the audited current state and should now receive regression protection only.

### CLOSED-01 — Safety backup was raw SQLite with `.financebackup`

Current audited behaviour already uses the real backup creation path and produces a ZIP-style `.financebackup`.

**Action:**
- keep implementation;
- add round-trip and format regression tests;
- improve restore atomicity separately.

### CLOSED-02 — Demo transactions auto-seeded on every empty database

Current audited behaviour only seeds demo transactions through explicit seed/demo actions.

**Action:**
- keep implementation;
- make demo workspace safer;
- remove remaining fake default accounts/balances from real-user startup.

### CLOSED-03 — Previously missing named backend analytics handlers

Handlers such as forecast, rolling metrics, review queue, and open-data-folder were already present in the audited current source.

**Action:**
- do not recreate them;
- test frontend/backend contract compatibility instead.

---

## 1.2 VERIFIED P0 — Release Blocking

- [ ] PyWebView business bridge parameter mismatch
- [ ] HTTP reflection-style API surface
- [ ] localhost API security boundary
- [ ] frontend/backend contract drift
- [ ] soft-delete contamination of analytics / budgets / intelligence
- [ ] transfer lifecycle integrity
- [ ] refund cumulative limits
- [ ] fake default financial accounts and balances
- [ ] exact financial truth across create/edit/delete/undo

---

## 1.3 VERIFIED P1 — Reliability / Security

- [ ] isolated automated tests
- [ ] proper ephemeral HTTP test server
- [ ] amount-only update regression
- [ ] atomic backup restore
- [ ] restore path validation
- [ ] schema/migration parity
- [ ] migration recovery
- [ ] merchant-learning confidence semantics
- [ ] base-currency semantics
- [ ] frontend stored-XSS hardening
- [ ] consistent account filtering across UI modules

---

## 1.4 P2 / P3 — After CORE Stability

- [ ] recurring schedule model
- [ ] split transactions
- [ ] reconciliation / cleared status
- [ ] separate demo workspace
- [ ] generated API wrappers
- [ ] improved category/account UX
- [ ] forecasting v2
- [ ] uncertainty intervals
- [ ] model backtesting and model selection

---

# 2. Non-Negotiable Engineering Principles

## 2.1 One Business Transport

Business logic must use one path:

```text
Frontend
   ↓
HTTP JSON API
   ↓
Explicit Route Registry
   ↓
ApiHandler / Request Validation
   ↓
Service Layer
   ↓
Repository Layer
   ↓
SQLite
```

Desktop mode:

```text
PyWebView
   ↓
loads FinScope localhost UI
   ↓
same HTTP business API
```

PyWebView may expose only narrow native shell capabilities.

---

## 2.2 One Financial Truth

For the same database state, these must agree:

```text
Transactions page
Dashboard
Calendar
Deep Dive
Rolling Analytics
What Changed
Spending Fingerprint
Anomalies
Forecast
Backtesting
Insights
Budgets
Merchant learning
Exports
Account balances
```

A feature is incorrect if any two surfaces disagree about the same transaction state.

---

## 2.3 Money Is Data, Not Display

Persistent money must be exact integer minor units.

```text
$52.40 -> 5240
```

Display formatting happens at the UI boundary.

No core financial calculation should depend on JavaScript or Python binary floating-point behaviour.

---

## 2.4 Every Fixed Bug Becomes a Regression Test

A bug is not considered permanently fixed until a test fails when the bug is reintroduced.

---

# 3. Target Architecture

```text
                         FinScope UI
                             │
                 ┌───────────┴───────────┐
                 │                       │
                 ▼                       ▼
          Business API              Desktop Shell
             HTTP                    PyWebView
                 │                       │
                 ▼                       ├── open_data_folder
        Explicit Route Map              ├── choose_backup_file
                 │                       └── window controls
                 ▼
          Request Validator
                 │
                 ▼
             ApiHandler
                 │
                 ▼
           Service Layer
                 │
                 ▼
          Repository Layer
                 │
                 ▼
              SQLite
```

Rules:

- `ApiHandler` is not automatically public.
- `window.pywebview.api` is not a second finance transport.
- HTTP route exposure is explicit.
- destructive operations require the same security checks as writes.
- native-only operations remain intentionally narrow.

---

# 4. Phase A — Establish the Testable Baseline

**Priority:** P0 foundation

## Goal

Make every hardening change reproducible without touching real user data.

## Tasks

- [ ] adopt `pytest` as the canonical automated test runner;
- [ ] use `tmp_path` / temporary directories for DB data;
- [ ] never run tests against `%LOCALAPPDATA%\FinScope`;
- [ ] remove order-dependent `test_01`, `test_02`, ... semantics;
- [ ] create deterministic fixtures;
- [ ] make server start on an ephemeral port;
- [ ] ensure server shutdown/cleanup after each integration test;
- [ ] expose a test-only way to point configuration at a temporary data directory;
- [ ] run migrations from an empty DB during tests.

## Suggested Layout

```text
tests/
├── unit/
│   ├── test_money.py
│   ├── test_transaction_repo.py
│   ├── test_transfer_service.py
│   ├── test_refund_service.py
│   └── test_merchant_rules.py
│
├── integration/
│   ├── test_api_transactions.py
│   ├── test_api_analytics.py
│   ├── test_financial_truth.py
│   ├── test_transport_contract.py
│   └── test_account_filtering.py
│
├── security/
│   ├── test_local_api_security.py
│   └── test_frontend_output_safety.py
│
├── backup/
│   └── test_backup_roundtrip.py
│
├── migration/
│   └── test_upgrade_paths.py
│
├── analytics/
│   ├── test_deleted_exclusion.py
│   ├── test_transfer_semantics.py
│   └── test_forecast_backtesting.py
│
└── regression/
    ├── test_amount_only_update.py
    ├── test_duplicate_transaction_contract.py
    ├── test_safety_backup_restorable.py
    └── test_recent_activity_account_filter.py
```

## Server Fixture Requirement

`start_server(0)` must return the actual OS-selected port:

```python
actual_port = httpd.server_address[1]
return httpd, actual_port
```

## Definition of Done

- tests run repeatedly from a clean checkout;
- no test depends on execution order;
- no test writes into the real FinScope data directory;
- failed tests leave no persistent finance DB behind.

---

# 5. Phase B — Transport Integrity

**Priority:** P0

## Problem

FinScope currently has conceptually different business-call behaviour between:

```text
browser -> HTTP
desktop -> PyWebView exposed Python methods
```

Passing one JS object into a Python function with positional/named parameters can produce incorrect argument shapes.

## Target

All business operations use HTTP.

```javascript
await businessApi.call("get_month_summary", {
  month: "2026-09",
  account_id: 1
});
```

Server dispatches named parameters only after validation.

## Tasks

- [ ] make HTTP the canonical business transport;
- [ ] remove generic business preference for `window.pywebview.api`;
- [ ] stop exposing raw `ApiHandler()` as `js_api`;
- [ ] add a narrow `DesktopBridge`;
- [ ] reserve PyWebView for desktop-only operations;
- [ ] create one API error model;
- [ ] create one API response model.

## Recommended Response Shape

Success:

```json
{
  "api_version": 2,
  "success": true,
  "data": {}
}
```

Failure:

```json
{
  "api_version": 2,
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Amount must be greater than zero."
  }
}
```

## Transport Tests

### TRN-001 — Zero-argument business method

```text
create_backup
list_backups
get_storage_health
```

Must work through HTTP without receiving an accidental `{}` positional argument.

### TRN-002 — Named arguments

```json
{
  "month": "2026-09",
  "account_id": 1
}
```

Backend receives:

```text
month: string
account_id: integer
```

### TRN-003 — Nested transaction payload

Create transaction request arrives with exactly one agreed DTO shape.

### TRN-004 — Desktop parity

Opening FinScope in PyWebView must still issue business HTTP requests.

### TRN-005 — Browser parity

Same request, same DB, same response semantics.

## Definition of Done

> Browser and desktop use the same business code path.

---

# 6. Phase C — Local API Security Boundary

**Priority:** P0 Security

Loopback binding is necessary but not sufficient.

## 6.1 Replace Reflection Routing

Do not expose every public `ApiHandler` method via:

```python
hasattr(...)
getattr(...)
```

Use an explicit route registry.

```python
ROUTES = {
    "get_transactions": Route(
        handler=api.get_transactions,
        capability="READ",
    ),
    "create_transaction": Route(
        handler=api.create_transaction,
        capability="WRITE",
    ),
    "delete_transaction": Route(
        handler=api.delete_transaction,
        capability="DESTRUCTIVE",
    ),
}
```

Capabilities:

```text
READ
WRITE
DESTRUCTIVE
PRIVILEGED_DESKTOP
```

Unknown method:

```text
404
```

---

## 6.2 Remove Wildcard CORS

Do not return:

```http
Access-Control-Allow-Origin: *
```

for the production FinScope local API.

The normal UI is same-origin and should not need wildcard CORS.

Development CORS, if required, should allow only explicitly configured origins.

---

## 6.3 Validate Host

Accept only the active local FinScope host/port forms.

Examples:

```text
127.0.0.1:<port>
localhost:<port>
```

Reject unexpected Host headers.

---

## 6.4 Validate Origin

For state-changing browser requests:

Allow the FinScope local origin.

Reject foreign web origins.

CORS response headers alone are not authentication.

---

## 6.5 Session Token

Generate a random per-launch token.

```python
secrets.token_urlsafe(32)
```

Require it for business API calls, especially writes/destructive operations.

Example:

```http
X-FinScope-Token: <random-session-token>
```

Never persist it as a long-term credential.

---

## 6.6 Input Hardening

Enforce:

- [ ] request size cap;
- [ ] JSON Content-Type;
- [ ] valid JSON;
- [ ] known route;
- [ ] request DTO validation;
- [ ] maximum string lengths where appropriate;
- [ ] integer IDs;
- [ ] valid dates/months;
- [ ] valid enum values.

Suggested status semantics:

```text
400 malformed request / invalid JSON
403 invalid local session / Origin / Host
404 unknown route
413 body too large
422 valid JSON but invalid business input
500 unexpected internal error
```

Never expose raw stack traces or internal filesystem paths to the UI.

## Security Tests

```text
SEC-001 unknown route                -> 404
SEC-002 missing token                -> 403
SEC-003 invalid token                -> 403
SEC-004 foreign Origin               -> 403
SEC-005 invalid Host                 -> 403
SEC-006 oversized body               -> 413
SEC-007 malformed JSON               -> 400
SEC-008 invalid Content-Type         -> reject
SEC-009 wildcard CORS                -> absent
SEC-010 internal Python exception    -> structured 500
```

---

# 7. Phase D — API Contract Integrity

**Priority:** P0/P1

## Goal

Every UI call must have an existing wrapper, route, request schema, response schema, and renderer-compatible DTO.

Flow:

```text
UI call site
   ↓
frontend wrapper
   ↓
HTTP route
   ↓
request DTO
   ↓
handler/service
   ↓
response DTO
   ↓
renderer
```

## Known Contract Classes To Fix

### D-01 — Duplicate transaction

If UI calls:

```javascript
api.duplicateTransaction(txId)
```

then one of the following must be true:

- wrapper exists and maps to `duplicate_transaction`; or
- UI stops calling it.

Add a static/contract regression test.

---

### D-02 — Merchant suggestions

Use one canonical DTO for:

```text
merchant search
recent payees
merchant rules
smart-capture autofill
```

Recommended:

```json
{
  "merchant_id": 12,
  "name": "Woolworths",
  "category_id": 3,
  "category_name": "Groceries",
  "account_id": 1,
  "essentiality": "essential",
  "confidence": "high",
  "transaction_count": 17
}
```

Do not mix:

```text
merchant_name
name
default_category_id
category_id
preferred_account_id
account_id
```

without an explicit mapper.

---

### D-03 — Review Queue / Analytics / Settings Shapes

Add schema assertions for:

```text
Review Queue
Rolling metrics
Forecast
What Changed
Fingerprint
Anomalies
Ranked insights
Backtesting
Settings
Storage health
Backup metadata
```

## Contract Tests

```text
CON-001 every frontend api.* call has a wrapper
CON-002 every wrapper points to an explicit route
CON-003 every route has a validator
CON-004 merchant suggestion DTO matches renderer
CON-005 analytics response DTO matches renderer
CON-006 API version is present
CON-007 unknown/missing fields fail predictably
```

---

# 8. Phase E — Financial Truth Hardening

**Priority:** P0

This phase is the core of the roadmap.

Advanced Analytics and forecasting must not be considered trustworthy until this phase passes.

---

# 8.1 Canonical Transaction Semantics

## Income

```text
income -> increases income / cash flow
```

## Expense

```text
expense -> increases gross spending
```

## Refund

Recommended:

```text
refund -> offsets expense
```

It should not artificially inflate income.

## Transfer

```text
source account decreases
destination account increases
global income unchanged
global expense unchanged
global net flow unchanged
```

## Soft Delete

```text
is_deleted = 1
```

means the transaction must not exist in active financial reporting.

---

# 8.2 Canonical Active Transaction Source

**Problem:** Manually adding `AND is_deleted = 0` across many queries is fragile.

## Preferred Option

Create a canonical database view:

```sql
CREATE VIEW active_transactions AS
SELECT *
FROM transactions
WHERE is_deleted = 0;
```

All active reporting queries use:

```sql
FROM active_transactions
```

Alternative: a mandatory repository/aggregation abstraction with the same guarantee.

## Audit Every Consumer

At minimum:

- [ ] Dashboard KPIs
- [ ] transaction list
- [ ] Calendar
- [ ] Deep Dive
- [ ] Rolling
- [ ] What Changed
- [ ] Fingerprint
- [ ] Anomalies
- [ ] Forecast
- [ ] Backtesting
- [ ] Insights
- [ ] Budgets
- [ ] merchant learning
- [ ] data-quality metrics
- [ ] exports
- [ ] account summaries

## Financial Truth Tests

### FT-001 — Delete expense

Create:

```text
income  = 3000
expense = 500
```

Before delete:

```text
income     3000
expense     500
net flow   2500
```

After soft delete:

```text
income     3000
expense       0
net flow   3000
```

Every analytics surface must agree.

### FT-002 — Undo delete

Undo must restore the original values everywhere.

### FT-003 — Delete refund

```text
expense 100
refund   25
net expense 75
```

Delete refund:

```text
net expense 100
```

### FT-004 — Deleted transactions excluded from merchant learning

A deleted purchase must not continue to train merchant category/account inference.

### FT-005 — Deleted transactions excluded from forecasting/backtesting

No deleted transaction may be used as model history.

---

# 9. Phase E2 — Exact Money Contract

**Priority:** P0/P1

## Goal

Money is integer minor units from UI parse boundary to SQLite.

Preferred API:

```json
{
  "amount_minor": 5240
}
```

not:

```json
{
  "amount": 52.40
}
```

## Pipeline

```text
user input text
    ↓
currency-aware exact parser
    ↓
integer amount_minor
    ↓
validated API DTO
    ↓
service/repository
    ↓
SQLite INTEGER
```

## Currency Metadata

Do not assume every currency has two decimals.

Examples:

```text
AUD 52.40  -> 5240
JPY 500    -> 500
VND 500000 -> 500000
```

Define:

```text
minor_digits
```

per supported currency.

## Money Tests

```text
MON-001 0.01
MON-002 12.34 round trip
MON-003 zero
MON-004 maximum supported amount
MON-005 too many decimal places
MON-006 invalid input
MON-007 comma/locale policy
MON-008 JPY zero decimals
MON-009 VND zero decimals
MON-010 negative values by transaction type
MON-011 rounding policy for 1.005
MON-012 rounding policy for 10.075
```

Do not leave rounding behaviour implicit.

---

# 10. Phase E3 — Amount-Only Update Regression

**Priority:** P1

## Known Failure Class

An update implementation can:

1. filter ordinary allowed fields;
2. see no updates;
3. return early;
4. never transform `"amount"` into `"amount_minor"`.

That means:

```python
update(id, {"amount": 85.00})
```

may fail while:

```python
update(id, {"amount": 85.00, "note": "x"})
```

succeeds.

## Correct Pattern

Normalise special fields before the empty-update check.

```python
updates = {}

if "amount_minor" in data:
    updates["amount_minor"] = validate_amount_minor(data["amount_minor"])

for field in ALLOWED_FIELDS:
    if field in data:
        updates[field] = data[field]

if not updates:
    return False
```

## Tests

```text
UPD-001 update amount only
UPD-002 update note only
UPD-003 update amount + note
UPD-004 empty patch
UPD-005 invalid amount
UPD-006 update deleted transaction policy
```

---

# 11. Phase E4 — Transfer Lifecycle Service

**Priority:** P0

Transfers must not be handled as two unrelated generic transactions.

## Service

```python
TransferService.create()
TransferService.update()
TransferService.duplicate()
TransferService.delete()
TransferService.undo_delete()
TransferService.validate_group()
```

Each operation must use one DB transaction.

## Invariants

For each active transfer group:

```text
exactly two active legs
same transfer_group_id
one source leg
one destination leg
same amount
source account != destination account
matching effective date unless explicitly supported otherwise
```

## Global Semantics

For a $500 transfer:

```text
Account A      -500
Account B      +500
Global income     0
Global expense    0
Global net flow   0
```

## Tests

```text
TRF-001 create pair
TRF-002 source/destination balance
TRF-003 global KPI neutrality
TRF-004 update amount updates both legs
TRF-005 update accounts maintains pair
TRF-006 duplicate creates a valid new pair
TRF-007 delete hides both legs
TRF-008 undo restores both legs
TRF-009 failure rolls back both legs
TRF-010 orphan detection
TRF-011 same-account transfer rejected
```

---

# 12. Phase E5 — Refund Lifecycle

**Priority:** P0/P1

## Invariants

A linked refund requires:

```text
original transaction exists
original transaction is an expense
refund > 0
sum(active linked refunds) <= original expense amount
```

Remaining refundable amount:

```text
remaining_refundable_minor
=
original_amount_minor
-
sum(active linked refund amounts)
```

## Reporting

```text
gross expense = original purchases
refunds = refund total
net expense = gross expense - refunds
```

Do not classify refunds as ordinary income.

## Tests

```text
RFD-001 full refund
RFD-002 partial refund
RFD-003 multiple partial refunds
RFD-004 over-refund rejected
RFD-005 deleted refund excluded
RFD-006 undo refund
RFD-007 original expense deleted policy
RFD-008 refund linked to non-expense rejected
RFD-009 failed refund leaves DB unchanged
```

---

# 13. Phase E6 — Account Filter Parity

**Priority:** P1

A selected account filter must affect every component that claims to show the selected account context.

Example failure class:

```text
Dashboard KPI -> account A only
Recent Activity -> all accounts
```

That creates a visually inconsistent financial story.

## Audit

Check:

```text
Overview KPI
Recent Activity
Calendar
Category breakdown
Deep Dive
Budget cards
Forecast
Insights
Exports
```

## Tests

### ACC-001

Create transaction in Account A and Account B.

Filter Account A.

Expected:

```text
KPI -> A only
Recent Activity -> A only
Charts -> A only
Forecast -> clearly A only or explicitly global
```

### ACC-002

Clear filter.

All global widgets return to global scope.

### ACC-003

A component that is intentionally global must label itself as global.

---

# 14. Phase E7 — Merchant Learning Integrity

**Priority:** P1

Merchant memory must distinguish:

```text
explicit user rule
```

from:

```text
statistical inference
```

One historical transaction should not automatically become high confidence.

## Suggested Confidence Semantics

```text
Explicit "Always" rule      -> high
17 / 18 same category       -> high
6 / 8 same category         -> moderate
1 / 1 historical example    -> early / low
```

Deleted transactions are excluded.

Refunds and transfer legs should not distort merchant purchase classification.

## Tests

```text
MER-001 explicit rule wins
MER-002 repeated history increases confidence
MER-003 one observation remains low confidence
MER-004 deleted history excluded
MER-005 transfer excluded
MER-006 refund learning policy explicit
MER-007 DTO maps category/account consistently
```

---

# 15. Phase E8 — Base Currency Truth

**Priority:** P1

Current product semantics should choose one of two models.

## CORE V2 Recommended Model

```text
One Base Currency
All accounts use the base currency
```

Changing currency means changing the base financial model, not merely relabelling symbols.

If multi-currency is not implemented, do not allow:

```text
100 USD + 100 AUD = 200 <display currency>
```

## True Multi-Currency Is a Later Feature

It requires:

```text
currency per transaction/account
FX rate source
rate date
base-currency conversion
historical FX treatment
gain/loss semantics
```

Do not silently fake this.

---

# 16. Phase F — Backup / Restore Hardening

**Priority:** P1, with data-loss implications

## Already Good

Keep the verified backup approach:

```text
SQLite Connection.backup()
    ↓
temporary snapshot DB
    ↓
PRAGMA integrity_check
    ↓
ZIP finance.db + metadata
    ↓
.financebackup
```

## Improve Restore

Preferred restore pipeline:

```text
select backup
    ↓
resolve / validate path
    ↓
validate extension
    ↓
validate ZIP structure
    ↓
extract into temporary directory
    ↓
validate SQLite
    ↓
PRAGMA integrity_check
    ↓
verify schema version
    ↓
migrate temporary DB if supported
    ↓
fsync
    ↓
enter maintenance mode
    ↓
close active DB users
    ↓
os.replace(temp_db, live_db)
    ↓
reopen DB
    ↓
post-restore integrity check
```

Never partially overwrite the live database with a manual byte-copy loop.

## Path Validation

If restoring an internal FinScope backup:

```text
resolved path must remain under BACKUPS_DIR
```

External import should use an explicit file picker / import workflow.

## Backup Tests

```text
BAK-001 WAL write -> backup -> restore
BAK-002 exact row equality after round trip
BAK-003 safety backup is valid ZIP
BAK-004 metadata valid
BAK-005 corrupt ZIP rejected
BAK-006 missing finance.db rejected
BAK-007 corrupted SQLite rejected
BAK-008 failed restore leaves live DB unchanged
BAK-009 restore older schema through supported migration path
BAK-010 path traversal/outside backup dir rejected
```

---

# 17. Phase G — Schema and Migration Integrity

**Priority:** P1

## Single Source of Truth

Use migrations as canonical schema evolution.

```text
migrations/
001_initial
002_relationships
003_...
```

If `schema.sql` remains, either:

- generate it from migrations; or
- validate it in tests against a fully migrated blank DB.

Do not maintain two silently divergent schemas.

## Migration Safety

Before destructive/high-risk migration:

```text
verified backup
    ↓
migration transaction
    ↓
integrity check
    ↓
expected schema version
    ↓
commit
```

On failure:

```text
rollback
preserve previous DB
surface recovery information
```

## Migration Tests

```text
MIG-001 blank DB -> latest
MIG-002 previous supported version -> latest
MIG-003 upgrade preserves transactions
MIG-004 upgrade preserves transfers/refunds
MIG-005 upgrade preserves soft-delete state
MIG-006 failed migration does not destroy original DB
MIG-007 schema.sql parity if schema.sql remains
```

---

# 18. Phase H — Frontend Output Safety / Stored XSS

**Priority:** P1 Security

## Risk

User-controlled or imported financial text may be rendered using template strings and `innerHTML`.

Examples of risky fields:

```text
merchant_name
description
note
account_name
category_name
CSV-imported text
```

A stored value must never be interpreted as trusted HTML.

## Preferred Fix

Use DOM creation and:

```javascript
element.textContent = value;
```

where possible.

If HTML templates remain, create one escaping helper and apply it to all untrusted values.

Example:

```javascript
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
```

## Audit

Search frontend for:

```text
.innerHTML =
insertAdjacentHTML
template strings containing transaction data
merchant autocomplete HTML
notes/descriptions rendered directly
```

## Tests

```text
XSS-001 merchant "<img ...>" renders as text
XSS-002 note "<script>" renders as text
XSS-003 category/account imported markup renders as text
XSS-004 autocomplete does not execute merchant HTML
XSS-005 CSV import cannot create executable UI markup
```

---

# 19. Phase I — First-Run Financial Truth

**Priority:** P0/P1

A new real-user database should begin with:

```text
schema
default categories
settings/onboarding state
0 real accounts
0 transactions
0 fake balances
```

Default categories are fine.

Fake accounts and balances are not.

## Onboarding

```text
Welcome
   ↓
Choose Base Currency
   ↓
Create First Account
   ↓
Enter Real Opening Balance
   ↓
Finish
```

`has_initialized` should mean onboarding is actually complete.

Initial value:

```text
false
```

After completion:

```text
true
```

---

# 20. Phase J — Demo Workspace Isolation

**Priority:** P2

Preferred:

```text
Open Demo Workspace
```

using:

```text
demo_finance.db
```

or an isolated temporary data directory.

Do not mix demo data into the personal DB unless the user receives an explicit destructive warning.

---

# 21. Phase K — Full Integration + Financial Truth Hardening Run

This is the mandatory end-to-end test pass.

## 21.1 Startup Integration

```text
fresh temp directory
    ↓
init DB
    ↓
run migrations
    ↓
start server on ephemeral port
    ↓
obtain session token
    ↓
load frontend/API
```

Assert:

- blank truthful financial state;
- no fake money;
- correct schema version;
- categories/settings expected.

---

## 21.2 Transaction Lifecycle Integration

Scenario:

```text
Create expense
    ↓
verify DB
    ↓
verify transaction list
    ↓
verify dashboard
    ↓
verify calendar
    ↓
verify analytics
    ↓
edit amount only
    ↓
verify all surfaces
    ↓
delete
    ↓
verify exclusion everywhere
    ↓
undo
    ↓
verify restoration everywhere
```

---

## 21.3 Transfer Lifecycle Integration

```text
Create transfer
    ↓
verify two legs
    ↓
verify account balances
    ↓
verify global KPI neutrality
    ↓
edit
    ↓
duplicate
    ↓
delete
    ↓
undo
```

At every step:

```text
validate_transfer_group(...)
```

---

## 21.4 Refund Lifecycle Integration

```text
Create expense 100
    ↓
refund 30
    ↓
refund 20
    ↓
net expense 50
    ↓
attempt refund 60
    ↓
reject
```

Verify:

- DB unchanged after rejected over-refund;
- analytics agrees;
- deleted refund is excluded.

---

## 21.5 Account Filtering Integration

```text
Account A transaction
Account B transaction
    ↓
select Account A
```

Verify every account-scoped widget and API result.

---

## 21.6 Backup Round-Trip Integration

```text
create realistic data
    ↓
force WAL activity
    ↓
backup
    ↓
mutate DB
    ↓
restore
    ↓
verify exact original records
    ↓
run analytics
    ↓
compare pre-backup financial truth snapshot
```

---

## 21.7 Security Integration

From HTTP test client:

```text
no token
wrong token
foreign Origin
wrong Host
unknown route
invalid JSON
oversized body
restore outside allowed path
```

All must fail correctly without modifying DB state.

---

# 22. Financial Truth Snapshot Test

Create a canonical function for integration tests:

```python
def financial_truth_snapshot(api):
    return {
        "dashboard": ...,
        "calendar": ...,
        "category_breakdown": ...,
        "account_balances": ...,
        "budget": ...,
        "rolling": ...,
        "forecast_input": ...,
    }
```

After each lifecycle operation, assert internal consistency.

Example:

```text
transaction repository active expense total
=
dashboard net expense component
=
analytics active expense total
=
forecast historical input expense total
```

This test class is more valuable than many isolated UI assertions because it tests the central FinScope promise.

---

# 23. Release-Blocking Regression Matrix

| ID | Scenario | Required Result |
|---|---|---|
| REG-001 | Amount-only update | succeeds |
| REG-002 | Deleted expense | excluded everywhere |
| REG-003 | Undo expense | restored everywhere |
| REG-004 | Deleted refund | no longer offsets expense |
| REG-005 | Transfer | globally neutral |
| REG-006 | Transfer delete | both legs hidden |
| REG-007 | Transfer undo | both legs restored |
| REG-008 | Over-refund | rejected atomically |
| REG-009 | Duplicate UI action | valid wrapper/route exists |
| REG-010 | Merchant DTO | frontend/backend shape aligned |
| REG-011 | Account filter | Recent Activity matches selected account |
| REG-012 | Backup safety file | restorable |
| REG-013 | Failed restore | live DB unchanged |
| REG-014 | Foreign origin | destructive API blocked |
| REG-015 | Stored HTML merchant | renders as text |
| REG-016 | Fresh install | no fake balance |
| REG-017 | Deleted history | absent from forecast input |
| REG-018 | Desktop mode | business calls still go through HTTP |

---

# 24. CI / Local Verification Order

Run in this order:

```text
1. static / syntax checks
2. unit tests
3. repository tests
4. service tests
5. migration tests
6. backup tests
7. API contract tests
8. HTTP security tests
9. financial truth integration tests
10. frontend smoke / contract tests
11. forecast/backtesting tests
12. packaged desktop smoke
```

Suggested command family:

```bash
pytest -q tests/unit
pytest -q tests/migration
pytest -q tests/backup
pytest -q tests/security
pytest -q tests/integration
pytest -q
```

If JS tests are introduced:

```bash
npm test
```

or the selected JS runner.

---

# 25. CORE Stability Gate

CORE V2 may be called stable only when all are true.

## Transport

- [ ] business API is one transport;
- [ ] desktop does not expose raw `ApiHandler`;
- [ ] explicit route registry exists;
- [ ] browser and desktop behaviour match.

## Security

- [ ] no wildcard production CORS;
- [ ] Host validated;
- [ ] Origin validated;
- [ ] session token required;
- [ ] request size/type validated;
- [ ] raw exceptions are not returned.

## Financial Truth

- [ ] deleted data excluded everywhere;
- [ ] money exact end-to-end;
- [ ] transfer invariants hold;
- [ ] refund limits hold;
- [ ] account filters are consistent;
- [ ] no fake new-user balances;
- [ ] merchant learning uses active truthful history.

## Data Safety

- [ ] backups are valid snapshots;
- [ ] restore is atomic;
- [ ] failed restore preserves live DB;
- [ ] migrations are recoverable.

## Tests

- [ ] temporary isolated DBs;
- [ ] automated HTTP server;
- [ ] no test-order dependency;
- [ ] regression matrix passes;
- [ ] integration financial truth suite passes.

---

# 26. Forecasting / Prediction — Only After CORE Financial Truth

**Priority:** P3 after hardening

FinScope already has analytics/forecast-related functionality, but prediction should not be trusted merely because a forecast number can be rendered.

A trustworthy forecast requires:

```text
trusted historical transactions
+
correct refund/transfer semantics
+
deleted-data exclusion
+
recurring detection
+
calendar behaviour
+
backtesting
+
uncertainty
```

---

# 27. Forecasting Architecture V2

Recommended decomposition:

```text
Projected month-end spending
=
Known remaining recurring expenses
+
Expected remaining variable spending
```

Variable spending:

```text
historical baseline
× current-month trend adjustment
× calendar/weekday adjustment
```

Avoid relying only on:

```text
spent_so_far / elapsed_days × days_in_month
```

because one-off rent, bills, or early-month timing can distort it badly.

---

# 28. Forecast Input Rules

Forecast history must exclude:

```text
soft-deleted transactions
transfers from spending
invalid/orphan transfer legs
demo data in real-user mode
corrupt/refunded semantics
```

Refund policy must be consistent with Analytics.

Account-filtered forecast must use the same account scope as the UI.

---

# 29. Recurring Detection

Start with explainable rules.

Candidate signals:

```text
normalised merchant
similar amount
regular date interval
same category
same account
monthly / weekly cadence
```

Example:

```text
Rent
01 Jun  620
01 Jul  620
01 Aug  620
```

can produce a high-confidence expected future recurring expense.

Do not require ML for this stage.

---

# 30. Variable-Spend Baseline

Prefer robust methods initially:

```text
rolling median
weighted moving average
EWMA
robust trend
weekday pattern
```

These are easier to validate and explain than a complex ML model on a small personal dataset.

---

# 31. Forecast Confidence

Do not show:

```text
Projected expense: $3,124
```

as if exact.

Prefer:

```text
Projected expense: $3,120
Likely range: $2,850–$3,410
Confidence: Medium
```

Confidence may consider:

```text
history length
historical volatility
recurring share
backtest error
current-month coverage
```

---

# 32. Backtesting Is Mandatory

A prediction feature is not considered validated without historical simulation.

Example:

```text
Pretend date = 15 May
Only data available up to 15 May
Forecast May end
Compare against actual May
```

Repeat across historical months.

## Metrics

Recommended:

```text
MAE
WAPE
Bias
```

MAPE may be reported carefully but behaves poorly around near-zero denominators.

## Backtest Rules

- [ ] no future leakage;
- [ ] only information available at the historical cutoff may be used;
- [ ] recurring detection must also respect cutoff dates;
- [ ] deleted data excluded;
- [ ] model hyperparameters cannot silently inspect future months.

---

# 33. Forecast Model Selection

Compare simple baselines.

```text
Model A — linear current-month pace
Model B — trailing median
Model C — EWMA
Model D — recurring + variable baseline
Model E — recurring + EWMA + calendar adjustment
```

Use historical backtests to decide whether complexity actually improves accuracy.

Do not assume a more complex model is better.

---

# 34. Forecast Tests

```text
FRC-001 no-history fallback
FRC-002 one-month-history low confidence
FRC-003 recurring rent detected
FRC-004 transfer excluded
FRC-005 refund offsets expense
FRC-006 deleted transaction excluded
FRC-007 account filter respected
FRC-008 forecast uses only data before cutoff
FRC-009 month-end projection deterministic
FRC-010 confidence falls with high volatility
FRC-011 backtest MAE computed correctly
FRC-012 bias direction computed correctly
FRC-013 model comparison selects by declared metric
FRC-014 no future leakage
```

---

# 35. Prediction Release Gate

Prediction may be promoted from experimental to trusted only when:

- [ ] CORE stability gate passes;
- [ ] minimum history policy is defined;
- [ ] recurring and variable components are explainable;
- [ ] backtesting exists;
- [ ] no future leakage tests pass;
- [ ] confidence/range is shown;
- [ ] fallback behaviour for insufficient data is defined;
- [ ] forecast input respects soft delete, refunds, transfers, account scope, and base currency;
- [ ] error metrics are visible in development/diagnostics.

---

# 36. Recommended Sprint / Merge Order

## CORE V2.0 — Testable Baseline

```text
temporary DB fixtures
ephemeral server
remove order-dependent tests
```

### Gate

Automated tests can run safely and repeatedly.

---

## CORE V2.1 — Transport & Local Security

```text
HTTP-only business API
DesktopBridge
explicit RouteRegistry
session token
Host/Origin checks
remove wildcard CORS
input limits
structured errors
```

### Gate

Browser and desktop business behaviour is identical and hostile foreign-origin writes are blocked.

---

## CORE V2.2 — Contract Integrity

```text
duplicateTransaction
merchant DTO
analytics DTOs
settings DTOs
API version
request validators
frontend call-site audit
```

### Gate

No rendered UI control points to a missing or incompatible backend operation.

---

## CORE V2.3 — Financial Truth

```text
active transaction source
soft-delete exclusion
exact money
amount-only update
transfer service
refund limits
account-filter parity
merchant truth
base currency
```

### Gate

Create/Edit/Delete/Undo causes every financial surface to agree.

---

## CORE V2.4 — Data Safety

```text
atomic restore
path validation
migration recovery
schema parity
first-run truthful state
```

### Gate

A DB failure/upgrade/restore cannot silently corrupt user financial state.

---

## CORE V2.5 — Frontend Safety

```text
stored-XSS audit
textContent / escape layer
CSV/import output safety
```

### Gate

Financial text is always rendered as data, never executable markup.

---

## CORE V2.6 — Full Integration Hardening

```text
transaction lifecycle
transfer lifecycle
refund lifecycle
account filtering
backup round trip
security matrix
financial truth snapshot
packaged desktop smoke
```

### Gate

The complete regression matrix passes.

---

## ANALYTICS V2.1 — Forecast Trustworthiness

```text
recurring detection
robust baseline
calendar behaviour
backtesting
confidence
model comparison
```

### Gate

Prediction is explainable, backtested, and built only from trusted financial truth.

---

# 37. What Not To Do Yet

Until CORE V2.6 passes, avoid spending major effort on:

```text
neural networks
LSTM forecasting
Random Forest forecasting
complex AI recommendations
multi-currency FX engine
large UX feature expansion
new analytics that depend on unverified aggregates
```

The most valuable work is still correctness and reproducibility.

---

# 38. Definition of Done for a FinScope Feature

A feature is complete only when all five agree:

```text
UI
transport
backend contract
financial semantics
tests
```

For finance features, add a sixth:

```text
recovery / data safety
```

A rendered button is not a completed feature.

A passing unit test is not enough if the HTTP path fails.

A working dashboard is not correct if deleted transactions still contaminate Analytics.

A forecast is not trustworthy if it has never been backtested.

---

# 39. Final Merge Checklist

## Must Merge Before CORE Stable

- [ ] isolated test infrastructure
- [ ] HTTP-only business transport
- [ ] narrow PyWebView DesktopBridge
- [ ] explicit API route registry
- [ ] localhost session security
- [ ] canonical DTO contracts
- [ ] duplicate transaction wrapper/contract fix
- [ ] merchant DTO fix
- [ ] canonical active transaction source
- [ ] financial truth regression suite
- [ ] amount-only update fix
- [ ] exact money boundary
- [ ] transfer lifecycle service
- [ ] refund cumulative validation
- [ ] account-filter parity
- [ ] remove fake default balances
- [ ] backup restore atomicity
- [ ] migration recovery
- [ ] frontend output escaping / XSS hardening
- [ ] full integration hardening run

## Keep as Closed + Regression Protected

- [x] safety backup uses real backup creation path
- [x] automatic demo transaction seeding fixed
- [x] previously reported missing analytics/review handlers now exist

## After CORE Stable

- [ ] demo workspace isolation
- [ ] recurring schedule UX
- [ ] split transactions
- [ ] reconciliation
- [ ] generated wrappers
- [ ] forecasting v2 + backtesting + confidence
- [ ] true multi-currency, if ever required

---

# 40. Final Technical Principle

> **FinScope must have one business transport, one set of API contracts, and one financial truth.**

> **Deleted data must be deleted from active truth, transfers must remain paired, refunds must remain bounded, and money must remain exact.**

> **Prediction should be the result of trusted history plus validated modelling, not a substitute for correct accounting semantics.**

> **A feature is ready only when UI, transport, backend, database, analytics, recovery behaviour, and automated tests all agree.**

---

# 41. Recommended Final Execution Sequence

```text
TEST BASELINE
    ↓
TRANSPORT + SECURITY
    ↓
API CONTRACTS
    ↓
FINANCIAL TRUTH
    ↓
DATA SAFETY + MIGRATIONS
    ↓
FRONTEND OUTPUT SAFETY
    ↓
FULL INTEGRATION HARDENING
    ↓
CORE STABILITY GATE
    ↓
FORECAST / BACKTEST HARDENING
    ↓
BETA STABILISATION
```

That sequence should be treated as the canonical FinScope CORE V2 merge plan.
