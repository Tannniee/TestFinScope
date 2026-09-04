# FinScope – Bug Fix & Hardening Tracker

> Scope: các lỗi/rủi ro liên quan đến transaction integrity, CSV import, backup error handling và frontend HTML rendering.

## Priority overview

| ID | Issue | Severity | Risk type | Suggested priority |
|---|---|---:|---|---:|
| BUG-001 | Duplicate transfer tạo transfer mồ côi | 🔴 High | Financial data integrity | P0 |
| BUG-002 | Generic update bypass transfer/refund invariants | 🔴 High | Financial data integrity | P0 |
| BUG-003 | CSV import parse sai amount/date và false duplicate | 🔴 High | Incorrect financial records | P0 |
| BUG-004 | Backup restore error handler dùng `logger` chưa khai báo | 🟠 Medium | Reliability / error masking | P1 |
| BUG-005 | Account/category data được insert vào `innerHTML` chưa escape | 🟠 Medium | Stored DOM/XSS risk | P1 |

---

# BUG-001 – Duplicate transfer có thể tạo orphan transfer

**Severity:** 🔴 High  
**Area:** Transaction integrity / Transfers  
**Main files:**

```text
app/backend/repositories/transaction_repo.py
app/backend/services/transfer_service.py
app/frontend/assets/js/pages/transactions.js
```

## 1. Current behaviour

Một transfer hợp lệ trong FinScope được thiết kế theo kiểu double-entry:

```text
Transfer $500 từ Account A → Account B

Transaction #101
type = transfer
account = A
role = source
transfer_group_id = abc
amount = 500

Transaction #102
type = transfer
account = B
role = destination
transfer_group_id = abc
amount = 500
```

Hai transaction này cùng thuộc một `transfer_group_id`.

Tuy nhiên `TransactionRepository.duplicate()` hiện:

1. Load transaction gốc.
2. Clone object.
3. Remove:
   - `transfer_group_id`
   - `transfer_role`
   - `linked_transaction_id`
4. **Không remove/change `transaction_type`.**
5. Gọi generic `TransactionRepository.create(clone)`.

Do đó nếu transaction gốc có:

```python
transaction_type = "transfer"
```

transaction mới vẫn là:

```python
transaction_type = "transfer"
```

nhưng không còn transfer metadata. `create()` hiện cũng không bắt buộc transaction loại `transfer` phải có `transfer_group_id` hoặc `transfer_role`.

Kết quả có thể trở thành:

```text
Transaction #103
type = transfer
account = A
transfer_group_id = NULL
transfer_role = NULL
linked_transaction_id = NULL
```

Đây là một **orphan transfer**.

Frontend hiện cũng render nút `Duplicate` cho mọi transaction, bao gồm transfer, nên user có đường UI trực tiếp để trigger hành vi này.

---

## 2. Why this is dangerous

FinScope đang dựa vào invariant:

```text
1 logical transfer
=
2 linked transaction legs
```

Orphan transfer phá invariant này.

Ví dụ balance:

```text
Before:

Checking       2,000
Savings        1,000
Total          3,000

Transfer 500 Checking → Savings:

Checking       1,500
Savings        1,500
Total          3,000
```

Nếu duplicate riêng source leg:

```text
Checking       1,000
Savings        1,500
Total          2,500   ❌
```

Tuỳ cách analytics xử lý transfer, nó có thể gây:

- account balance sai;
- cash flow sai;
- transfer reporting sai;
- analytics hiểu transfer như một transaction độc lập;
- delete/undo không operate theo transfer group;
- future migration/data validation gặp corrupted logical state.

---

## 3. Reproduction

### Steps

1. Tạo hai accounts:
   - Everyday
   - Savings
2. Tạo transfer:
   - Everyday → Savings
   - Amount: `$500`
3. Mở Transactions page.
4. Click **Duplicate** trên một leg của transfer.
5. Inspect transaction mới trong database.

### Check

```sql
SELECT
    id,
    account_id,
    transaction_type,
    amount_minor,
    transfer_group_id,
    transfer_role,
    linked_transaction_id
FROM transactions
WHERE transaction_type = 'transfer';
```

### Current problematic state

```text
transaction_type = transfer
transfer_group_id = NULL
transfer_role = NULL
```

---

## 4. Expected behaviour

Một transaction có:

```python
transaction_type == "transfer"
```

không bao giờ được tồn tại độc lập.

Transfer phải luôn được tạo/thay đổi thông qua `TransferService`.

Invariant mong muốn:

```text
transfer
→ exactly one source leg
→ exactly one destination leg
→ same transfer_group_id
→ matching amount
→ matching date/time
→ different accounts
```

---

# 5. Recommended fix

## Option A – Minimal safe fix ⭐ Recommended first

Không cho phép generic duplicate đối với transfer.

### Backend

Trong:

```python
TransactionRepository.duplicate()
```

thêm guard:

```python
original = TransactionRepository.get_by_id(tx_id)

if not original:
    return None

if original["transaction_type"] == "transfer":
    raise ValueError(
        "Transfer transactions cannot be duplicated individually."
    )
```

### Frontend

Không render nút Duplicate cho transfer:

```javascript
const canDuplicate = tx.transaction_type !== 'transfer';
```

sau đó:

```javascript
${canDuplicate ? `
  <button
    class="btn btn-secondary btn-icon btn-sm action-duplicate"
    data-id="${tx.id}"
    title="Duplicate"
  >
    ...
  </button>
` : ''}
```

### Why both?

Không nên chỉ hide button frontend.

Frontend chỉ là UX protection.

Backend mới là data-integrity boundary.

Một API call trực tiếp vẫn có thể bypass UI.

---

## Option B – Support "Duplicate Transfer"

Nếu muốn UX cho phép duplicate transfer thì **duplicate logical transfer**, không duplicate một transaction row.

Ví dụ:

```python
TransferService.duplicate_transfer(group_id)
```

Flow:

```text
Get selected transfer leg
        ↓
Find transfer_group_id
        ↓
Load source + destination
        ↓
Validate existing group
        ↓
TransferService.create_transfer(
    from_account_id=source.account_id,
    to_account_id=destination.account_id,
    amount=source.amount,
    transaction_date=...
)
        ↓
Create NEW pair with NEW group ID
```

Kết quả:

```text
Original

source      group=ABC
destination group=ABC

Duplicate

source      group=XYZ
destination group=XYZ
```

---

# 6. Additional backend protection

Nên thêm invariant protection trong creation layer.

Ví dụ generic `TransactionRepository.create()` không nên được dùng để tạo transfer:

```python
if data.get("transaction_type") == "transfer":
    raise ValueError(
        "Transfers must be created through TransferService."
    )
```

Tuy nhiên trước khi làm điều này cần kiểm tra `TransferService` hiện có sử dụng `TransactionRepository.create()` bên trong hay không.

Nếu có, nên tạo low-level private method:

```python
_insert_transaction(...)
```

và phân biệt:

```text
Public API

create()
create_refund()
create_transfer()

        ↓

Private persistence API

_insert_transaction()
```

---

# 7. Acceptance criteria

- [ ] Duplicate một expense vẫn hoạt động.
- [ ] Duplicate một income vẫn hoạt động.
- [ ] Transfer không còn nút generic Duplicate hoặc duplicate thành cả pair.
- [ ] API không thể tạo orphan transfer.
- [ ] Không tồn tại active transfer với `transfer_group_id IS NULL`.
- [ ] Mỗi transfer group có đúng 2 active legs.
- [ ] Mỗi group có đúng một `source` và một `destination`.
- [ ] Amount của hai legs giống nhau.
- [ ] Source account khác destination account.

### Integrity query

```sql
SELECT *
FROM active_transactions
WHERE transaction_type = 'transfer'
  AND (
      transfer_group_id IS NULL
      OR transfer_role IS NULL
  );
```

Expected:

```text
0 rows
```

---

# 8. Tests to add

### Test 1

```text
test_duplicate_normal_expense_succeeds
```

### Test 2

```text
test_duplicate_transfer_does_not_create_orphan_leg
```

### Test 3

```text
test_every_transfer_group_has_exactly_two_legs
```

### Test 4

```text
test_transfer_group_contains_source_and_destination
```

---

# BUG-002 – Generic transaction update có thể bypass transfer/refund invariants

**Severity:** 🔴 High  
**Area:** Transaction update / domain invariants  
**Main files:**

```text
app/backend/repositories/transaction_repo.py
app/backend/services/transfer_service.py
app/frontend/assets/js/components/modals.js
```

---

## 1. Current behaviour

Project đã có specialised update logic:

```python
update_transfer(...)
update_refund(...)
```

Điều này đúng vì transfer/refund có business rules riêng.

Tuy nhiên generic:

```python
TransactionRepository.update(tx_id, data)
```

hiện cho phép update các fields bao gồm:

```python
account_id
category_id
transaction_type
transaction_date
transaction_time
...
amount / amount_minor
```

mà không kiểm tra transaction hiện tại thuộc loại gì.

Frontend hiện cố gọi:

```javascript
api.updateTransfer(...)
```

nếu type trong form là `transfer`, và:

```javascript
api.updateRefund(...)
```

nếu type là `refund`.

Nhưng đây vẫn chưa đủ an toàn vì backend invariant đang phụ thuộc vào frontend chọn đúng API.

---

# 2. Example failure – Transfer

Giả sử:

```text
#101
type = transfer
role = source
amount = 500

#102
type = transfer
role = destination
amount = 500
```

Nếu generic update được gọi:

```python
TransactionRepository.update(
    101,
    {"amount": 1000}
)
```

có khả năng thành:

```text
source      1000
destination 500
```

Transfer pair không còn cân bằng.

Tương tự:

```python
{"account_id": 7}
```

có thể thay đổi một leg mà không thay đổi leg còn lại.

---

# 3. Example failure – Refund

Refund có invariant:

```text
sum(all active refunds)
<=
original expense amount
```

`update_refund()` hiện có logic kiểm tra remaining refundable amount trước khi update.

Nhưng nếu code khác gọi generic:

```python
TransactionRepository.update(
    refund_id,
    {"amount": 999999}
)
```

thì validation ở `update_refund()` có thể bị bypass.

---

# 4. Example failure – Type mutation

Generic update còn cho sửa:

```python
transaction_type
```

Do đó theoretically có thể xảy ra:

```text
transfer → expense
refund   → income
expense  → transfer
```

mà không tạo/remove metadata tương ứng.

Ví dụ:

```text
Before:

type = transfer
transfer_group_id = ABC
transfer_role = source

After generic update:

type = expense
transfer_group_id = ABC
transfer_role = source
```

Đây là inconsistent domain state.

---

# 5. Frontend weakness

Khi mở transaction modal để edit, frontend set:

```javascript
document.getElementById('tx-type').value = type;
```

và segmented transaction-type controls vẫn tồn tại trong edit modal. Không có domain-level guarantee rằng transaction type không bị thay đổi trong quá trình edit.

Ngay cả khi frontend được sửa, backend vẫn phải enforce invariant.

---

# 6. Recommended architecture

Không nên dùng một generic method để update mọi transaction type.

Nên tách:

```text
update_standard_transaction()
update_transfer()
update_refund()
```

Và có một private low-level persistence function:

```text
_update_fields()
```

Ví dụ:

```python
def update(tx_id, data):
    existing = TransactionRepository.get_by_id(tx_id)

    if not existing:
        return False

    if existing["transaction_type"] == "transfer":
        raise ValueError(
            "Transfers must be updated through TransferService."
        )

    if existing["transaction_type"] == "refund":
        raise ValueError(
            "Refunds must be updated through update_refund()."
        )

    if data.get("transaction_type") in ("transfer", "refund"):
        raise ValueError(
            "Cannot convert a standard transaction into a specialised transaction."
        )

    return TransactionRepository._update_fields(tx_id, data)
```

Sau đó:

```python
def update_refund(...):
    # validation
    ...
    return TransactionRepository._update_fields(
        tx_id,
        validated_data
    )
```

Quan trọng: không gọi lại public generic `update()` từ `update_refund()` nếu generic method đã được guard.

---

# 7. Transfer update

Transfer update phải atomic.

Correct flow:

```text
BEGIN

Validate:
- source exists
- destination exists
- same group
- different accounts
- amount > 0

UPDATE source leg
UPDATE destination leg

COMMIT
```

Nếu bất kỳ update nào fail:

```text
ROLLBACK
```

Không bao giờ:

```text
Update source
commit

Update destination
commit
```

---

# 8. Transaction type policy

Nên xác định policy rõ ràng.

### Safe recommendation

Cho phép:

```text
expense ↔ income
```

nếu business requirements cần.

Không cho generic conversion:

```text
expense → transfer
expense → refund

transfer → expense
transfer → income
transfer → refund

refund → expense
refund → income
refund → transfer
```

Transfer/refund nên được xem là specialised domain entities.

---

# 9. Frontend proposal

Khi edit:

```text
transfer
refund
```

disable transaction type selector.

Ví dụ:

```javascript
const isSpecial =
  txData?.transaction_type === 'transfer' ||
  txData?.transaction_type === 'refund';
```

Nếu special:

```text
Type selector disabled
```

User muốn thay đổi bản chất transaction thì:

```text
delete existing
+
create new transaction
```

thay vì mutate type.

---

# 10. Acceptance criteria

- [ ] Generic update không thể update transfer.
- [ ] Generic update không thể update refund.
- [ ] Transfer update luôn update cả pair.
- [ ] Refund update luôn kiểm tra cumulative refund limit.
- [ ] Generic update không thể chuyển transaction thành transfer/refund.
- [ ] Transfer/refund không thể đổi sang normal transaction bằng generic API.
- [ ] Frontend không cho type switching khi edit specialised transaction.
- [ ] Failure giữa transfer update rollback toàn bộ operation.

---

# 11. Tests to add

```text
test_generic_update_rejects_transfer
test_generic_update_rejects_refund

test_generic_update_cannot_convert_expense_to_transfer
test_generic_update_cannot_convert_expense_to_refund

test_transfer_update_changes_both_legs
test_transfer_update_is_atomic

test_refund_update_cannot_exceed_original_amount
```

---

# BUG-003 – CSV import có thể tạo incorrect financial records

**Severity:** 🔴 High  
**Area:** CSV import / financial data normalization  
**Main file:**

```text
app/backend/services/import_service.py
```

Có ba vấn đề chính cần xử lý riêng:

```text
BUG-003A Amount parsing
BUG-003B Invalid date handling
BUG-003C Duplicate detection
```

---

# BUG-003A – `50.000 VND` có thể bị parse thành `50`

## Current behaviour

Docstring của `parse_amount()` ghi rằng function hỗ trợ:

```text
50.000 VND
```

Nhưng code hiện chỉ xử lý dấu `.` như thousands separator khi string đồng thời có `,`.

Nếu input:

```text
50.000 VND
```

sau khi strip currency:

```text
50.000
```

sau đó:

```python
float("50.000")
```

kết quả:

```text
50.0
```

thay vì:

```text
50000
```



---

## Impact

Input:

```text
50.000 VND
```

Expected:

```text
50,000
```

Current interpretation:

```text
50
```

Financial value sai **1000 lần**.

Đây là data corruption chứ không chỉ formatting issue.

---

# Recommended fix

Không nên parse currency bằng một chuỗi heuristic + `float()` duy nhất.

Nên:

1. normalize currency;
2. detect separators;
3. parse bằng `Decimal`;
4. reject ambiguous values nếu không chắc.

Ví dụ:

```python
from decimal import Decimal, InvalidOperation
```

### Suggested rules

#### Case 1

```text
1,250.50
```

Interpret:

```text
, = thousands
. = decimal
```

Result:

```text
1250.50
```

#### Case 2

```text
1.250,50
```

Interpret:

```text
. = thousands
, = decimal
```

Result:

```text
1250.50
```

#### Case 3

```text
50.000 VND
```

Interpret:

```text
. = thousands
```

Result:

```text
50000
```

#### Case 4

```text
12,50 EUR
```

Interpret:

```text
, = decimal
```

Result:

```text
12.50
```

---

## Important

Một value như:

```text
1.234
```

có thể nghĩa là:

```text
one point two three four
```

hoặc:

```text
one thousand two hundred thirty-four
```

Không nên guess mù.

Import UI tốt hơn nên có:

```text
Number format:

○ 1,234.56
○ 1.234,56
○ 1.234
○ Auto detect
```

và preview normalized value trước khi commit.

---

## Parsing failure

Hiện parse failure có thể cuối cùng thành:

```python
val = 0.0
```

Nên thay bằng explicit error.

Ví dụ:

```python
raise ValueError(
    f"Unable to parse amount: {amount_str}"
)
```

hoặc return structured result:

```python
{
    "value": None,
    "error": "Invalid amount format"
}
```

Không nên silently convert malformed financial value thành zero.

---

# BUG-003B – Invalid date đang bị đổi thành ngày hiện tại

## Current behaviour

Preview hiện dùng:

```python
parsed_date = cls.parse_date(raw_date) or datetime.now().strftime(...)
```

Commit cũng làm tương tự.

Ví dụ CSV:

```text
Date,Merchant,Amount
31-ABC-2025,Woolworths,-50
```

`parse_date()` fail.

Thay vì row bị reject:

```text
Invalid date
```

nó có thể trở thành ngày import hiện tại.

Ví dụ user import ngày:

```text
2026-09-04
```

thì transaction được lưu:

```text
2026-09-04
```

---

## Impact

Đây là lỗi đặc biệt nguy hiểm vì transaction:

- vẫn nhìn hợp lệ;
- không báo lỗi;
- có amount đúng;
- merchant đúng;
- nhưng nằm sai date.

Nó có thể làm sai:

```text
monthly spending
budget calculations
cash flow
forecasting
"What Changed?"
recurring pattern detection
historical analysis
```

---

# Recommended behaviour

Invalid date phải được coi là validation error.

Ví dụ preview:

```json
{
  "row_index": 12,
  "raw_date": "31-ABC-2025",
  "date": null,
  "is_valid": false,
  "errors": [
    "Unable to parse transaction date"
  ]
}
```

UI:

```text
Row 12
Date: 31-ABC-2025
⚠ Invalid date
```

---

## Commit rule

Nếu row invalid:

### Option A – safest

Không import row đó.

```text
Imported: 95
Invalid: 3
Duplicates: 2
```

### Option B

Block toàn bộ import đến khi user xử lý invalid rows.

Đối với finance app, Option B an toàn nhất nếu mục tiêu là strict correctness.

---

# BUG-003C – Duplicate detection quá yếu

## Current behaviour

Hiện duplicate identity chỉ dùng:

```python
(transaction_date, amount_minor)
```



Ví dụ account có:

```text
2026-09-01 | Woolworths | $25
```

Sau đó import CSV có:

```text
2026-09-01 | Chemist Warehouse | $25
```

Code chỉ nhìn:

```text
date   = same
amount = same
```

và có thể coi transaction Chemist là duplicate.

---

## Impact

Một transaction thật có thể bị silently skipped.

Đặc biệt dễ xảy ra với:

```text
coffee
public transport
subscriptions
small purchases
same-value transfers
round-number expenses
```

---

# Recommended duplicate hierarchy

## Best case – Bank transaction ID

Nếu CSV có:

```text
transaction_id
reference_id
bank_reference
```

dùng nó làm primary dedup identity.

Ví dụ:

```text
account_id + external_transaction_id
```

---

## Fallback

Nếu không có bank ID, dùng stronger fingerprint:

```text
account_id
+
transaction_date
+
amount_minor
+
transaction_type
+
normalized_merchant
+
normalized_description
```

Ví dụ:

```python
fingerprint = (
    account_id,
    parsed_date,
    amount_minor,
    tx_type,
    normalize(payee),
    normalize(description)
)
```

---

## Even safer

Không gọi fingerprint match là:

```text
definite duplicate
```

mà gọi:

```text
possible duplicate
```

và cho user review trước commit.

Ví dụ UI:

```text
⚠ Possible duplicate

Existing:
01/09 | Woolworths | $25

Imported:
01/09 | Woolworths | $25
```

Buttons:

```text
Skip
Import anyway
Skip all exact matches
```

---

# BUG-003 overall refactor recommendation

Hiện preview và commit có khá nhiều parsing logic bị duplicate.

Nên tạo:

```python
_parse_csv_row(...)
```

Flow:

```text
CSV raw row
   ↓
_parse_csv_row()
   ↓
NormalizedTransaction
   ↓
validation
   ↓
duplicate detection
   ↓
preview
```

Commit sử dụng **cùng normalized result**, thay vì parse lại bằng một logic song song.

Target:

```text
Preview result
=
what commit will actually import
```

---

# CSV import acceptance criteria

### Amount

- [ ] `50.000 VND` → `50000`.
- [ ] `1.250,50 EUR` → `1250.50`.
- [ ] `1,250.50` → `1250.50`.
- [ ] `(123.45)` → expense `123.45`.
- [ ] Invalid amount không silently trở thành `0`.
- [ ] Ambiguous format có warning hoặc deterministic locale configuration.

### Date

- [ ] Invalid date không fallback sang today.
- [ ] Invalid date xuất hiện trong preview.
- [ ] Invalid row không được silently commit.
- [ ] Preview và commit dùng cùng normalization logic.

### Deduplication

- [ ] Hai merchant khác nhau cùng ngày/cùng amount không bị auto-skip.
- [ ] Exact existing transaction được detect.
- [ ] Dedup scope bao gồm `account_id`.
- [ ] Bank transaction/reference ID được ưu tiên nếu có.
- [ ] Possible duplicate có thể review/import manually.

---

# CSV tests to add

```text
test_parse_vnd_thousands_dot
test_parse_european_currency
test_parse_us_currency
test_invalid_amount_returns_validation_error

test_invalid_date_is_not_today
test_invalid_date_is_rejected_from_commit

test_same_date_same_amount_different_merchant_not_duplicate
test_exact_fingerprint_detected_as_duplicate
test_duplicate_detection_is_account_scoped

test_preview_and_commit_normalize_rows_identically
```

---

# BUG-004 – Backup restore exception handler sử dụng undefined `logger`

**Severity:** 🟠 Medium  
**Area:** Backup / restore / exception handling  
**Main file:**

```text
app/backend/services/backup_service.py
```

---

# 1. Current behaviour

`backup_service.py` hiện import:

```python
os
json
zipfile
csv
sqlite3
...
```

nhưng không thấy:

```python
import logging

logger = logging.getLogger(__name__)
```

Trong restore error handler lại có:

```python
except Exception as e:
    logger.error(...)
    raise
```



---

# 2. Failure mode

Giả sử restore thật sự fail vì:

```text
ValueError: Backup integrity check failed
```

Execution vào:

```python
except Exception as e:
```

sau đó:

```python
logger.error(...)
```

Nhưng `logger` chưa tồn tại.

Python có thể ném:

```text
NameError: name 'logger' is not defined
```

Kết quả user/developer nhìn thấy:

```text
NameError
```

thay vì root cause thật:

```text
Backup integrity check failed
```

---

# 3. Why this matters

Backup/restore là safety-critical path.

Khi restore fail, điều quan trọng nhất là:

```text
preserve original DB
+
preserve original exception
+
provide useful diagnostic information
```

Error handler không được tạo thêm một exception mới.

---

# 4. Minimal fix

Ở đầu file:

```python
import logging

logger = logging.getLogger(__name__)
```

---

# 5. Better logging

Nên dùng:

```python
logger.exception(
    "Restore failed. Preserving original database."
)
```

thay vì:

```python
logger.error(...)
```

Vì `logger.exception()` khi chạy trong `except` sẽ tự include traceback.

Ví dụ:

```python
except Exception:
    logger.exception(
        "Restore failed. Preserving original database."
    )
    raise
```

Điều này cũng preserve original exception.

---

# 6. Tests need improvement

Test không nên chỉ:

```python
with pytest.raises(Exception):
```

hoặc:

```python
with self.assertRaises(Exception):
```

vì `NameError` cũng thoả điều kiện đó.

Nên assert exact exception.

Ví dụ:

```python
with pytest.raises(ValueError, match="integrity"):
    BackupService.restore_backup(...)
```

Sau đó verify original database vẫn tồn tại và data không đổi.

---

# 7. Acceptance criteria

- [ ] Restore failure không tạo `NameError`.
- [ ] Original exception type được preserved.
- [ ] Error traceback được logged.
- [ ] Existing live DB vẫn intact khi restore validation fail.
- [ ] Temporary restore file được cleanup.
- [ ] Safety backup behaviour vẫn hoạt động.

---

# 8. Tests to add

```text
test_restore_invalid_backup_preserves_original_exception
test_restore_invalid_backup_preserves_live_database
test_restore_failure_cleans_temp_files
```

---

# BUG-005 – Unescaped account/category values trong `innerHTML`

**Severity:** 🟠 Medium  
**Area:** Frontend security / DOM rendering  
**Main file:**

```text
app/frontend/assets/js/components/modals.js
```

---

# 1. Current state

Transaction table hiện đã dùng:

```javascript
escapeHtml(...)
```

cho nhiều user-facing fields như:

```text
merchant
note
category_name
account_name
date
```

đây là improvement tốt.

Tuy nhiên modal dropdown hiện vẫn build HTML như:

```javascript
state.accounts.map(
  a => `<option value="${a.id}">
          ${a.name} (${a.account_type})
        </option>`
)
```

và:

```javascript
filtered.map(
  c => `<option value="${c.id}">
          ${c.name}
        </option>`
)
```

sau đó assign bằng:

```javascript
element.innerHTML = ...
```



---

# 2. Example attack/input

User tạo account name:

```html
<img src=x onerror=alert(1)>
```

hoặc category:

```html
</option><img src=x onerror=alert(1)>
```

Nếu value này đi vào an HTML sink không escape:

```javascript
innerHTML
```

browser sẽ parse nó như markup thay vì plain text.

---

# 3. Why stored DOM injection matters here

Data có thể được:

```text
entered by user
stored in SQLite
loaded later
inserted into DOM
```

Nên đây là kiểu:

```text
stored data
→ unsafe DOM sink
```

Ngay cả với local desktop app, vẫn nên xử lý vì data còn có thể đến từ:

```text
CSV import
backup restore
future sync/import features
manually edited database
```

---

# 4. Minimal fix

Dùng existing:

```javascript
escapeHtml()
```

Ví dụ:

```javascript
state.accounts.map(a => `
  <option value="${a.id}">
    ${escapeHtml(a.name)}
    (${escapeHtml(a.account_type)})
  </option>
`)
```

và:

```javascript
filtered.map(c => `
  <option value="${c.id}">
    ${escapeHtml(c.name)}
  </option>
`)
```

---

# 5. Recommended fix ⭐

Đối với `<select>`, tốt hơn là không dùng `innerHTML`.

Dùng DOM APIs:

```javascript
function createOption(value, label) {
  const option = document.createElement('option');
  option.value = String(value);
  option.textContent = label;
  return option;
}
```

Ví dụ:

```javascript
accSelect.replaceChildren();

accSelect.appendChild(
  createOption('', 'Select Account...')
);

for (const account of state.accounts) {
  accSelect.appendChild(
    createOption(
      account.id,
      `${account.name} (${account.account_type})`
    )
  );
}
```

`textContent` sẽ treat input như plain text.

Không cần tự escape HTML.

---

# 6. General frontend rule

Nên document rule:

### Safe

```javascript
element.textContent = userValue;
input.value = userValue;
option.textContent = userValue;
```

### Requires escaping

```javascript
element.innerHTML = `
    <div>${escapeHtml(userValue)}</div>
`;
```

### Avoid

```javascript
element.innerHTML = `
    <div>${userValue}</div>
`;
```

---

# 7. Suggested security audit

Search toàn frontend:

```text
.innerHTML
insertAdjacentHTML
outerHTML
```

Sau đó classify mỗi interpolated value:

```text
Static constant?
→ safe

Internal enum?
→ generally safe

User/database/import-controlled?
→ textContent / escape required
```

---

# 8. Acceptance criteria

- [ ] Account name không được interpreted như HTML.
- [ ] Category name không được interpreted như HTML.
- [ ] Account type không được interpreted như HTML nếu value không phải trusted enum.
- [ ] Transaction table vẫn escape dynamic strings.
- [ ] Search toàn frontend không còn unescaped user-controlled `innerHTML` sinks.

---

# 9. Tests

Frontend test case:

```text
Account:
<img src=x onerror=window.__xss=true>
```

Expected UI:

```text
<img src=x onerror=window.__xss=true>
```

phải hiển thị dưới dạng text.

Không được tạo `<img>` element.

Tương tự:

```text
Category:
</option><script>...</script>
```

phải hiển thị nguyên text.

---

# Recommended implementation order

## Phase 1 – Protect financial invariants

### Step 1

Fix BUG-001:

```text
Reject duplicate transfer
+
hide Duplicate button for transfer
```

### Step 2

Fix BUG-002:

```text
Guard generic update
+
route transfer/refund through specialised services
```

Sau hai bước này, thêm integrity tests trước khi tiếp tục.

---

## Phase 2 – Fix CSV correctness

Fix theo thứ tự:

```text
Invalid dates
    ↓
Amount parsing
    ↓
Dedup fingerprint
    ↓
Unify preview/commit parser
```

Reason:

CSV import có khả năng đưa nhiều records sai vào database cùng lúc nên đây là risk surface lớn.

---

## Phase 3 – Reliability & security

Fix:

```text
Backup logger
    ↓
Backup failure tests
    ↓
Remaining innerHTML sinks
```

---

# Definition of Done

Không xem issue là hoàn thành chỉ vì UI có vẻ hoạt động.

Một fix được xem là complete khi có đủ:

```text
1. Backend invariant enforced
2. Frontend behaviour correct
3. Existing data path không bypass được validation
4. Regression test added
5. Error case tested
6. Existing tests still pass
```

---

# Final integrity checklist

Sau khi hoàn thành 5 issues, nên verify:

```text
[ ] Không có orphan transfers
[ ] Transfer pair luôn balanced
[ ] Refund không vượt original expense
[ ] Generic API không bypass specialised rules
[ ] CSV invalid date không biến thành today
[ ] VND thousands separator được parse đúng
[ ] CSV duplicate detection không skip legitimate transaction
[ ] Backup restore giữ đúng root exception
[ ] User-controlled strings không đi trực tiếp vào innerHTML
[ ] Regression tests tồn tại cho từng bug
```