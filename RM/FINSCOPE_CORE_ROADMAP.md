# FinScope CORE Roadmap

> **Purpose:** Define the stable CORE foundation that should be completed before FinScope's advanced Analytics layer is treated as production-ready.
>
> **CORE principle:** The interface should feel simple, fast, and forgiving, while the underlying data remains structured, exact, and reliable enough for long-term analytics.
>
> **Target outcome:** A normal transaction should take roughly **3–10 seconds** to record, while still producing clean data for Rolling Analytics, What Changed?, Spending Fingerprint, Anomaly Detection, Insights, and Forecasting.

---

# 1. CORE Philosophy

FinScope CORE is not only:

```text
Database
+
Transactions
+
Accounts
+
Categories
```

It is the system that guarantees:

```text
FAST INPUT
+
CLEAN DATA
+
CORRECT MONEY
+
SAFE STORAGE
+
CLEAR FINANCIAL SEMANTICS
```

Everything in Analytics depends on this.

If CORE data is inconsistent, then:

```text
Rolling averages become unreliable
What Changed? becomes misleading
Fingerprint becomes noisy
Anomaly detection produces false positives
Forecasting becomes inaccurate
Insights become untrustworthy
```

Therefore:

> **CORE should optimise both user convenience and analytical data quality.**

---

# 2. CORE Scope

CORE should contain:

```text
1. Transaction model
2. Smart Transaction Capture
3. Accounts
4. Categories
5. Merchants / Payees
6. Transfers
7. Refunds
8. Recurring transactions
9. Exact money handling
10. Financial semantics
11. Validation
12. Data quality
13. Backup / restore
14. Database migrations
15. Base currency
16. Settings
17. Storage architecture
18. Import-ready metadata
19. UI interaction foundations
20. Testing
```

Advanced Analytics belongs above CORE.

---

# 3. CORE Architecture

```text
                     USER INPUT
                         │
                         ▼
              Smart Transaction Capture
                         │
              ┌──────────┼──────────┐
              │          │          │
              ▼          ▼          ▼
          Merchant    Category   Account Logic
              │          │          │
              └──────────┼──────────┘
                         ▼
                Validation Layer
                         │
                         ▼
              Financial Semantics
                         │
                         ▼
                    Repository
                         │
                         ▼
                      SQLite
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
      Backup         Analytics        Export
```

---

# 4. Smart Transaction Capture

## Goal

A transaction should feel like a quick capture action, not a database form.

Normal user-facing form should show only the information that usually requires active user input.

Recommended default fields:

```text
Transaction Type
Amount
Payee
Category
Account
Date
```

Everything else should be secondary.

---

# 5. Recommended Quick Transaction UI

```text
╭──────────────────────────────────────╮
│ New Transaction                  ×   │
│                                      │
│  Expense   Income   Transfer          │
│                                      │
│             $ 52.40                  │
│                                      │
│ Payee                                │
│ Woolworths                           │
│                                      │
│ Category                             │
│ 🛒 Groceries                      ▾  │
│                                      │
│ Account                              │
│ CommBank Everyday                 ▾  │
│                                      │
│ Today                          More  │
│                                      │
│      Save & Add Another      Save    │
╰──────────────────────────────────────╯
```

---

# 6. Progressive Disclosure

Do not show all optional fields by default.

`More Details` can contain:

```text
Date
Time
Memo
Essentiality override
Recurring
Payment method
Tags
Attachment / receipt
```

This keeps the normal transaction workflow fast while preserving advanced data when needed.

---

# 7. Quick Input Target

## First time merchant

Example:

```text
Ctrl + N
52.40
Woolworths
Groceries
Save
```

Target:

```text
~8–10 seconds
```

---

## Familiar merchant

Example:

```text
Ctrl + N
52.40
woo
Enter
Ctrl + Enter
```

FinScope automatically knows:

```text
Expense
Woolworths
Groceries
Essential
CommBank Everyday
Today
Current time
```

Target:

```text
~3–5 seconds
```

---

# 8. Amount Input

Amount should be the first focused field.

On:

```text
Ctrl + N
```

cursor should immediately enter Amount.

Recommended appearance:

```text
         $ 52.40
```

Avoid browser-style numeric spinner controls.

---

# 9. Exact Money Handling

Never use floating-point values for stored money.

Bad:

```text
52.40
→ float
→ round
```

Recommended:

```text
"52.40"
→ exact parser
→ 5240
```

Database:

```sql
amount_minor INTEGER NOT NULL
```

Examples:

```text
$1.00
→ 100

$52.40
→ 5240

$1,284.56
→ 128456
```

---

# 10. End-to-End Money Rule

Preferred flow:

```text
User text
"52.40"

      ↓

Exact amount parser

      ↓

5240

      ↓

Backend API

amount_minor = 5240

      ↓

SQLite INTEGER
```

Avoid:

```text
parseFloat()
float()
round(float * 100)
```

for financial values.

---

# 11. Transaction Type

Primary quick types:

```text
Expense
Income
Transfer
```

Refund should normally be contextual rather than a primary quick-capture type.

---

# 12. Refund UX

Preferred workflow:

```text
Original transaction

Nike
-$200
Shopping

⋯
Record Refund
```

Then:

```text
Refund amount
$120

Date
Today

Account
CommBank

Save
```

FinScope should inherit:

```text
Merchant
Category
Essentiality
Original transaction relationship
```

---

# 13. Refund Data Model

Add:

```text
refund_of_transaction_id
```

Example:

```text
Original Expense
transaction_id = 381

Refund
refund_of_transaction_id = 381
```

This enables:

```text
Gross Shopping
Refunds
Net Shopping
```

and improves auditability.

---

# 14. Transfer UX

Transfer should use a separate form.

```text
╭──────────────────────────────╮
│ Transfer                     │
│                              │
│          $500                │
│                              │
│ From                         │
│ CommBank Everyday            │
│                              │
│              ↓               │
│                              │
│ To                           │
│ Savings                      │
│                              │
│ Today                        │
│                              │
│ Memo                         │
│ Monthly savings              │
│                              │
│          Transfer            │
╰──────────────────────────────╯
```

Do not show:

```text
Category
Merchant
Essentiality
```

for transfers.

---

# 15. Transfer Data Model

Transfers should have explicit meaning.

Do not infer direction from description text.

Recommended:

```text
transfer_group_id
transfer_role
```

Possible roles:

```text
source
destination
```

Double-entry example:

```text
Entry A
Everyday
-$500
transfer_role = source

Entry B
Savings
+$500
transfer_role = destination

same transfer_group_id
```

---

# 16. Transfer Rules

Transfer must satisfy:

```text
source_account != destination_account
amount > 0
both legs created atomically
both legs linked
```

Analytics:

```text
Income        unchanged
Expense       unchanged
Net Spending  unchanged
Net Worth     unchanged
```

Account balances change appropriately.

---

# 17. Transfer Edit

Editing transfer must update both legs atomically.

Do not:

```text
Edit one leg only
```

Do:

```text
Load transfer pair
→ edit transfer object
→ update both legs in one transaction
```

---

# 18. Transfer Duplicate

Do not duplicate one transfer leg.

Preferred:

```text
Duplicate Transfer
→ open prefilled Transfer form
→ Date defaults to Today
→ user confirms
```

---

# 19. Payee / Merchant First

For Expense input, recommended order:

```text
Amount
↓
Payee
↓
Category
↓
Account
```

Merchant data should help FinScope suggest:

```text
Category
Essentiality
Account
Recurring pattern
```

---

# 20. Merchant Entity

Do not rely only on free-text merchant names.

Recommended merchant table:

```text
merchants

id
canonical_name
default_category_id
default_essentiality
preferred_account_id
merchant_pattern
created_at
updated_at
```

---

# 21. Merchant Normalisation

Example raw inputs:

```text
WOOLWORTHS 1234 QLD
Woolworths
WOOLWORTHS
Woolies
```

should resolve to:

```text
Merchant
Woolworths
```

Keep:

```text
raw_description
```

separately for imports.

---

# 22. Merchant Memory

FinScope should learn from history.

Example:

```text
Woolworths
17 previous transactions

Groceries
16

Household
1
```

Suggested:

```text
Groceries
```

Confidence:

```text
94%
```

---

# 23. Merchant Category Rule

When user changes:

```text
Woolworths
Other
→ Groceries
```

FinScope may ask:

```text
Use Groceries for Woolworths in future?

Always
This time only
```

---

# 24. Smart Defaults Hierarchy

## Category

```text
Explicit merchant rule
↓
Merchant history
↓
Recently used category
↓
Uncategorized
```

---

## Account

```text
Merchant preferred account
↓
Last-used account for transaction type
↓
User default account
↓
Single available account
↓
Ask user
```

---

## Essentiality

```text
Transaction override
↓
Merchant rule
↓
Category default
```

---

# 25. Category Input

Do not use a long static `<select>`.

Use a searchable picker.

Example:

```text
Category

🔍 gro

🛒 Groceries
🍴 Food & Dining

Recently Used
🚆 Transport
🛍 Shopping

+ Create Category
```

---

# 26. Category Quality

Expense transactions should not silently have:

```text
category_id = NULL
```

Preferred model:

```text
Uncategorized
```

as a real system category.

Transaction can additionally carry:

```text
needs_review = true
```

---

# 27. Review Queue

If user wants to capture quickly:

```text
Amount
$31.20

Merchant
Unknown Store

Category
?
```

Allow Save.

Store:

```text
Category = Uncategorized
Needs Review = true
```

Dashboard:

```text
DATA TO REVIEW

5 transactions
$182.40

Review Now
```

---

# 28. Review Workflow

```text
Unknown Store       $31.20
Suggested:
Shopping

[ Accept ] [ Change ]

Coffee Club          $8.50
Suggested:
Food

[ Accept ]
```

This keeps capture fast without sacrificing analytical quality.

---

# 29. Category Essentiality

Essentiality should usually come from Category.

Examples:

```text
Rent
→ Essential

Groceries
→ Essential

Utilities
→ Essential

Restaurants
→ Discretionary

Entertainment
→ Discretionary
```

User should not manually select Essentiality for every transaction.

---

# 30. Essentiality Model

Recommended:

```text
essential
discretionary
```

Avoid:

```text
savings
```

inside Essentiality.

Savings is better represented through:

```text
transfer to savings account
```

or separate analytical purpose.

---

# 31. Memo Simplification

User-facing fields should not include:

```text
Merchant
Description
Note
```

all at once.

Recommended:

```text
Payee
Memo
```

Backend can retain:

```text
merchant_id
raw_description
memo
```

---

# 32. Date Input

Default:

```text
Today
```

Quick choices:

```text
Today
Yesterday
Choose date...
```

No need to open a date picker for most transactions.

---

# 33. Time Input

Time should be stored when useful but hidden in Quick Capture.

Default:

```text
current time
```

User can edit under:

```text
More Details
```

---

# 34. Account Management

FinScope should not create fake financial accounts in real mode.

Default database:

```text
accounts = empty
```

On first run:

```text
Create your first account
```

---

# 35. First Account Flow

```text
Account Name
CommBank Everyday

Type
Everyday

Opening Balance
$3,482.15

Base Currency
AUD

Create Account
```

---

# 36. Account Types

Recommended initial types:

```text
Everyday
Savings
Cash
Credit Card
Other
```

Investment accounts can come later.

---

# 37. Account Defaults

Settings:

```text
Default Spending Account
CommBank Everyday

Default Income Account
CommBank Everyday
```

FinScope can also remember:

```text
last used expense account
last used income account
```

---

# 38. Account Balance Semantics

Balance calculation must respect:

```text
Opening balance
Income
Expense
Refund
Transfer In
Transfer Out
Adjustment
```

One central semantics layer should define these rules.

---

# 39. Base Currency

V1 should use one base currency.

Settings:

```text
Base Currency
AUD
```

All V1 accounts should use the same base currency.

Do not imply that changing currency formatting performs foreign exchange conversion.

---

# 40. Currency Metadata

Define:

```text
currency_code
symbol
minor_digits
locale
input_step
```

Examples:

```text
AUD
minor_digits = 2

JPY
minor_digits = 0

VND
minor_digits = 0
```

---

# 41. Financial Semantics Layer

CORE must centrally define transaction meaning.

Example:

| Type | Income | Expense | Cash In | Cash Out | Net Spending |
|---|---:|---:|---:|---:|---:|
| Income | + | 0 | + | 0 | 0 |
| Expense | 0 | + | 0 | + | + |
| Refund | 0 | 0 | + | 0 | − |
| Transfer In | 0 | 0 | + | 0 | 0 |
| Transfer Out | 0 | 0 | 0 | + | 0 |
| Adjustment | configurable | configurable | configurable | configurable | configurable |

---

# 42. Important Distinction

Do not confuse:

```text
Net Spending
```

with:

```text
Net Cash Flow
```

Example:

```text
Net Spending
= Expenses - Refunds
```

while:

```text
Net Cash Flow
= Cash In - Cash Out
```

These may differ.

---

# 43. Recurring Transactions

Do not model recurring as only:

```text
is_recurring = true
```

CORE should support a rule.

---

# 44. Recurring Rule

Suggested fields:

```text
id
name
transaction_type
merchant_id
category_id
account_id
amount_minor
frequency
interval
next_due_date
active
created_at
updated_at
```

---

# 45. Recurring Input UX

User clicks:

```text
Make recurring...
```

Then:

```text
Frequency
Monthly

Every
15th

Expected Amount
$22.99

Next Payment
15 Oct

Include in Forecast
Yes
```

---

# 46. Recurring Examples

```text
Salary
Fortnightly

Rent
Monthly

Netflix
Monthly

Phone Bill
Monthly
```

---

# 47. Split Transactions

Not required immediately, but CORE architecture should leave room.

Example:

```text
Costco
$182

Groceries       $120
Household        $42
Clothing         $20
```

Recommended model:

```text
transaction
      │
      ├── split line
      ├── split line
      └── split line
```

---

# 48. Split Data Model Direction

Possible:

```text
transaction_splits

id
transaction_id
category_id
amount_minor
memo
```

Constraint:

```text
sum(split amounts)
=
transaction amount
```

---

# 49. Transaction Status

Useful future-ready fields:

```text
pending
cleared
reconciled
```

At minimum consider:

```text
status
```

or:

```text
cleared BOOLEAN
```

before bank imports arrive.

---

# 50. Transaction Source

Recommended:

```text
manual
csv_import
recurring_generated
adjustment
```

Add:

```text
source
```

to transaction metadata.

---

# 51. Import Metadata

Before CSV import, leave room for:

```text
external_id
import_hash
raw_description
import_batch_id
```

This enables duplicate detection.

---

# 52. Duplicate Import Prevention

Possible identity:

```text
account
date
amount
raw_description
external_id
```

combined into:

```text
import_hash
```

Do not allow importing the same bank file twice to duplicate transactions silently.

---

# 53. Duplicate Transaction UX

Current manual duplicate should not save immediately.

Recommended:

```text
Duplicate
↓
Open pre-filled transaction
↓
Date = Today
↓
User reviews
↓
Save
```

---

# 54. Delete UX

Avoid native browser:

```text
confirm()
```

Preferred:

```text
Transaction deleted.

Undo
```

Possible soft-delete window:

```text
5 seconds
```

---

# 55. Keyboard UX

Recommended:

```text
Ctrl + N
New Transaction

Ctrl + Enter
Save

Ctrl + Shift + Enter
Save & Add Another

Esc
Close

Ctrl + F
Search
```

---

# 56. Save & Add Another

After Save & Add:

Reset:

```text
Amount
Payee
Category
Memo
```

Keep:

```text
Date
Account
Transaction Type
```

where appropriate.

---

# 57. Recent Transactions Shortcut

Under Quick Capture:

```text
Recent

Woolworths
$52.40 · Groceries

KFC
$18.90 · Food

Translink
$12.50 · Transport
```

Click:

```text
prefill
```

but require confirmation before saving.

---

# 58. Repeat Last

Possible action:

```text
Repeat Last
```

Prefill last transaction with:

```text
Date = Today
```

Do not create transaction instantly.

---

# 59. Validation Layer

Backend validation is mandatory.

Frontend validation improves UX but is not authoritative.

---

# 60. Required Validation

Check:

```text
amount > 0
valid transaction type
valid account
valid date
valid currency
category compatibility
transfer source != destination
refund amount valid
split total matches transaction amount
linked transaction exists
```

---

# 61. Inline Validation

Bad:

```text
Toast:
Please select an account
```

Preferred:

```text
Account
[ Select Account ]
⚠ Account is required.
```

Use toast for:

```text
Saved
Backup completed
Unexpected backend error
```

---

# 62. Transaction Signs

Presentation must use financial semantics.

Recommended:

```text
Income        + green
Refund        + cyan
Expense       - red
Transfer Out  → neutral
Transfer In   ← neutral
```

Transfer should not look like spending.

---

# 63. Transaction Filters

Include:

```text
All
Expense
Income
Refund
Transfer
Adjustment
```

Or user-friendly grouping:

```text
All
Spending
Income
Refunds
Transfers
Adjustments
```

---

# 64. Search Period

Transactions search should clearly state scope.

Recommended period selector:

```text
This Month
Last 3 Months
This Year
All Time
Custom
```

Do not make search silently constrained to current month without showing it.

---

# 65. Global vs Local Filters

Avoid ambiguous states.

Example bad state:

```text
Global Account = CommBank
Local Account = All Accounts
```

but results still show CommBank only.

Use:

```text
Account: CommBank ×
```

filter chip.

---

# 66. Calendar Input

Keep:

```text
double-click date
```

as a shortcut.

Also support discoverable:

```text
+ icon on hover
```

Single click:

```text
open day drawer
```

---

# 67. Account & Category Management UI

Recommended Settings sections:

```text
General
Accounts
Categories
Merchants
Rules
Recurring
Data & Backup
```

No need to overload sidebar.

---

# 68. Category Management

Support:

```text
Create
Rename
Archive
Default Essentiality
Icon
Colour
Parent Category
```

Do not hard-delete categories with transaction history.

Use:

```text
archive
```

---

# 69. Merchant Management

Support:

```text
Canonical name
Default category
Preferred account
Default essentiality
Patterns
Merge merchants
```

Merchant merge is useful for:

```text
Woolworths
WOOLWORTHS
Woolies
```

---

# 70. Data Quality Centre

Potential Settings or Dashboard card:

```text
DATA QUALITY

Uncategorized transactions      12
Unknown merchants                4
Possible duplicates              2
Unreviewed imports               0

Review
```

---

# 71. Data Storage

Production user data should live outside app code.

Recommended Windows path:

```text
%LOCALAPPDATA%\FinScope\
```

Structure:

```text
finance.db
settings.json

backups/
exports/
attachments/
logs/
cache/
```

---

# 72. Application/Data Separation

```text
FinScope.exe
```

must be replaceable without replacing:

```text
finance.db
```

Updating app should not delete user data.

---

# 73. Backup

Use SQLite backup API.

Recommended flow:

```text
Live DB
↓
SQLite Connection.backup()
↓
Snapshot
↓
PRAGMA integrity_check
↓
Backup archive
```

---

# 74. Backup Package

Example:

```text
FinScope_2026-09-04.financebackup
```

Contains:

```text
finance.db
settings.json
metadata.json
```

Potential future:

```text
attachments
```

if selected.

---

# 75. Backup Metadata

Include:

```text
backup_format_version
schema_version
app_version
created_at
transaction_count
account_count
database_size
```

---

# 76. Restore

Recommended:

```text
Select backup
↓
Validate archive
↓
Validate database
↓
Create safety backup
↓
Check schema version
↓
Migrate temporary restored DB
↓
Integrity check
↓
Atomic replacement
↓
Reload app
```

---

# 77. Atomic Restore

Prefer:

```text
temporary restored database
↓
fsync
↓
os.replace()
```

instead of writing directly over live DB.

---

# 78. Migration Framework

Use explicit versions.

Example:

```text
001_initial
002_minor_units
003_transfer_roles
004_refund_links
005_transaction_source
```

Never reuse migration version numbers.

---

# 79. Migration Safety

Before pending migration:

```text
backup current database
```

Then:

```text
run migration
↓
integrity check
↓
commit
```

Failure:

```text
stop
restore previous state
show error
```

---

# 80. Demo Data

Real mode should not automatically create fake balances.

Allowed:

```text
default categories
```

Not allowed:

```text
fake accounts
fake opening balances
fake transactions
```

Demo should be explicit:

```text
Explore Demo Data
```

---

# 81. Demo Mode

If user selects Demo:

```text
Create demo accounts
Create demo transactions
Create demo budgets
```

Keep demo mode clearly separate from personal data.

---

# 82. Security Preparation

Not necessarily CORE release blocker, but architecture should support later:

```text
PIN
Auto-lock
Encrypted backups
Sensitive value hiding
Database encryption
```

Do not implement encryption before backup reliability is stable.

---

# 83. Frontend Data Safety

Avoid injecting user-controlled text directly with:

```text
innerHTML
```

Prefer:

```text
textContent
```

or:

```text
escapeHTML()
```

Important before CSV import.

---

# 84. Accessibility Foundation

CORE UI components should support:

```text
role="dialog"
aria-modal
focus trap
keyboard navigation
ARIA pressed state
visible focus
```

Components:

```text
Modal
Dropdown
Segmented Control
Tooltip
Toast
Dialog
```

---

# 85. CORE Transaction Model

Recommended long-term structure:

```text
TRANSACTION

id

account_id

transaction_type
expense
income
refund
transfer
adjustment

amount_minor

transaction_date
transaction_time

merchant_id
raw_description

category_id

memo

essentiality

status
pending
cleared
reconciled

source
manual
csv_import
recurring_generated
adjustment

needs_review

recurring_rule_id

refund_of_transaction_id

transfer_group_id
transfer_role

external_id
import_hash

created_at
updated_at
```

---

# 86. Optional Later Fields

Potential future:

```text
payment_method
location
attachment_id
tags
split status
```

Do not add prematurely unless needed.

---

# 87. CORE Database Tables

Suggested:

```text
transactions
accounts
categories
merchants
budgets
recurring_rules
settings
schema_migrations
transaction_splits
insight_history        ← Analytics
forecast_evaluations   ← Analytics
anomaly_feedback       ← Analytics
```

---

# 88. CORE Service Layer

Recommended:

```text
TransactionService
TransferService
RefundService
MerchantService
CategoryService
AccountService
RecurringService
ValidationService
BackupService
MigrationService
SettingsService
```

Avoid putting all transaction semantics into one repository.

---

# 89. Transaction Service Responsibilities

```text
Create
Edit
Delete
Duplicate
Validate
Resolve defaults
Resolve merchant
Resolve category
Apply rules
Set review status
```

---

# 90. Transfer Service Responsibilities

```text
Create pair
Edit pair
Delete pair
Validate pair
Protect atomicity
```

---

# 91. Refund Service Responsibilities

```text
Link original
Validate amount
Inherit merchant
Inherit category
Inherit essentiality
Update semantics
```

---

# 92. Merchant Service Responsibilities

```text
Normalize name
Find canonical merchant
Suggest category
Suggest account
Create rule
Merge merchants
```

---

# 93. Smart Rule Engine

Rule types:

```text
Merchant → Category
Merchant → Account
Merchant → Essentiality
Description Pattern → Merchant
```

Priority:

```text
explicit rule
↓
merchant history
↓
default
```

---

# 94. Rule Confidence

Possible confidence:

```text
high
medium
low
```

Example:

```text
Woolworths
17/18 → Groceries

High confidence
```

Automatically prefill.

Example:

```text
Amazon
8 Shopping
6 Electronics
4 Books

Low confidence
```

Ask user.

---

# 95. CORE Testing

CORE needs stronger tests than UI-only testing.

Must test:

```text
exact money parsing
transaction create/edit/delete
transfer pair creation
transfer pair edit
transfer pair delete
refund linking
refund semantics
account balances
merchant normalisation
category defaults
backup round-trip
WAL backup
restore
migration
failed migration
invalid backup
duplicate detection
review queue
```

---

# 96. Golden CORE Dataset

Create deterministic fixture:

```text
2 accounts
1 savings account
1 credit card
10 categories
5 merchants

salary
rent
groceries
restaurant
transport
refund
transfer
recurring bill
uncategorized expense
```

Use same dataset across tests.

---

# 97. CORE Acceptance Criteria

CORE is ready when user can:

```text
Create an account
Record expense quickly
Record income quickly
Transfer money correctly
Record refund from original transaction
Use merchant suggestions
Use category suggestions
Save uncategorized to Review Queue
Edit transaction
Delete with recovery
Back up data
Restore data
Move data to another computer
Upgrade schema without losing data
```

and Analytics receives correct structured data.

---

# 98. CORE P0 Checklist

Complete before Analytics is considered trustworthy:

- [ ] Exact money input end-to-end
- [ ] Explicit transfer direction / role
- [ ] Atomic transfer create/edit/delete
- [ ] Remove fake default balances
- [ ] Base Currency semantics
- [ ] Backend validation layer
- [ ] Merchant canonicalisation plan
- [ ] Uncategorized + Needs Review strategy
- [ ] Category default essentiality
- [ ] Correct refund semantics
- [ ] Correct transaction signs
- [ ] Correct transaction filters
- [ ] Backup round-trip verified
- [ ] Migration versioning verified

---

# 99. CORE P1 Checklist

Complete before personal beta:

- [ ] Smart merchant autocomplete
- [ ] Merchant → category learning
- [ ] Merchant → account learning
- [ ] Account management UI
- [ ] Category management UI
- [ ] Merchant management UI
- [ ] Refund linking UX
- [ ] Recurring schedule model
- [ ] Save & Add Another
- [ ] Review Queue
- [ ] Search period control
- [ ] Duplicate opens prefilled form
- [ ] Undo delete
- [ ] Data Quality panel

---

# 100. CORE P2 Checklist

Design now, implement later:

- [ ] Split transaction model
- [ ] Cleared / reconciled status
- [ ] CSV import metadata
- [ ] Merchant merge tool
- [ ] Tags
- [ ] Attachment support
- [ ] Accessibility polish
- [ ] Advanced command input
- [ ] Natural quick-entry parser
- [ ] Multi-currency FX engine

---

# 101. CORE and Analytics Boundary

CORE owns:

```text
What happened?
```

with reliable structured data.

Analytics owns:

```text
What does it mean?
```

Pipeline:

```text
CORE
Transactions
Accounts
Categories
Merchants
Transfers
Refunds
Recurring
Validation

        ↓

ANALYTICS
Rolling
What Changed?
Fingerprint
Anomalies
Forecasting
Insights
```

---

# 102. Core Rule: Do Not Ask What Can Be Inferred

Example:

```text
Woolworths
```

FinScope may infer:

```text
Groceries
Essential
CommBank Everyday
```

If confidence is high, user should not have to select them every time.

---

# 103. Core Rule: Do Not Hide Uncertainty

If FinScope does not know:

```text
Unknown Store
```

do not guess aggressively.

Use:

```text
Suggested category?
```

or:

```text
Uncategorized
Needs Review
```

---

# 104. Core Rule: Keep Data Structured

Even when UI is simplified, backend should retain:

```text
Merchant entity
Category entity
Account
Transaction type
Exact amount
Date
Relationships
Source
Review status
```

Simple UI must not mean weak data.

---

# 105. Core Rule: Separate Fast Capture from Data Cleanup

User should be able to:

```text
capture now
review later
```

This is especially useful during:

```text
busy workday
end-of-day batch entry
CSV import
unknown merchant
```

---

# 106. Recommended Final Quick Capture Flow

```text
Ctrl + N
    ↓
Amount
    ↓
Payee
    ↓
Auto-suggest Category
    ↓
Auto-select Account
    ↓
Save
```

Everything else is background logic.

---

# 107. Recommended Final Smart Capture Architecture

```text
USER
 │
 │ $52.40 + Woolworths
 ▼
Quick Capture
 │
 ▼
Merchant Resolver
 │
 ├── Woolworths canonical merchant
 │
 ▼
Rule Engine
 │
 ├── Category = Groceries
 ├── Essentiality = Essential
 └── Account = CommBank Everyday
 │
 ▼
Validation
 │
 ▼
TransactionService
 │
 ▼
SQLite
 │
 ▼
Analytics
```

---

# 108. Immediate CORE Sprint

## Sprint Name

```text
CORE — Smart Transaction Capture
```

Tasks:

- [ ] Replace current form with progressive disclosure
- [ ] Autofocus amount
- [ ] Exact amount parser
- [ ] Move Payee before Category
- [ ] Add searchable Category picker
- [ ] Add smart Account default
- [ ] Hide Time
- [ ] Hide Essentiality
- [ ] Hide Recurring
- [ ] Merge Description + Note into Memo
- [ ] Add Save & Add Another
- [ ] Add Uncategorized + Needs Review
- [ ] Add inline validation
- [ ] Rename Record Expense → New Transaction

Definition of Done:

> Normal transaction can be entered in less than 10 seconds without sacrificing category/account data quality.

---

# 109. Second CORE Sprint

## Sprint Name

```text
CORE — Merchant Intelligence
```

Tasks:

- [ ] Canonical merchants
- [ ] Merchant normalisation
- [ ] Merchant autocomplete
- [ ] Merchant history
- [ ] Default category
- [ ] Preferred account
- [ ] Default essentiality
- [ ] Rule confidence
- [ ] Always / This Time Only rule action
- [ ] Merchant management UI

Definition of Done:

> Familiar merchants require almost no manual classification.

---

# 110. Third CORE Sprint

## Sprint Name

```text
CORE — Financial Relationships
```

Tasks:

- [ ] Transfer role
- [ ] Transfer atomic edit
- [ ] Transfer atomic delete
- [ ] Refund original link
- [ ] Refund inherit category
- [ ] Recurring rules
- [ ] Correct account balance semantics
- [ ] Correct UI signs

Definition of Done:

> Transfers, refunds, and recurring transactions cannot distort financial reporting.

---

# 111. Fourth CORE Sprint

## Sprint Name

```text
CORE — Data Quality & Reliability
```

Tasks:

- [ ] Review Queue
- [ ] Data Quality dashboard
- [ ] Duplicate checks
- [ ] Backup round-trip
- [ ] Migration backup
- [ ] Atomic restore
- [ ] Search period
- [ ] Account/category management
- [ ] Source metadata
- [ ] Import-ready schema

Definition of Done:

> User can safely maintain clean data over years.

---

# 112. CORE Release Gate

Do not declare CORE stable until:

```text
Quick Capture works
Exact money works
Transfers are safe
Refunds are linked
Accounts are real
Categories are manageable
Merchant suggestions work
Review Queue works
Backup restores correctly
Migrations are safe
```

---

# 113. Analytics Push Compatibility

The Analytics branch can continue in parallel if it consumes stable canonical fields only.

Analytics should rely on:

```text
amount_minor
transaction_type
transaction_date
account_id
category_id
merchant_id
essentiality
transfer_role
refund_of_transaction_id
source
```

Avoid coupling Analytics to temporary UI fields.

---

# 114. Analytics Should Not Depend on Free Text

Bad analytical dependency:

```text
description contains "(Received)"
```

Good:

```text
transfer_role = destination
```

Bad:

```text
merchant_name string grouping
```

Good:

```text
merchant_id
```

This is a major CORE responsibility.

---

# 115. Analytics-Safe Data Contract

Recommended transaction output:

```json
{
  "id": 381,
  "transaction_type": "expense",
  "amount_minor": 5240,
  "transaction_date": "2026-09-04",
  "transaction_time": "15:42",
  "account_id": 2,
  "merchant_id": 14,
  "category_id": 6,
  "essentiality": "essential",
  "needs_review": false,
  "source": "manual",
  "refund_of_transaction_id": null,
  "transfer_group_id": null,
  "transfer_role": null
}
```

Analytics should build on this contract.

---

# 116. Final CORE Vision

The user should experience:

```text
Simple
Fast
Predictable
Low friction
```

while FinScope internally maintains:

```text
Exact money
Canonical merchants
Structured categories
Valid accounts
Linked refunds
Linked transfers
Recurring schedules
Review status
Backup safety
Migration safety
```

---

# 117. CORE Success Example

User enters:

```text
52.40
Woolworths
```

FinScope resolves:

```text
Type
Expense

Amount
5240 minor units

Merchant
Woolworths

Category
Groceries

Essentiality
Essential

Account
CommBank Everyday

Date
Today

Source
Manual

Needs Review
False
```

User presses Save.

Analytics immediately receives clean data.

That is the target behaviour.

---

# 118. Final Priority Order

```text
1. Exact Money
2. Smart Capture
3. Merchant Canonicalisation
4. Category Defaults
5. Account Defaults
6. Transfer Integrity
7. Refund Relationships
8. Recurring Rules
9. Review Queue
10. Validation
11. Backup / Restore
12. Migration Safety
13. Import Metadata
14. UX Polish
```

---

# 119. Final Product Principle

> **The user should enter as little as possible, while FinScope should infer as much as it can safely infer.**

And:

> **When FinScope is uncertain, it should ask later rather than forcing the user through a long form now.**

This balance is the CORE foundation that allows the Analytics layer to become powerful without making everyday transaction entry annoying.
