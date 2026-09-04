# FinScope — Personal Finance Analytics App

> **Understand your money, not just your transactions.**
> A private, offline-first personal finance BI and analytics application for Windows.

FinScope goes beyond basic expense recording into a lightweight personal finance business intelligence (BI) system. It answers:
- **What happened?** (Totals, cash flow, category breakdowns)
- **Why did it change?** ("What Changed?" month-over-month variance analysis)
- **When do I spend?** (Spending by weekday, daily heatmap calendar)
- **Am I on track?** (Budget pacing, % consumed vs % elapsed, projections)
- **What action to take?** (Over-budget warnings, discretionary limits)

---

## 🚀 Key Features

### 1. Overview Dashboard
- **4 Core KPI Cards**: Total Income, Total Expense, Net Cash Flow, Savings Rate with vs. previous month deltas.
- **Cash Flow Trend**: Smooth daily area/line chart comparing Income and Expense.
- **Expense Breakdown**: Interactive Donut chart by category.
- **Daily Spending**: Intensity bars for each day of the month.
- **Recent Activity**: Instant overview with status tags and amounts.

### 2. Transactions Workspace
- Full CRUD operations: **Add, Edit, Duplicate, Delete**.
- Real-time search by merchant, description, or notes.
- Multi-filters: Category, Account, Type (Expense/Income/Transfer), Essentiality (Essential/Discretionary/Savings).
- Fast keyboard shortcut: `Ctrl + N` to quickly open the Add Transaction modal.

### 3. Financial Calendar Matrix
- Monthly 7-day grid showing daily income & expense sums.
- Spend heat levels (highlights high-spend days).
- Double-click any day to prefill a transaction for that date.
- **Slide-out Day Details Drawer**: Click any day to see all transactions for that date with quick actions.

### 4. BI Analytics Workspace
- **"What Changed?" Variance Analysis**: Visualizes which categories contributed most to expense increases/decreases vs. previous month.
- **Spending by Weekday**: Mon–Sun average expense distributions.
- **Cumulative Pacing Curve**: Compare day-by-day spending pace against the previous month.
- **Top Merchants Leaderboard**: Identifies top spending destinations.
- **Essential vs. Discretionary Breakdown**: 50/30/20 rule tracker.

### 5. Budget System
- Set monthly limits per category.
- **Budget Pacing**: Tracks % of month elapsed vs. % of budget consumed.
- Automatic health badges: `On Track`, `Spending Fast`, `Over Budget`.
- Month-end projected spend calculation.

### 6. Reports & Export
- Executive **Monthly Financial Statement** view.
- 1-click **Export to CSV** for spreadsheets.
- **Print / PDF** statement export.

### 7. Data & Storage Management
- 100% offline SQLite database (`data/finance.db`).
- **Backup Now**: Creates portable `.financebackup` archive.
- **Restore Backup**: Restores previous backups with an automatic safety snapshot.
- **Privacy Mode**: Eye icon toggle in topbar masks currency values with blur when in public.
- **Demo Data Seeder**: Instant 4-month realistic dataset for exploration.

---

## 🛠️ Requirements & Setup

- **Operating System**: Windows 10 / 11
- **Runtime**: Python 3.10+ (tested and verified on Python 3.14)
- **Web Engine**: Microsoft Edge WebView2 (pre-installed on modern Windows)

### Quick Start

Simply run:
```bat
run.bat
```

Or run via Python:
```bash
# Launch as native Windows desktop window:
python app/main.py

# Or launch in your preferred web browser:
python app/main.py --browser
```

---

## 📁 Architecture & File Structure

```text
FINANCE/
├── app/
│   ├── backend/
│   │   ├── config.py                 # Data & path configuration
│   │   ├── database/
│   │   │   ├── connection.py         # SQLite connection manager & WAL mode
│   │   │   └── schema.sql            # Normalized schema with performance indexes
│   │   ├── repositories/             # Data access layer (accounts, categories, tx, budgets)
│   │   ├── services/                 # Analytics, budget pacing, backups, demo seeder
│   │   ├── api/
│   │   │   └── handler.py            # Unified API bridge for PyWebView & HTTP
│   │   └── server.py                 # Local server with automatic port fallback
│   ├── frontend/
│   │   ├── index.html                # App shell
│   │   ├── assets/
│   │   │   ├── css/                  # Theme tokens, layouts, components
│   │   │   ├── js/                   # Router, state, modals, page controllers
│   │   │   └── vendor/               # Offline ECharts 5.5 & Lucide icons
│   └── main.py                       # App entrypoint (WebView2 & Browser launcher)
├── data/                             # User data directory (finance.db, backups, exports)
├── tests/                            # Automated unit and HTTP tests
├── requirements.txt
├── run.bat                           # 1-click launcher
└── README.md
```
