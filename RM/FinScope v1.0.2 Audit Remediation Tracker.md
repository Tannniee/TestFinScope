# FinScope v1.0.2 – Audit Remediation Tracker

> Target release: `v1.0.3`  
> Purpose: theo dõi các lỗi/rủi ro phát hiện trong audit toàn app và hướng sửa đề xuất.

---

# Priority Overview

| ID | Finding | Severity | Type | Priority |
|---|---|---:|---|---:|
| AUD-001 | Multi-currency bị cộng trực tiếp như cùng currency | 🔴 High | Financial correctness | P0 |
| AUD-002 | Soft-deleted transactions vẫn ảnh hưởng một số analytics | 🔴 High | Financial correctness | P0 |
| AUD-003 | Refund validation có concurrency race | 🟠 High | Data integrity | P1 |
| AUD-004 | CSV preview/commit mismatch + date ambiguity + false duplicate | 🟠 High | Import correctness | P1 |
| AUD-005 | Recurring bill có thể bị đánh paid bởi transaction sai account/type | 🟠 High | Recurring correctness | P1 |
| AUD-006 | Forecast recurring có thể double-count hoặc dùng history không deterministic | 🟠 High | Forecast correctness | P1 |
| AUD-007 | Demo/sample data tự tạo transfer không đúng invariant | 🟠 High | Data integrity | P1 |
| AUD-008 | Backup restore chưa tự rollback nếu fail sau khi overwrite live DB | 🟠 High | Recovery safety | P1 |
| AUD-009 | Category colour còn stored DOM injection path | 🟠 Medium | Frontend security | P1 |
| AUD-010 | Localhost origin/token model còn quá rộng | 🟠 Medium | API security | P1 |
| AUD-011 | Backend validation còn thiếu ở amount/date/budget/recurring | 🟠 Medium | Domain validation | P1 |
| AUD-012 | `schema.sql` và schema thật từ migrations bị drift | 🟠 Medium | Schema correctness | P1/P2 |
| AUD-013 | Recent Payee suggestion lấy metadata không deterministic | 🟡 Medium | UX/data correctness | P2 |
| AUD-014 | Async page render có stale-render race | 🟡 Medium | Frontend reliability | P2 |
| AUD-015 | Test/dev dependencies chưa quản lý rõ | 🟡 Low | Engineering hygiene | P2 |

---

# AUD-001 – Multi-currency đang được cộng trực tiếp như cùng một currency

**Severity:** 🔴 High  
**Priority:** P0  
**Area:** Accounts / Analytics / Settings / Reporting

## Current behaviour

FinScope cho mỗi account có field:

```text
currency
```

Ví dụ:

```text
Account A → USD
Account B → VND
```

Trong khi analytics tổng hợp toàn account hiện cộng trực tiếp:

```sql
SUM(amount_minor)
```

mà không:

```text
group by currency
convert FX
store base currency amount
```

Display Currency ở Settings về bản chất đang hoạt động chủ yếu như formatting setting.

Điều này có thể dẫn đến:

```text
Account A:
1,000 USD

Account B:
10,000,000 VND
```

nhưng dashboard tổng:

```text
1,000 + 10,000,000
```

rồi format toàn bộ theo một currency duy nhất.

---

## Why this is dangerous

Đây không phải lỗi hiển thị đơn thuần.

Nó làm sai:

```text
Net worth
Income totals
Expense totals
Monthly comparison
Budget utilisation
Forecast
What Changed?
Merchant analytics
Category analytics
```

Nếu hai currency khác nhau được cộng như cùng đơn vị, mọi aggregated metric cross-account đều không còn ý nghĩa tài chính.

---

## Example failure

### Step 1

Tạo account:

```text
Everyday
Currency: USD
Balance: 1,000
```

### Step 2

Đổi Display Currency sang:

```text
VND
```

### Step 3

Tạo account khác:

```text
Savings Vietnam
Currency: VND
Balance: 10,000,000
```

### Step 4

Mở Overview.

Nếu app hiển thị kiểu:

```text
Total Balance:
10,001,000 VND
```

thì đây là incorrect financial aggregation.

---

# Recommended product decision

## Option A – Single-currency application ⭐ Recommended for v1.x

FinScope chỉ có một:

```text
base_currency
```

Mọi account bắt buộc dùng cùng currency.

Ví dụ:

```text
settings.base_currency = "USD"
```

và:

```text
account.currency = base_currency
```

### Rules

Nếu đã có transaction/account:

```text
Changing base currency
```

không nên chỉ đổi symbol.

Có thể:

```text
Disable currency change after first financial data exists
```

hoặc yêu cầu:

```text
Reset database / migrate data
```

---

## Option B – True multi-currency

Nếu muốn support thật sự:

```text
amount_minor
native_currency

base_amount_minor
base_currency

fx_rate
fx_rate_date
```

Mọi cross-account analytics dùng:

```text
base_amount_minor
```

Nhưng đây là scope lớn hơn nhiều.

---

# Recommended fix for v1.0.3

Chọn single-currency.

### Backend

Khi create account:

```python
account_currency = settings.base_currency
```

Không nhận arbitrary currency từ client.

Hoặc validate:

```python
if requested_currency != base_currency:
    raise ValueError(
        "All accounts must use the application base currency."
    )
```

### Settings

Nếu database đã có financial data:

```text
Base Currency
[ USD ] 🔒
```

và giải thích:

```text
Currency cannot be changed after financial data has been created.
```

---

# Acceptance criteria

- [ ] Không thể tạo hai active accounts với hai currencies khác nhau.
- [ ] Display Currency không chỉ đổi symbol mà gây hiểu lầm về conversion.
- [ ] All-account analytics chỉ aggregate cùng một currency.
- [ ] Existing databases có migration/validation phù hợp.
- [ ] Currency mismatch được phát hiện rõ thay vì silently aggregate.

---

# Tests

```text
test_account_currency_must_match_base_currency
test_cannot_change_base_currency_after_financial_data_exists
test_all_account_analytics_operates_on_single_currency
```

---

# AUD-002 – Soft-deleted transactions vẫn ảnh hưởng một số analytics

**Severity:** 🔴 High  
**Priority:** P0  
**Area:** Analytics / What Changed / Anomalies

---

## Current behaviour

FinScope dùng soft-delete:

```text
is_deleted = 1
```

và có view:

```sql
active_transactions
```

để chỉ lấy transaction đang active.

Một số analytics đã dùng đúng:

```sql
FROM active_transactions
```

nhưng một số module vẫn query raw table:

```sql
FROM transactions
```

hoặc:

```sql
JOIN transactions
```

Điều này khiến deleted transaction vẫn ảnh hưởng analytics.

---

## Example failure

Ban đầu:

```text
Dining
$300
```

User delete một transaction:

```text
$100
```

Expected:

```text
Dining total = $200
```

Overview có thể đúng:

```text
$200
```

nhưng:

```text
What Changed?
Category Anomaly
```

vẫn có thể tính:

```text
$300
```

---

## Why this matters

Đây là consistency violation.

Cùng một database nhưng:

```text
Overview says $200
Analytics says $300
```

User không biết màn nào đúng.

Đối với finance app, đây là issue nghiêm trọng vì analytics được user dùng để ra quyết định.

---

# Root cause

Không có một rule toàn app kiểu:

```text
User-facing transaction query
→ active_transactions by default
```

Một số analytics query raw table trực tiếp.

---

# Recommended fix

Search toàn backend cho:

```text
FROM transactions
JOIN transactions
LEFT JOIN transactions
```

Classify từng query.

### Default rule

Nếu query phục vụ:

```text
analytics
dashboard
budget
forecast
merchant stats
reports
recurring matching
```

thì dùng:

```sql
active_transactions
```

### Raw `transactions`

Chỉ dùng khi thật sự cần:

```text
Trash
Restore deleted transaction
Audit/history
Internal integrity repair
```

---

# Additional recommendation

Tạo convention/helper:

```python
ACTIVE_TX_VIEW = "active_transactions"
```

hoặc repository-level query APIs để analytics không tự query raw table tùy ý.

---

# Acceptance criteria

- [ ] Deleted expense không xuất hiện trong Overview.
- [ ] Deleted expense không xuất hiện trong What Changed.
- [ ] Deleted expense không ảnh hưởng anomalies.
- [ ] Deleted expense không ảnh hưởng recurring matching.
- [ ] Deleted expense không ảnh hưởng forecast.
- [ ] Deleted transaction chỉ xuất hiện ở trash/history features.

---

# Regression tests

```text
test_deleted_transaction_excluded_from_month_summary
test_deleted_transaction_excluded_from_what_changed
test_deleted_transaction_excluded_from_category_anomalies
test_deleted_transaction_excluded_from_forecast
```

Suggested integration test:

```text
Create transaction
→ calculate every analytics output
→ delete transaction
→ rerun all analytics
→ transaction must disappear everywhere
```

---

# AUD-003 – Refund validation có concurrency race

**Severity:** 🟠 High  
**Priority:** P1  
**Area:** Refund / SQLite transactions / API concurrency

---

## Current behaviour

Refund validation hiện theo flow gần như:

```text
Read original transaction
↓
SUM existing refunds
↓
Calculate remaining refundable amount
↓
Validate requested refund
↓
Insert refund
```

Nhưng validation và final INSERT không được đảm bảo chạy trong cùng một locked write transaction.

Server sử dụng threaded request handling.

---

# Race scenario

Original expense:

```text
$100
```

Existing refunds:

```text
$0
```

Hai HTTP requests chạy gần như đồng thời:

```text
Request A:
refund $70

Request B:
refund $70
```

### A

Đọc:

```text
remaining = $100
```

Pass.

### B

Cũng đọc trước khi A commit:

```text
remaining = $100
```

Pass.

Sau đó cả hai insert.

Final state:

```text
Original expense: $100
Total refunds:    $140
```

Invariant:

```text
total refunds <= original amount
```

bị phá.

---

# Recommended fix

Validation + write phải atomic.

SQLite flow:

```sql
BEGIN IMMEDIATE;
```

Sau đó trong **cùng connection**:

```text
SELECT original
SELECT SUM(active refunds)
validate
INSERT refund
COMMIT
```

Nếu fail:

```text
ROLLBACK
```

`BEGIN IMMEDIATE` giúp acquire write reservation sớm, tránh hai writers cùng validate stale state.

---

## Pseudocode

```python
conn = get_connection()

try:
    conn.execute("BEGIN IMMEDIATE")

    original = load_original(conn, original_id)

    refunded = get_total_refunded(
        conn,
        original_id
    )

    remaining = original.amount_minor - refunded

    if requested_minor > remaining:
        raise ValueError(...)

    insert_refund(
        conn,
        ...
    )

    conn.commit()

except:
    conn.rollback()
    raise

finally:
    conn.close()
```

---

# Apply same principle to update refund

Nếu edit refund amount:

```text
Current refund = $20
Other refunds = $30
Original = $100
```

Available for this refund:

```text
100 - 30 = $70
```

Validation phải tính:

```text
all other refunds
```

trong cùng write transaction.

---

# Acceptance criteria

- [ ] Concurrent refunds không thể vượt original expense.
- [ ] Validation và insert dùng cùng connection.
- [ ] Failed refund transaction rollback hoàn toàn.
- [ ] Updating refund cũng atomic.
- [ ] Deleted refunds không tính vào active refunded amount.

---

# Tests

```text
test_create_refund_is_atomic
test_concurrent_refunds_cannot_over_refund
test_refund_update_is_atomic
test_deleted_refund_restores_refundable_amount
```

---

# AUD-004 – CSV import correctness issues

**Severity:** 🟠 High  
**Priority:** P1  
**Area:** CSV import

Có ba sub-issues:

```text
AUD-004A Preview/commit mismatch
AUD-004B Ambiguous date interpretation
AUD-004C Duplicate fingerprint too aggressive
```

---

# AUD-004A – Preview và commit không nhất quán

## Current behaviour

Preview bắt đầu với fingerprints từ database.

Ví dụ CSV:

```text
01/09/2026,Starbucks,-5
01/09/2026,Starbucks,-5
```

Nếu DB ban đầu chưa có hai rows này:

Preview có thể đánh cả hai:

```text
valid
valid
```

vì preview không add fingerprint row đầu vào working set.

Commit thì:

```text
insert first row
add fingerprint

second row
→ duplicate
```

Kết quả:

```text
Preview:
2 valid
0 duplicate

Commit:
1 imported
1 skipped
```

---

# Expected behaviour

Preview phải phản ánh chính xác commit.

Invariant:

```text
preview outcome
=
commit outcome
```

trừ khi database bị thay đổi bởi một operation khác giữa preview và commit.

---

# Recommended fix

Preview dùng mutable working set:

```python
working = set(existing_fingerprints)

for row in rows:
    parsed = parse_row(
        row,
        working
    )

    if parsed.is_valid \
       and not parsed.is_duplicate:
        working.add(
            parsed.fingerprint
        )
```

Commit dùng cùng logic.

Tốt nhất tách:

```python
normalize_import_rows(...)
```

trả full normalized plan.

Preview:

```text
display plan
```

Commit:

```text
execute same plan
```

---

# Acceptance criteria

- [ ] Duplicate trong cùng CSV được preview detect.
- [ ] Preview counts = commit counts.
- [ ] Preview and commit dùng cùng parser/fingerprint logic.

---

# Test

```text
test_csv_preview_matches_commit_for_in_file_duplicates
```

---

# AUD-004B – Ambiguous date format

## Current behaviour

Parser thử nhiều date formats theo thứ tự.

Value:

```text
01/02/2026
```

có thể nghĩa:

```text
1 February 2026
```

hoặc:

```text
January 2 2026
```

Nếu parser mặc định thử `DD/MM/YYYY` trước thì transaction sẽ silently được hiểu theo kiểu đó.

---

# Why this matters

CSV ngân hàng từ:

```text
Australia
US
Europe
```

có thể dùng format khác nhau.

Nếu user import:

```text
03/04/2026
```

sai interpretation rất khó phát hiện vì cả hai đều là valid dates.

---

# Recommended fix

CSV import wizard thêm:

```text
Date Format

○ Auto Detect
○ DD/MM/YYYY
○ MM/DD/YYYY
○ YYYY-MM-DD
```

Nếu Auto Detect gặp date ambiguous:

```text
01/02/2026
```

đánh:

```text
Ambiguous date
```

thay vì guess.

---

# Acceptance criteria

- [ ] User có thể chọn explicit date format.
- [ ] Ambiguous date không silently interpreted trong Auto mode.
- [ ] Preview hiển thị normalized ISO date.
- [ ] Commit dùng date format đã preview.

---

# Tests

```text
test_ddmmyyyy_import
test_mmddyyyy_import
test_iso_date_import
test_auto_detect_rejects_ambiguous_date
```

---

# AUD-004C – Duplicate fingerprint vẫn có false positives

## Current fingerprint

Gần dạng:

```text
account
date
amount
transaction type
merchant
```

Nếu có payee thì description có thể không tham gia fingerprint.

---

# Example false duplicate

Hai giao dịch thật:

```text
04/09
Starbucks
$5
Morning coffee
```

và:

```text
04/09
Starbucks
$5
Afternoon coffee
```

Có cùng:

```text
account
date
amount
type
merchant
```

nhưng là hai purchases khác nhau.

Transaction thứ hai có thể bị skip.

---

# Recommended duplicate strategy

## Tier 1

Nếu bank cung cấp:

```text
transaction_id
bank_reference
external_id
```

dùng:

```text
account_id + external_id
```

để deduplicate.

---

## Tier 2

Fallback fingerprint:

```text
account_id
date
amount_minor
transaction_type
normalized_merchant
normalized_description
```

---

## Tier 3

Nếu vẫn không đủ chắc:

```text
possible_duplicate
```

không automatically skip.

UI:

```text
Possible duplicate

Existing:
04/09 | Starbucks | $5

Import:
04/09 | Starbucks | $5

[Skip]
[Import Anyway]
```

---

# Acceptance criteria

- [ ] Same date + same amount + different merchant không duplicate.
- [ ] Same merchant + same amount nhưng different description có thể coexist.
- [ ] External bank ID được ưu tiên nếu có.
- [ ] Ambiguous matches không silently discard legitimate records.

---

# Tests

```text
test_same_merchant_same_amount_different_description_not_duplicate
test_external_transaction_id_dedup
test_possible_duplicate_can_be_imported_anyway
```

---

# AUD-005 – Recurring bill có thể bị đánh paid bởi transaction sai

**Severity:** 🟠 High  
**Priority:** P1  
**Area:** Recurring rules

---

## Current behaviour

Recurring rule có thể chứa:

```text
account_id
transaction_type
amount
category
name
```

Nhưng recurring matching lấy candidate transactions trong period rồi fuzzy match dựa vào:

```text
name
amount
category
```

mà không đủ chặt theo:

```text
account_id
transaction_type
```

---

# Example failure

Recurring rule:

```text
Netflix
Account: Credit Card
Type: expense
Amount: $19.99
```

Trong cùng tháng có transaction khác:

```text
Account: Everyday
Type: refund
Merchant: Netflix
Amount: $19.99
```

Nếu matcher chỉ nhìn name/amount/category, recurring rule có thể bị đánh:

```text
paid
```

dù actual Netflix expense trên Credit Card chưa xảy ra.

---

# Recommended fix

Candidate transaction trước fuzzy matching phải satisfy:

```python
tx.account_id == rule.account_id
```

và:

```python
tx.transaction_type == rule.transaction_type
```

sau đó mới match:

```text
merchant/name
amount tolerance
category
date window
```

---

# Better long-term design

Khi transaction được:

```text
generated from recurring rule
```

hoặc user manually marks it linked, lưu:

```text
recurring_rule_id
```

trên transaction.

Khi đó:

```text
rule paid status
```

ưu tiên exact linkage.

Fuzzy matching chỉ dùng cho auto-detection legacy/imported transactions.

---

# Acceptance criteria

- [ ] Transaction ở account khác không mark rule paid.
- [ ] Income/refund không mark expense recurring rule paid.
- [ ] Correct transaction ở đúng account/type vẫn match.
- [ ] Deleted transaction không mark recurring rule paid.

---

# Tests

```text
test_recurring_match_requires_account
test_recurring_match_requires_transaction_type
test_deleted_transaction_does_not_mark_rule_paid
test_correct_recurring_transaction_marks_paid
```

---

# AUD-006 – Forecast recurring double-count / historical selection issue

**Severity:** 🟠 High  
**Priority:** P1  
**Area:** Forecasting

---

# AUD-006A – Case normalization mismatch

## Current behaviour

Historical recurring name có thể được thêm vào set như:

```text
Netflix
```

nhưng explicit recurring rule check lại dùng:

```text
netflix
```

Nếu set chưa normalize:

```python
"netflix" not in {"Netflix"}
```

→ `True`

và forecast add explicit recurring rule lần nữa.

---

# Impact

Forecast:

```text
Netflix expected = $20
```

có thể thành:

```text
Netflix historical = $20
+
Netflix rule = $20
=
$40
```

---

# Recommended fix

Tạo một canonical recurring key:

```python
def recurring_key(name):
    return normalize_merchant_name(
        name or ""
    ).strip().casefold()
```

Mọi place đều:

```python
seen.add(
    recurring_key(name)
)
```

và:

```python
if recurring_key(rule_name) not in seen:
```

---

# AUD-006B – Historical row được chọn không deterministic

Nếu recurring merchant có nhiều historical transactions:

```text
Netflix
Jan $18
Feb $19
Mar $20
```

query không explicit:

```sql
ORDER BY transaction_date DESC
```

nhưng code lấy một row làm expected amount/day.

SQL không guarantee row order nếu không `ORDER BY`.

---

# Recommended fix

Dùng latest record deterministic:

```sql
ROW_NUMBER() OVER (
    PARTITION BY normalized_merchant
    ORDER BY
        transaction_date DESC,
        transaction_time DESC,
        id DESC
) AS rn
```

sau đó:

```sql
WHERE rn = 1
```

Hoặc nếu mục tiêu là typical amount/day thì tốt hơn tính:

```text
median amount
median day
```

thay vì latest.

---

# Acceptance criteria

- [ ] Same recurring item không double-count do case.
- [ ] Historical recurring row selection deterministic.
- [ ] Forecast output stable giữa repeated runs.
- [ ] Explicit rule + detected history không cộng hai lần nếu cùng obligation.

---

# Tests

```text
test_forecast_does_not_double_count_recurring_case_variants
test_forecast_uses_deterministic_recurring_history
```

---

# AUD-007 – Demo data tạo transfer không đúng invariant

**Severity:** 🟠 High  
**Priority:** P1  
**Area:** Sample data / transfer integrity

---

## Current behaviour

Demo seeder tự insert transfer rows.

Các rows có thể có:

```text
transfer_group_id
```

nhưng thiếu:

```text
transfer_role = source/destination
linked_transaction_id
```

Trong khi production `TransferService` yêu cầu logical transfer pair hoàn chỉnh.

---

# Why this matters

Demo data đang tạo state mà production code xem là invalid.

Điều này gây:

```text
false test confidence
broken transfer reports
unexpected delete/update behaviour
future migration problems
```

Và đặc biệt nguy hiểm vì demo database thường được dùng để test UI.

---

# Recommended fix

Không raw-insert transfer.

Dùng:

```python
TransferService.create_transfer(...)
```

Nếu cần seed với custom connection:

```python
TransferService._insert_transfer_pair(
    conn,
    ...
)
```

và production create cũng sử dụng cùng low-level helper.

---

# Recommended invariant checker

Thêm utility:

```python
validate_all_transfer_groups()
```

check:

```text
exactly 2 active legs
one source
one destination
same amount
same date
different accounts
non-null group id
```

Seeder chạy xong:

```python
assert validate_all_transfer_groups()
```

---

# Acceptance criteria

- [ ] Demo transfers pass production validator.
- [ ] Không demo transfer nào có null role.
- [ ] Seeder không duplicate transfer logic riêng.
- [ ] Integrity query trả 0 invalid transfer groups.

---

# Tests

```text
test_sample_data_contains_no_orphan_transfers
test_sample_transfer_groups_pass_validator
```

---

# AUD-008 – Backup restore chưa rollback live database khi post-restore fail

**Severity:** 🟠 High  
**Priority:** P1  
**Area:** Backup / Restore

---

## Current behaviour

Restore flow có safety backup.

Tuy nhiên simplified flow:

```text
Create safety snapshot
↓
Validate incoming DB
↓
Copy incoming DB over live DB
↓
Run post-restore integrity check
```

Nếu failure xảy ra:

```text
after live DB has already been replaced
```

exception handler log lỗi và raise, nhưng không chắc tự copy safety snapshot trở lại live database.

---

# Risk

Log/message có thể nói:

```text
Original database preserved
```

nhưng thực tế live DB đã bị overwrite.

Nếu incoming DB pass pre-check nhưng fail post-check/migration/startup check thì user có thể bị mắc ở database không dùng được.

---

# Recommended restore architecture

```text
Extract backup
↓
Validate archive
↓
Validate metadata
↓
Validate format version
↓
Open TEMP database
↓
Run integrity_check
↓
Run migrations on TEMP database
↓
Validate domain invariants
↓
Create safety snapshot of LIVE
↓
Swap validated TEMP into LIVE
↓
Open LIVE and run final check
↓
Success
```

Nếu bất kỳ failure nào sau swap:

```text
restore safety snapshot automatically
```

---

# Metadata validation

Backup metadata nên có:

```json
{
  "format_version": 2,
  "app_version": "1.0.2",
  "schema_version": 5
}
```

Restore phải reject unsupported:

```text
format_version
schema too new
corrupt metadata
```

---

# Acceptance criteria

- [ ] Failure trước swap không modify live DB.
- [ ] Failure sau swap automatically restores safety DB.
- [ ] Unsupported backup format bị reject.
- [ ] Too-new schema version bị reject gracefully.
- [ ] Temporary files cleaned.
- [ ] Live DB integrity verified after successful restore.

---

# Tests

```text
test_restore_failure_before_swap_preserves_live_db
test_restore_failure_after_swap_rolls_back_live_db
test_restore_rejects_unsupported_format_version
test_restore_rejects_newer_schema_version
```

---

# AUD-009 – Category colour còn stored DOM injection path

**Severity:** 🟠 Medium  
**Priority:** P1  
**Area:** Frontend security / Category settings

---

## Current behaviour

Category colour là user-controlled string.

Frontend có thể nhận qua prompt/input:

```text
#FF0000
```

nhưng backend không bắt buộc format.

Sau đó Settings render màu trong:

```html
style="background: ${catColor}"
```

Nếu `catColor` chứa quote hoặc HTML-breaking content thì nó không còn chỉ là CSS value.

---

# Example malicious value

```text
red" onmouseover="alert(1)
```

Nếu interpolate trực tiếp:

```html
style="background:red" onmouseover="alert(1)"
```

thì user-controlled value đã tạo HTML attribute mới.

---

# Recommended fix

## Backend validation ⭐ Most important

Category colour chỉ cho:

```text
#RRGGBB
```

Regex:

```python
^#[0-9A-Fa-f]{6}$
```

Ví dụ:

```python
COLOR_RE = re.compile(
    r"^#[0-9A-Fa-f]{6}$"
)

if not COLOR_RE.fullmatch(color):
    raise ValueError(
        "Invalid category colour."
    )
```

Apply cho:

```text
create
update
import/restore normalization if necessary
```

---

## Frontend rendering

Không build style bằng HTML interpolation.

Prefer:

```javascript
element.style.backgroundColor = color;
element.style.color = color;
```

hoặc nếu chỉ display dot:

```javascript
dot.style.backgroundColor = color;
```

---

# Acceptance criteria

- [ ] Backend reject non-hex category colour.
- [ ] Quote-containing values không được persist.
- [ ] Category rendering không interpolate arbitrary CSS into `innerHTML`.
- [ ] Existing valid `#RRGGBB` values vẫn hoạt động.

---

# Tests

```text
test_category_rejects_invalid_colour
test_category_accepts_hex_colour
test_category_colour_cannot_break_html_attribute
```

---

# AUD-010 – Localhost API origin/token model còn rộng

**Severity:** 🟠 Medium  
**Priority:** P1  
**Area:** Local HTTP server / Session token

---

## Current behaviour

Origin validation chủ yếu kiểm tra hostname:

```text
127.0.0.1
localhost
```

nhưng không nhất thiết restrict đúng FinScope port.

Ví dụ:

```text
FinScope:
http://localhost:8080
```

Một unrelated local page:

```text
http://localhost:3000
```

vẫn cùng hostname:

```text
localhost
```

và có thể vượt qua hostname-only check.

---

# Why this matters

FinScope có session token dùng để authorize local API writes.

Nếu bootstrap/token endpoint accessible cho bất kỳ localhost origin nào, một app local khác có khả năng acquire token rồi gọi API.

Threat model này là:

```text
local malicious web app/service
```

không phải remote internet attacker.

Nhưng vẫn nên tighten.

---

# Recommended fix

Allowed origins phải là exact:

```text
http://127.0.0.1:<actual-port>
http://localhost:<actual-port>
```

Compare:

```text
scheme
hostname
port
```

không chỉ hostname.

---

# Bootstrap

Nếu index HTML đã được server inject token trực tiếp thì evaluate việc bỏ:

```text
GET /api/bootstrap → token
```

hoặc bootstrap chỉ trả token khi request đúng exact origin.

---

# Route capabilities

Nếu route metadata có:

```text
READ
WRITE
DESTRUCTIVE
PRIVILEGED_DESKTOP
```

thì phải:

```text
actually enforce it
```

Nếu không, remove để tránh false sense of security.

Example:

```python
authorize(
    request,
    route.capability
)
```

---

# Acceptance criteria

- [ ] Wrong localhost port origin bị reject.
- [ ] Correct FinScope origin vẫn hoạt động.
- [ ] State-changing API requires valid token.
- [ ] Bootstrap token không leak cho arbitrary localhost origin.
- [ ] Capability metadata được enforce hoặc removed.

---

# Tests

```text
test_same_host_wrong_port_origin_rejected
test_correct_origin_allowed
test_write_route_requires_token
test_bootstrap_not_available_to_untrusted_local_origin
```

---

# AUD-011 – Backend validation chưa đủ chặt

**Severity:** 🟠 Medium  
**Priority:** P1  
**Area:** Repository / API / Domain validation

---

## Current risk

Một số validation hiện chủ yếu ở frontend.

Ví dụ frontend có thể reject:

```text
amount <= 0
```

nhưng backend generic transaction create có thể chỉ convert:

```python
amount_minor = int(
    round(float(amount) * 100)
)
```

rồi insert.

API caller có thể bypass frontend.

---

# Examples

Potential invalid data:

```text
expense amount = -100
expense amount = 0
date = "abc"
category type mismatch
budget amount = -500
recurring amount = 0
recurring amount = -10
invalid frequency
invalid currency
```

---

# Recommended solution

Tạo centralized domain validators.

Example:

```text
app/backend/domain/validators.py
```

Functions:

```python
validate_positive_amount(...)
validate_iso_date(...)
validate_transaction_type(...)
validate_currency_code(...)
validate_hex_colour(...)
validate_recurring_frequency(...)
validate_budget_amount(...)
```

---

# Transaction rules

For:

```text
expense
income
refund
transfer
```

amount phải:

```text
> 0
```

Nếu `adjustment` hỗ trợ signed value thì define riêng.

---

# Date

Normalize:

```text
YYYY-MM-DD
```

Backend phải parse/reject invalid.

Không chỉ trust frontend calendar input.

---

# Budget

Require:

```text
budget_amount_minor > 0
```

---

# Recurring update

Validation phải apply cả:

```text
create
update
```

không chỉ create.

---

# Acceptance criteria

- [ ] Backend reject zero expense.
- [ ] Backend reject negative expense.
- [ ] Backend reject malformed dates.
- [ ] Budget cannot be negative/zero.
- [ ] Recurring create/update share same validation.
- [ ] Frontend validation remains UX layer only.

---

# Tests

```text
test_backend_rejects_zero_transaction_amount
test_backend_rejects_negative_transaction_amount
test_backend_rejects_invalid_date
test_budget_rejects_non_positive_amount
test_recurring_update_rejects_invalid_amount
```

---

# AUD-012 – `schema.sql` và migrations đang drift

**Severity:** 🟠 Medium  
**Priority:** P1/P2  
**Area:** Database schema / migrations

---

## Current behaviour

`schema.sql` có thể mô tả constraints như:

```sql
CHECK (
    transfer_role IN (
        'source',
        'destination'
    )
)
```

nhưng migration tạo/upgrades actual database lại add column mà không có same CHECK.

Kết quả:

```text
schema.sql says invariant protected
production DB actually does not enforce it
```

---

# Why this matters

Developer có thể:

```text
read schema.sql
assume DB guarantees constraint
remove application validation
```

sau đó production DB vẫn cho invalid state.

---

# Recommended strategy

## Make migrations authoritative

Rule:

```text
migrations = source of truth
```

`schema.sql` chỉ:

```text
generated documentation
```

hoặc generated latest bootstrap schema.

---

# Existing database migration

Nếu muốn thêm CHECK constraint vào SQLite existing table:

```text
ALTER COLUMN
```

không đủ.

Cần:

```text
CREATE new table with constraints
COPY data
DROP old table
RENAME new table
```

trong migration.

---

# Schema consistency test

Trong CI:

```text
Create DB from scratch using migrations
↓
Inspect sqlite_master / PRAGMA
↓
Compare expected columns/indexes/constraints
```

---

# Acceptance criteria

- [ ] Fresh DB generated entirely by migrations has expected schema.
- [ ] `schema.sql` không contradict migrations.
- [ ] Developer documentation nói rõ authoritative source.
- [ ] Critical indexes/constraints verified by tests.

---

# Tests

```text
test_fresh_migrated_schema_matches_expected_contract
test_transfer_role_schema_constraint
test_source_schema_constraint
```

---

# AUD-013 – Recent Payee suggestion không deterministic

**Severity:** 🟡 Medium  
**Priority:** P2  
**Area:** Merchant suggestions

---

## Current behaviour

Query conceptually:

```sql
SELECT
    merchant_name,
    category_id,
    account_id,
    amount_minor,
    MAX(transaction_date)
FROM active_transactions
GROUP BY merchant_name
```

Các fields:

```text
category_id
account_id
amount_minor
```

không aggregate.

SQL không guarantee chúng thuộc row có:

```text
MAX(transaction_date)
```

---

# Example

Transactions:

```text
Jan:
Starbucks
Account A
Category Dining
$5

Sep:
Starbucks
Account B
Category Coffee
$7
```

Recent suggestion có thể trả:

```text
merchant = Starbucks
latest date = September

but:
account = Account A
category = Dining
amount = $5
```

metadata từ old row.

---

# Recommended fix

Use window function:

```sql
WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY merchant_name
            ORDER BY
                transaction_date DESC,
                transaction_time DESC,
                id DESC
        ) AS rn
    FROM active_transactions
)
SELECT *
FROM ranked
WHERE rn = 1;
```

Count/frequency nếu cần thì window separately:

```sql
COUNT(*) OVER (
    PARTITION BY merchant_name
)
```

---

# Acceptance criteria

- [ ] Recent merchant metadata comes from latest transaction.
- [ ] Ties resolved deterministically by time/id.
- [ ] Deleted transaction cannot become recent merchant.

---

# Tests

```text
test_recent_payee_uses_latest_transaction_metadata
test_recent_payee_tie_break_is_deterministic
```

---

# AUD-014 – Async frontend render stale race

**Severity:** 🟡 Medium  
**Priority:** P2  
**Area:** Router / Async pages

---

## Current behaviour

Page render có thể:

```text
start API request
await response
write into shared page container
```

User chuyển route trước khi request cũ resolve.

---

# Example

```text
Open Analytics
↓
analytics API request starts

Immediately open Transactions
↓
Transactions renders

Old analytics request finishes
↓
Analytics writes into same container
```

Potential result:

```text
URL says /transactions
but content shows Analytics
```

---

# Recommended fix

## Generation token

Router:

```javascript
this.renderGeneration += 1;
const generation = this.renderGeneration;

await route.render(container);

if (
    generation !==
    this.renderGeneration
) {
    return;
}
```

Tuy nhiên page itself phải tránh DOM write trước generation check.

Better:

```text
fetch data
↓
verify generation
↓
render
```

---

## AbortController

Best:

```javascript
currentController?.abort();

currentController =
    new AbortController();
```

Pass:

```javascript
signal
```

vào fetch.

Route change:

```text
abort previous requests
```

---

# Acceptance criteria

- [ ] Rapid navigation không cho old page overwrite current page.
- [ ] Aborted requests không show error toast.
- [ ] Current URL luôn match rendered page.

---

# Tests

```text
test_stale_page_render_does_not_overwrite_current_route
test_aborted_navigation_request_is_silent
```

---

# AUD-015 – Test/dev dependency management

**Severity:** 🟡 Low  
**Priority:** P2  
**Area:** Tooling / CI

---

## Current behaviour

Tests use:

```python
pytest
```

nhưng runtime requirements có thể không declare it.

Developer mới:

```text
pip install -r requirements.txt
pytest
```

có thể gặp:

```text
ModuleNotFoundError: pytest
```

---

# Recommended fix

Create:

```text
requirements.txt
```

runtime only:

```text
pywebview
typing_extensions
...
```

and:

```text
requirements-dev.txt
```

```text
-r requirements.txt
pytest>=8
```

Nếu Bottle không còn dùng:

```text
remove bottle
```

sau khi grep toàn repo xác nhận không import.

---

# Better long-term option

Use:

```text
pyproject.toml
```

with:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8"
]
```

Developer install:

```text
pip install -e .[dev]
```

---

# Acceptance criteria

- [ ] Fresh development environment có thể install và run tests từ documented commands.
- [ ] Runtime dependency list không chứa unused packages.
- [ ] Test dependencies không lẫn vào production nếu không cần.

---

# Recommended Implementation Order

## Phase 1 – Financial correctness blockers

```text
AUD-002
Soft-delete analytics
```

↓

```text
AUD-001
Single-currency invariant
```

↓

```text
AUD-003
Atomic refund handling
```

↓

```text
AUD-007
Sample transfer integrity
```

---

## Phase 2 – Import and recurring correctness

```text
AUD-004
CSV import
```

↓

```text
AUD-005
Recurring matching
```

↓

```text
AUD-006
Forecast recurring
```

---

## Phase 3 – Recovery and security

```text
AUD-008
Backup restore rollback
```

↓

```text
AUD-009
Category colour injection
```

↓

```text
AUD-010
Localhost API hardening
```

↓

```text
AUD-011
Central backend validation
```

---

## Phase 4 – Maintainability

```text
AUD-012
Schema/migration consistency
```

↓

```text
AUD-013
Recent Payee deterministic query
```

↓

```text
AUD-014
Async route race
```

↓

```text
AUD-015
Dev/test dependencies
```

---

# Suggested Commit Structure

Không nên fix toàn bộ audit trong một commit.

Suggested:

```text
fix(analytics): exclude soft-deleted transactions from all analytics

fix(currency): enforce single base currency across accounts

fix(refunds): make refund validation and insert atomic

fix(sample-data): create demo transfers through transfer invariant path

fix(import): align CSV preview and commit deduplication

fix(import): add explicit date format handling

fix(import): improve duplicate fingerprint strategy

fix(recurring): constrain paid matching by account and type

fix(forecast): normalize recurring keys and deterministic history selection

fix(backup): rollback live database on failed restore

fix(security): validate category colours and remove unsafe style interpolation

fix(server): restrict API origins to FinScope host and port

fix(validation): centralize backend domain validation

refactor(db): make migrations authoritative schema source

fix(merchant): make recent payee metadata deterministic

fix(router): cancel stale async page renders

chore(test): separate development dependencies
```

---

# Definition of Done for Each Audit Issue

Một issue không nên được close chỉ vì manual UI test pass.

Minimum:

```text
[ ] Root cause fixed
[ ] Backend/domain invariant enforced
[ ] Frontend behaviour updated if relevant
[ ] Bypass path considered
[ ] Regression test added
[ ] Error path tested
[ ] Existing tests still pass
[ ] No new inconsistent data state introduced
```

---

# Final v1.0.3 Integrity Checklist

## Transactions

```text
[ ] Transfer pairs always valid
[ ] Refund totals never exceed original expense
[ ] Deleted transactions excluded from all active analytics
[ ] Amount/date validation exists backend-side
```

## Currency

```text
[ ] All accounts use one base currency
[ ] No mixed-currency aggregation
```

## CSV

```text
[ ] Preview matches commit
[ ] Invalid/ambiguous dates are not guessed silently
[ ] Duplicate detection does not skip legitimate repeated purchases
```

## Recurring / Forecast

```text
[ ] Recurring paid matching requires correct account
[ ] Recurring paid matching requires correct transaction type
[ ] Same recurring obligation is not forecast twice
[ ] Historical recurring selection deterministic
```

## Backup

```text
[ ] Backup source validated
[ ] Format/schema compatibility checked
[ ] Restore failure after live overwrite rolls back automatically
```

## Security

```text
[ ] All user-controlled HTML/CSS values validated or safely rendered
[ ] Category colours restricted to safe format
[ ] Local API accepts only expected origin/port
[ ] State-changing routes require valid session token
```

## Database

```text
[ ] Migrations are authoritative
[ ] Fresh migration produces expected schema
[ ] Demo data satisfies production invariants
```

## Frontend

```text
[ ] Rapid navigation cannot render stale page
[ ] Async request cancellation does not show misleading errors
```

## Tests

```text
[ ] Fresh dev install can run pytest
[ ] Regression tests cover each P0/P1 issue
[ ] Financial invariant tests run automatically
```