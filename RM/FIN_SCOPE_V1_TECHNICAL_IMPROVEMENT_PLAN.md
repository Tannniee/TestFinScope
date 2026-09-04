# FinScope v1.0.0 — Technical Improvement, UX Hardening & Forecast V3 Plan

> **Baseline:** Git tag `v1.0.0`  
> **Purpose:** Technical remediation guide, implementation roadmap, acceptance criteria, and regression test plan for the next FinScope releases.  
> **Primary goals:** protect financial correctness, reduce user friction, improve perceived smoothness, and evolve forecasting from a heuristic projection into an empirically validated personal cash-flow forecast.

---

## 1. Scope and engineering principles

This document is based on a source-level audit of the `v1.0.0` tag. It focuses on the following layers:

1. **Financial correctness and data integrity**
2. **Transaction workflow reliability**
3. **Frontend state/render lifecycle and perceived smoothness**
4. **User experience and accessibility**
5. **Feature completeness for a personal finance application**
6. **Forecasting architecture, validation, uncertainty, and explainability**
7. **Regression testing and release gates**

This document does **not** claim measured Windows/WebView2 frame-time or latency benchmark results. Runtime performance recommendations below are based on current code paths and should be validated with profiling on a packaged Windows build.

### Engineering principles

FinScope should continue to optimise for:

- **Offline-first**
- **Private by default**
- **Exact money semantics using integer minor units**
- **Explainable analytics**
- **Deterministic behaviour**
- **Minimal user effort**
- **One canonical source of truth for financial calculations**
- **Regression tests for every financial invariant**
- **No feature should silently change money totals**

---

# 2. Priority model

Use the following severity definitions.

| Priority | Meaning |
|---|---|
| **P0** | Can produce incorrect financial data, duplicate money movement, or materially misleading analytics |
| **P1** | Reliability or UX issue likely to frustrate users or create inconsistent behaviour |
| **P2** | Product completeness / friction reduction |
| **P3** | Polish, accessibility, maintainability, or future-facing improvement |

Recommended release grouping:

- **v1.0.1:** P0 correctness hotfix
- **v1.1.0:** UX + smoothness + scope consistency
- **v1.2.0:** Import + account/category management
- **v1.3.0:** Recurring system + Forecast V3
- **v1.4.0:** Planning features such as projected cash flow, savings and net cash position

---

# 3. P0 — Financial correctness fixes

## 3.1 Deep Dive variance must exclude soft-deleted transactions

### Current risk

Most analytical queries correctly use the canonical:

```sql
active_transactions
```

However, `AnalyticsService.get_analytics_deep_dive()` contains variance queries that join directly against:

```sql
transactions
```

instead of:

```sql
active_transactions
```

This means a transaction may disappear from Transactions, KPI summaries, budgets and other analytics while still influencing the legacy Deep Dive variance view.

### Affected area

```text
app/backend/services/analytics_service.py
AnalyticsService.get_analytics_deep_dive()
```

### Required fix

Replace both category variance joins with `active_transactions`.

Before:

```sql
FROM categories c
LEFT JOIN transactions t
    ON t.category_id = c.id
```

After:

```sql
FROM categories c
LEFT JOIN active_transactions t
    ON t.category_id = c.id
```

Also qualify account filtering explicitly:

```python
acc_clause = " AND t.account_id = ?" if account_id else ""
```

Do not rely on an unqualified `account_id` inside JOIN conditions.

### Acceptance criteria

- A soft-deleted expense must not contribute to current month category variance.
- A soft-deleted expense from the comparison month must not contribute to previous month variance.
- Undoing the delete must restore the transaction to the variance result.
- Account-scoped Deep Dive must only include that account.
- Result totals must reconcile with canonical month summary.

### Regression test

Add:

```python
def test_reg_020_deep_dive_excludes_soft_deleted_transactions(isolated_db):
    # Arrange
    # Create category + account
    # Create previous month expense = $100
    # Create current month expense = $150
    # Verify initial delta = +$50

    # Act
    # Soft-delete current month expense

    # Assert
    # Current category value == 0
    # Previous category value == 100
    # Delta == -100
```

Add a second test for a deleted previous-month record.

---

## 3.2 Editing a transfer or refund must never create a duplicate financial event

### Current risk

The transaction modal supports editing and sets:

```javascript
activeTxId
```

for an existing row. However the submit path handles `transfer` and `refund` before the generic edit path.

Conceptually:

```javascript
if (type === 'transfer') {
    createTransfer(...)
}
else if (type === 'refund') {
    createRefund(...)
}
else if (activeTxId) {
    updateTransaction(...)
}
```

An Edit action for an existing transfer/refund can therefore enter a create path instead of an update path.

This is unacceptable for a finance application because an innocent edit can create a second money movement.

### Immediate hotfix option

For `v1.0.1`, if proper relationship-aware editing is not implemented yet:

- Disable Edit for `transfer`
- Disable Edit for `refund`
- Keep Delete / Undo
- Show a tooltip:

> Editing linked transfers/refunds is not supported yet. Delete and recreate the record.

This is safer than partial editing.

### Proper long-term design

#### Transfer update API

Add:

```python
ApiHandler.update_transfer(...)
```

Recommended input:

```python
def update_transfer(
    tx_id: int,
    from_account_id: int,
    to_account_id: int,
    amount: float,
    transaction_date: str,
    transaction_time: str = "12:00",
    description: str = "Account Transfer",
    note: str = ""
) -> Dict[str, Any]:
```

Repository/service behaviour:

1. Resolve `tx_id` to `transfer_group_id`
2. Load both active legs
3. Validate exactly two legs exist
4. Validate source and destination are different
5. Update both legs in **one SQLite transaction**
6. Preserve group identity
7. Recompute both amount values exactly
8. Roll back if either update fails

#### Refund update API

Linked refund edits must preserve:

```text
refund_of_transaction_id
account_id
category semantics
financial sign semantics
```

Recommended:

```python
update_refund(refund_tx_id, amount, transaction_date, account_id, note, ...)
```

Do not allow a generic update to silently detach the linked relationship unless the UI explicitly asks the user to unlink it.

### Acceptance criteria

Transfer:

- Editing amount changes both legs exactly once.
- Editing date changes both legs.
- Editing source/destination updates balances correctly.
- Global net flow remains neutral.
- No extra transaction rows are created.
- `transfer_group_id` remains stable.

Refund:

- Editing amount changes the refund once.
- Original purchase remains unchanged.
- Net expense reflects the new refund amount.
- Refund cannot exceed business rules if such a rule is introduced.
- No duplicate refund is created.

### Regression tests

```text
REG-021 transfer edit does not create new rows
REG-022 transfer edit preserves global neutrality
REG-023 transfer edit updates both account balances
REG-024 refund edit does not create a second refund
REG-025 refund edit updates net expense exactly
```

---

## 3.3 Local date handling must not use UTC ISO dates

### Current risk

The transaction modal currently derives "Today" / "Yesterday" using:

```javascript
new Date().toISOString().split('T')[0]
```

`toISOString()` is UTC.

For users in positive UTC offsets, especially around midnight, "Today" may be saved as the previous calendar day.

### Required fix

Create one canonical local date helper.

Recommended:

```javascript
export function toLocalDateString(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}
```

Yesterday:

```javascript
export function localYesterdayString() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return toLocalDateString(d);
}
```

Replace all UI date defaults that mean **user-local calendar date**.

### Do not replace

Do not blindly replace ISO handling for timestamps that intentionally represent UTC. Only transaction/calendar date fields that represent a local calendar date should use the helper.

### Acceptance criteria

Test at simulated local times:

```text
UTC+7  2026-09-04 00:05 -> Today = 2026-09-04
UTC+7  2026-09-04 23:55 -> Today = 2026-09-04
UTC-7  2026-09-04 00:05 -> Today = 2026-09-04
```

### Test strategy

Prefer a small pure helper that accepts a `Date`, making it unit-testable without changing machine timezone.

---

## 3.4 Prevent duplicate submission

### Current risk

Transaction form submission is asynchronous, but Save / keyboard submission is not protected by a submission lock.

Possible user action:

```text
double click Save
Ctrl+Enter twice
slow machine + user retries
```

Potential result:

```text
two POST requests
two transaction rows
```

### Frontend fix

Add modal state:

```javascript
isSubmitting: false
```

Guard:

```javascript
async handleTransactionSubmit(isSaveAndAddAnother = false) {
  if (this.isSubmitting) return;
  this.isSubmitting = true;

  try {
    this.setSubmitState(true);
    // existing submit logic
  } finally {
    this.isSubmitting = false;
    this.setSubmitState(false);
  }
}
```

UI:

```text
Save -> Saving…
disable Save
disable Save & Add Another
block Ctrl+Enter re-entry
```

### Stronger backend protection

For maximum reliability, introduce optional idempotency.

Frontend:

```json
{
  "client_request_id": "uuid-v4"
}
```

Backend stores recent request IDs or writes them to a small idempotency table.

A lighter alternative is acceptable initially because the app is local-only, but frontend locking should be mandatory.

### Regression tests

Backend idempotency if implemented:

```text
same client_request_id submitted twice
=> exactly one transaction row
```

Frontend E2E/manual test:

```text
double-click Save rapidly
=> exactly one transaction
=> button remains disabled until request finishes
```

---

# 4. P1 — Scope consistency and stale state

## 4.1 Budget page must respect the selected account or clearly reject account scope

### Current behaviour

The global application state contains:

```javascript
state.accountId
```

but Budget currently requests:

```javascript
api.getMonthlyBudget(state.month)
```

without the account scope.

This breaks the user mental model because other screens use the global Month + Account context.

### Preferred design

Make account scope canonical across all finance screens.

API:

```javascript
getMonthlyBudget(month, accountId = null) {
  return this.call('get_monthly_budget', {
    month,
    account_id: accountId
  });
}
```

Backend:

```python
def get_monthly_budget(self, month: str, account_id: Optional[int] = None):
    return BudgetService.get_monthly_budget_status(month, account_id)
```

Repository queries must filter spend by account when provided.

### Product decision

Budget *limits* may remain category/month-level global values, while *actual spent* and projections can be account-scoped.

If this distinction is confusing, choose one explicit model:

#### Option A — Global budgets only

- Hide account selector on Budget page
- Display:

```text
Scope: All Accounts
```

#### Option B — Account budgets

Requires schema change:

```sql
account_id INTEGER NULL REFERENCES accounts(id)
```

and uniqueness:

```sql
UNIQUE(category_id, start_date, account_id)
```

For v1.x, **Option A or account-filtered actuals against global budget** is simpler.

### Acceptance criteria

- User can always tell which account scope is applied.
- Budget screen must never silently show "All Accounts" while topbar indicates one account.

---

## 4.2 Report and CSV export scopes must match

### Current risk

Report screen displays month/account scoped summary, while CSV export endpoint can export the entire active transaction set.

User expectation:

```text
September 2026 + Everyday Account
click Export CSV
```

Expected:

```text
September 2026 + Everyday Account rows
```

Not:

```text
entire database history
```

### Required design

Split export intents.

#### Reports page

```text
Export Current View
```

Request:

```text
/api/export_csv
?month=2026-09
&account_id=3
```

#### Settings / Data page

```text
Export All Transactions
```

Clearly labelled.

### Backend interface

Recommended service signature:

```python
def export_csv(
    month: Optional[str] = None,
    account_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
```

All exports must query `active_transactions`.

### Test cases

```text
EXP-001 month filter
EXP-002 account filter
EXP-003 month + account combined
EXP-004 soft-deleted rows excluded
EXP-005 refunds included with correct type
EXP-006 transfer rows included or excluded according to explicit export policy
```

---

## 4.3 Restore must refresh metadata, not only page data

### Current risk

After restore the database may contain different:

- accounts
- categories
- settings
- currency

but frontend state caches:

```javascript
state.accounts
state.categories
state.settings
```

A simple `data_changed` event does not guarantee these collections are reloaded.

### Required fix

After successful restore:

```javascript
await api.restoreBackup(path);

await state.loadInitialData();

if (
  state.accountId &&
  !state.accounts.some(a => a.id === state.accountId)
) {
  state.setAccountId(null);
}

state.notify({ type: 'database_restored' });
```

Avoid multiple redundant rerenders by controlling notification order.

### Better state API

Add:

```javascript
async reloadMetadata({ notify = true } = {})
```

Separate data reload from notification.

### Acceptance criteria

Restore database A -> B where B has different account/category configuration.

Immediately after restore, without restarting app:

- Account dropdown reflects B
- Category dropdown reflects B
- Currency reflects B
- Removed selected account falls back to All Accounts
- Current page renders using restored database
- Backup table refreshes

---

# 5. P1 — Frontend smoothness and render lifecycle

## 5.1 Separate presentation-only state changes from data reloads

### Current behaviour

Router rerenders the whole active page on events including:

```text
month_changed
account_changed
data_changed
privacy_toggled
```

Privacy mode should normally be a presentation concern, not a backend reload concern.

### Recommended event model

```text
month_changed       -> invalidate scoped data + reload
account_changed     -> invalidate scoped data + reload
transaction_changed -> invalidate relevant caches + reload
budget_changed      -> budget + forecast invalidation
privacy_changed     -> CSS/presentation update only
currency_changed    -> formatting/chart labels update
metadata_changed    -> selectors + dependent page reload
```

### Implementation options

#### Minimal change

Modify router subscription so privacy mode does not call `renderCurrentView()`.

#### Better change

Each page exposes lifecycle methods:

```javascript
{
  mount(container),
  refresh(event),
  unmount()
}
```

Router calls `unmount()` before replacing DOM.

This enables:

- chart disposal
- request cancellation
- event listener cleanup
- selective refresh

---

## 5.2 Add latest-request-wins or AbortController

### Current risk

Search and fast state changes can trigger overlapping requests.

Example:

```text
request A: search "W"
request B: search "Wool"
B returns first
A returns later
A overwrites the UI with stale results
```

### Lightweight solution

Per page:

```javascript
let requestSeq = 0;

async function loadTransactions() {
  const seq = ++requestSeq;
  const res = await api.getTransactions(...);

  if (seq !== requestSeq) return;

  renderTable(res.items, res.total);
}
```

### Preferred API-level solution

Support `AbortController`.

```javascript
let activeController = null;

async function loadTransactions() {
  activeController?.abort();
  activeController = new AbortController();

  const res = await api.call(
    'get_transactions',
    params,
    { signal: activeController.signal }
  );
}
```

Modify `api.call()`:

```javascript
async call(method, params = {}, options = {}) {
  return fetch(url, {
    ...,
    signal: options.signal
  });
}
```

Do not show error toast for `AbortError`.

### Acceptance criteria

Rapidly:

- typing in search
- switching months
- switching accounts
- switching analytics tabs

must never render stale data.

---

## 5.3 Fix ECharts lifecycle

### Current risk

Chart instances are retained in module-level variables while router may replace page DOM.

A chart instance can remain bound to a removed DOM node.

### Required pattern

Each chart page must implement cleanup.

```javascript
export function disposeOverviewCharts() {
  trendChartInstance?.dispose();
  donutChartInstance?.dispose();
  dailyChartInstance?.dispose();

  trendChartInstance = null;
  donutChartInstance = null;
  dailyChartInstance = null;
}
```

Router before navigation:

```javascript
currentPage?.unmount?.();
```

Or, before chart reuse:

```javascript
const existing = window.echarts.getInstanceByDom(chartDom);

if (!existing) {
  chart = window.echarts.init(chartDom);
}
```

### Resize listener

Do not add a new anonymous global listener each time a page mounts.

Use a stable handler and remove it on unmount.

### Acceptance criteria

Repeated sequence:

```text
Overview
Transactions
Overview
change month
toggle privacy
change account
resize window
```

must retain working charts with no duplicate listeners and no blank chart area.

---

## 5.4 Add a small client-side cache for read-only analytics

Do not over-engineer.

A short-lived cache can make month/account switching feel instant.

Suggested cache key:

```text
method + JSON.stringify(params)
```

Example:

```javascript
cache.get('month_summary:2026-09:account=3')
```

Invalidate on:

```text
transaction_changed
budget_changed
database_restored
metadata_changed
```

Recommended TTL:

```text
5–30 seconds
```

The primary benefit is avoiding duplicate calls during route rerender, not long-term caching.

---

# 6. P1/P2 — Transaction capture UX

## 6.1 Default to currently selected account

Current new-transaction behaviour should prefer:

```javascript
state.accountId
```

when it exists.

Fallback:

```javascript
state.accounts[0]
```

Recommended:

```javascript
const defaultAccountId =
  state.accountId ||
  state.accounts[0]?.id ||
  '';
```

This reduces input friction and respects global context.

---

## 6.2 Refund workflow should not require manual transaction ID knowledge

Do not make users type:

```text
Refund for transaction #184
```

### Recommended UX

Refund original purchase picker:

```text
Search purchase...
[ Woolworths       $84.30   Sep 02 ]
[ Nike            $160.00   Aug 31 ]
[ JB Hi-Fi        $499.00   Aug 25 ]
```

Search by:

- merchant
- amount
- date
- description

Then:

```text
Original purchase: Nike — $160.00
Refund amount: $80.00
```

### Backend validation

When linked:

- original transaction exists
- original is an expense
- not deleted
- account/category inheritance is explicit
- optionally prevent cumulative refunds > original amount

### Tests

```text
REF-001 link to valid expense
REF-002 reject deleted original
REF-003 reject transfer as refund source
REF-004 partial refund
REF-005 multiple partial refunds
REF-006 cumulative refund boundary
```

---

## 6.3 Dirty-form protection

Current modal can be closed by:

- Escape
- clicking backdrop
- Cancel

If the user has typed data, accidental close should not silently discard it.

### Implement

Track initial form snapshot:

```javascript
initialFormSnapshot
```

Before close:

```javascript
if (this.isDirty() && !confirm('Discard unsaved changes?')) {
  return;
}
```

Do not show confirmation if user has not changed anything.

---

## 6.4 Accessibility improvements

### Modal

Add:

```text
role="dialog"
aria-modal="true"
aria-labelledby="tx-modal-title"
```

Implement focus trap.

Return focus to the control that opened the modal.

### Buttons

Icon-only controls require:

```html
aria-label="Edit transaction"
aria-label="Delete transaction"
aria-label="Duplicate transaction"
```

### Toasts

Container:

```html
aria-live="polite"
aria-atomic="true"
```

Errors may use assertive messaging if necessary.

### Toast XSS hardening

Current toast API accepts a message and inserts it into `innerHTML`.

Use DOM nodes:

```javascript
const text = document.createElement('span');
text.textContent = message;
toast.appendChild(text);
```

Avoid interpolating arbitrary error text into HTML.

---

# 7. P1 — Filter state must match visible controls

Transactions stores filter state separately from freshly rendered controls.

After a route rerender, internal state and visible dropdowns can diverge.

### Required rule

At render time:

```text
UI controls must be initialised from activeFilters
```

or:

```text
activeFilters must reset explicitly on mount
```

Do not have an invisible active filter.

### Better design

Move filter state into one serialisable object:

```javascript
transactionQueryState = {
  month,
  accountId,
  categoryId,
  type,
  essentiality,
  search,
  page
}
```

Optionally mirror it to URL parameters in browser mode.

### Acceptance criteria

Every applied filter is visibly represented.

Add a:

```text
Clear Filters
```

button when any non-default filter is active.

---

# 8. P1 — Currency model must be explicit

## 8.1 Remove hard-coded `$` in charts

Formatting in chart tooltips/axes must use the same currency source as KPI cards.

Add:

```javascript
state.formatCompactCurrency(value)
```

Example implementation:

```javascript
formatCompactCurrency(amount) {
  if (this.privacyMode) return '••';

  return new Intl.NumberFormat(
    this.currency === 'VND' ? 'vi-VN' : 'en-US',
    {
      style: 'currency',
      currency: this.currency,
      notation: 'compact',
      maximumFractionDigits: 1
    }
  ).format(Number(amount || 0));
}
```

Use for ECharts tooltips/axis labels.

---

## 8.2 Decide whether multi-currency is supported

The `accounts` table currently has per-account currency.

If FinScope sums accounts globally without FX conversion, multi-currency totals are mathematically invalid.

### Recommended v1.x policy

Use **one workspace/base currency**.

Rules:

- All new accounts default to workspace currency
- Prevent account currency from differing unless experimental multi-currency mode exists
- Show explicit message in Account Manager:

> All accounts in this workspace use USD.

Do not build FX conversion until there is a clear product requirement.

---

# 9. P1 — Test infrastructure improvements

## 9.1 Add dev/test dependencies

Runtime `requirements.txt` contains only runtime libraries, while tests import `pytest`.

Create:

```text
requirements-dev.txt
```

Example:

```text
-r requirements.txt
pytest>=8.0
pytest-cov>=5.0
```

Optional later:

```text
ruff
mypy
playwright
```

### Standard test command

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Coverage:

```bash
python -m pytest --cov=app --cov-report=term-missing
```

---

## 9.2 Establish test layers

### Layer 1 — Pure unit tests

No database.

Examples:

- money conversions
- date helpers
- rolling metrics
- forecast weighting
- interval calibration
- duplicate fingerprint generation

### Layer 2 — Isolated SQLite integration tests

Use `FINSCOPE_DATA_DIR` fixture.

Examples:

- transaction repository
- transfer atomicity
- refund semantics
- budget scope
- forecast with real queries

### Layer 3 — HTTP API tests

Test:

- token
- request envelope
- API input validation
- export scopes
- restore
- errors

### Layer 4 — Browser/WebView interaction tests

Recommended later using Playwright in browser mode.

High-value flows:

```text
create expense
edit expense
delete + undo
create transfer
refund purchase
search
filter
switch month/account
backup + restore
```

### Layer 5 — Packaged Windows smoke test

Before tagged release:

- launch packaged app
- WebView2 loads
- create transaction
- restart app
- data persists
- backup/restore
- export
- no blank charts

---

# 10. P2 — Account and Category Manager

Backend CRUD already exists for accounts and categories. Expose it in the frontend instead of leaving configuration partially hidden.

## 10.1 Accounts page/section

Recommended fields:

```text
Name
Type
Institution
Opening balance
Workspace currency
Archived
Current balance
```

Actions:

```text
Add
Rename
Archive
Restore
```

Avoid hard-delete if transactions reference the account.

### API client methods

```javascript
createAccount(data)
updateAccount(accountId, fields)
deleteAccount(accountId)
```

Same pattern for categories.

### UX

After account mutation:

```javascript
await state.reloadMetadata();
```

---

## 10.2 Categories manager

Support:

```text
Name
Type
Icon
Color
Parent category
Archive
```

Archive should be preferred over destructive delete for categories used historically.

### Safety

If category has historical transactions:

- archive by default
- do not force user to recategorise immediately
- keep historical reporting intact

---

# 11. P2 — Bank CSV Import

This is one of the highest-value features for daily usability because it removes repeated manual entry.

The existing `transactions.source` model already includes:

```text
csv_import
```

which fits this direction.

## 11.1 Import workflow

```text
Choose CSV
  ↓
Choose account
  ↓
Detect or map columns
  ↓
Preview
  ↓
Duplicate detection
  ↓
Merchant/category suggestions
  ↓
Review unresolved rows
  ↓
Commit import batch
```

### Column mapping example

```text
CSV column       FinScope
--------------------------------
TransactionDate  transaction_date
Debit            expense amount
Credit           income amount
Description      merchant/description
```

Save reusable mapping profiles per institution.

---

## 11.2 Suggested schema additions

Migration:

```sql
CREATE TABLE import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    rows_total INTEGER NOT NULL DEFAULT 0,
    rows_imported INTEGER NOT NULL DEFAULT 0,
    rows_skipped INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE transactions ADD COLUMN import_batch_id INTEGER
    REFERENCES import_batches(id);

ALTER TABLE transactions ADD COLUMN import_fingerprint TEXT;
```

Index:

```sql
CREATE INDEX idx_tx_import_fingerprint
ON transactions(import_fingerprint);
```

### Duplicate fingerprint

When bank does not supply stable transaction ID:

```text
hash(
  account_id
  + transaction_date
  + amount_minor
  + normalized description
  + transaction_type
)
```

Do not silently drop duplicates based only on amount/date. Show them in review.

---

## 11.3 Import review states

```text
Ready
Likely duplicate
Needs category
Unrecognised format
Invalid amount/date
```

Use existing Review Queue where possible rather than building two separate review systems.

---

## 11.4 Import tests

```text
IMP-001 expense row
IMP-002 income row
IMP-003 negative debit convention
IMP-004 separate debit/credit columns
IMP-005 quoted comma merchant name
IMP-006 UTF-8 merchant
IMP-007 duplicate batch import
IMP-008 same-day same-amount legitimate transactions
IMP-009 malformed date
IMP-010 malformed amount
IMP-011 empty row
IMP-012 imported transaction excluded after soft-delete
```

---

# 12. P2 — Recurring Bills Manager

`recurring_rules` already exists and should become the explicit source of truth for known future bills.

## 12.1 UI

Example:

```text
Upcoming Bills
------------------------------------------------
Sep 06   Spotify       $13.99
Sep 10   Internet      $79.00
Sep 14   Rent         $620.00
Sep 22   Phone         $49.00

Expected remaining recurring spend: $761.99
```

Actions:

```text
Add recurring rule
Confirm detected recurring payment
Edit amount
Edit next due date
Pause
Resume
Archive
```

---

## 12.2 Extend recurring rule schema

Current schema is minimal.

Consider future migration:

```sql
ALTER TABLE recurring_rules ADD COLUMN interval_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE recurring_rules ADD COLUMN day_of_month INTEGER;
ALTER TABLE recurring_rules ADD COLUMN amount_mode TEXT NOT NULL DEFAULT 'fixed';
ALTER TABLE recurring_rules ADD COLUMN amount_tolerance_minor INTEGER NOT NULL DEFAULT 0;
ALTER TABLE recurring_rules ADD COLUMN last_matched_transaction_id INTEGER;
ALTER TABLE recurring_rules ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP;
```

Possible `amount_mode`:

```text
fixed
historical_median
historical_mean
variable
```

---

# 13. Forecast V3 — Target architecture

The current Forecast V2 has a good explainable structure:

```text
Actual spend to date
+ upcoming recurring
+ remaining variable spend
```

The goal of Forecast V3 should **not** be "add machine learning".

The goal should be:

> Use the correct future components, validate the exact live model historically, calibrate uncertainty from real errors, and explain the result clearly.

---

## 13.1 Define forecast semantics for past, current and future months

Current behaviour should be made explicit.

### Past completed month

Default:

```text
Actual month result
```

Optional:

```text
Historical forecast replay
As of day 5 / 10 / 15 / 20 / 25
```

Do not display a historical mid-month simulation as if it were a live projection.

### Current month

```text
Live month-end forecast
as_of_date = today
```

### Future month

```text
Forward forecast
actual_to_date = 0
```

Use:

- known recurring rules
- historical variable baseline
- income rules
- seasonality if supported

### API result metadata

Return:

```json
{
  "forecast_mode": "live",
  "as_of_date": "2026-09-04",
  "target_month": "2026-09",
  "is_historical_replay": false
}
```

Possible modes:

```text
actual
live
forward
historical_replay
```

---

# 14. Forecast V3 — Recurring component

## 14.1 Prefer `recurring_rules`

Current historical merchant-name deduplication is fragile.

Use priority:

```text
1. active recurring_rules
2. detected recurring patterns not yet confirmed
3. historical recurring fallback
```

### Recurring identity

Do not identify recurring bills using merchant name alone.

Use:

```text
recurring_rule_id
```

If no rule exists, detection key may include:

```text
normalised merchant
account
category
cadence
amount band
```

---

## 14.2 Match paid occurrences before counting upcoming bills

Problem example:

```text
Netflix normally due Sep 10
User is charged Sep 8
Today is Sep 9
```

Forecast must recognise the Sep occurrence is already paid.

Algorithm:

```text
for each recurring rule:
    expected occurrence = next expected date in target month

    search current-month active transactions
    for matching transaction around expected date

    if matched:
        mark occurrence fulfilled
    else if expected date > as_of_date:
        add to upcoming
```

### Matching window

Example:

```text
±3 days
```

but tune based on cadence and history.

Amount matching:

```text
fixed bill:
  strict or small tolerance

variable bill:
  historical range
```

### Test cases

```text
FRC-001 future recurring bill counted
FRC-002 bill paid early not counted twice
FRC-003 bill paid late matched
FRC-004 recurring bill deleted -> considered unpaid only if rule still active
FRC-005 paused recurring rule not forecast
FRC-006 two same-merchant subscriptions remain distinct
```

---

# 15. Forecast V3 — Variable spending component

## 15.1 Exclude recurring spend from variable baseline

Fallback and history should represent **non-recurring variable behaviour**.

Use:

```sql
transaction_type IN ('expense', 'refund')
AND is_recurring = 0
```

with net refund semantics.

Do not use total current net spending as variable daily pace because early rent/subscription payments can inflate it.

### Cold-start fallback

Instead of:

```text
total actual net spend / elapsed days
```

use:

```text
current non-recurring net spend / elapsed days
```

If there are too few observations, reduce confidence instead of pretending precision.

---

## 15.2 Historical variable baseline must be refund-aware

Historical variable weekday spend should use:

```text
expense - refund
```

not gross expenses only.

If a refund is linked to an expense category, it should reduce that category's historical variable baseline.

---

## 15.3 Category-specific variable models

Different categories behave differently.

Suggested classification:

```text
Recurring
Stable variable
Seasonal
Lumpy
Sparse
```

Examples:

```text
Groceries -> stable variable + weekday/calendar effects
Dining    -> variable + strong weekend effect
Shopping  -> lumpy
Rent      -> recurring
Insurance -> recurring/irregular
```

### Minimum category forecast

For each category:

```text
baseline remaining spend
× calendar adjustment
× current-month adjustment
```

Aggregate category forecasts back to total and reconcile to the top-level forecast.

---

# 16. Forecast V3 — Shrinkage between history and current month

Early-month pace is noisy.

Use a controlled blend:

```text
forecast variable rate
=
history_weight * historical_rate
+
current_weight * observed_current_rate
```

Weights should depend on:

- elapsed days
- number of observed transactions
- historical volatility
- backtested performance

Conceptual example only:

```text
Day  5: 90% history / 10% current
Day 15: 60% history / 40% current
Day 25: 25% history / 75% current
```

Do **not** hard-code these final values without backtesting.

Test a grid of candidate schedules and choose based on historical error.

---

# 17. Forecast V3 — True as-of backtesting

This is the most important forecast improvement.

The current monthly backtesting model should not be presented as proof of the live ForecastingEngine unless the same live algorithm is actually replayed historically.

## 17.1 Required methodology

For every historical target month:

```text
March
April
May
...
```

select multiple forecast origins:

```text
day 5
day 10
day 15
day 20
day 25
```

At each origin:

```text
1. Only expose data with transaction_date <= origin
2. Run the same ForecastingEngine code path
3. Predict target month-end
4. Compare against actual completed month
```

This is an **as-of replay**.

### Critical rule

No future leakage.

At `2026-05-10`, the model must not know:

- May 11–31 transactions
- recurring payments that were only discovered after May 10
- future merchant/category updates if they depend on later observations
- later refunds

---

## 17.2 Backtest result model

Store or return:

```json
{
  "model": "finscope_forecast_v3",
  "origins": 42,
  "mae_minor": 18500,
  "wape_pct": 7.4,
  "bias_pct": -1.3,
  "median_ape_pct": 6.1,
  "horizon_metrics": {
    "day_5":  { "wape_pct": 12.8 },
    "day_10": { "wape_pct": 9.6 },
    "day_15": { "wape_pct": 7.1 },
    "day_20": { "wape_pct": 5.2 },
    "day_25": { "wape_pct": 3.4 }
  }
}
```

### Keep baseline comparisons

Continue comparing against:

```text
Previous month
3M mean
3M median
EWMA
Seasonal naive
```

But rename the old weighted model so it is not confused with the live engine.

Example:

```text
monthly_blend_baseline
```

Do not call it `finscope_hybrid` if it is not the live forecast.

---

# 18. Forecast V3 — Empirical confidence and intervals

Current confidence should not be determined only by the number of history months.

## 18.1 Confidence inputs

Use:

```text
historical forecast error
number of backtest origins
historical volatility
current-month observed coverage
recurring coverage
data quality / review state
```

### Example confidence policy

High:

```text
>= 8 valid origins
WAPE <= 8%
low bias
good recurring match coverage
```

Moderate:

```text
>= 4 origins
WAPE <= 15%
```

Low:

```text
insufficient origins
high volatility
large recent anomalies
```

Exact thresholds should be tuned.

---

## 18.2 Prediction intervals from residuals

Instead of:

```text
±18% of remaining variable spend
```

use historical backtest residuals.

For each relevant forecast horizon:

```text
residual = actual - predicted
```

For an 80% interval:

```text
lower residual quantile = P10
upper residual quantile = P90
```

Then:

```text
lower = forecast + P10 residual
upper = forecast + P90 residual
```

If sample size is insufficient, fall back to conservative heuristic and label confidence low.

### Add interval coverage metric

Backtest:

```text
coverage =
% of actual values falling inside predicted interval
```

Example UI:

```text
Likely range: $2,620–$3,080
Historical interval coverage: 82%
```

---

# 19. Forecast V3 — Income, net cash flow and savings

Expense forecast alone is useful, but planning becomes much more useful with income.

## 19.1 Projected income

Use:

```text
actual income to date
+ known recurring salary/income
+ variable income baseline
```

Do not assume salary if no recurring rule/pattern exists.

### Output

```text
Projected income
Projected expense
Projected net cash flow
Projected savings rate
```

Formula:

```text
projected_net_flow
=
projected_income - projected_expense
```

```text
projected_savings_rate
=
projected_net_flow / projected_income
```

when projected income > 0.

---

# 20. Forecast V3 — Explainability payload

Every forecast should return structured components.

Example:

```json
{
  "projected_expense": 2840.00,
  "components": {
    "actual_to_date": 920.00,
    "upcoming_recurring": 761.99,
    "remaining_variable": 1158.01,
    "expected_refunds": 0.00
  },
  "confidence": {
    "band": "moderate",
    "typical_error_pct": 8.2,
    "sample_origins": 9
  },
  "range": {
    "lower": 2610.00,
    "upper": 3090.00
  },
  "explanation": [
    "3 recurring bills remain this month",
    "Weekend dining is running 12% above your recent baseline",
    "Groceries are close to their 3-month normal range"
  ]
}
```

The frontend should render the structured fields, not generate financial reasoning itself.

---

# 21. Forecast V3 test matrix

## 21.1 Temporal semantics

```text
FC-001 current month uses today's cutoff
FC-002 completed historical month defaults to actual
FC-003 historical replay respects as_of_date
FC-004 future month has zero actual_to_date
FC-005 February leap year
FC-006 month with 30 days
FC-007 Dec -> Jan boundary
```

## 21.2 Recurring

```text
FC-010 fixed bill upcoming
FC-011 paid early
FC-012 paid late
FC-013 changed bill amount
FC-014 two subscriptions same merchant
FC-015 paused recurring rule
FC-016 deleted recurring transaction
FC-017 rule exists but no history
```

## 21.3 Variable spend

```text
FC-020 no history
FC-021 one month history
FC-022 stable six-month history
FC-023 volatile history
FC-024 no current-month variable spend
FC-025 unusually high first-week spend
FC-026 large recurring bill on day 1 does not inflate variable pace
FC-027 refund reduces historical baseline correctly
```

## 21.4 Category forecasts

```text
FC-030 category totals reconcile to projected variable component
FC-031 category budget variance
FC-032 archived category history preserved
FC-033 uncategorised expense handling
```

## 21.5 Backtesting

```text
BT-001 no future leakage
BT-002 exact live engine is called
BT-003 day-5 metric
BT-004 day-15 metric
BT-005 day-25 metric
BT-006 WAPE calculation
BT-007 bias sign
BT-008 baseline comparison
BT-009 insufficient history
BT-010 interval coverage
```

## 21.6 Reconciliation invariants

Always assert:

```text
projected_expense
=
actual_to_date
+ upcoming_recurring
+ remaining_variable
+ irregular
- expected_refunds
```

and:

```text
sum(category projected amounts)
≈ total projected expense
```

Any rounding remainder must be assigned deterministically so there is no penny drift.

---

# 22. P2 — Net cash position / account balances

FinScope already has account balances. Surface them.

Recommended Overview card:

```text
Net Cash Position
$18,340

Everyday      $2,130
Savings      $15,900
Credit Card    -$690
Investments    $1,000
```

### Important

If multi-currency remains unsupported, only aggregate accounts using the workspace currency.

### Tests

Transfer must not change total cash position:

```text
before = sum balances
transfer A -> B
after = sum balances
assert before == after
```

Expense/income/refund should change it according to account semantics.

---

# 23. P2 — Responsive desktop UX

FinScope does not need to become a mobile app, but it should work well with Windows Snap Layout.

Recommended breakpoints:

```text
>= 1200px   full sidebar, 4-column KPI
900–1199px  2-column KPI
< 1000px    collapsible sidebar
< 850px     1-column dense content where appropriate
```

Analytics tabs should scroll horizontally instead of compressing unreadably.

### Manual test matrix

Windows sizes:

```text
1920x1080 full
1440x900
1366x768
1080x720 minimum
960x1080 half screen
```

Check:

- no clipped buttons
- no horizontal page overflow except intentional tab/table scrollers
- modal fits
- chart labels remain readable
- sidebar can collapse
- topbar wraps cleanly

---

# 24. P3 — Maintainability improvements

## 24.1 Fix latent category aggregation query

`AggregateQueries.get_categories_breakdown()` references:

```sql
c.essentiality
```

while category schema does not contain `essentiality`.

Essentiality belongs to transactions.

Decide intended semantics.

If category breakdown should include transaction essentiality, aggregate by:

```sql
t.essentiality
```

If not required, remove the column entirely.

Add a direct unit/integration test that calls this method so future schema drift is caught.

---

## 24.2 Reduce duplicate analytics implementations

There are legacy analytics paths in `AnalyticsService` and newer engine modules.

Long-term goal:

```text
AnalyticsService
    -> canonical aggregate/engine modules
```

rather than maintaining equivalent SQL in multiple places.

For example, Deep Dive variance should preferably delegate to the newer `WhatChangedEngine` instead of retaining independent calculation logic.

Benefits:

- fewer semantic mismatches
- soft-delete safety
- refund consistency
- account scope consistency
- fewer duplicate tests

---

## 24.3 Add schema contract tests

Test expected columns and views.

Examples:

```text
active_transactions exists
amount_minor is INTEGER
transfer_group_id exists
refund_of_transaction_id exists
recurring_rules exists
```

This catches schema/migration drift before runtime.

---

# 25. Recommended user-facing feature order

Do not prioritise another analytics dashboard before reducing daily friction.

Recommended order:

## Tier 1 — High user value

1. **CSV bank import**
2. **Recurring Bills Manager**
3. **Accounts / Categories Manager**
4. **Forecast V3**
5. **Net cash position**

## Tier 2 — Useful planning

6. Goals / sinking funds
7. Cash runway
8. Planned large expenses
9. Annual summary
10. Better bulk transaction editing

## Tier 3 — Consider later

- investment portfolio tracking
- bank API integrations
- AI chatbot
- tax engine
- credit score
- complex multi-currency FX

These should only be added when they support the core product identity.

---

# 26. Suggested release roadmap

## v1.0.1 — Correctness hotfix

Must include:

```text
P0 deep-dive soft-delete fix
safe transfer/refund editing behaviour
local date helper
submission lock
category aggregation SQL fix
restore metadata refresh
```

### Release gate

No release if any core financial regression test fails.

---

## v1.1.0 — UX & smoothness

Implement:

```text
request cancellation/latest-wins
chart lifecycle cleanup
partial/presentation-only rerender
filter state synchronisation
account scope consistency
CSV current-view export
selected account transaction default
dirty form protection
toast/accessibility hardening
responsive desktop layout
```

### Performance target

On a realistic 10k transaction local dataset:

- common navigation should feel immediate
- avoid visible full-page flicker
- cached/read-only revisits should not trigger unnecessary duplicate requests
- search must not display stale results

Benchmark exact timings on Windows before release.

---

## v1.2.0 — Data entry upgrade

Implement:

```text
Account Manager
Category Manager
CSV Import Wizard
mapping profiles
duplicate review
bulk categorisation
```

Success metric:

> A user should be able to import a bank statement and resolve unknown categories without manually retyping every transaction.

---

## v1.3.0 — Recurring + Forecast V3

Implement:

```text
Recurring Bills Manager
recurring rule matching
paid-early detection
variable-spend cleanup
refund-aware baseline
true as-of backtesting
empirical confidence intervals
category forecast improvements
```

### Forecast release gate

Do not market confidence as "High" unless it is tied to empirical error.

Expose:

```text
sample origins
typical historical error
forecast range
```

when available.

---

## v1.4.0 — Planning

Implement:

```text
projected income
projected net flow
projected savings rate
net cash position
cash runway
optional goals/sinking funds
```

---

# 27. Regression test catalogue

Suggested IDs to keep test history readable.

## Core money

```text
REG-001 amount-only update
REG-002 deleted expense excluded
REG-003 undo expense restored
REG-004 deleted refund semantics
REG-005 transfer neutrality
REG-006 transfer delete both legs
REG-007 transfer undo both legs
REG-008 backup WAL consistency
REG-009 restore integrity
REG-010 XSS escaping
```

## New correctness

```text
REG-020 deep-dive soft-delete current month
REG-021 deep-dive soft-delete comparison month
REG-022 transfer edit no duplicate
REG-023 transfer edit balance invariant
REG-024 refund edit no duplicate
REG-025 refund edit net-spend invariant
REG-026 local date UTC+ offset
REG-027 submission double-click protection
REG-028 restore metadata refresh
REG-029 budget account scope
REG-030 CSV export current-view scope
```

## UI state

```text
UI-001 stale search request cannot overwrite latest
UI-002 month switching latest request wins
UI-003 chart survives repeated route mount/unmount
UI-004 privacy toggle causes no business data mutation
UI-005 filter controls reflect active state
UI-006 selected account becomes default transaction account
UI-007 unsaved modal change prompts before discard
```

## Forecast

Use `FC-*` and `BT-*` cases defined earlier.

---

# 28. Definition of Done for financial features

A financial feature is not done until all are true:

- [ ] Uses integer minor units internally
- [ ] Defines transfer behaviour explicitly
- [ ] Defines refund behaviour explicitly
- [ ] Defines soft-delete behaviour explicitly
- [ ] Respects account scope
- [ ] Respects month/date scope
- [ ] Has at least one negative/error-path test
- [ ] Has a financial invariant test
- [ ] Does not trust frontend-calculated financial totals
- [ ] Has user-facing empty/loading/error states
- [ ] Does not silently lose user input
- [ ] Does not double-submit
- [ ] Works after backup/restore
- [ ] Does not expose stale cached state after mutation

---

# 29. Release checklist

## Automated

```bash
python -m pytest -q
```

Recommended:

```bash
python -m pytest --cov=app --cov-report=term-missing
```

Required result:

```text
0 failed
```

## Database

- [ ] New DB initialises
- [ ] Existing v1.0.0 DB migrates
- [ ] Migration rerun is idempotent
- [ ] `PRAGMA integrity_check` passes
- [ ] backup restores on new build

## Financial invariants

- [ ] transfer global net flow = 0
- [ ] transfer does not change total account balance
- [ ] refund offsets expense, not income
- [ ] soft-deleted records are excluded from all active analytics
- [ ] category totals reconcile
- [ ] forecast components reconcile

## UX smoke

- [ ] Add expense
- [ ] Add income
- [ ] Add transfer
- [ ] Add linked refund
- [ ] Edit supported types
- [ ] Delete + undo
- [ ] Search + filters
- [ ] Change month
- [ ] Change account
- [ ] Change currency
- [ ] Privacy mode
- [ ] Create backup
- [ ] Restore backup
- [ ] Export report
- [ ] Resize window
- [ ] Restart app

## Forecast smoke

- [ ] current month live forecast
- [ ] historical month
- [ ] future month
- [ ] recurring bill
- [ ] paid-early bill
- [ ] refund
- [ ] sparse history
- [ ] high volatility
- [ ] backtest metrics
- [ ] confidence/range shown correctly

---

# 30. Final technical direction

FinScope should not try to win by becoming a generic "AI finance app".

Its strongest technical identity is:

```text
Private
Offline
Correct
Explainable
Fast
Low-friction
Empirically validated
```

The next engineering focus should therefore be:

```text
Correctness
    ↓
Frictionless capture/import
    ↓
Consistent state and smooth rendering
    ↓
Recurring future cash-flow knowledge
    ↓
True forecast backtesting
    ↓
Calibrated uncertainty
    ↓
Planning
```

The forecast should evolve from:

> "FinScope calculated a projected value"

to:

> "FinScope projected this value from known bills and your spending pattern, and historically forecasts made at this point in the month have approximately X% typical error."

That is a stronger, safer, and more defensible product direction than adding opaque machine learning before the underlying personal-finance evidence is mature.
