# FinScope ANALYTICS V2 — Deep Technical Roadmap

> **Document type:** Technical implementation roadmap  
> **Target:** FinScope Analytics V2  
> **Primary objective:** Convert the current Analytics beta into a reliable, explainable, period-consistent, testable personal-finance intelligence layer.
>
> **Core rule:** Analytics V2 must prioritise **correct temporal context, financial semantics, reconciliation, and traceability** before adding more charts or more advanced models.

---

# 1. Executive Summary

FinScope already has a strong Analytics foundation:

```text
analytics/
├── semantics
├── aggregates
├── rolling
├── changes
├── fingerprint
├── anomalies
├── forecasting
├── backtesting
├── insight_rules
├── insight_ranker
└── models
```

The V2 effort should **not** rewrite this architecture.

Instead, V2 should harden the current implementation around five risks:

```text
1. TIME CONTEXT
2. FINANCIAL SEMANTICS
3. RECONCILIATION
4. DATA SUFFICIENCY
5. FRONTEND/BACKEND CONTRACT CONSISTENCY
```

The most important V2 outcome is:

> The same selected month, account scope, category scope, and transaction semantics must produce consistent results across every Analytics module.

---

# 2. Main Problems V2 Must Solve

Current Analytics risks can be grouped into:

```text
A. API integration gaps
B. Selected-period inconsistency
C. Partial-period comparison errors
D. Refund decomposition ambiguity
E. Weekday metric definition mismatch
F. Missing zero-month handling
G. Forecast simplifications
H. Insight memory / novelty not yet persistent
I. Fingerprint insufficient-data overconfidence
J. Backtesting not yet evaluating the actual hybrid forecast
```

---

# 3. V2 Design Philosophy

Analytics V2 should follow this pipeline:

```text
TRANSACTIONS
    ↓
CANONICAL FINANCIAL SEMANTICS
    ↓
CANONICAL PERIOD CONTEXT
    ↓
CANONICAL AGGREGATION
    ↓
ROLLING / CHANGE / FINGERPRINT
    ↓
ANOMALY / FORECAST
    ↓
INSIGHT CANDIDATES
    ↓
RANK + DEDUP + NOVELTY
    ↓
USER-FACING ANALYTICS
```

Every module should consume the same canonical inputs.

---

# 4. Non-Negotiable V2 Invariants

These are rules that must always hold.

## 4.1 Scope invariance

If user selects:

```text
Month = 2026-08
Account = CommBank
Category = Food
```

then:

```text
Rolling
What Changed
Fingerprint
Anomalies
Forecast
Insights
```

must all use:

```text
as_of_month = 2026-08
account_id = CommBank
category_id = Food
```

unless the module explicitly documents otherwise.

---

## 4.2 Financial reconciliation invariance

For any period:

```text
Net Spending
=
Gross Expense
-
Refunds
```

and:

```text
Net Cash Flow
=
Cash In
-
Cash Out
```

Transfers must not inflate income or expense.

---

## 4.3 Change decomposition invariance

For a category:

```text
Net Spend Delta
=
Frequency Effect
+
Average Ticket Effect
-
Refund Effect
```

All components must reconcile exactly after integer rounding.

---

## 4.4 Calendar continuity invariance

A missing month in history means:

```text
0
```

not:

```text
month removed from time series
```

Example:

```text
Jan = 500
Feb = 0
Mar = 600
```

must remain three periods.

---

## 4.5 Partial period invariance

If today is:

```text
04 Sep 2026
```

and user compares current month with previous month:

```text
Sep 1–4
vs
Aug 1–4
```

not:

```text
Sep 1–4
vs
Aug 1–31
```

unless user explicitly chooses full-period comparison.

---

# 5. V2 Module Architecture

Recommended:

```text
app/backend/analytics/
│
├── context.py
├── semantics.py
├── aggregates.py
├── period_series.py
├── reconciliation.py
│
├── rolling.py
├── changes.py
├── fingerprint.py
├── anomalies.py
├── forecasting.py
├── backtesting.py
│
├── insight_rules.py
├── insight_ranker.py
├── insight_history.py
│
├── models.py
└── validation.py
```

New recommended modules:

```text
context.py
period_series.py
reconciliation.py
insight_history.py
```

---

# 6. Analytics Context Object

Create one shared context model.

Recommended:

```python
@dataclass(frozen=True)
class AnalyticsContext:
    start_date: date
    end_date: date
    as_of_month: str
    account_id: int | None
    category_id: int | None
    merchant_id: int | None
    include_pending: bool
    comparison_mode: str
    comparison_start: date | None
    comparison_end: date | None
```

---

# 7. Comparison Modes

Supported:

```text
previous_period
previous_month_matched
previous_month_full
previous_year_same_period
custom
```

Default for current month:

```text
previous_month_matched
```

Default for historical completed month:

```text
previous_month_full
```

---

# 8. Backend Owns Time Semantics

Frontend should not be responsible for deciding:

```text
max_day
```

or partial-period comparison rules.

Frontend sends:

```text
selected month
selected account
selected category
comparison mode
```

Backend derives exact dates.

Reason:

```text
multiple frontend callers
future API clients
reports
tests
```

must all produce the same answer.

---

# 9. Current-Month Detection

Pseudo-logic:

```python
def resolve_period(selected_month, today):
    if selected_month == today.strftime("%Y-%m"):
        start = first_day(selected_month)
        end = today
        completed = False
    else:
        start = first_day(selected_month)
        end = last_day(selected_month)
        completed = True
```

---

# 10. Matched Comparison Resolver

Example:

```text
Current:
2026-09-01 → 2026-09-04

Previous:
2026-08-01 → 2026-08-04
```

Handle month length safely:

```text
31 Jan
vs
28 Feb
```

Use:

```text
min(current_day, last_day(previous_month))
```

---

# 11. API Contract V2

All major Analytics endpoints should accept a standard scope.

Recommended query fields:

```text
month
account_id
category_id
merchant_id
comparison_mode
```

Avoid endpoint-specific ad hoc names unless necessary.

---

# 12. Recommended Analytics Endpoints

```text
GET /analytics/overview
GET /analytics/rolling
GET /analytics/changes
GET /analytics/fingerprint
GET /analytics/anomalies
GET /analytics/forecast
GET /analytics/insights
GET /analytics/backtest
GET /analytics/normal-range
```

---

# 13. Frontend API Bridge

`api.js` must expose all V2 methods.

Example:

```javascript
getRollingMetrics(params)
getWhatChanged(params)
getSpendingFingerprint(params)
getAnomalies(params)
getForecast(params)
getRankedInsights(params)
getBacktestEvaluation(params)
```

---

# 14. API Integration Test

Add a test that verifies:

```text
every frontend Analytics API method
maps to a valid backend route
```

Goal:

Prevent:

```text
api.getWhatChanged is not a function
```

after backend feature additions.

---

# 15. Canonical Semantics

Create one canonical row transformation.

Example output per transaction:

```python
SemanticTransaction(
    amount_minor,
    income_minor,
    gross_expense_minor,
    refund_minor,
    cash_in_minor,
    cash_out_minor,
    net_spending_minor,
    transfer_effect_minor
)
```

---

# 16. Semantics Table

| Type | Income | Gross Expense | Refund | Cash In | Cash Out | Net Spend |
|---|---:|---:|---:|---:|---:|---:|
| Income | + | 0 | 0 | + | 0 | 0 |
| Expense | 0 | + | 0 | 0 | + | + |
| Refund | 0 | 0 | + | + | 0 | − |
| Transfer In | 0 | 0 | 0 | + | 0 | 0 |
| Transfer Out | 0 | 0 | 0 | 0 | + | 0 |
| Adjustment | explicit | explicit | explicit | explicit | explicit | explicit |

---

# 17. Reconciliation Service

Create:

```python
reconciliation.py
```

Functions:

```text
reconcile_period_totals()
reconcile_category_totals()
reconcile_change_decomposition()
reconcile_forecast_components()
```

---

# 18. Reconciliation Result

```python
@dataclass
class ReconciliationResult:
    expected_minor: int
    actual_minor: int
    difference_minor: int
    passed: bool
```

During development/tests:

```text
difference must equal 0
```

or known integer rounding tolerance.

---

# 19. Zero-Filled Period Series

Create reusable helper:

```python
calendar_month_series(
    start_month,
    end_month,
    raw_values
)
```

Input:

```text
Jan 500
Mar 600
```

Output:

```text
Jan 500
Feb 0
Mar 600
```

---

# 20. Zero-Fill Applies To

Use for:

```text
Rolling analytics
Fingerprint persistence
Monthly anomaly detection
Forecast training
Backtesting
Savings trends
Category trends
```

---

# 21. Distinguish Zero From Missing Data

Important:

```text
0 spending
```

is not always the same as:

```text
no data coverage
```

Recommended period metadata:

```python
PeriodValue(
    period="2026-02",
    value_minor=0,
    has_transactions=False,
    coverage="complete"
)
```

---

# 22. Data Coverage Metadata

Potential statuses:

```text
complete
partial
unknown
```

Current month:

```text
partial
```

Historical imported month:

```text
complete
```

Month before user started using app:

```text
unknown
```

This distinction matters for rolling and fingerprint.

---

# 23. Rolling Analytics V2

## Goal

Rolling metrics must be:

```text
scope-aware
period-aware
zero-aware
coverage-aware
```

---

# 24. Rolling API Inputs

```text
as_of_month
window
metric
account_id
category_id
```

Example:

```text
as_of_month = 2026-08
```

means:

```text
current = August
historical baseline ends July
```

---

# 25. Current vs Baseline

Do not include current period in baseline unless explicitly intended.

Recommended:

```text
current_value = selected month
baseline = periods before selected month
```

---

# 26. Rolling Metrics

Implement:

```text
3M mean
3M median
6M mean
6M median
12M mean
12M median
rolling MAD
EWMA
trend slope
```

---

# 27. History Sufficiency

Return:

```text
available_periods
required_periods
sufficient
```

Example:

```json
{
  "mean_6": null,
  "available_periods": 3,
  "required_periods": 6,
  "sufficient": false
}
```

Do not silently compute a "6M average" from 3 months.

---

# 28. Partial Current Month Handling

For current month:

Do not compare raw partial current month to full historical monthly means without context.

Support two metric modes:

```text
period_total
pace_adjusted
```

Example:

```text
Sep 1–4 spend
$500
```

against:

```text
historical day 1–4 baseline
```

or forecasted full-month baseline.

---

# 29. Rolling UI Labels

Use:

```text
This month to date
```

when partial.

Avoid:

```text
This month
```

if user may interpret it as completed.

---

# 30. What Changed V2.1

## Goal

Reconcile:

```text
Net Spending Delta
```

into meaningful behavioural causes.

---

# 31. Change Hierarchy

```text
TOTAL CHANGE
    ↓
CATEGORY
    ↓
MERCHANT
    ↓
BEHAVIOURAL DRIVER
    ↓
TRANSACTIONS
```

---

# 32. Category Contribution

For each category:

```text
current net spend
previous net spend
delta
share of total increase
```

---

# 33. Merchant Drill-Down

Within selected category:

```text
merchant current
merchant previous
delta
share of category change
```

---

# 34. Merchant Classification

Tag merchant changes:

```text
NEW_MERCHANT
RETURNED_MERCHANT
MORE_FREQUENT
HIGHER_TICKET
LOWER_TICKET
LESS_FREQUENT
REFUND_CHANGE
ONE_OFF
```

---

# 35. Frequency/Ticket/Refund Decomposition

Use **gross purchases** for purchase behaviour.

Definitions:

```text
Gross Spend
=
sum(expense transactions)
```

```text
Refund Total
=
sum(refund transactions)
```

```text
Net Spend
=
Gross Spend - Refund Total
```

---

# 36. Decomposition Formula

Let:

```text
N0 = previous gross expense count
N1 = current gross expense count

A0 = previous gross average ticket
A1 = current gross average ticket

R0 = previous refunds
R1 = current refunds
```

Then:

```text
Frequency Effect =
(N1 - N0) * (A0 + A1) / 2
```

```text
Ticket Effect =
(A1 - A0) * (N0 + N1) / 2
```

```text
Refund Effect =
-(R1 - R0)
```

Reconciliation:

```text
Net Delta
=
Frequency Effect
+
Ticket Effect
+
Refund Effect
```

---

# 37. Integer Rounding Strategy

Because money uses integer minor units:

Decomposition may yield fractional minor units.

Recommended:

```text
calculate using Decimal
round component 1
round component 2
set final component = exact delta - previous components
```

This guarantees reconciliation.

---

# 38. Refund Example

Previous:

```text
10 purchases
$50 average
$0 refund
Net = $500
```

Current:

```text
10 purchases
$50 average
$100 refund
Net = $400
```

Output:

```text
Frequency Effect    $0
Ticket Effect       $0
Refund Effect    -$100
──────────────────────
Net Delta         -$100
```

---

# 39. Merchant Decomposition Example

```text
Food +$160

Restaurant A    +$82
Uber Eats       +$47
Coffee          +$31
```

Click Restaurant A:

```text
More frequent      +$40
Higher ticket      +$42
Refund effect       $0
```

---

# 40. Time Contribution

Calculate:

```text
weekday delta
weekend delta
```

and:

```text
Mon
Tue
Wed
Thu
Fri
Sat
Sun
```

contribution.

---

# 41. What Changed Reconciliation Tests

Must verify:

```text
sum(category deltas) = total delta
sum(merchant deltas) = category delta
frequency + ticket + refund = category delta
```

for every test fixture.

---

# 42. Weekday Metrics V2

Current ambiguity must be removed.

Define at least two separate metrics:

```text
Average Transaction Size by Weekday
Average Daily Spend by Weekday
```

Do not use one label for the other.

---

# 43. Average Transaction Size by Weekday

Formula:

```text
sum(transaction amounts on Monday)
/
number of Monday transactions
```

---

# 44. Average Daily Spend by Weekday

Step 1:

```text
aggregate spending by calendar date
```

Step 2:

```text
group daily totals by weekday
```

Step 3:

```text
average daily totals
```

---

# 45. Example

Monday:

```text
Date A:
$10 + $20 + $30 = $60

Date B:
$40 + $20 = $60
```

Then:

```text
Average transaction size
= $24
```

while:

```text
Average Monday daily spend
= $60
```

Both are valid but different.

---

# 46. Fingerprint V2

Fingerprint should represent:

```text
descriptive behaviour
```

not psychology.

---

# 47. Fingerprint Scope

Inputs:

```text
end_month
months_window
account_id
category_id
```

Example:

```text
end_month = 2026-08
window = 6
```

must analyse:

```text
Mar–Aug
```

not latest 6 months globally.

---

# 48. Fingerprint Metrics

Recommended:

```text
median transaction
90th percentile transaction
robust variability
weekend concentration
recurring share
essential share
discretionary share
category diversity
category concentration
merchant concentration
burstiness
category persistence
most active weekday
most variable category
most stable category
```

---

# 49. Insufficient Data Policy

Never output fake certainty.

Bad:

```text
Category Stability = 100%
```

with 1 month.

Good:

```text
Category Stability
Not enough history yet
```

---

# 50. Availability Flags

Return per metric:

```text
value
available
sample_size
reason
```

Example:

```json
{
  "persistence": {
    "value": null,
    "available": false,
    "sample_size": 1,
    "reason": "requires at least 3 months"
  }
}
```

---

# 51. Most Variable/Stable Category

Do not return default category names.

If insufficient:

```text
null
```

Frontend:

```text
Not enough data
```

---

# 52. Category Persistence

Use zero-filled monthly vectors.

Important:

```text
inactive category
```

must be represented as:

```text
0
```

within period vector.

---

# 53. Anomaly Detection V2

Anomaly should be:

```text
scope-aware
context-aware
baseline-aware
explainable
```

---

# 54. Transaction Anomaly Baseline Hierarchy

```text
merchant + category
↓
merchant
↓
category
↓
overall comparable transactions
```

Use fallback only when sample insufficient.

---

# 55. Robust Score

Use:

```text
median
MAD
robust z-like score
```

Threshold initially configurable:

```text
3.5
```

---

# 56. Minimum Samples

Suggested defaults:

```text
merchant baseline >= 5
category baseline >= 10
overall baseline >= 20
```

Expose constants centrally.

---

# 57. Normal Range

Return:

```text
median
lower
upper
sample_size
confidence
```

UI:

```text
Typical range
$20 ───────── $58

Current
                ● $184
```

---

# 58. Recurring Anomaly

Treat separately:

```text
Netflix usually $22.99
Current $31.99
```

Insight:

```text
Recurring payment increased by $9.00
```

Do not compare it to all entertainment transactions.

---

# 59. Dismissed/Expected Anomalies

User feedback statuses:

```text
confirmed
expected
ignored
```

Ignored anomalies should reduce repeated notifications.

---

# 60. Forecasting V2

Forecast must be improved around:

```text
historical weekday denominator
category-specific projection
scope-consistent confidence
backtested performance
```

---

# 61. Forecast Architecture

```text
Actual To Date
+
Known Future Recurring
+
Expected Remaining Variable
+
Expected Irregular
-
Expected Refund
=
Projected Month-End
```

---

# 62. Historical Weekday Rate

Do not hardcode:

```text
12 occurrences
```

Calculate actual count.

Example:

```text
Historical window:
Jun–Aug

Mondays observed:
13

Monday total spend:
$1,040

Average Monday spend:
$80
```

---

# 63. Category Forecast

Do not allocate remaining variable spending only by current-month category share.

Use category-specific model:

```text
Category Expected Remaining
=
historical weekday rate
+
current month evidence
+
recent EWMA
+
known recurring
```

---

# 64. Zero-Current Category Example

Current:

```text
Travel = $0 by day 15
```

History:

```text
Travel averages $400/month
```

Forecast should not necessarily become:

```text
$0
```

Use historical evidence if category normally appears later.

---

# 65. Category Forecast Eligibility

Category forecast should choose method based on data:

```text
No history
→ current pace only

1–2 months
→ simple daily rate

3–5 months
→ 3M median / EWMA

6+ months
→ weekday-adjusted hybrid

12+ months
→ seasonal models eligible
```

---

# 66. Forecast Confidence Scope

If forecast is filtered to:

```text
account_id = Cash
```

then:

```text
history length
transaction count
forecast error
```

must all use Cash account scope only.

---

# 67. Forecast Range V2

Start simple:

```text
Expected
Lower
Upper
```

Range may derive from historical forecast residuals.

If insufficient backtest history:

```text
use conservative heuristic interval
```

but label:

```text
Early estimate
```

---

# 68. Forecast Component Reconciliation

Must satisfy:

```text
Expected Total
=
Actual To Date
+
Future Recurring
+
Remaining Variable
+
Irregular
-
Expected Refund
```

---

# 69. Backtesting V2

Backtesting must evaluate:

```text
FinScope Hybrid Forecast
```

not only baselines.

---

# 70. Required Models

```text
Previous Month
3M Mean
3M Median
EWMA
Seasonal Naive
FinScope Hybrid
ETS later
```

---

# 71. Rolling-Origin Evaluation

Example:

```text
Train through March
→ forecast April

Train through April
→ forecast May

Train through May
→ forecast June
```

No random split.

---

# 72. Metrics

Use:

```text
MAE
Median Absolute Error
WAPE
Bias
```

Optional:

```text
RMSE
```

---

# 73. Model Selection Rule

If:

```text
Hybrid MAE > simple baseline MAE
```

do not promote Hybrid as superior.

User does not need to see model complexity.

Use whichever performs better.

---

# 74. Forecast Performance Metadata

Store:

```text
method
period
prediction
actual
error
scope
```

Scope must include:

```text
account
category
metric
```

---

# 75. Insights Engine V2

Insights should become:

```text
context-aware
history-aware
novelty-aware
evidence-backed
```

---

# 76. Candidate Sources

Generate candidates from:

```text
What Changed
Rolling
Fingerprint
Anomalies
Budget
Forecast
Recurring
Cashflow
Data quality
```

---

# 77. Insight History

Create:

```text
insight_history
```

Fields:

```text
id
insight_key
entity_type
entity_id
first_seen
last_seen
times_shown
last_value_minor
last_rank
dismissed
created_at
updated_at
```

---

# 78. Insight Key

Example:

```text
category_increase:food
forecast_over_budget:total
merchant_anomaly:netflix
```

---

# 79. Novelty Score

Possible logic:

```text
new insight
→ 1.0

shown last month
→ 0.7

shown 4 consecutive months
→ 0.3

materially changed
→ increase novelty again
```

---

# 80. Material Change Reset

Example:

```text
Food high
+$40
```

shown repeatedly.

Later:

```text
Food high
+$400
```

Novelty should rise again.

---

# 81. Insight Confidence V2

Do not hardcode fixed confidence where possible.

Inputs:

```text
history length
sample size
baseline agreement
data coverage
backtest accuracy
```

---

# 82. Insight Rank Formula

Suggested:

```text
Score =
0.30 Impact
+ 0.20 Unusualness
+ 0.15 Confidence
+ 0.15 Actionability
+ 0.10 Novelty
+ 0.10 Relevance
```

Keep weights central/configurable.

---

# 83. Deduplication

Combine related facts.

Bad:

```text
Food +28% vs last month
Food +20% vs 3M mean
Food outside normal range
```

Good:

```text
Food is 28% higher than last month and above its six-month typical range.
```

---

# 84. Insight Evidence Contract

Each insight should include:

```text
current value
baseline
delta
confidence
source module
source metric
drilldown filter
```

---

# 85. Insights UI Placement

Primary:

```text
Overview dashboard
Top 3–5 insights
```

Secondary:

```text
Analytics → Insights
```

Do not require user to open a special tab to benefit from Insights.

---

# 86. Frontend V2 Integration

Recommended Analytics page:

```text
Overview
Changes
Patterns
Anomalies
Forecast
```

---

# 87. Overview Tab

Contains:

```text
KPI context
Top Insights
Rolling summary
Forecast summary
Normal range flags
```

---

# 88. Changes Tab

Contains:

```text
Waterfall
Category drivers
Merchant drill-down
Frequency effect
Ticket effect
Refund effect
Weekday/weekend contribution
```

---

# 89. Patterns Tab

Contains:

```text
Rolling trends
Fingerprint
Weekday daily spend
Category persistence
Merchant concentration
```

---

# 90. Anomalies Tab

Contains:

```text
Transaction anomalies
Category anomalies
Recurring changes
Normal ranges
Dismissed/expected controls
```

---

# 91. Forecast Tab

Contains:

```text
Expected month-end
Likely range
Budget comparison
Forecast components
Category projections
Forecast confidence
```

---

# 92. Selected-Month Banner

Always show analytical context.

Example:

```text
August 2026
All Accounts
Completed Month
Compared with July 2026
```

Current month:

```text
September 2026
Month-to-Date through Sep 4
Compared with Aug 1–4
```

---

# 93. Filter Chips

Example:

```text
Account: CommBank ×
Category: Food ×
Period: Sep 1–4 ×
```

All Analytics modules update together.

---

# 94. Cross-Filtering V2

Click:

```text
Food
```

on waterfall:

```text
Category = Food
```

Then:

```text
Fingerprint
Anomalies
Forecast
Transactions
```

should respect filter.

---

# 95. Drill-Down Contract

Recommended:

```python
DrilldownFilter(
    start_date,
    end_date,
    account_id,
    category_id,
    merchant_id,
    transaction_types
)
```

Pass directly to Transactions page.

---

# 96. Data Sufficiency Framework

Create central helper:

```text
DataSufficiency
```

Instead of each module inventing thresholds.

---

# 97. Data Sufficiency Model

```python
@dataclass
class DataSufficiency:
    available: bool
    sample_size: int
    months_history: int
    reason: str | None
    confidence_band: str
```

---

# 98. Recommended Thresholds

Initial:

| Feature | Minimum |
|---|---:|
| Previous period compare | 2 periods |
| 3M rolling | 3 periods |
| 6M rolling | 6 periods |
| 12M rolling | 12 periods |
| Fingerprint basic | 30 transactions |
| Persistence | 3 months |
| Merchant anomaly | 5 tx |
| Category anomaly | 10 tx |
| Hybrid forecast | 1 month |
| Historical forecast | 3 months |
| Seasonal analysis | 12+ months |

Centralise, do not scatter constants.

---

# 99. Unknown vs Zero Data

A user may begin FinScope in:

```text
June
```

Months before June should not automatically be interpreted as:

```text
zero spending
```

They are:

```text
unknown
```

This matters for historical averages.

---

# 100. Coverage Start

Store or infer:

```text
analytics_data_start_date
```

Possible source:

```text
earliest reliable transaction
```

or user setting after import.

---

# 101. Partial Historical Month

If user starts on:

```text
15 June
```

June coverage is:

```text
partial
```

Should not be treated as a normal full month for long-term averages without adjustment.

---

# 102. Analytics Validation Layer

Before returning result:

Validate:

```text
period order
scope consistency
reconciliation
sufficiency metadata
no NaN
no infinite values
no impossible percentages
```

---

# 103. Percentage Rules

Handle division by zero explicitly.

Previous:

```text
$0
```

Current:

```text
$100
```

Do not return:

```text
infinity%
```

Return:

```text
new spending
```

or:

```text
percent_change = null
change_type = "new"
```

---

# 104. Negative Net Category Edge Case

Refund can exceed current-period purchases.

Example:

```text
Expense = $20
Refund = $100
Net Spend = -$80
```

Do not clamp automatically to zero in all analytical contexts.

Need separate metrics:

```text
Gross Expense = $20
Refund = $100
Net Spending = -$80
Cash In from Refund = $100
```

User-facing summary may decide how to display negative net spend, but engine should preserve truth.

---

# 105. Forecast Refund Handling

Do not assume historical refund is recurring.

Expected refunds should require:

```text
known pending refund
scheduled recurring refund
high-confidence linked event
```

Otherwise forecast:

```text
0 expected future refund
```

---

# 106. Transaction Count Semantics

For frequency decomposition:

Use:

```text
gross expense transaction count
```

not:

```text
expense + refund count
```

Refund effect handled separately.

---

# 107. Merchant Count Semantics

Merchant frequency:

```text
expense purchase count
```

Refund can be separate:

```text
refund count
```

---

# 108. Fingerprint Refund Policy

For behavioural purchase fingerprint:

Prefer:

```text
gross purchase transactions
```

for:

```text
transaction size
burstiness
merchant frequency
```

Use net spend for:

```text
category financial share
```

Document this explicitly.

---

# 109. Anomaly Refund Policy

Refund itself can be anomalous:

```text
unusually large refund
```

But do not compare refund amount to normal expense purchase amounts in the same baseline.

Separate transaction class.

---

# 110. Testing Strategy V2

Testing is a release gate.

Test layers:

```text
Unit
Integration
Reconciliation
API contract
Frontend smoke
Golden dataset
Backtest
Regression
```

---

# 111. Golden Analytics Dataset V2

Create deterministic dataset containing:

```text
12 months
2 accounts
10 categories
8 merchants
salary
rent
groceries
restaurants
shopping
transport
refunds
transfers
recurring subscriptions
zero-spend month
partial month
one anomaly
one merchant increase
one category increase
one refund-heavy month
```

---

# 112. Required Golden Outcomes

Precompute expected:

```text
monthly totals
gross expense
refunds
net spending
cashflow
rolling median
MAD
What Changed decomposition
weekday averages
fingerprint metrics
anomaly flags
forecast components
insight ranking
```

---

# 113. Temporal Context Test

Given data through September.

Request:

```text
as_of_month = August
```

Expected:

```text
Rolling current = August
Fingerprint ends August
Forecast analyses August
Insights use August
```

No September leakage.

---

# 114. Partial Month Test

Today mocked:

```text
Sep 4
```

Request:

```text
September
```

Expected compare:

```text
Sep 1–4
vs
Aug 1–4
```

---

# 115. Zero Month Test

History:

```text
Jan 500
Feb 0
Mar 600
```

Expected series length:

```text
3
```

---

# 116. Refund Decomposition Test

Previous:

```text
10 × $50
refund $0
```

Current:

```text
10 × $50
refund $100
```

Expected:

```text
Frequency 0
Ticket 0
Refund -100
Net delta -100
```

---

# 117. Weekday Metric Test

Monday:

```text
Day 1 total = 60
Day 2 total = 100
```

Expected:

```text
Average Monday Daily Spend = 80
```

not transaction average.

---

# 118. Forecast Scope Test

Account A:

```text
12 months history
```

Account B:

```text
1 month history
```

Forecast Account B confidence must use:

```text
1 month
```

not 12.

---

# 119. Fingerprint Sufficiency Test

1 month only.

Expected:

```text
persistence = unavailable
most stable category = null
most variable category = null
```

---

# 120. Insight Novelty Test

Same insight generated 4 months.

Expected novelty:

```text
declines
```

Large material change month 5:

```text
novelty rises
```

---

# 121. Backtesting Test

Hybrid should be evaluated against:

```text
naive
3M mean
3M median
EWMA
```

If worse:

```text
best_method != hybrid
```

---

# 122. API Contract Tests

For every endpoint:

Verify:

```text
valid response schema
selected scope reflected
no missing required fields
no NaN
no infinity
```

---

# 123. Analytics Models V2

Recommended models:

```text
AnalyticsContext
MetricResult
RollingResult
ChangeDriver
MerchantDriver
DecompositionResult
FingerprintMetric
AnomalyResult
ForecastResult
Insight
DataSufficiency
ReconciliationResult
```

---

# 124. Strong Typing

Avoid unstructured dicts for complex internal logic.

Use:

```text
dataclasses
TypedDict
Pydantic optional
```

This reduces field-name drift.

---

# 125. Versioned Response Contracts

Recommended:

```json
{
  "analytics_api_version": 2,
  ...
}
```

Useful during frontend migration.

---

# 126. Error Contract

Return structured errors:

```json
{
  "error": {
    "code": "INSUFFICIENT_HISTORY",
    "message": "...",
    "details": {}
  }
}
```

Do not rely only on generic 500.

---

# 127. Logging V2

Log:

```text
module
period
scope
duration
result size
reconciliation status
error code
```

Do not log:

```text
sensitive merchant memo content
```

unless debug mode explicitly enabled.

---

# 128. Performance Targets

Typical personal scale:

```text
Overview < 250 ms
Rolling < 250 ms
What Changed < 400 ms
Fingerprint < 400 ms
Anomalies < 500 ms
Forecast < 500 ms
Insights < 600 ms
```

---

# 129. Caching Strategy

Cache only derived results.

Possible keys:

```text
module
as_of_month
account_id
category_id
merchant_id
data_version
```

---

# 130. Data Version

Increment analytical data version when:

```text
transaction created
transaction updated
transaction deleted
refund linked
category changed
merchant changed
account changed
```

Cache key includes version.

---

# 131. Cache Safety

Cache is:

```text
disposable
```

Never authoritative.

If invalid:

```text
rebuild
```

---

# 132. V2 Rollout Plan

---

# Sprint V2.0 — Integration Stabilisation

## Goal

Make current Analytics modules consistently callable.

Tasks:

- [ ] Complete frontend API bridge
- [ ] Add API contract tests
- [ ] Add selected month parameter everywhere
- [ ] Add central AnalyticsContext
- [ ] Add scope banner in UI
- [ ] Fix current integration failures

Definition of Done:

> Every Analytics tab loads for any selected month/account without JS method errors or scope mismatch.

---

# Sprint V2.1 — Temporal Semantics

Tasks:

- [ ] Backend period resolver
- [ ] Partial current month detection
- [ ] Matched previous-month comparison
- [ ] Historical completed month handling
- [ ] zero-filled month series
- [ ] unknown vs zero coverage
- [ ] partial historical month metadata
- [ ] temporal leakage tests

Definition of Done:

> No Analytics module accidentally analyses a different month than the one selected by the user.

---

# Sprint V2.2 — What Changed Reconciliation

Tasks:

- [ ] Gross vs net spending separation
- [ ] Refund Effect
- [ ] Exact decomposition reconciliation
- [ ] Merchant drill-down
- [ ] Merchant driver classification
- [ ] Waterfall reconciliation
- [ ] transaction drill-down
- [ ] What Changed golden tests

Definition of Done:

> Every change can be traced from total → category → merchant → behavioural driver → transactions.

---

# Sprint V2.3 — Weekday & Fingerprint Corrections

Tasks:

- [ ] Separate transaction average from daily average
- [ ] true weekday daily spending
- [ ] selected-month fingerprint
- [ ] persistence zero-fill
- [ ] availability metadata
- [ ] remove fake stable/variable defaults
- [ ] cold-start states
- [ ] fingerprint tests

Definition of Done:

> Fingerprint never reports certainty when history is insufficient.

---

# Sprint V2.4 — Forecast Mathematics

Tasks:

- [ ] remove hardcoded weekday count
- [ ] actual weekday denominators
- [ ] category-specific forecast
- [ ] current-month + historical blending
- [ ] scoped confidence
- [ ] negative/refund edge cases
- [ ] forecast component reconciliation
- [ ] likely range
- [ ] forecast tests

Definition of Done:

> Forecast components are mathematically explainable and scoped to the selected context.

---

# Sprint V2.5 — Hybrid Backtesting

Tasks:

- [ ] evaluate FinScope Hybrid
- [ ] baseline comparison
- [ ] rolling-origin backtest
- [ ] MAE
- [ ] WAPE
- [ ] bias
- [ ] best-method selection
- [ ] forecast evaluation storage
- [ ] historical accuracy display optional

Definition of Done:

> FinScope only claims forecast improvement when backtesting supports it.

---

# Sprint V2.6 — Insights Memory

Tasks:

- [ ] insight_history table
- [ ] persistent novelty
- [ ] material-change reset
- [ ] dynamic confidence
- [ ] deduplication improvements
- [ ] Overview insight card
- [ ] View All Insights
- [ ] dismiss/suppress
- [ ] drill-down evidence

Definition of Done:

> Insights are useful, non-repetitive, and explain why they are being shown.

---

# Sprint V2.7 — Anomaly Hardening

Tasks:

- [ ] contextual baseline hierarchy
- [ ] recurring anomaly
- [ ] refund anomaly separation
- [ ] normal-range output
- [ ] expected/ignored anomaly memory
- [ ] partial-history handling
- [ ] anomaly regression tests

Definition of Done:

> Anomaly detection finds unusual behaviour without overwhelming the user with false positives.

---

# Sprint V2.8 — BI Interaction Layer

Tasks:

- [ ] global cross-filtering
- [ ] chart click → filters
- [ ] filter chips
- [ ] merchant drill-down
- [ ] Transactions deep-link
- [ ] period banner
- [ ] loading states
- [ ] insufficient-data states
- [ ] explanation drawers

Definition of Done:

> Analytics behaves like a coherent personal BI system instead of separate widgets.

---

# 133. Risk Register

## Risk 1 — Temporal Leakage

**Description:** Future month data influences selected historical month.

Mitigation:

```text
as_of_month required
central AnalyticsContext
temporal tests
```

---

## Risk 2 — Semantic Drift

**Description:** Different modules define expense/refund differently.

Mitigation:

```text
central semantics.py
reconciliation tests
```

---

## Risk 3 — Percentage Misleading

**Description:** Huge percent on tiny absolute amount dominates insight.

Mitigation:

```text
impact score includes absolute delta
```

---

## Risk 4 — Forecast Overconfidence

Mitigation:

```text
backtesting
confidence band
likely range
cold-start labels
```

---

## Risk 5 — Missing Months

Mitigation:

```text
calendar series helper
coverage metadata
```

---

## Risk 6 — Refund Distortion

Mitigation:

```text
gross purchase decomposition
separate Refund Effect
```

---

## Risk 7 — Insufficient Fingerprint History

Mitigation:

```text
availability flags
null instead of fake defaults
```

---

## Risk 8 — Frontend Contract Drift

Mitigation:

```text
API version
contract tests
single api.js mapping
```

---

## Risk 9 — Cache Staleness

Mitigation:

```text
data_version in cache key
cache disposable
```

---

## Risk 10 — Model Complexity Without Benefit

Mitigation:

```text
benchmark against naive methods
choose by backtest performance
```

---

# 134. Release Gates

Analytics V2 cannot be called stable until all P0 gates pass.

## P0

- [ ] All frontend Analytics methods connected
- [ ] Selected historical month respected everywhere
- [ ] Current partial month comparison correct
- [ ] zero months preserved
- [ ] refund effect decomposition reconciles
- [ ] weekday metric corrected
- [ ] forecast denominator corrected
- [ ] fingerprint insufficient-data states correct
- [ ] cross-module semantics consistent
- [ ] golden tests pass

---

## P1

- [ ] merchant drill-down
- [ ] category-specific forecast
- [ ] hybrid backtest
- [ ] persistent insight novelty
- [ ] scoped forecast confidence
- [ ] anomaly feedback memory
- [ ] normal range
- [ ] insight card on Overview

---

## P2

- [ ] seasonal anomaly
- [ ] ETS/Holt models
- [ ] automatic model selection per category
- [ ] advanced forecast uncertainty
- [ ] annual fingerprint evolution
- [ ] more advanced merchant behaviour analysis

---

# 135. Recommended V2 API Examples

## Rolling

```text
GET /analytics/rolling
?month=2026-08
&metric=net_spending
&account_id=2
&category_id=6
```

---

## Changes

```text
GET /analytics/changes
?month=2026-09
&comparison_mode=previous_month_matched
```

---

## Fingerprint

```text
GET /analytics/fingerprint
?month=2026-08
&window=6
```

---

## Forecast

```text
GET /analytics/forecast
?month=2026-09
&account_id=2
```

---

# 136. Example V2 Response Context

Every response should include:

```json
{
  "context": {
    "selected_month": "2026-09",
    "start_date": "2026-09-01",
    "end_date": "2026-09-04",
    "coverage": "partial",
    "account_id": null,
    "category_id": null,
    "comparison": {
      "start_date": "2026-08-01",
      "end_date": "2026-08-04",
      "mode": "previous_month_matched"
    }
  }
}
```

This greatly reduces ambiguity.

---

# 137. Example What Changed V2 Response

```json
{
  "context": {...},
  "total_delta_minor": 36300,
  "drivers": [
    {
      "category_id": 7,
      "category_name": "Shopping",
      "delta_minor": 14200,
      "share_of_increase": 0.39,
      "decomposition": {
        "frequency_effect_minor": 9000,
        "ticket_effect_minor": 5200,
        "refund_effect_minor": 0
      },
      "merchants": [
        {
          "merchant_id": 12,
          "merchant_name": "Amazon",
          "delta_minor": 11000
        }
      ]
    }
  ],
  "reconciliation": {
    "passed": true,
    "difference_minor": 0
  }
}
```

---

# 138. Example Fingerprint V2 Response

```json
{
  "context": {...},
  "window_months": 6,
  "metrics": {
    "median_transaction": {
      "value_minor": 2480,
      "available": true,
      "sample_size": 86
    },
    "category_persistence": {
      "value": null,
      "available": false,
      "sample_size": 2,
      "reason": "requires at least 3 completed months"
    }
  }
}
```

---

# 139. Example Forecast V2 Response

```json
{
  "context": {...},
  "expected_minor": 284000,
  "lower_minor": 255000,
  "upper_minor": 318000,
  "confidence": "moderate",
  "method": "hybrid_v2",
  "components": {
    "actual_to_date_minor": 142000,
    "future_recurring_minor": 67200,
    "remaining_variable_minor": 74800,
    "expected_irregular_minor": 0,
    "expected_refund_minor": 0
  },
  "reconciliation": {
    "passed": true
  }
}
```

---

# 140. Example Insight V2

```json
{
  "type": "change_driver",
  "title": "Shopping drove this month's increase",
  "summary": "Shopping explains 39% of the increase, mainly due to more frequent purchases.",
  "confidence": "high",
  "impact_score": 0.88,
  "novelty_score": 0.92,
  "rank_score": 0.86,
  "evidence": {
    "delta_minor": 14200,
    "frequency_effect_minor": 9000,
    "ticket_effect_minor": 5200
  },
  "drilldown": {
    "category_id": 7,
    "month": "2026-09"
  }
}
```

---

# 141. Technical Definition of Done

Analytics V2 is technically complete when:

```text
1. Every module receives the same context.
2. No historical screen leaks future data.
3. Partial periods compare correctly.
4. Missing months do not disappear.
5. Refunds cannot distort behavioural decomposition.
6. Weekday metrics match their labels.
7. Fingerprint knows when data is insufficient.
8. Forecast is scoped, explainable, and backtested.
9. Insights remember what has already been shown.
10. Every major number can drill down to source transactions.
11. Golden dataset reconciliation tests pass.
12. Frontend and backend API contracts are versioned and tested.
```

---

# 142. Recommended Implementation Order

```text
FIRST
│
├── Context
├── API bridge
├── Temporal semantics
├── Zero-fill
├── Reconciliation
│
├── What Changed refund fix
├── Merchant drill-down
├── Weekday correction
├── Fingerprint sufficiency
│
├── Forecast mathematics
├── Backtesting
│
├── Insight history
├── Anomaly hardening
│
└── BI interaction polish
```

---

# 143. What NOT to Add Until V2 Stabilises

Avoid adding:

```text
new charts without validated metrics
new ML anomaly models
new forecasting algorithms
LLM insight generation
multi-user analytics
cloud sync analytics
investment intelligence
```

until V2 invariants are stable.

---

# 144. Final Product Standard

FinScope Analytics V2 should be able to say:

```text
From Sep 1–4, you spent $363 more than Aug 1–4.

Shopping explains 39% of that increase.

Within Shopping:
+$90 came from more frequent purchases.
+$52 came from larger average purchases.
Refunds had no material effect.

Food is above its six-month typical range.

Friday remains your highest-spending weekday
based on average daily spending, not transaction size.

At the current pace, projected month-end spending is $2,840,
with a likely range of $2,550–$3,180.

This forecast is based on your selected account history,
upcoming recurring transactions, and weekday-adjusted spending.

Here are the transactions responsible.
```

If FinScope can produce that consistently across months and filters, Analytics V2 has achieved the intended quality bar.

---

# 145. Final V2 Principle

> **Every analytical statement must be period-correct, financially reconciled, scope-consistent, explainable, and traceable.**

And:

> **If the data is insufficient, FinScope should say so instead of inventing certainty.**

That is the standard that should separate FinScope Analytics V2 from a visually attractive but unreliable finance dashboard.
