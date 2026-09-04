# FinScope v1.0.3 – Residual Issues & Hardening Tracker

> Target release: `v1.0.4`  
> Scope: các lỗi/rủi ro còn lại sau khi recheck `v1.0.3`.

---

# Priority Overview

| ID | Finding | Severity | Priority |
|---|---|---:|---:|
| V103-01 | Currency selector báo success dù backend reject | 🔴 High | P1 |
| V103-02 | Settings API có thể persist invalid currency code | 🟠 High | P1 |
| V103-03 | Transfer create/update bypass ISO date validation | 🟠 High | P1 |
| V103-04 | All-account forecast collapse recurring merchant cùng tên ở nhiều account | 🔴 High | P1 |
| V103-05 | Generic transaction create cho phép standalone unlinked refund | 🟠 High | P1 |
| V103-06 | Router generation guard chưa prevent stale render side effects | 🟡 Medium | P2 |
| V103-07 | Route capability metadata chưa thực sự là authorization layer | 🟡 Medium | P2 |

---

# V103-01 – Currency selector báo thành công dù backend từ chối thay đổi

**Severity:** 🔴 High  
**Priority:** P1  
**Area:** Frontend state / Settings / Currency

---

## Current behaviour

Backend `v1.0.3` đã đúng khi không cho đổi base currency sau khi database đã có transaction.

Tuy nhiên frontend hiện có flow gần như:

```javascript
async setCurrency(currencyCode) {
    this.currency = currencyCode;

    try {
        await api.updateSettings({
            currency: currencyCode
        });
    } catch (err) {
        console.error(err);
    }
}
```

Điểm quan trọng là:

```text
state.currency
```

được đổi **trước khi backend xác nhận success**.

Ngoài ra exception từ API bị catch và không propagate lên caller.

Settings page sau đó vẫn có thể:

```javascript
await state.setCurrency(newCurr);

showToast(
    `Currency changed to ${newCurr}`,
    'success'
);
```

---

## Failure scenario

Database:

```text
Base currency = USD
Transactions exist = Yes
```

User vào Settings và chọn:

```text
VND
```

Flow:

```text
User selects VND
        ↓
state.currency = VND
        ↓
POST updateSettings
        ↓
Backend rejects:
"Currency cannot be changed after transactions exist"
        ↓
setCurrency catches error internally
        ↓
Caller thinks operation succeeded
        ↓
Success toast shown
```

---

## Result

Persistent database:

```text
USD
```

Frontend memory state:

```text
VND
```

User có thể thấy dashboard tạm thời format:

```text
₫ / VND
```

dù dữ liệu thực tế vẫn là USD.

Đây là một dạng:

```text
UI state != persisted state
```

---

## Why this matters

Currency không chỉ là cosmetic setting.

Nếu UI format amount bằng currency sai, user có thể hiểu:

```text
1000 USD
```

thành:

```text
1000 VND
```

dù numeric value không đổi.

Nó làm giảm độ tin cậy của toàn app.

---

# Recommended fix

Không mutate local state trước khi server success.

### Preferred flow

```javascript
async setCurrency(currencyCode) {
    await api.updateSettings({
        currency: currencyCode
    });

    this.currency = currencyCode;

    this.notify({
        type: 'currency_changed',
        currency: currencyCode
    });
}
```

Exception phải được propagate.

---

## Settings caller

```javascript
const previousCurrency = state.currency;

try {
    await state.setCurrency(newCurr);

    showToast(
        `Currency changed to ${newCurr}`,
        'success'
    );

} catch (err) {

    currencySelect.value =
        previousCurrency;

    showToast(
        err.message ||
        'Unable to change currency',
        'error'
    );
}
```

---

## Additional recommendation

Sau successful settings update, có thể reload canonical settings từ backend:

```javascript
const updated =
    await api.getSettings();

state.currency =
    updated.currency;
```

để đảm bảo:

```text
frontend state
=
backend state
```

---

# Acceptance criteria

- [ ] Currency state chỉ đổi sau successful backend response.
- [ ] Backend reject thì frontend giữ currency cũ.
- [ ] Backend reject không show success toast.
- [ ] Dropdown tự revert về persisted currency.
- [ ] Dashboard formatting không đổi khi operation fail.
- [ ] Error được hiển thị rõ cho user.

---

# Tests

```text
test_currency_state_changes_only_after_success
test_currency_reverts_when_backend_rejects
test_currency_failure_does_not_show_success_message
test_currency_failure_preserves_dashboard_format
```

---

# V103-02 – Settings API có thể lưu invalid currency code

**Severity:** 🟠 High  
**Priority:** P1  
**Area:** Backend validation / Settings

---

## Current behaviour

Project hiện có currency validator ở domain validation layer.

Tuy nhiên settings update path vẫn có thể nhận:

```json
{
  "currency": "BANANA"
}
```

và xử lý value này mà không nhất thiết gọi:

```python
validate_currency_code(...)
```

trước khi persist.

Nếu database chưa có transactions, code còn có thể update account currencies sang value mới.

---

## Failure scenario

Direct API request:

```json
{
  "currency": "ABCXYZ"
}
```

hoặc:

```json
{
  "currency": "<script>"
}
```

Nếu backend chỉ kiểm tra:

```text
new currency != current currency
```

nhưng không validate ISO currency code thì invalid state có thể được lưu.

---

## Result

Có thể xuất hiện:

```text
app_settings.currency = BANANA
accounts.currency = BANANA
```

Frontend formatter sau đó có thể:

- throw;
- fallback không nhất quán;
- hiển thị raw code;
- gây lỗi ở Intl.NumberFormat;
- làm reports không ổn định.

---

# Domain rule

Currency phải là canonical supported code.

Ví dụ:

```text
USD
AUD
VND
EUR
GBP
JPY
...
```

Không nhận arbitrary string.

---

# Recommended fix

Trong settings service:

```python
from app.backend.domain.validators import (
    validate_currency_code,
)
```

Sau đó:

```python
new_curr = settings.get("currency")

if new_curr is not None:
    new_curr = validate_currency_code(
        new_curr
    )
```

Validation phải xảy ra **trước**:

```text
checking whether currency can change
updating accounts
persisting app_settings
```

---

## Optional stricter model

Nếu FinScope chỉ support một finite list:

```python
SUPPORTED_CURRENCIES = {
    "USD",
    "AUD",
    "VND",
    "EUR",
    "GBP",
    "JPY",
}
```

then:

```python
if currency not in SUPPORTED_CURRENCIES:
    raise ValueError(
        "Unsupported currency."
    )
```

Điều này tốt hơn chỉ check regex:

```text
[A-Z]{3}
```

vì:

```text
ZZZ
```

vẫn match regex nhưng không phải currency FinScope support.

---

# Acceptance criteria

- [ ] Invalid currency string bị reject.
- [ ] Unsupported 3-letter code bị reject nếu app dùng whitelist.
- [ ] Valid currency code được normalize uppercase.
- [ ] Không account nào bị update trước validation.
- [ ] Failed update không thay đổi app settings.
- [ ] Failed update không thay đổi account currency.

---

# Tests

```text
test_settings_reject_invalid_currency_code
test_settings_reject_unsupported_currency
test_settings_currency_validation_happens_before_database_write
test_valid_currency_update_succeeds_when_database_empty
```

---

# V103-03 – Transfer create/update chưa validate ISO transaction date

**Severity:** 🟠 High  
**Priority:** P1  
**Area:** Transfer Service / Domain validation

---

## Current behaviour

Normal transaction path đã có date validation.

Ví dụ:

```text
YYYY-MM-DD
```

được validate trước khi insert.

Nhưng specialised transfer path hiện vẫn có thể nhận:

```python
transaction_date
```

rồi insert/update trực tiếp.

---

## Failure scenario

Direct API request:

```json
{
  "from_account_id": 1,
  "to_account_id": 2,
  "amount": 500,
  "transaction_date": "banana"
}
```

Transfer service vẫn có thể pass:

```text
different accounts
amount > 0
accounts exist
```

nhưng date không được validate.

---

## Result

Hai transfer legs có thể được tạo:

```text
transaction_date = banana
```

Database field là TEXT nên SQLite không tự reject.

---

## Impact

Invalid date có thể phá:

```text
monthly filtering
date range filtering
forecast
analytics
sorting
recurring logic
reports
CSV export
```

Ví dụ query:

```sql
WHERE transaction_date
BETWEEN '2026-09-01'
AND '2026-09-30'
```

sẽ không xử lý `"banana"` như transaction date bình thường.

---

# Recommended fix

Transfer create:

```python
clean_date =
    validate_iso_date(
        transaction_date,
        "Transfer transaction date"
    )
```

và dùng:

```python
clean_date
```

cho cả source/destination legs.

---

## Transfer update

Không dùng:

```python
if transaction_date:
    updates["transaction_date"] =
        transaction_date
```

Thay bằng:

```python
if transaction_date is not None:
    updates["transaction_date"] =
        validate_iso_date(
            transaction_date,
            "Transfer transaction date"
        )
```

---

# Additional invariant

Cả hai legs phải luôn có:

```text
same transaction_date
same transaction_time
```

nếu FinScope xem chúng là một logical transfer.

---

# Acceptance criteria

- [ ] Transfer create reject malformed date.
- [ ] Transfer update reject malformed date.
- [ ] Transfer accepts valid ISO `YYYY-MM-DD`.
- [ ] Source và destination luôn cùng date.
- [ ] Failed validation không tạo partial transfer.
- [ ] Failed update không modify một leg.

---

# Tests

```text
test_transfer_create_rejects_invalid_date
test_transfer_update_rejects_invalid_date
test_transfer_create_accepts_iso_date
test_transfer_pair_has_identical_date
test_invalid_transfer_update_is_atomic
```

---

# V103-04 – All-account forecast collapse recurring merchant cùng tên ở nhiều accounts

**Severity:** 🔴 High  
**Priority:** P1  
**Area:** Forecasting / Recurring bills

---

## Current behaviour

Recurring forecast sử dụng một set để tránh double-count:

```python
seen_bills
```

Key hiện được normalize chủ yếu từ:

```text
bill name
```

ví dụ:

```python
"netflix"
```

Điều này đúng để tránh:

```text
Netflix
NETFLIX
netflix
```

bị forecast nhiều lần trong cùng logical context.

Nhưng key chưa phân biệt account.

---

# Failure scenario

User có:

```text
Account A:
Netflix
$20/month
```

và:

```text
Account B:
Netflix
$15/month
```

Đây là hai obligations khác nhau.

Khi forecast cho all accounts:

```text
context.account_id = None
```

flow có thể thành:

```text
Encounter:
Account A + Netflix

seen_bills = {
    "netflix"
}
```

sau đó:

```text
Account B + Netflix
```

cũng tạo key:

```text
"netflix"
```

→ bị xem là already seen.

---

## Incorrect result

Expected:

```text
Netflix Account A = $20
Netflix Account B = $15

Total = $35
```

Possible current forecast:

```text
$20
```

hoặc:

```text
$15
```

tuỳ record nào được xử lý trước.

---

# Root cause

Recurring identity hiện gần như:

```text
normalized merchant/name
```

nhưng logical recurring obligation phải tối thiểu là:

```text
account
+
recurring identity
```

---

# Recommended fix

Canonical key:

```python
def recurring_key(
    account_id,
    name
):
    return (
        account_id,
        normalize_merchant_name(
            name or ""
        ).strip().casefold()
    )
```

---

## Historical recurring query

Phải select:

```sql
account_id
```

rồi:

```python
key = recurring_key(
    row["account_id"],
    row["merchant_name"]
)
```

---

## Explicit recurring rule

Cũng dùng:

```python
key = recurring_key(
    rule["account_id"],
    rule["name"]
)
```

---

# Better long-term identity

Tên merchant vẫn không phải perfect identity.

Ví dụ cùng account có:

```text
Netflix Basic
Netflix Add-on
```

hoặc hai subscriptions khác nhau cùng merchant.

Tốt nhất recurring forecast nên dựa trên:

```text
recurring_rule_id
```

khi có explicit rule.

Suggested key hierarchy:

```text
if recurring_rule_id exists:
    ("rule", recurring_rule_id)

else:
    (
        "detected",
        account_id,
        normalized merchant,
        amount bucket / category
    )
```

---

# Acceptance criteria

- [ ] Same merchant ở hai accounts được forecast riêng.
- [ ] Same recurring rule không double-count do casing.
- [ ] All-account forecast = sum logical obligations across accounts.
- [ ] Single-account forecast vẫn hoạt động như trước.
- [ ] Forecast deterministic independent of query row order.

---

# Tests

```text
test_all_account_forecast_keeps_same_merchant_across_accounts
test_same_account_case_variant_not_double_counted
test_explicit_recurring_rules_are_distinct_by_rule_id
test_all_account_forecast_is_deterministic
```

---

# V103-05 – Generic transaction create cho phép standalone unlinked refund

**Severity:** 🟠 High  
**Priority:** P1  
**Area:** Transaction integrity / Refunds

---

## Current behaviour

Project có specialised flow:

```text
create_refund()
```

với:

```text
original_transaction_id
refund amount validation
atomic cumulative-refund validation
```

Đây là đúng.

Nhưng generic:

```text
create_transaction()
```

vẫn có thể nhận:

```json
{
  "transaction_type": "refund",
  "amount": 50
}
```

mà không bắt buộc:

```text
refund_of_transaction_id
```

---

# Result

Database có thể tồn tại:

```text
transaction_type = refund
refund_of_transaction_id = NULL
```

Đây là refund không có original transaction.

---

## Why this is dangerous

Các business rules hiện assume refund có original expense để:

```text
calculate remaining refundable amount
validate cumulative refunds
link analytics
update/delete safely
```

Standalone refund bypass toàn bộ logic này.

---

## Invariant conflict

FinScope hiện có logic:

```text
refund
→ specialised update
→ linked original transaction
→ cumulative cap
```

Nhưng generic create lại cho trạng thái:

```text
refund
without original
```

Hai domain model đang mâu thuẫn.

---

# Recommended product decision

## Option A – Refund luôn linked ⭐ Recommended

Generic `create()` reject:

```python
if tx_type == "refund":
    raise ValueError(
        "Refunds must be created through create_refund()."
    )
```

Giống transfer.

Only:

```text
create_refund(original_transaction_id, ...)
```

được tạo refund.

---

## Option B – Support standalone bank credit

Nếu bank statement có refund nhưng user không biết original transaction, không nên dùng cùng semantics một cách mơ hồ.

Có thể tạo:

```text
transaction_type = income
source = refund
```

hoặc thêm:

```text
transaction_type = credit
```

hoặc explicitly:

```text
refund_of_transaction_id nullable
linked_refund boolean
```

Nhưng mọi analytics phải hiểu hai trường hợp.

Cho v1.x, Option A đơn giản và an toàn hơn.

---

# Recommended fix

Trong public generic create:

```python
if tx_type == "transfer":
    raise ValueError(
        "Transfers must be created through TransferService."
    )

if tx_type == "refund":
    raise ValueError(
        "Refunds must be created through create_refund()."
    )
```

Specialised refund function dùng internal low-level insert.

---

# Existing data audit

Sau fix, nên check database:

```sql
SELECT *
FROM active_transactions
WHERE transaction_type = 'refund'
AND refund_of_transaction_id IS NULL;
```

Expected:

```text
0 rows
```

Nếu existing users có rows này thì cần migration/repair strategy trước khi thêm DB-level constraint.

---

# Acceptance criteria

- [ ] Generic create cannot create refund.
- [ ] Refund must reference valid original transaction.
- [ ] Original transaction must be refundable type.
- [ ] Refund amount remains bounded.
- [ ] Existing normal transaction creation unaffected.
- [ ] Existing transfer protection unaffected.

---

# Tests

```text
test_generic_create_rejects_refund
test_create_refund_requires_original_transaction
test_refund_always_has_original_transaction_id
test_no_active_unlinked_refunds_exist
```

---

# V103-06 – Router generation guard chưa thực sự prevent stale render side effects

**Severity:** 🟡 Medium  
**Priority:** P2  
**Area:** Frontend router / Async rendering

---

## Current behaviour

Router đã thêm generation token.

Simplified:

```javascript
const generation =
    ++this.renderGeneration;

await route.render(container);

if (
    generation !==
    this.renderGeneration
) {
    return;
}
```

Ý tưởng đúng, nhưng guard xảy ra:

```text
AFTER route.render()
```

---

# Problem

`route.render()` không chỉ return data.

Nó có thể:

```text
await API
mutate DOM
register listeners
show toast
modify page state
```

Tức là stale render có thể đã gây side effects trước khi router kiểm tra generation.

---

# Race example

```text
T0:
Navigate → Analytics

Analytics render starts API request
```

```text
T1:
Immediately navigate → Transactions

renderGeneration increments
Transactions page renders
```

```text
T2:
Old Analytics request resolves

Analytics render function writes into DOM
or updates global state
```

```text
T3:
Router checks generation

"Oh, stale."
return;
```

Nhưng damage ở T2 đã xảy ra.

---

# Potential effects

- stale page modifies current DOM;
- loading state thay đổi sai;
- stale error toast xuất hiện;
- old event listeners được attach;
- global state bị overwritten;
- current route và visual content lệch nhau.

---

# Recommended fix A – AbortController ⭐ Preferred

Router giữ:

```javascript
this.currentAbortController
```

On navigation:

```javascript
this.currentAbortController?.abort();

const controller =
    new AbortController();

this.currentAbortController =
    controller;
```

Pass:

```javascript
signal: controller.signal
```

cho page render/API.

Example:

```javascript
await api.getDashboard({
    signal
});
```

Khi route đổi:

```text
old requests aborted
```

---

## Handle AbortError silently

```javascript
catch (err) {
    if (
        err.name === 'AbortError'
    ) {
        return;
    }

    showToast(...);
}
```

Không show:

```text
Failed to load analytics
```

khi user chỉ đơn giản chuyển trang.

---

# Recommended fix B – Detached rendering

Alternative:

```javascript
const staging =
    document.createElement('div');

await route.render(
    staging,
    context
);

if (
    generation !==
    this.renderGeneration
) {
    return;
}

container.replaceChildren(
    ...staging.childNodes
);
```

Stale render chỉ mutate detached node.

Tuy nhiên global side effects vẫn cần control.

---

# Best pattern

Kết hợp:

```text
AbortController
+
generation check
```

Generation vẫn là safety net.

Abort là primary cancellation.

---

# Acceptance criteria

- [ ] Rapid route changes không cho stale page alter current content.
- [ ] Previous API request bị cancel khi route changes.
- [ ] Abort không trigger error toast.
- [ ] Current route always matches page content.
- [ ] Stale render không attach active event listeners vào current page.

---

# Tests

```text
test_navigation_aborts_previous_page_request
test_stale_page_cannot_overwrite_current_page
test_abort_does_not_show_error_toast
test_current_route_matches_rendered_page_after_rapid_navigation
```

Frontend integration/E2E test phù hợp hơn source-string test cho issue này.

---

# V103-07 – Route capability metadata chưa thực sự là authorization layer

**Severity:** 🟡 Medium  
**Priority:** P2  
**Area:** Local API authorization

---

## Current behaviour

Routes có metadata dạng:

```text
READ
WRITE
DESTRUCTIVE
PRIVILEGED_DESKTOP
```

Ví dụ conceptual:

```python
Route(
    handler=delete_account,
    capability="DESTRUCTIVE"
)
```

Nhưng execution path chủ yếu vẫn:

```text
validate session token
find route
call handler
```

Capability chưa tạo ra khác biệt authorization rõ ràng giữa:

```text
READ
WRITE
DESTRUCTIVE
```

---

## Why this matters

Metadata như:

```text
DESTRUCTIVE
```

tạo expectation rằng operation có security boundary riêng.

Nhưng nếu:

```text
same token
same checks
same permission
```

cho cả read và destructive operations thì capability chỉ là label.

Điều này dễ gây:

```text
false sense of security
```

cho future developer.

---

# Product decision

Có hai hướng hợp lệ.

---

# Option A – Actually enforce capabilities

Nếu muốn giữ model này, define authorization policy.

Example:

```text
READ
→ trusted local origin

WRITE
→ trusted origin + session token

DESTRUCTIVE
→ trusted origin + session token
   + explicit destructive authorization rule

PRIVILEGED_DESKTOP
→ desktop/native context only
```

---

## Example central authorization

```python
def authorize_request(
    request,
    capability
):
    if capability == READ:
        ...

    elif capability == WRITE:
        require_session_token(...)

    elif capability == DESTRUCTIVE:
        require_session_token(...)
        require_trusted_origin(...)

    elif capability == PRIVILEGED_DESKTOP:
        require_native_context(...)
```

Sau đó:

```python
route =
    ROUTES[method_name]

authorize_request(
    request,
    route.capability
)

return route.handler(...)
```

---

# Option B – Remove capability metadata

Nếu current threat model chỉ cần:

```text
all local API methods require same session authorization
```

thì simpler and clearer là bỏ:

```text
READ
WRITE
DESTRUCTIVE
```

metadata.

Keep only route handler mapping.

Security model documented explicitly:

```text
All state-changing endpoints require:
- exact FinScope local origin
- valid session token
```

Better no abstraction than misleading abstraction.

---

# Recommendation

Cho current local desktop app:

- giữ `READ`;
- `WRITE` + `DESTRUCTIVE` có thể cùng token policy;
- `PRIVILEGED_DESKTOP` chỉ giữ nếu thật sự có native-only enforcement.

Nếu chưa có use case capability separation, **remove hoặc rename metadata thành classification**.

Ví dụ:

```text
risk_class
```

thay vì:

```text
capability
```

để developer không hiểu nhầm nó là permission.

---

# Acceptance criteria

Một trong hai phải đúng:

### Model A

- [ ] Capability được central authorize.
- [ ] Tests chứng minh capability classes có policy khác nhau khi cần.
- [ ] Privileged desktop route không callable từ normal browser context nếu được định nghĩa như vậy.

### Model B

- [ ] Unused capability metadata removed.
- [ ] Security model documented clearly.
- [ ] No dead authorization abstraction remains.

---

# Tests

Nếu enforce:

```text
test_write_route_requires_authorization
test_destructive_route_requires_authorization
test_privileged_route_rejects_non_native_context
test_route_authorization_uses_capability
```

---

# Recommended Implementation Order

## Phase 1 – Financial/domain correctness

```text
V103-01
Currency frontend state consistency
```

↓

```text
V103-02
Currency backend validation
```

↓

```text
V103-03
Transfer date validation
```

↓

```text
V103-04
Multi-account recurring forecast
```

↓

```text
V103-05
Unlinked refund prevention
```

---

## Phase 2 – Frontend/API hardening

```text
V103-06
Async route cancellation
```

↓

```text
V103-07
Capability model cleanup/enforcement
```

---

# Suggested Commit Structure

```text
fix(settings): only update currency state after backend success

fix(settings): validate currency codes before persistence

fix(transfers): validate ISO dates on create and update

fix(forecast): scope recurring identities by account

fix(refunds): reject refund creation through generic transaction API

fix(router): cancel stale page requests during navigation

refactor(server): enforce or remove unused route capability metadata
```

---

# Definition of Done

Mỗi issue chỉ close khi:

```text
[ ] Root cause fixed
[ ] Backend invariant protected where applicable
[ ] Frontend state remains consistent with persisted state
[ ] Direct API bypass considered
[ ] Failure path tested
[ ] Regression test added
[ ] Existing tests still pass
[ ] No stale/invalid data state introduced
```

---

# v1.0.4 Final Checklist

## Currency

```text
[ ] Backend rejects invalid currency
[ ] Currency cannot change after financial data exists
[ ] Frontend only updates currency after backend success
[ ] Failed change reverts UI cleanly
```

## Transfers

```text
[ ] Transfer create validates ISO date
[ ] Transfer update validates ISO date
[ ] Both transfer legs always share valid date
```

## Forecast

```text
[ ] Same merchant in different accounts remains distinct
[ ] Same obligation is not double-counted due casing
[ ] All-account forecast equals sum of account-level obligations
```

## Refunds

```text
[ ] Generic API cannot create refund
[ ] Every refund is linked to an original transaction
[ ] No active orphan refund exists
```

## Router

```text
[ ] Route navigation cancels stale requests
[ ] Stale render cannot modify current page
[ ] Abort does not display misleading error
```

## API

```text
[ ] Route security model is explicit
[ ] Capability metadata is either enforced or removed
[ ] No misleading dead authorization layer remains
```

---

# Suggested Release Gate for v1.0.4

Before tagging `v1.0.4`, minimum recommended gate:

```text
P1 issues:
V103-01 ✅
V103-02 ✅
V103-03 ✅
V103-04 ✅
V103-05 ✅
```

`V103-06` và `V103-07` có thể được xem là hardening/P2 nếu cần tách release, nhưng 5 issue P1 phía trên nên được hoàn thành trước khi coi financial/domain correctness của `v1.0.3` là fully remediated.