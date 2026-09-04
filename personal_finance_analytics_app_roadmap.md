# Personal Finance Analytics App — Detailed Product & Development Roadmap

> **Working concept:** A private, offline-first Windows personal finance analytics application that does more than record transactions. It should help the user understand *what happened, why it happened, how financial behaviour is changing, what may happen next, and what action to take*.

---

# 1. Product Vision

## 1.1 Core idea

This app is **not just an expense tracker**.

It is closer to a lightweight personal finance BI/analytics system with a polished desktop interface.

The product should support the full flow:

```text
RECORD
   ↓
UNDERSTAND
   ↓
EXPLAIN
   ↓
COMPARE
   ↓
PREDICT
   ↓
ACT
```

Examples:

```text
Record:
Woolworths -$52.40

Understand:
Groceries account for 18% of this month's spending.

Explain:
Groceries increased by $96 compared with last month.

Compare:
Current grocery spending is 21% above the 3-month average.

Predict:
At the current pace, grocery spending may reach $690 by month-end.

Act:
You have $110 left before reaching your $800 grocery budget.
```

---

# 2. Product Principles

These principles should guide every development decision.

## 2.1 Offline-first

The app should function completely without internet.

No server should be required for:

- entering transactions
- viewing dashboards
- generating reports
- analysing data
- viewing calendar
- backup/restore
- exporting data

Optional cloud backup can be added later, but the app itself should not depend on it.

---

## 2.2 Data belongs to the user

The user must always be able to:

- see where the data is stored
- create backups
- restore backups
- export all transactions
- move data to another computer
- leave the app without losing access to their records

Recommended export formats:

```text
CSV
Excel
JSON
PDF reports
```

---

## 2.3 Analytics over decoration

Every graph should answer a question.

Examples:

| Visual | Question |
|---|---|
| KPI Card | What is happening now? |
| Line chart | Is this increasing or decreasing? |
| Donut | Where is my money going? |
| Variance chart | What caused the change? |
| Heatmap | When do I spend the most? |
| Cumulative spending | Am I spending faster than usual? |
| Budget pacing | Am I likely to exceed my budget? |
| Forecast | Where may I end the month? |
| Transaction table | Which transactions created this result? |

Avoid adding graphs only because they look attractive.

---

## 2.4 Progressive complexity

A new user should be able to do this immediately:

```text
Open app
→ Add transaction
→ See dashboard update
```

Advanced analysis should be available without making basic usage complicated.

---

## 2.5 App code and user data must be separate

```text
APPLICATION
MyFinance.exe

USER DATA
finance.db
settings.json
attachments/
backups/
```

Updating or reinstalling the application must not delete user financial data.

---

# 3. Recommended Technology Stack

## 3.1 Desktop shell

```text
Python
+
pywebview
```

Reason:

- native Windows application window
- can package into `.exe`
- frontend remains flexible
- Python is excellent for analytics
- no browser needs to be opened manually

---

## 3.2 Frontend

Recommended:

```text
React
Vite
TypeScript
Tailwind CSS
ECharts
Lucide Icons
```

### Responsibilities

React:
- application interface
- pages
- components
- filters
- modals
- navigation

Tailwind:
- layout
- spacing
- responsive design
- dark theme
- cards
- states

ECharts:
- line charts
- donut charts
- heatmaps
- stacked bars
- variance visuals
- tooltips
- cross-filtering

Lucide:
- sidebar icons
- action icons
- UI consistency

---

## 3.3 Backend

Recommended:

```text
Python
SQLite
Pandas
```

Python responsibilities:

- transaction CRUD
- calculations
- analytics
- database access
- backup/restore
- import/export
- report generation
- recurring transaction detection
- anomaly detection
- forecasting

---

# 4. High-Level Architecture

```text
┌─────────────────────────────────────────────────────┐
│                    WINDOWS APP                      │
│                                                     │
│  ┌───────────────────────────────────────────────┐  │
│  │               React Frontend                  │  │
│  │                                               │  │
│  │ Dashboard                                     │  │
│  │ Analytics                                     │  │
│  │ Calendar                                      │  │
│  │ Transactions                                  │  │
│  │ Budget                                        │  │
│  │ Reports                                       │  │
│  │ Accounts                                      │  │
│  │ Settings                                      │  │
│  └───────────────────────┬───────────────────────┘  │
│                          │                          │
│                       WebView API                   │
│                          │                          │
│  ┌───────────────────────▼───────────────────────┐  │
│  │                 Python Core                   │  │
│  │                                               │  │
│  │ Transaction Service                           │  │
│  │ Analytics Engine                              │  │
│  │ Budget Engine                                 │  │
│  │ Backup Service                                │  │
│  │ Report Service                                │  │
│  │ Import/Export Service                         │  │
│  └───────────────────────┬───────────────────────┘  │
│                          │                          │
│                    ┌─────▼─────┐                    │
│                    │  SQLite   │                    │
│                    │finance.db │                    │
│                    └───────────┘                    │
└─────────────────────────────────────────────────────┘
```

---

# 5. Proposed Navigation Structure

```text
Overview
Analytics
Calendar
Transactions
Budget
Accounts
Reports
Insights
Settings

+ Add Transaction
```

Possible simplification for Version 1:

```text
Dashboard
Calendar
Transactions
Budget
Reports
Settings
```

Accounts and Insights can become separate pages later.

---

# 6. Design Direction

## 6.1 Overall aesthetic

Target:

```text
Dark personal-finance BI dashboard
+
Windows desktop productivity application
+
modern banking application
```

Characteristics:

- dark navy background
- slightly lighter cards
- subtle borders
- purple / blue / cyan accent gradients
- high contrast numbers
- muted secondary text
- rounded cards
- smooth transitions
- clean charts
- large spacing
- dense information without visual clutter

---

## 6.2 Suggested design tokens

Initial palette only — can be refined later.

```css
--background: #0E1324;
--sidebar: #12182A;
--card: #171E33;
--card-hover: #1D2540;
--border: rgba(255,255,255,0.07);

--text-primary: #F5F7FB;
--text-secondary: #929CB6;
--text-muted: #66708A;

--purple: #C85AF4;
--blue: #5B8CFF;
--cyan: #27D5D5;

--positive: #4DD5A5;
--negative: #FF6B8A;
--warning: #FFCC66;
```

---

## 6.3 Typography hierarchy

Example:

```text
Page title          28–32px
KPI value           28–36px
Card title          12–14px
Body                14–15px
Secondary metadata  12–13px
```

Use one modern sans-serif font throughout.

---

# 7. Core Data Model

The database needs to support both basic tracking and future analytics.

---

## 7.1 Transactions

```text
transactions
```

Suggested columns:

```text
id
account_id
category_id
merchant_id
transaction_type
amount
transaction_date
transaction_time
description
note
is_recurring
recurring_rule_id
payment_method
essentiality
created_at
updated_at
```

### transaction_type

```text
income
expense
transfer
refund
adjustment
```

---

## 7.2 Categories

```text
categories
```

Fields:

```text
id
name
type
parent_category_id
icon
color
is_archived
created_at
```

Possible structure:

```text
Food
├── Groceries
├── Restaurant
├── Coffee
└── Delivery

Transport
├── Public Transport
├── Uber/Taxi
├── Fuel
└── Parking
```

---

## 7.3 Accounts

```text
accounts
```

Fields:

```text
id
name
account_type
institution
opening_balance
currency
is_archived
created_at
```

Possible types:

```text
Everyday
Savings
Cash
Credit Card
Investment
Other
```

---

## 7.4 Merchants

```text
merchants
```

Fields:

```text
id
name
default_category_id
merchant_pattern
created_at
```

This supports automatic categorisation later.

Example:

```text
merchant_pattern = "WOOLWORTHS"
default_category = Groceries
```

---

## 7.5 Budgets

```text
budgets
```

Fields:

```text
id
category_id
amount
period_type
start_date
end_date
rollover
created_at
```

---

## 7.6 Recurring Rules

```text
recurring_rules
```

Fields:

```text
id
name
transaction_type
amount
category_id
account_id
frequency
next_due_date
active
```

Examples:

```text
Salary → fortnightly
Rent → monthly
Netflix → monthly
Phone bill → monthly
```

---

## 7.7 Monthly Summary Cache

Optional optimization:

```text
monthly_summary
```

Fields:

```text
month
category_id
income_total
expense_total
transaction_count
average_transaction
largest_transaction
```

Raw transaction history remains the source of truth.

The summary table only improves dashboard loading speed.

---

# 8. Data Storage Strategy

Recommended location:

```text
%LOCALAPPDATA%\MyFinance\
```

Structure:

```text
MyFinance/
│
├── finance.db
├── settings.json
│
├── backups/
│   ├── daily/
│   ├── weekly/
│   └── monthly/
│
├── attachments/
│   ├── 2026/
│   ├── 2027/
│   └── ...
│
├── exports/
│
└── logs/
```

---

# 9. Backup Strategy

## 9.1 Manual backup

Settings:

```text
Data & Storage
→ Backup Now
```

Output:

```text
MyFinance_2026-09-04.financebackup
```

The backup file should contain:

```text
finance.db
settings.json
attachments metadata
app data version
```

---

## 9.2 Automatic backup

Options:

```text
Daily
Weekly
Monthly
Disabled
```

Suggested retention:

```text
Daily backups    → 14
Weekly backups   → 8
Monthly backups  → 12
```

Old backups can be deleted automatically.

Raw financial records should not be automatically deleted.

---

## 9.3 Restore workflow

```text
Open MyFinance
→ Settings
→ Data & Storage
→ Restore Backup
→ Select .financebackup
→ Validate backup
→ Create safety backup of current data
→ Restore
→ Rebuild analytics cache
→ Restart dashboard
```

---

# 10. Migration to Another Computer

Goal:

```text
Old computer
→ Create backup
→ Copy backup
→ Install app on new computer
→ Restore
→ Continue normally
```

Optional later:

```text
Backup folder = OneDrive
```

The app remains offline-first.

OneDrive simply copies the encrypted backup file.

---

# 11. Storage Growth Strategy

Financial transaction data is lightweight.

Example:

```text
20 transactions/day
× 365 days
= 7,300 transactions/year

10 years
≈ 73,000 transactions
```

SQLite can handle this comfortably.

Therefore:

> Do not delete historical transactions just to reduce database size.

Historical data is valuable because analytics improves over time.

---

## 11.1 What may actually consume storage

Images and files.

Examples:

```text
receipts
invoices
PDF statements
screenshots
```

Do not store these binary files directly inside SQLite.

Instead:

```text
attachments/
2026/
09/
receipt_000128.webp
```

The database stores only the path.

---

# 12. App Versioning and Database Migration

Example:

```text
App v1
Database schema v1
```

Later:

```text
App v2
Database schema v4
```

Migration system:

```text
schema v1
→ migration_002
→ schema v2
→ migration_003
→ schema v3
...
```

Never destroy the previous user database during an app update.

Before migration:

```text
automatic safety backup
```

---

# 13. Phase 0 — Planning and Product Specification

## Goal

Define the app before writing implementation code.

## Tasks

- [ ] Confirm product name
- [ ] Confirm navigation
- [ ] Confirm visual direction
- [ ] Confirm account model
- [ ] Confirm category structure
- [ ] Confirm transaction fields
- [ ] Confirm dashboard KPIs
- [ ] Confirm analytics requirements
- [ ] Confirm calendar behaviour
- [ ] Confirm budget logic
- [ ] Confirm backup strategy
- [ ] Confirm report structure
- [ ] Define Version 1 scope
- [ ] Define features intentionally postponed

## Deliverable

```text
Product Requirements Document
+
Wireframes
+
Database draft
```

---

# 14. Phase 1 — Development Environment

## Goal

Create the base project and make Python + WebView + React communicate.

## Structure

```text
myfinance/
│
├── backend/
│   ├── main.py
│   ├── api/
│   ├── services/
│   ├── analytics/
│   ├── database/
│   └── models/
│
├── frontend/
│   ├── src/
│   ├── components/
│   ├── pages/
│   ├── charts/
│   └── styles/
│
├── tests/
├── scripts/
└── README.md
```

## Tasks

- [ ] Install Python
- [ ] Create virtual environment
- [ ] Install pywebview
- [ ] Create React/Vite project
- [ ] Add TypeScript
- [ ] Add Tailwind
- [ ] Add ECharts
- [ ] Add Lucide icons
- [ ] Create pywebview window
- [ ] Load React frontend
- [ ] Create basic Python ↔ JavaScript API call
- [ ] Package development app once

## Definition of Done

Clicking a React button successfully calls Python and returns a result to the interface.

---

# 15. Phase 2 — Design System and App Shell

## Goal

Build the visual foundation before feature development.

## Components

- [ ] Main app frame
- [ ] Frameless/window controls if desired
- [ ] Sidebar
- [ ] Page header
- [ ] Card component
- [ ] KPI card
- [ ] Button
- [ ] Icon button
- [ ] Dropdown
- [ ] Date selector
- [ ] Modal
- [ ] Drawer
- [ ] Tooltip
- [ ] Table
- [ ] Empty state
- [ ] Loading skeleton
- [ ] Toast notification
- [ ] Confirmation dialog

## Sidebar

```text
Logo

Overview
Analytics
Calendar
Transactions
Budget
Accounts
Reports
Insights

────────────

Settings

+ Add Transaction
```

## Definition of Done

The app can navigate between empty pages while maintaining the final visual style.

---

# 16. Phase 3 — SQLite Database Foundation

## Goal

Build reliable local storage.

## Tasks

- [ ] Create database connection layer
- [ ] Create schema
- [ ] Create migrations system
- [ ] Create transaction repository
- [ ] Create category repository
- [ ] Create account repository
- [ ] Create budget repository
- [ ] Add foreign keys
- [ ] Add indexes
- [ ] Add validation
- [ ] Add created/updated timestamps

Recommended indexes:

```text
transaction_date
category_id
account_id
merchant_id
transaction_type
```

## Definition of Done

The backend can create, read, update and delete transactions without using the UI.

---

# 17. Phase 4 — Transaction Engine

## Goal

Make recording financial activity fast and reliable.

## Add Transaction Modal

Fields:

```text
Type
Amount
Account
Category
Merchant/Description
Date
Time
Note
Essential / Discretionary
Recurring
```

Example:

```text
Expense

Amount
$52.40

Category
Groceries

Merchant
Woolworths

Account
CommBank Everyday

Date
04 Sep 2026
```

## Features

- [ ] Add transaction
- [ ] Edit transaction
- [ ] Delete transaction
- [ ] Duplicate transaction
- [ ] Search
- [ ] Sort
- [ ] Filter
- [ ] Multi-filter
- [ ] Pagination / virtual scrolling
- [ ] Quick add
- [ ] Keyboard shortcuts

Possible shortcut:

```text
Ctrl + N
→ Add Transaction
```

## Definition of Done

The app can function as a complete basic expense tracker.

---

# 18. Phase 5 — Overview Dashboard V1

## Goal

Provide a useful monthly financial summary.

## Global Filters

```text
Period
Account
Compare With
```

Default:

```text
Current Month
All Accounts
Previous Month
```

---

## KPI Cards

### Total Income

```text
$4,820
↑ 8.2% vs August
```

### Total Expense

```text
$2,940
↑ 14.1% vs August
```

### Net Cash Flow

```text
+$1,880
```

Formula:

```text
Income - Expenses
```

### Savings Rate

```text
39.0%
```

Possible formula:

```text
Net Cash Flow / Income × 100
```

---

## Dashboard Visuals

### Cash Flow Trend

Income and expense over the selected period.

### Expense Breakdown

Donut chart.

### Income Breakdown

Income sources.

### Daily Spending

Daily expense bars or area chart.

### Budget Status

Budget progress.

### Recent Transactions

Most recent entries.

## Definition of Done

Changing the selected month updates all dashboard components.

---

# 19. Phase 6 — Calendar

## Goal

Visualise money over time by day.

## Month View

Each day can show:

```text
4

+$1,250
-$86.40

3 transactions
```

---

## Calendar Modes

```text
Net Cash Flow
Expenses
Income
Transaction Count
```

---

## Heatmap

Cell intensity indicates spending.

Example:

```text
Low spending     ░
Medium spending  ▒
High spending    █
```

---

## Day Detail Panel

Click a date:

```text
Thursday, 4 September

Income
+$1,250

Expenses
-$86.40

Net
+$1,163.60

Transactions
────────────
Salary       +$1,250
Woolworths      -$52
Coffee            -$7
Train            -$27
```

---

## Interactions

- [ ] Click day → open detail
- [ ] Double-click day → add transaction with date prefilled
- [ ] Hover → summary tooltip
- [ ] Month navigation
- [ ] Today shortcut
- [ ] Filter by account
- [ ] Filter by category

---

# 20. Phase 7 — Analytics Engine V1

## Goal

Move from tracking to analysis.

Create backend analytics functions for:

```text
monthly totals
category totals
daily totals
weekday averages
monthly comparison
category variance
rolling average
transaction averages
top merchants
largest transactions
savings rate
```

---

## Example Analytics API

Conceptually:

```text
get_month_summary(month)
get_category_breakdown(month)
compare_months(current, previous)
get_spending_by_weekday(period)
get_top_merchants(period)
get_cumulative_spending(month)
```

---

# 21. Phase 8 — Analytics Page

## Goal

Give the user a BI-style exploration workspace.

## Top controls

```text
Metric
Expenses ▼

Period
Last 12 Months ▼

Group By
Month ▼

Breakdown
Category ▼
```

---

## Sections

### Spending Trend

```text
Monthly / weekly / daily
```

### Category Performance

```text
Category     Current     Previous     Change
Food         $620        $524         +18.3%
Shopping     $480        $366         +31.1%
Transport    $182        $264         -31.1%
```

### Spending by Weekday

```text
Mon
Tue
Wed
Thu
Fri
Sat
Sun
```

### Cumulative Spending

Compare current month with previous month.

### Merchant Analysis

Top merchants.

### Transaction Distribution

Possible buckets:

```text
<$10
$10–25
$25–50
$50–100
>$100
```

---

# 22. Phase 9 — Cross-Filtering

## Goal

Make charts interact like a BI tool.

Example:

```text
User clicks Food in donut
```

Active filter:

```text
Category: Food
```

Every compatible visual updates.

Then user clicks Friday:

```text
Category: Food
Weekday: Friday
```

Now dashboard answers:

```text
How do I spend on Food on Fridays?
```

## Tasks

- [ ] Global filter state
- [ ] Chart click handlers
- [ ] Filter chips
- [ ] Clear all filters
- [ ] Preserve selected period
- [ ] Synchronise table and charts

---

# 23. Phase 10 — “What Changed?” Analysis

## Goal

Explain *why* totals changed.

Example:

```text
Expenses increased by $363.

Contributors:

Shopping     +$142
Food          +$96
Travel        +$83
Bills         +$29
Transport     -$41
```

Possible chart:

```text
Waterfall / variance bar chart
```

## Drill-down

Click Shopping:

```text
Shopping increased $142.

Largest new or increased transactions:
Nike       $180
Uniqlo      $94
Amazon      $72
```

This is a major differentiating feature.

---

# 24. Phase 11 — Budget System

## Goal

Move from passive tracking to active financial control.

## Category Budget

Example:

```text
Food

Budget
$600

Spent
$420

Remaining
$180
```

---

## Budget Pacing

```text
Month completed:
47%

Budget consumed:
70%

Status:
Spending faster than planned
```

---

## Projection

Basic calculation:

```text
current spend
÷ elapsed days
× total days in month
```

Example:

```text
Projected month-end:
$742

Expected over budget:
+$142
```

---

## Budget States

```text
On Track
Watch
Likely Over Budget
Over Budget
```

---

# 25. Phase 12 — Reports

## Goal

Create formal financial summaries.

## Monthly Report

```text
SEPTEMBER 2026

Income
$4,820

Expenses
$2,940

Net
$1,880

Savings Rate
39%
```

Then:

```text
Expense breakdown
Income breakdown
Month comparison
Budget performance
Largest transactions
Highest spending day
Category changes
Insights
```

---

## Annual Report

```text
2026

Total Income
Total Expenses
Net Savings
Average Monthly Spend
Best Savings Month
Highest Spending Month
Top Categories
Category Trends
```

---

## Export

- [ ] PDF
- [ ] CSV
- [ ] Excel

---

# 26. Phase 13 — Spending Fingerprint

## Goal

Analyse personal spending behaviour.

Metrics:

```text
Highest spending weekday
Lowest spending weekday
Weekend vs weekday spending
Average transaction amount
Most frequent category
Largest category
Most common merchant
Discretionary spending share
Essential spending share
```

Example insight:

```text
36% of discretionary spending occurs on weekends.
```

---

# 27. Phase 14 — Fixed vs Variable Spending

Each category or transaction can carry analytical tags.

Examples:

```text
Rent
Fixed
Essential

Restaurant
Variable
Discretionary

Groceries
Variable
Essential
```

Analytics:

```text
Fixed expenses           42%
Variable expenses        58%

Essential spending       61%
Discretionary spending   39%
```

---

# 28. Phase 15 — Recurring Transaction Detection

## Goal

Automatically detect subscriptions and regular payments.

Example pattern:

```text
Netflix
$22.99

28 Jul
28 Aug
28 Sep
```

App suggests:

```text
Possible recurring transaction detected.
```

User chooses:

```text
Mark as recurring
Ignore
```

---

## Recurring Dashboard

```text
Rent       $600
Netflix     $23
Phone       $49
Gym         $30

Monthly recurring expenses
$702
```

---

# 29. Phase 16 — Insights Engine

## Goal

Automatically describe useful financial patterns.

No AI is required initially.

Rule-based examples:

```text
If category increase > 20%
→ "Food spending increased 24% compared with last month."
```

```text
If projected budget > budget
→ "Food is projected to exceed budget by $142."
```

```text
If spending < rolling average by 20%
→ "Transport spending is unusually low this month."
```

---

## Insight Groups

```text
Important
Trends
Warnings
Achievements
Anomalies
```

---

# 30. Phase 17 — Anomaly Detection

## Goal

Highlight unusual transactions or periods.

### Transaction anomaly

Example:

```text
Typical Food transaction:
$10–45

New transaction:
$284
```

Insight:

```text
Unusually large Food transaction.
```

---

## Category anomaly

Example:

```text
Shopping 6-month average:
$310

Current month:
$860
```

Insight:

```text
Shopping is 2.8× your 6-month average.
```

Initial detection can use:

```text
rolling averages
standard deviation
IQR
percentage deviation
```

No machine learning required for Version 1.

---

# 31. Phase 18 — Forecasting

## Goal

Estimate where the month may end.

Inputs:

```text
current spending
elapsed days
historical patterns
known recurring payments
scheduled income
budget
```

Outputs:

```text
Projected Income
Projected Expense
Projected Net Savings
Projected Savings Rate
Projected Category Spend
```

Example:

```text
September Forecast

Income
$4,900

Expenses
$3,180

Net Savings
$1,720
```

---

# 32. Phase 19 — CSV Bank Import

## Goal

Reduce manual data entry.

Flow:

```text
Import CSV
→ Detect columns
→ Preview
→ Detect duplicates
→ Categorise
→ Confirm
→ Import
```

Example preview:

```text
43 transactions detected

39 new
4 possible duplicates
```

---

## Auto Categorisation Rules

Example:

```text
Description contains "WOOLWORTHS"
→ Groceries

Description contains "UBER"
→ Transport
```

User correction:

```text
KFC → Food & Drink
```

App can ask:

```text
Always categorise transactions containing "KFC"
as Food & Drink?
```

---

# 33. Phase 20 — Search and Query Experience

Basic search:

```text
Woolworths
```

Return:

```text
46 transactions
Total spent
Average transaction
First transaction
Latest transaction
Most common category
```

Advanced search later:

```text
food september
shopping >100
weekend
uber august
```

---

# 34. Phase 21 — Accounts and Net Worth

Later-stage feature.

Accounts:

```text
CommBank Everyday
CommBank Savings
Cash
Credit Card
```

Net Worth:

```text
Assets
──────────
Everyday   $2,420
Savings    $8,200

Liabilities
──────────
Credit Card -$620

Net Worth
$10,000
```

Trend:

```text
Net worth by month
```

---

# 35. Phase 22 — Data Health & Storage Page

Settings:

```text
DATA & STORAGE
```

Display:

```text
Transactions        18,429
Date range           Jul 2026 – Sep 2030
Database size        34.8 MB
Attachments          472 MB
Backups              186 MB
Last backup          Today, 2:14 PM
Database health      Healthy
```

Actions:

```text
Backup Now
Restore Backup
Export Data
Optimise Database
Open Data Folder
```

---

# 36. Phase 23 — Database Maintenance

Do not automatically delete raw transactions.

Allowed cleanup:

```text
old cache
temporary imports
old logs
expired backups
unused thumbnails
```

SQLite maintenance:

```text
VACUUM
ANALYZE
index maintenance
integrity check
```

---

# 37. Phase 24 — Privacy & Security

Because financial data is sensitive.

Possible security features:

```text
App PIN
Auto-lock
Encrypted backup
Encrypted database
Sensitive-value hiding
```

Privacy mode:

```text
Balance
••••••

Income
••••••

Expenses
••••••
```

Useful when using the app in public.

---

# 38. Phase 25 — Keyboard and Power-User Features

Examples:

```text
Ctrl + N
Add transaction

Ctrl + F
Search

Ctrl + B
Backup

Ctrl + Shift + E
Export

Esc
Close modal
```

Possible command palette later:

```text
Ctrl + K
```

Then type:

```text
Add expense
Open calendar
Show August report
Backup data
```

---

# 39. Phase 26 — UI Polish

Focus areas:

- [ ] Page transitions
- [ ] Chart animation
- [ ] Count-up KPI animation
- [ ] Hover states
- [ ] Tooltips
- [ ] Loading skeletons
- [ ] Empty states
- [ ] Error states
- [ ] Smooth filtering
- [ ] Responsive resizing
- [ ] High-DPI Windows support
- [ ] Light animation without excessive movement

---

# 40. Phase 27 — Performance Optimisation

Potential bottlenecks:

```text
large transaction table
complex dashboard queries
many charts
long date range
large imports
```

Strategies:

```text
SQLite indexes
summary tables
query caching
frontend memoization
virtualized transaction table
lazy chart rendering
background analytics calculations
```

---

# 41. Phase 28 — Testing Strategy

## Unit tests

Test:

```text
income totals
expense totals
savings rate
budget projection
monthly comparison
recurring detection
anomaly logic
```

---

## Database tests

Test:

```text
create transaction
edit transaction
delete transaction
migration
backup
restore
duplicate detection
```

---

## UI tests

Test:

```text
filters
modal
calendar selection
cross-filtering
chart interaction
form validation
```

---

## Critical recovery tests

Must test:

```text
App crashes during write
Backup restore fails
Database migration interrupted
Invalid CSV imported
Duplicate transaction
Corrupted backup
```

---

# 42. Phase 29 — Packaging for Windows

Goal:

```text
MyFinance.exe
```

Tasks:

- [ ] Build React frontend
- [ ] Bundle static frontend
- [ ] Package Python backend
- [ ] Include dependencies
- [ ] Create app icon
- [ ] Create installer
- [ ] Create shortcuts
- [ ] Verify user data directory
- [ ] Test clean install
- [ ] Test update
- [ ] Test uninstall

Important:

```text
Uninstalling application code
must not automatically delete financial data.
```

---

# 43. Suggested Version Roadmap

## Version 0.1 — Foundation

```text
App shell
Sidebar
React + Python connection
SQLite
Basic theme
```

---

## Version 0.2 — Transaction Tracker

```text
Add transaction
Edit
Delete
Categories
Accounts
Transaction history
```

---

## Version 0.3 — Dashboard

```text
Income
Expense
Net
Savings rate
Cash flow
Expense donut
Recent transactions
```

---

## Version 0.4 — Calendar

```text
Monthly calendar
Daily income/expense
Heatmap
Day details
```

---

## Version 0.5 — Analytics

```text
Month comparison
Category trends
Weekday analysis
Cumulative spending
Top merchants
```

---

## Version 0.6 — Budget

```text
Category budgets
Budget progress
Budget pacing
Projection
```

---

## Version 0.7 — Reports

```text
Monthly review
Annual review
CSV export
PDF export
```

---

## Version 0.8 — Intelligence

```text
What Changed?
Insights
Recurring detection
Anomaly detection
```

---

## Version 0.9 — Data Management

```text
Backup
Restore
Migration
Storage health
CSV bank import
```

---

## Version 1.0 — Stable Personal Release

Requirements:

```text
Reliable database
Reliable backup/restore
Polished dashboard
Calendar
Analytics
Budget
Reports
Import/export
Installer
Recovery testing
```

---

# 44. MVP Scope

To avoid building too much at once, the first usable version should include only:

```text
1. Transactions
2. Categories
3. Accounts
4. Monthly dashboard
5. Calendar
6. Basic analytics
7. Backup
8. Export
```

Do **not** initially build:

```text
advanced forecasting
AI
complex machine learning
cloud sync
net worth
receipt OCR
bank API integration
```

These can wait.

---

# 45. Recommended Development Order

```text
01 Product spec
02 Wireframe
03 Design system
04 App shell
05 Database
06 Transaction CRUD
07 Transaction page
08 Dashboard KPIs
09 Dashboard charts
10 Calendar
11 Analytics engine
12 Analytics page
13 Budget
14 Reports
15 Backup / restore
16 Export
17 Insights
18 Recurring detection
19 CSV import
20 Security
21 Performance
22 Packaging
23 Testing
24 Version 1 release
```

---

# 46. Definition of Version 1 Success

Version 1 is successful if the user can:

```text
Open the app
→ Add income
→ Add expenses
→ Categorise them
→ See monthly totals
→ See category breakdown
→ View spending calendar
→ Compare with previous month
→ Understand what changed
→ See basic budget progress
→ Export data
→ Backup data
→ Move data to another computer
→ Restore everything successfully
```

---

# 47. Long-Term Product Vision

Eventually the app should answer five levels of financial questions.

## Level 1 — What happened?

```text
I spent $2,940 this month.
```

## Level 2 — Where?

```text
$620 was Food.
$480 was Shopping.
```

## Level 3 — Why did it change?

```text
Expenses increased mainly because Shopping rose by $142.
```

## Level 4 — Is this unusual?

```text
Shopping is 41% above the 6-month average.
```

## Level 5 — What happens next?

```text
At the current pace, you may spend $3,180 this month
and save approximately $1,720.
```

This progression should remain the central product philosophy.

---

# 48. Proposed Final Product Identity

Possible names:

```text
FinScope
LedgerLab
MoneyLens
FinSight
CashScope
MyFinance Analytics
Personal Ledger
FlowLens
```

Possible tagline:

> **Understand your money, not just your transactions.**

Alternative:

> **A private personal finance dashboard that explains where your money goes and how your behaviour changes over time.**

---

# 49. Immediate Next Steps

Before coding, complete these design decisions:

- [ ] Choose product name
- [ ] Choose exact sidebar pages
- [ ] Define account types
- [ ] Define default categories
- [ ] Define transaction fields
- [ ] Define Dashboard layout
- [ ] Define Analytics layout
- [ ] Define Calendar design
- [ ] Define Monthly Report design
- [ ] Choose final dark-theme palette
- [ ] Draw wireframes
- [ ] Finalise Version 0.1 scope

Then development can begin.

---

# 50. Recommended First Sprint

## Sprint Goal

Create a visual prototype with fake data.

### Sprint tasks

- [ ] Create desktop shell
- [ ] Build sidebar
- [ ] Build top filter bar
- [ ] Build four KPI cards
- [ ] Create cash-flow chart
- [ ] Create category donut
- [ ] Create daily spending chart
- [ ] Create recent transactions table
- [ ] Build Add Transaction modal
- [ ] Use mock JSON data only

### Why start with mock data?

Because it allows the UI and product logic to be refined before database complexity is introduced.

After the interface feels right:

```text
Mock Data
    ↓
SQLite
    ↓
Real Transactions
```

This avoids spending time building backend logic for an interface that may later be redesigned.

---

# Final Roadmap Summary

```text
PRODUCT DESIGN
      ↓
UI PROTOTYPE
      ↓
DATABASE
      ↓
TRANSACTIONS
      ↓
DASHBOARD
      ↓
CALENDAR
      ↓
ANALYTICS
      ↓
BUDGET
      ↓
REPORTS
      ↓
BACKUP / RESTORE
      ↓
INSIGHTS
      ↓
IMPORT / EXPORT
      ↓
SECURITY
      ↓
PERFORMANCE
      ↓
WINDOWS PACKAGING
      ↓
VERSION 1.0
```

The most important rule throughout development:

> **Do not build features merely because they are possible. Build each feature because it helps the user understand, explain, predict, or act on their personal financial data.**
