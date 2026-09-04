# FinScope — Recheck Notes & Recommended Fixes

> Repository reviewed: `https://github.com/Tannniee/TestFinScope`

These notes summarise the main technical observations, risks, and recommended priorities before FinScope is used with long-term real financial data.

---

# 1. Current Overall Assessment

FinScope has progressed beyond a simple mock-up.

It already has a fairly complete functional prototype with:

- Overview / Dashboard
- Transactions
- Calendar
- Analytics / BI-style analysis
- Budget
- Reports
- Data & Storage
- SQLite backend
- Backup / restore
- CSV export
- Python service / repository structure

The current frontend uses:

```text
HTML
CSS
Vanilla JavaScript
ECharts
Lucide Icons
```

The backend uses:

```text
Python
SQLite
Repository / Service / API separation
```

This is already a workable architecture for a personal offline finance application.

There is **no urgent reason to rewrite the frontend into React** unless future development becomes difficult to maintain.

The more important priority is now:

> **data safety, financial correctness, migrations, and long-term reliability**

---

# 2. Priority Summary

| Priority | Issue | Severity |
|---|---|---|
| P0 | Backup / restore with SQLite WAL | Critical |
| P0 | Safety backup uses incorrect file format | Bug |
| P0 | User data stored inside project folder | Critical before packaging |
| P0 | Monetary values stored as `REAL` | Should change before real long-term data |
| P1 | Transfers are not modelled correctly | Important financial logic |
| P1 | Demo data automatically reappears | Production issue |
| P1 | Migration system is incomplete | Important for future updates |
| P2 | Currency is hardcoded | Should become a setting |
| P2 | Refund / adjustment semantics incomplete | Analytics correctness |
| P2 | Backup / migration failure tests incomplete | Reliability |
| P3 | Advanced analytics / forecasting | Later feature |
| P3 | AI insights | Not needed yet |

---

# 3. P0 — Backup / Restore Must Be Hardened

## Problem

The database currently uses SQLite WAL mode:

```python
conn.execute("PRAGMA journal_mode = WAL;")
```

However, backup currently appears to copy only:

```text
finance.db
```

into the backup archive.

With WAL mode, some recent committed changes may temporarily exist in:

```text
finance.db-wal
```

rather than being fully checkpointed into the main database file.

Therefore:

> Copying only `finance.db` is not the safest backup strategy.

---

## Recommended Approach

Use SQLite's own backup API.

Conceptual flow:

```text
LIVE DATABASE

finance.db
finance.db-wal
finance.db-shm

        ↓

SQLite Connection.backup()

        ↓

Clean temporary database snapshot

        ↓

Validate snapshot

        ↓

Create .financebackup archive
```

Example architecture:

```text
backup_service.py

1. Open live database connection
2. Create temporary snapshot database
3. Run sqlite3.Connection.backup()
4. Run integrity_check on snapshot
5. Add snapshot to backup archive
6. Add settings / metadata
7. Save final .financebackup
8. Remove temporary snapshot
```

---

# 4. P0 Bug — Safety Backup Has the Wrong Format

Current restore process creates a safety backup before restoring.

The issue is conceptually:

```python
safety_name = "Safety_PreRestore_....financebackup"
shutil.copyfile(DB_PATH, BACKUPS_DIR / safety_name)
```

This produces:

```text
Safety_PreRestore_xxx.financebackup
```

but the file is actually just:

```text
raw SQLite database
```

Later, the restore system expects `.financebackup` to be a ZIP archive.

Therefore:

```text
extension says ZIP backup
actual content = SQLite file
```

This can cause restore failure.

---

## Fix

The safety backup should use the **same backup creation function** as a normal backup.

Correct flow:

```text
Before restore

Current DB
    ↓
create_backup()
    ↓
Safety_PreRestore_2026-09-04.financebackup
```

Do not manually copy the raw DB and rename it.

---

# 5. P0 — Separate Application Code from User Data

Current development storage is effectively:

```text
TestFinScope/
├── app/
├── data/
│   └── finance.db
```

This is acceptable during development.

It is **not ideal for an installed Windows application**.

---

## Recommended Production Structure

Use a Windows application data directory.

Example:

```text
%LOCALAPPDATA%\FinScope\
```

Structure:

```text
FinScope/
│
├── finance.db
├── settings.json
│
├── backups/
│
├── exports/
│
├── attachments/
│
├── cache/
│
└── logs/
```

---

## Why This Matters

Application code and data should behave independently.

Example:

```text
FinScope v1.exe
        ↓
update
        ↓
FinScope v2.exe
```

while:

```text
finance.db
```

remains untouched.

The user should be able to:

```text
upgrade app
reinstall app
replace app executable
```

without losing transaction history.

---

# 6. P0 — Do Not Store Money as SQLite REAL

Current schema uses values similar to:

```sql
amount REAL NOT NULL
```

This is common in prototypes, but not ideal for financial applications.

Floating-point arithmetic can produce representation errors.

Classic example:

```python
0.1 + 0.2
```

may internally produce:

```text
0.30000000000000004
```

UI rounding can hide this, but the data model should ideally be exact.

---

# 7. Recommended Money Storage Model

Store monetary values in the currency's smallest unit.

For AUD / USD:

```text
$52.40
```

store as:

```text
5240
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

Display layer:

```text
128456 minor units
→ 1284.56
→ $1,284.56
```

---

## Benefits

- exact arithmetic
- reliable totals
- reliable budget comparison
- reliable reports
- easier testing
- fewer rounding surprises

---

# 8. Important Timing

This change is easiest **before a large amount of real data exists**.

If changed later, a migration must convert:

```text
REAL
→ INTEGER minor units
```

Therefore this should be treated as a high-priority schema improvement.

---

# 9. P1 — Transfer Logic Needs a Proper Financial Model

The app currently supports the concept:

```text
Expense
Income
Transfer
```

but the transaction model only appears to have one account reference.

A real transfer requires:

```text
source account
destination account
amount
```

Example:

```text
Transfer $500

From:
CommBank Everyday

To:
CommBank Savings
```

This is:

```text
NOT an expense
NOT an income
```

It is simply money moving between owned accounts.

---

# 10. Recommended Transfer Models

## Option A — Single transfer record

Fields:

```text
from_account_id
to_account_id
amount_minor
date
note
```

Simple and easy to understand.

---

## Option B — Double-entry style

Create two linked ledger entries.

Example:

```text
Entry A
CommBank Everyday
-$500

Entry B
CommBank Savings
+$500

transfer_group_id = abc123
```

Advantages:

- account balances remain intuitive
- strong audit trail
- easier account ledger views
- closer to proper accounting logic

For FinScope, this is probably the stronger long-term design.

---

# 11. P1 — Demo Data Should Not Automatically Reappear

Current startup logic appears to seed sample data when:

```text
transaction count = 0
```

This means:

```text
new database
→ demo data inserted
```

But also potentially:

```text
user deletes all transactions
→ restart app
→ demo data appears again
```

This is undesirable in production.

---

# 12. Recommended First-Run Experience

Instead:

```text
Welcome to FinScope
```

Offer:

```text
○ Start with an empty database

○ Explore with demo data
```

Default should be:

```text
Start empty
```

Demo data should only be inserted after explicit user choice.

---

# 13. P1 — Migration System Needs to Become Real

There is already a useful foundation:

```text
schema_migrations
CURRENT_SCHEMA_VERSION
```

However, simply updating a version marker is not enough.

A real migration system should contain explicit transformations.

---

# 14. Recommended Migration Structure

Example:

```text
backend/database/migrations/

001_initial.sql
002_money_minor_units.sql
003_transfer_model.sql
004_app_settings.sql
005_refund_semantics.sql
```

---

## Migration Flow

Example:

```text
Database version: 2
App requires: 5
```

Startup:

```text
1. Detect schema version
2. Create safety backup
3. Run migration 003
4. Validate
5. Run migration 004
6. Validate
7. Run migration 005
8. Run integrity check
9. Save new schema version
10. Launch app
```

---

# 15. Migration Safety

If migration fails:

```text
DO NOT partially continue
```

The app should:

```text
stop migration
restore previous database
show error
preserve original data
```

A failed migration should never silently damage the database.

---

# 16. P2 — Currency Should Be Configurable

Current defaults are strongly oriented around:

```text
USD
$
```

FinScope should instead support a user-level currency setting.

Example:

```text
Settings
→ Currency
```

Options:

```text
AUD
USD
VND
EUR
GBP
...
```

---

# 17. Currency Formatting

Frontend should format values based on currency metadata rather than hardcoding `$`.

Possible implementation:

```javascript
Intl.NumberFormat(...)
```

Examples:

```text
AUD
$1,250.00

USD
$1,250.00

VND
1.250.000 ₫
```

---

# 18. P2 — Refunds Need Explicit Financial Semantics

The schema supports concepts similar to:

```text
income
expense
transfer
refund
adjustment
```

but analytics currently focuses mainly on:

```text
income
expense
```

This can produce misleading reports.

---

# 19. Example Refund Problem

Original purchase:

```text
Nike
Shopping
-$200
```

Later refund:

```text
Nike refund
+$200
```

How should analytics interpret it?

Recommended interpretation:

```text
Refund
→ reduces Shopping expense
```

rather than:

```text
new income
```

Otherwise income can become artificially inflated.

---

# 20. Recommended Financial Semantics Layer

Define exactly how transaction types affect analytics.

Example:

```text
EXPENSE
→ expense +amount

REFUND
→ expense -amount

INCOME
→ income +amount

TRANSFER
→ neither income nor expense

ADJUSTMENT
→ account balance adjustment
```

This logic should live in one central financial calculation layer.

Do not duplicate the rules in multiple pages.

---

# 21. Recommended Transaction Semantics

A future model could include:

```text
transaction_type

income
expense
refund
transfer
adjustment
```

and optionally:

```text
linked_transaction_id
```

For refunds:

```text
refund linked to original purchase
```

This enables analysis such as:

```text
Gross Shopping Spend
$1,000

Refunds
-$200

Net Shopping Spend
$800
```

---

# 22. Analytics Engine — Current Direction Is Good

The analytics layer already appears aligned with the desired product direction.

Useful existing concepts include:

```text
What Changed?
Category variance
Spending by weekday
Cumulative spending
Top merchants
Transaction size distribution
Calendar aggregation
Income / expense summaries
```

These are good foundations.

Do not rewrite the analytics engine unnecessarily.

Instead:

```text
preserve
test
extend
```

---

# 23. Important Analytics Philosophy

FinScope should remain focused on:

```text
WHAT happened?
WHERE did money go?
WHY did it change?
IS it unusual?
WHAT may happen next?
```

Each visual should support one of these questions.

---

# 24. Analytics Layer Structure

Recommended structure:

```text
Raw Transactions
       ↓
Financial Semantics
       ↓
Aggregations
       ↓
Comparisons
       ↓
Insights
       ↓
Forecasts
```

---

# 25. Example

Raw:

```text
Nike -$200
Nike refund +$100
Salary +$1,500
Transfer savings $500
```

Financial semantics:

```text
Shopping net expense = $100
Income = $1,500
Transfer = excluded from income/expense
```

Dashboard then receives clean analytical values.

---

# 26. Testing — Existing Tests Are a Good Start

The current tests cover useful areas such as:

```text
CRUD
analytics
budget
backup creation
CSV export
```

This is a good base.

However, the most critical data-safety scenarios should be tested explicitly.

---

# 27. High-Priority Tests to Add

## Backup round-trip

```text
create database
→ add transactions
→ create backup
→ destroy/modify database
→ restore
→ verify every record
```

---

## WAL backup test

```text
write data in WAL mode
→ backup immediately
→ restore
→ verify latest transaction exists
```

---

## Invalid backup

```text
select broken file
→ restore rejected safely
→ current database unchanged
```

---

## Failed restore

```text
restore interrupted
→ original database still available
```

---

## Migration

```text
schema v1
→ migration
→ schema v2
→ verify data unchanged
```

---

## Failed migration

```text
migration raises error
→ rollback
→ original DB restored
```

---

## Transfer accounting

```text
Everyday $1000
Savings $0

Transfer $500

Expected:
Everyday $500
Savings $500

Income unchanged
Expense unchanged
Net worth unchanged
```

---

## Refund analytics

```text
Expense $200
Refund $80

Expected net category expense:
$120
```

---

# 28. Recommended Production Data Folder

Possible final structure:

```text
%LOCALAPPDATA%\FinScope\

finance.db

settings.json

backups/
├── daily/
├── weekly/
└── monthly/

exports/

attachments/
├── 2026/
├── 2027/
└── ...

cache/

logs/
```

---

# 29. Backup Retention Strategy

Do not keep endless backup copies.

Suggested:

```text
Daily backups
Keep 14

Weekly backups
Keep 8

Monthly backups
Keep 12
```

Delete old **backup copies**, not old financial history.

---

# 30. Historical Transactions Should Normally Never Be Deleted Automatically

Old transaction data is valuable.

It enables:

```text
month-over-month trends
year-over-year analysis
long-term averages
seasonality
merchant history
behaviour patterns
forecasting
anomaly detection
```

Therefore:

> Raw financial history should not be automatically deleted to save space.

---

# 31. Storage Growth Is Not a Major Concern

Typical personal finance transaction data is small.

Example:

```text
20 transactions/day
× 365
= 7,300/year
```

Over 10 years:

```text
≈ 73,000 transactions
```

This is easily manageable for SQLite with good indexing.

---

# 32. What Actually Causes Storage Growth

Usually:

```text
receipt images
PDF statements
screenshots
attachments
large exports
backups
```

These should not be embedded directly into SQLite.

---

# 33. Attachment Strategy

Database stores:

```text
attachment_path
```

Files live separately:

```text
attachments/
2026/
09/
receipt_000123.webp
```

This keeps:

```text
finance.db
```

small and efficient.

---

# 34. Database Indexes to Maintain

Important fields to index:

```text
transaction_date
category_id
account_id
merchant_id
transaction_type
transfer_group_id
```

These will help with:

```text
monthly reports
category analytics
account filtering
merchant analysis
calendar loading
```

---

# 35. Recommended Database Maintenance

Safe operations:

```text
PRAGMA integrity_check
ANALYZE
VACUUM
index maintenance
cache rebuild
```

These optimise storage without deleting historical records.

---

# 36. Data Health Page

A useful production feature:

```text
Settings
→ Data & Storage
```

Display:

```text
Database Status
Healthy ✓

Transactions
18,429

Date Range
Jul 2026 – Sep 2030

Database Size
34.8 MB

Attachments
472 MB

Backups
186 MB

Last Backup
Today, 2:14 PM
```

Actions:

```text
Backup Now
Restore Backup
Export Data
Optimise Database
Open Data Folder
Run Integrity Check
```

---

# 37. Security Recommendations

Because finance data is sensitive, future versions may support:

```text
PIN lock
auto-lock
database encryption
encrypted backups
hide balances mode
```

Important priority:

```text
correctness first
encryption second
```

Do not add complex encryption before backup and restore are fully reliable.

---

# 38. Packaging Recommendations

Before packaging as an `.exe`, ensure:

- [ ] Data path no longer depends on repository folder
- [ ] Backup path works after installation
- [ ] Database migrations work
- [ ] Demo seeding is disabled by default
- [ ] App update does not replace user DB
- [ ] Uninstall does not silently delete finance data
- [ ] Backup restore is tested on a clean machine
- [ ] User can locate data folder
- [ ] App can recover from corrupted config

---

# 39. Current Development Maturity Estimate

Approximate status:

```text
Foundation          ██████████  ~90%
Transaction CRUD    ██████████  ~90%
Dashboard           █████████░  ~85%
Calendar            █████████░  ~85%
Analytics BI        ████████░░  ~75%
Budget              ████████░░  ~75%
Reports             ███████░░░  ~65%
Data Management     ██████░░░░  ~55%
Production Safety   ███░░░░░░░  ~30%
Advanced Insights   ██░░░░░░░░  ~20%
Forecasting         ░░░░░░░░░░
Bank CSV Import     ░░░░░░░░░░
```

This means FinScope is best described as:

> **a strong functional prototype, but not yet production-safe for long-term real financial data**

---

# 40. Recommended Development Order From Here

Do not prioritise more charts yet.

Recommended order:

```text
1. Data Safety Hardening
2. Money Storage Model
3. Transfer Model
4. Migration System
5. Currency / Settings
6. Refund & Adjustment Semantics
7. Automated Tests
8. Analytics Expansion
9. UI Polish
10. Insights
11. Forecasting
12. Bank CSV Import
13. Packaging / Installer
```

---

# 41. Milestone A — Data Safety Hardening

Tasks:

- [ ] Replace raw DB backup with SQLite backup API
- [ ] Fix safety backup format
- [ ] Validate backup before marking successful
- [ ] Run integrity check during restore
- [ ] Automatically backup before restore
- [ ] Test WAL scenario
- [ ] Test backup round-trip
- [ ] Protect current DB from failed restore
- [ ] Add backup metadata
- [ ] Add backup version

Definition of done:

> A backup made today can restore every transaction correctly on another computer.

---

# 42. Milestone B — Financial Data Correctness

Tasks:

- [ ] Change money fields from REAL to integer minor units
- [ ] Define transaction type semantics
- [ ] Implement transfers correctly
- [ ] Implement refunds correctly
- [ ] Define adjustments
- [ ] Centralise calculation rules
- [ ] Add financial correctness tests

Definition of done:

> Income, expense, refunds, transfers, and balances cannot distort analytics.

---

# 43. Milestone C — Long-Term Upgrade Safety

Tasks:

- [ ] Build real migration framework
- [ ] Create migration files
- [ ] Backup before migration
- [ ] Add migration rollback strategy
- [ ] Add schema version tests
- [ ] Test old DB opening in new app version

Definition of done:

> FinScope can evolve for years without requiring the user to reset their database.

---

# 44. Milestone D — Production Data Location

Tasks:

- [ ] Move user DB to LocalAppData
- [ ] Move settings to app-data directory
- [ ] Add data-folder helper
- [ ] Add Open Data Folder button
- [ ] Test portable backup / restore
- [ ] Test reinstall
- [ ] Test application update

Definition of done:

> The executable can be replaced without affecting user financial data.

---

# 45. Milestone E — Analytics Expansion

Once the above is stable, continue with:

```text
What Changed?
Drill-down
Cross-filtering
Rolling averages
Spending fingerprint
Budget pacing
Anomalies
Insights
Forecasting
```

---

# 46. What Should NOT Be Prioritised Yet

Avoid investing heavily in:

```text
AI chatbot
machine learning
cloud sync
complex forecasting
bank API connection
receipt OCR
more decorative charts
```

before financial data safety is strong.

---

# 47. Recommended Product Philosophy

The long-term goal should remain:

```text
RECORD
→ UNDERSTAND
→ EXPLAIN
→ COMPARE
→ PREDICT
→ ACT
```

But beneath all of that must be:

```text
TRUST THE DATA
```

If the numbers are not reliable, no amount of attractive BI visualisation is useful.

---

# 48. Most Important Rule Going Forward

> **FinScope should be designed so it can hold 5–10+ years of personal financial history without requiring the user to delete old data, rebuild the database, or fear losing information during an update or computer migration.**

---

# 49. Immediate Recommended Next Sprint

## Sprint: FinScope Data Safety

### P0 tasks

- [ ] Replace backup implementation with SQLite `Connection.backup()`
- [ ] Fix pre-restore safety backup
- [ ] Add backup validation
- [ ] Add restore validation
- [ ] Add backup / restore integration test
- [ ] Add WAL backup test
- [ ] Move production data path design to LocalAppData
- [ ] Design migration from `REAL` money values to integer minor units

### P1 tasks

- [ ] Remove automatic demo seeding
- [ ] Design transfer schema
- [ ] Create migration framework
- [ ] Add currency setting model
- [ ] Define refund / adjustment semantics

---

# 50. Recommended Target Before Real Personal Data

Before using FinScope as the main personal finance tracker, aim for this checklist:

- [ ] Money values stored exactly
- [ ] Backups verified
- [ ] Restore verified
- [ ] WAL-safe backups
- [ ] Transfers correct
- [ ] Refunds correct
- [ ] App data outside application folder
- [ ] Migration system works
- [ ] Demo data disabled
- [ ] Currency configurable
- [ ] Backup before migrations
- [ ] Backup before restore
- [ ] Tests pass
- [ ] Clean install tested
- [ ] New-machine restore tested

Once this is complete, FinScope will have a much stronger foundation for the analytics features planned later.
