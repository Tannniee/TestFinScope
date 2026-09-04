# FinScope Analytics Engine Roadmap

> **Document purpose:** Detailed implementation roadmap for the next analytical layer of FinScope.
>
> **Focus:** Rolling analytics, **What Changed? v2**, Spending Fingerprint, Insights Engine, Anomaly Detection, Forecasting, Backtesting, and BI-style drill-down.
>
> **Product principle:** FinScope should not merely report financial totals. It should help answer:
>
> 1. **What happened?**
> 2. **Where did it happen?**
> 3. **Why did it change?**
> 4. **Is it normal for me?**
> 5. **What is likely to happen next?**
> 6. **What should I pay attention to?**

---

# 0. Executive Summary

The next stage of FinScope should be built as a layered analytics system rather than as separate dashboard widgets.

Recommended analytical pipeline:

```text
Raw Transactions
       │
       ▼
Financial Semantics Layer
       │
       ▼
Canonical Daily / Monthly Metrics
       │
       ├──────────────► Rolling Analytics
       │
       ├──────────────► What Changed?
       │
       ├──────────────► Spending Fingerprint
       │
       ├──────────────► Anomaly Detection
       │
       └──────────────► Forecasting
                           │
                           ▼
                    Insights Engine
                           │
                           ▼
                 Ranked User Insights
                           │
                           ▼
                   Dashboard / Reports
```

The system should be developed in this order:

```text
1. Analytics Foundations
2. Rolling Analytics
3. What Changed? v2
4. Spending Fingerprint
5. Insights Engine v1
6. Anomaly Detection v1
7. Forecasting v1
8. Forecast Backtesting
9. Advanced Anomalies / Forecasts
10. Analytics UX & Drill-down Polish
```

The key idea:

> **Insights are the output. Metrics, baselines, anomalies, and forecasts are the evidence.**

---

# 1. Goals

## 1.1 Primary goals

FinScope Analytics should allow the user to understand:

- monthly financial performance
- category contribution to spending
- changes compared with prior periods
- changes compared with personal historical norms
- behavioural spending patterns
- unusual transactions or category behaviour
- likely month-end outcomes
- which changes matter most financially
- which insights are actionable
- how reliable an insight or forecast is

---

## 1.2 Secondary goals

The analytics engine should also:

- remain fully offline
- be deterministic where possible
- make every insight traceable back to raw transactions
- avoid black-box recommendations in early versions
- work reasonably well with small personal datasets
- improve automatically as more history accumulates
- support drill-down from insight → metric → transactions
- avoid statistical overreaction to one unusual month

---

# 2. Non-Goals for the First Analytics Release

Do **not** prioritise these initially:

```text
AI chatbot
LLM-generated financial advice
portfolio optimisation
investment recommendations
credit score prediction
personality inference
bank API connectivity
complex neural forecasting
deep learning anomaly detection
cloud analytics
```

The first priority is:

```text
accurate
explainable
personal
traceable
offline
```

---

# 3. Analytics Design Principles

## 3.1 Personal baseline, not population baseline

FinScope should answer:

> Is this unusual **for you**?

not:

> Is this unusual compared with the average person?

Baseline hierarchy:

```text
User history
→ category history
→ merchant history
→ weekday pattern
→ recurring pattern
```

---

## 3.2 Absolute impact before percentage drama

Bad insight:

```text
Coffee spending increased 400%
$2 → $10
```

Better ranking:

```text
Shopping increased $340
+48%
```

Therefore insight importance must combine:

```text
absolute financial impact
+
relative change
+
statistical unusualness
+
confidence
+
actionability
+
novelty
```

---

## 3.3 Separate accounting semantics from analytics semantics

Example:

```text
Expense
Refund
Income
Transfer
Adjustment
```

should not be interpreted ad hoc inside each chart.

One central semantics layer should define:

```text
expense contribution
income contribution
cash-in contribution
cash-out contribution
net spending contribution
account balance effect
```

---

## 3.4 Avoid overconfidence

Do not display:

```text
October spending will be $2,843.17
```

Prefer:

```text
Projected spending
$2,840

Likely range
$2,550 – $3,180
```

---

## 3.5 Explain every analytical output

Any insight shown to the user should be able to answer:

```text
Why did FinScope say this?
```

Example:

```text
Food spending is unusually high.

Why?

Current month          $684
3-month median         $531
Typical range       $448–$601
Difference             +$153
Transactions           27
```

---

# 4. Analytics System Architecture

Recommended package structure:

```text
app/backend/
│
├── analytics/
│   ├── __init__.py
│   ├── models.py
│   ├── semantics.py
│   ├── aggregates.py
│   ├── rolling.py
│   ├── changes.py
│   ├── fingerprint.py
│   ├── anomalies.py
│   ├── forecasting.py
│   ├── backtesting.py
│   ├── confidence.py
│   ├── insight_rules.py
│   ├── insight_ranker.py
│   ├── normal_ranges.py
│   └── cache.py
│
├── services/
│   └── analytics_service.py
│
└── repositories/
```

`analytics_service.py` should become the coordinator, not the home of every formula.

---

# 5. Core Analytics Data Contracts

## 5.1 Money

All calculations should use minor units.

Example:

```text
$52.40
→ 5240
```

Use:

```python
int
```

for stored/calculated money where possible.

Convert to decimal display only at the boundary.

---

## 5.2 Period object

Recommended model:

```python
AnalyticsPeriod(
    start_date,
    end_date,
    comparison_start,
    comparison_end,
    granularity
)
```

Granularity:

```text
day
week
month
quarter
year
```

---

## 5.3 Metric result

```python
MetricResult(
    metric_name,
    current_value_minor,
    comparison_value_minor,
    absolute_delta_minor,
    percent_delta,
    sample_size,
    confidence,
    metadata
)
```

---

## 5.4 Insight object

Recommended canonical object:

```python
Insight(
    id,
    insight_type,
    title,
    summary,
    metric,
    entity_type,
    entity_id,
    current_value,
    baseline_value,
    delta_value,
    delta_percent,
    severity,
    confidence,
    impact_score,
    novelty_score,
    actionability_score,
    final_rank_score,
    drilldown_filter,
    evidence,
    generated_at
)
```

---

# 6. Financial Semantics Layer

Before advanced analytics, define canonical financial meanings.

Suggested mapping:

| Transaction Type | Income | Gross Expense | Refund | Cash In | Cash Out | Net Spending |
|---|---:|---:|---:|---:|---:|---:|
| Income | + | 0 | 0 | + | 0 | 0 |
| Expense | 0 | + | 0 | 0 | + | + |
| Refund | 0 | 0 | + | + | 0 | − |
| Transfer In | 0 | 0 | 0 | + | 0 | 0 |
| Transfer Out | 0 | 0 | 0 | 0 | + | 0 |
| Adjustment | configurable | configurable | configurable | configurable | configurable | configurable |

Important:

```text
Net Spending = Expenses − Refunds
```

but:

```text
Net Cash Flow = Cash In − Cash Out
```

These are related but not always identical.

---

# 7. Canonical Aggregation Layer

Create reusable aggregations once.

Needed dimensions:

```text
date
week
month
category
merchant
account
weekday
transaction type
essentiality
recurring status
```

Canonical outputs:

```text
daily totals
weekly totals
monthly totals
category totals
merchant totals
transaction counts
average transaction amount
median transaction amount
refund totals
net spending totals
income totals
cashflow totals
```

---

# 8. Phase A — Rolling Analytics Foundation

## Objective

Build reliable historical baselines used by all later analytics.

---

# 9. Rolling Metrics to Implement

For each relevant metric:

```text
current period
previous period
3-period mean
3-period median
6-period mean
6-period median
12-period mean
12-period median
rolling standard deviation
rolling MAD
EWMA
```

Examples:

```text
Food monthly spend
Shopping monthly spend
Total monthly spend
Monthly savings rate
Transaction count
Average transaction amount
```

---

# 10. Rolling Mean

Formula:

```text
Rolling Mean_n =
(sum of latest n periods) / n
```

Example:

```text
Food

Jul      $520
Aug      $540
Sep      $650

3M mean
($520 + $540 + $650) / 3
= $570
```

---

# 11. Rolling Median

Why:

Personal finance often contains large one-off purchases.

Example:

```text
$400
$420
$450
$2,000
$430
$410
```

Mean is distorted by `$2,000`.

Median better represents the user's typical level.

Use rolling median as a primary robust baseline for anomaly detection.

---

# 12. Rolling MAD

MAD:

```text
MAD = median(|x_i − median(x)|)
```

Use for robust dispersion.

Purpose:

```text
How variable is this category normally?
```

---

# 13. EWMA

Exponentially Weighted Moving Average gives recent periods more influence.

Concept:

```text
recent history > older history
```

Suggested spans:

```text
EWMA short = 3 periods
EWMA medium = 6 periods
```

Use cases:

- anomaly expected value
- trend direction
- short-term spending baseline
- forecasting input

---

# 14. Rolling Analytics API

Suggested endpoints:

```text
GET /analytics/rolling
```

Parameters:

```text
metric
category_id
account_id
periods
window
```

Example:

```text
/analytics/rolling?metric=expense&category_id=food&window=6
```

Response:

```json
{
  "current": 68400,
  "mean_3": 57200,
  "median_3": 55800,
  "mean_6": 54800,
  "median_6": 54100,
  "mean_12": 53100,
  "ewma_3": 60300,
  "mad_6": 4200
}
```

---

# 15. Rolling Analytics UI

Category detail card:

```text
FOOD

This month              $684

Compared with:
Last month              +31%
3-month average         +20%
6-month average         +25%
12-month average        +29%
```

Optional chart:

```text
Monthly spending
+ 3M rolling average
+ 6M rolling average
```

---

# 16. Acceptance Criteria — Rolling Analytics

- [ ] Works for total spending
- [ ] Works by category
- [ ] Works by merchant where history is sufficient
- [ ] Handles missing months
- [ ] Handles partial current month
- [ ] Does not treat zero-data months incorrectly
- [ ] Uses integer money internally
- [ ] Returns sample size
- [ ] Returns history sufficiency flags
- [ ] Unit tests cover mean / median / MAD / EWMA

---

# 17. Phase B — What Changed? v2

## Objective

Move from:

```text
Spending increased
```

to:

```text
Why did spending increase?
```

---

# 18. Level 1 — Total Variance

Example:

```text
August Expenses
$2,577

September Expenses
$2,940

Difference
+$363
```

---

# 19. Level 2 — Category Contribution

Example:

```text
Shopping       +$142
Food            +$96
Travel          +$83
Bills           +$29
Transport       -$41
Other           +$54
```

Check:

```text
sum(category variance)
=
total expense variance
```

within semantics rules.

---

# 20. Contribution Share

Calculate:

```text
category contribution share =
category delta / total positive delta
```

Example:

```text
Shopping caused 39% of the total increase.
```

---

# 21. Level 3 — Merchant Contribution

Inside category:

```text
Food +$160

Restaurant A       +$82
Uber Eats          +$47
Coffee shops       +$31
```

Possible insight:

```text
51% of the Food increase came from Restaurant A.
```

---

# 22. Level 4 — Frequency vs Average Ticket Decomposition

Core identity:

```text
Spending = Transaction Count × Average Transaction Amount
```

Let:

```text
N0 = previous transaction count
N1 = current transaction count

A0 = previous average transaction
A1 = current average transaction
```

Symmetric decomposition:

```text
Frequency Effect =
(N1 − N0) × (A0 + A1) / 2

Average Ticket Effect =
(A1 − A0) × (N0 + N1) / 2
```

Then:

```text
Frequency Effect
+
Average Ticket Effect
=
Current Spend − Previous Spend
```

---

# 23. Example Frequency Decomposition

```text
Shopping

August
8 purchases
Average $42.25
Total $338

September
10 purchases
Average $48.00
Total $480
```

Output:

```text
Total increase              +$142

More frequent purchases      +$90
Higher average purchase      +$52
```

Narrative:

> Shopping increased mainly because purchases became more frequent, with a smaller contribution from higher transaction values.

---

# 24. Level 5 — Time Contribution

Analyse whether change occurred mainly on:

```text
weekdays
weekends
specific weekdays
first half of month
second half of month
```

Example:

```text
September increase: +$363

Weekend spending:   +$220
Weekday spending:   +$143
```

Possible insight:

> 61% of this month's spending increase occurred on weekends.

---

# 25. What Changed? Classification

Each driver can be tagged:

```text
NEW
INCREASED FREQUENCY
HIGHER TICKET
NEW MERCHANT
RETURNED MERCHANT
CATEGORY MIX SHIFT
WEEKEND SHIFT
ONE-OFF PURCHASE
REFUND DIFFERENCE
```

---

# 26. What Changed? API

```text
GET /analytics/changes
```

Parameters:

```text
current_period
comparison_period
account
category
```

Suggested response:

```json
{
  "total_delta_minor": 36300,
  "drivers": [
    {
      "dimension": "category",
      "name": "Shopping",
      "delta_minor": 14200,
      "share": 0.39,
      "frequency_effect_minor": 9000,
      "ticket_effect_minor": 5200
    }
  ]
}
```

---

# 27. What Changed? UI

Primary chart:

```text
waterfall chart
```

Example:

```text
August   Shopping   Food   Travel   Transport   September
$2577      +142      +96     +83       -41        $2940
```

Click `Shopping`:

```text
Shopping Breakdown
```

Then:

```text
Frequency      +$90
Ticket Size    +$52
```

Then merchant breakdown.

---

# 28. Acceptance Criteria — What Changed v2

- [ ] Total variance reconciles
- [ ] Category variance reconciles
- [ ] Merchant drill-down works
- [ ] Frequency decomposition reconciles
- [ ] Refund semantics are respected
- [ ] Transfers excluded
- [ ] Supports partial-month comparison
- [ ] Supports previous month comparison
- [ ] Supports same month previous year later
- [ ] Drill-down filter returns source transactions

---

# 29. Phase C — Spending Fingerprint

## Objective

Describe the user's personal spending behaviour without making psychological or moral judgements.

---

# 30. Fingerprint Categories

Recommended dimensions:

```text
Spending Level
Spending Variability
Spending Rhythm
Category Concentration
Merchant Concentration
Weekend Concentration
Recurring Expense Share
Essential vs Discretionary Share
Transaction Size Profile
Category Persistence
Month-to-Month Stability
```

---

# 31. Typical Transaction

Metrics:

```text
median transaction
mean transaction
75th percentile
90th percentile
largest transaction
```

UI:

```text
Typical transaction      $24.80
Large transaction         $92+
Very large transaction   $180+
```

---

# 32. Spending Variability

Possible coefficient:

```text
CV = standard deviation / mean
```

For robust version:

```text
robust variability =
MAD / median
```

Prefer robust version when outliers are common.

---

# 33. Weekend Concentration

Formula:

```text
Weekend Spend / Total Discretionary Spend
```

Example:

```text
Weekend concentration
38%
```

Comparison:

```text
3 months ago
29%
```

---

# 34. Category Concentration

Use entropy or Herfindahl-style measure internally.

User-facing output:

```text
Spending concentration
Low / Moderate / High
```

Example:

```text
Top 3 categories account for 72% of spending.
```

---

# 35. Category Diversity

Possible normalized entropy:

```text
H = -Σ p_i log(p_i)

Normalized H =
H / log(number of active categories)
```

Range:

```text
0 → highly concentrated
1 → highly diversified
```

Do not expose entropy terminology by default.

UI:

```text
Category diversity
64 / 100
```

---

# 36. Merchant Concentration

Examples:

```text
Top merchant share
Top 3 merchant share
number of active merchants
```

Possible insight:

```text
Woolworths accounts for 43% of your grocery spending.
```

---

# 37. Spending Rhythm / Burstiness

Calculate transaction inter-event time:

```text
Δt_i = transaction_time_i − transaction_time_(i−1)
```

Then:

```text
r = std(Δt) / mean(Δt)

B = (r − 1) / (r + 1)
```

Interpretation:

```text
B close to -1 → regular
B around 0    → random-ish
B close to +1 → clustered / bursty
```

UI:

```text
Spending Rhythm

Regular ─────●──── Bursty
```

---

# 38. Category Persistence

Represent monthly spending distribution as category vectors.

Example:

```text
Jan = [Food .25, Rent .40, Shopping .10, ...]
Feb = [Food .24, Rent .41, Shopping .09, ...]
```

Calculate cosine similarity between consecutive periods.

High similarity:

```text
category mix is stable
```

Low similarity:

```text
category mix shifted materially
```

---

# 39. Fingerprint Change Over Time

Store snapshot monthly or calculate dynamically.

Example:

```text
2026
Weekend concentration       31%
Discretionary share         37%
Median transaction        $28.40
Category diversity          0.61
Burstiness                  0.22

2027
Weekend concentration       39%
Discretionary share         46%
Median transaction        $34.80
Category diversity          0.69
Burstiness                  0.41
```

Possible insight:

> Spending has become more concentrated into high-activity days over the past year.

---

# 40. Fingerprint UI Page

Suggested card layout:

```text
YOUR SPENDING FINGERPRINT
Last 12 months

Typical transaction        $24.80
Weekend concentration        38%
Recurring expense ratio      41%
Essential spending           58%
Category diversity          64/100
Spending consistency        72/100
Most active weekday        Friday
Most variable category   Shopping
Most stable category        Rent
```

---

# 41. Acceptance Criteria — Spending Fingerprint

- [ ] Metrics are descriptive only
- [ ] No personality labels
- [ ] No moral judgement
- [ ] Shows sample period
- [ ] Shows insufficient-data state
- [ ] Works without merchant data
- [ ] Supports 3M / 6M / 12M period
- [ ] Metrics are reproducible from transactions
- [ ] Snapshot comparison possible

---

# 42. Phase D — Insights Engine v1

## Objective

Select the most meaningful facts from all analytical modules and present them clearly.

---

# 43. Insight Categories

Suggested:

```text
CHANGE
TREND
ANOMALY
BUDGET
FORECAST
BEHAVIOUR
ACHIEVEMENT
RECURRING
CASHFLOW
DATA_QUALITY
```

---

# 44. Candidate Insight Generation

Each analytical module generates candidate insights.

Example sources:

```text
Rolling Analytics
→ category above 6M norm

What Changed
→ category explains 42% of increase

Fingerprint
→ weekend share increased

Budget
→ likely to exceed budget

Anomaly
→ unusual transaction

Forecast
→ projected savings lower than recent norm
```

---

# 45. Insight Ranking Model

Recommended score:

```text
Final Score =
w1 × Impact
+
w2 × Unusualness
+
w3 × Confidence
+
w4 × Actionability
+
w5 × Novelty
+
w6 × Relevance
```

Example weights for v1:

```text
Impact         0.30
Unusualness    0.20
Confidence     0.15
Actionability  0.15
Novelty        0.10
Relevance      0.10
```

Keep configurable.

---

# 46. Financial Impact Score

Possible normalization:

```text
abs(delta) / total monthly expense
```

Example:

```text
Food +$20
Total expense $3000
impact low

Shopping +$400
Total expense $3000
impact high
```

---

# 47. Unusualness Score

Possible inputs:

```text
distance from rolling median
MAD z-like score
percent deviation from historical baseline
seasonal residual
```

---

# 48. Confidence Score

Confidence should reflect data sufficiency and consistency.

Possible components:

```text
history length
sample size
baseline stability
agreement across baselines
missing data ratio
```

Example:

```text
1 month history
→ low confidence

18 months history
→ higher confidence
```

---

# 49. Suggested Confidence Formula v1

```text
history_score =
min(months_history / 12, 1)

sample_score =
min(transaction_count / 20, 1)

baseline_agreement =
1 - normalized disagreement between
previous month / 3M median / 6M median

confidence =
0.4 * history_score
+ 0.3 * sample_score
+ 0.3 * baseline_agreement
```

Keep internal.

UI:

```text
Low confidence
Moderate confidence
High confidence
```

---

# 50. Novelty Score

Store recent insight keys.

Example:

```text
category_increase:food
```

If shown repeatedly:

```text
novelty decreases
```

If materially changed:

```text
novelty increases again
```

Suggested table:

```sql
insight_history

id
insight_key
first_seen
last_seen
times_shown
last_value
last_rank
```

---

# 51. Insight Deduplication

Avoid:

```text
Food increased 28%.
Food is above 3M average.
Food is above 6M average.
Food is unusually high.
```

all appearing simultaneously.

Combine:

> Food spending is $153 above its 6-month norm and increased 28% from last month.

---

# 52. Insight Narrative Templates

Avoid AI initially.

Template:

```text
"{category} spending is {delta_percent}% higher than last month,
mainly due to {driver}."
```

Template:

```text
"{category} is {difference} above your {window}-month typical range."
```

Template:

```text
"At the current pace, {category} is projected to exceed budget by {amount}."
```

---

# 53. Insight Evidence Drawer

Every insight should support:

```text
Why am I seeing this?
```

Example:

```text
FOOD SPENDING IS UNUSUALLY HIGH

Current month        $684
6M median            $531
Typical range     $448–$601
Difference           +$153

Main contributors
Restaurant A          +$82
Uber Eats             +$47
```

---

# 54. Insight Drill-down

Insight carries:

```python
drilldown_filter = {
    "category_id": 4,
    "period": "2026-09",
    "comparison": "2026-08"
}
```

Click:

```text
View transactions
```

→ Transactions page with filter applied.

---

# 55. Insights Dashboard UI

Suggested layout:

```text
INSIGHTS

Important
────────────────────────

▲ Shopping drove 39% of this month's increase.
  +$142 vs August
  [Explore]

⚠ Food is above its typical 6-month range.
  +$153 above median
  [Explore]

◷ At the current pace, expenses may finish
  $230 over budget.
  [View Forecast]
```

---

# 56. Acceptance Criteria — Insights Engine

- [ ] Candidate generation separated from ranking
- [ ] No duplicate insight spam
- [ ] Every insight has evidence
- [ ] Every insight has drill-down
- [ ] Ranking considers absolute impact
- [ ] Low-confidence insights are marked
- [ ] Repeated insights lose novelty
- [ ] Rules fully unit tested
- [ ] No LLM required

---

# 57. Phase E — Anomaly Detection v1

## Objective

Detect transactions and periods that are unusual relative to the user's own history.

---

# 58. Anomaly Types

```text
Transaction amount anomaly
Category monthly anomaly
Merchant amount anomaly
Merchant frequency anomaly
Recurring payment change
Daily spending anomaly
Weekly spending anomaly
Cashflow anomaly
```

---

# 59. Transaction Amount Anomaly

Baseline hierarchy:

```text
merchant + category
↓
merchant
↓
category
↓
overall discretionary
```

Example:

```text
Restaurant transaction
$184

Category median
$26

Category MAD
$8
```

Flag as unusual.

---

# 60. Robust Anomaly Score

Use robust z-like score:

```text
Robust Score =
0.6745 × (x − median) / MAD
```

Possible initial threshold:

```text
|score| >= 3.5
```

Do not hardcode permanently; tune through tests.

---

# 61. Minimum Sample Guard

Do not detect category anomalies from:

```text
3 transactions
```

Suggested:

```text
transaction-level category baseline
minimum n = 10

merchant baseline
minimum n = 5
```

If insufficient:

```text
fallback to parent baseline
```

---

# 62. Monthly Category Anomaly

Example:

```text
Shopping monthly median
$310

MAD
$85

Current month
$860
```

Flag:

```text
Shopping unusually high
```

---

# 63. Context-Aware Recurring Anomaly

Example:

```text
Netflix

usual
$22.99

new
$31.99
```

This should be treated differently from a normal one-off transaction.

Possible alert:

> Netflix is $9.00 above its usual recurring amount.

---

# 64. Daily Spending Anomaly

Compare day against:

```text
same weekday history
```

not only global daily average.

Example:

```text
Friday expected
$90

This Friday
$210
```

---

# 65. Normal Range

User-facing representation:

```text
Typical range
$460 ───────────── $590

Current
                       ● $684
```

This is easier to understand than a z-score.

---

# 66. Typical Range v1

For robust baseline:

```text
lower =
median − k × MAD_scaled

upper =
median + k × MAD_scaled
```

Where:

```text
MAD_scaled ≈ 1.4826 × MAD
```

Use a configurable multiplier.

---

# 67. Anomaly Severity

Possible levels:

```text
Mild
Moderate
Strong
```

Based on:

```text
robust score
financial impact
baseline confidence
```

---

# 68. False Positive Controls

Exclude or treat separately:

```text
known transfers
known recurring changes
large scheduled bills
manual adjustments
new category with little history
```

---

# 69. Anomaly UX

Do not say:

```text
ANOMALY DETECTED!!!
```

Prefer:

```text
Unusually large transaction

Restaurant
$184

Typical Food transaction
$12–$58
```

---

# 70. Acceptance Criteria — Anomaly Detection v1

- [ ] Uses robust baseline
- [ ] Minimum sample guard
- [ ] Category-aware
- [ ] Merchant-aware where possible
- [ ] Recurring payments handled separately
- [ ] Transfers excluded
- [ ] Shows typical range
- [ ] Supports dismiss / ignore
- [ ] Dismissed anomaly stored
- [ ] No ML required

---

# 71. Phase F — Seasonal Anomaly Detection v2

Only after sufficient history.

Use seasonal decomposition for daily/weekly series.

Concept:

```text
Observed =
Trend
+
Seasonality
+
Residual
```

Detect anomaly on:

```text
Residual
```

not raw spending.

---

# 72. Minimum History for Seasonal Analysis

Suggested:

```text
weekly seasonality
minimum ~12 weeks

monthly seasonal structure
minimum 12–24 months
```

If insufficient:

```text
fallback to robust rolling baseline
```

---

# 73. Advanced Isolation Forest — Later

Only consider when enough transactions exist.

Possible feature vector:

```text
log(amount)
category encoding
merchant frequency
weekday
day of month
time of day
days since previous purchase
recurring flag
essential/discretionary flag
```

Use only as supplementary signal.

Do not let it override explainable rules.

---

# 74. Phase G — Forecasting v1

## Objective

Forecast month-end totals in an explainable way.

---

# 75. Forecasting Principle

Do not model all spending as one homogeneous time series.

Separate:

```text
Known Recurring
Variable Spending
Irregular / One-Off
Expected Income
Refunds
```

---

# 76. Forecast Formula v1

```text
Projected Month-End Expense =

Actual Spend To Date
+
Known Future Recurring Expense
+
Expected Remaining Variable Spend
+
Expected Irregular Spend
-
Expected Refunds
```

---

# 77. Variable Spend Forecast

For category `c`:

```text
Expected Remaining Spend_c =
Expected Daily Spend_c
× Remaining Relevant Days
```

Expected daily spend can combine:

```text
current month pace
3M weekday-adjusted average
6M EWMA
```

---

# 78. Weekday Adjustment

Example:

If user spends more on:

```text
Friday / Saturday
```

then remaining month calculation should account for how many Fridays/Saturdays remain.

Better than:

```text
current spend / elapsed days × total days
```

---

# 79. Forecast Confidence by Data Age

## Data < 1 month

Use:

```text
actual pace
known recurring only
```

Confidence:

```text
Very Low
```

---

## Data 1–3 months

Add:

```text
category daily averages
weekday pattern
```

Confidence:

```text
Low
```

---

## Data 3–6 months

Add:

```text
rolling medians
EWMA
recurring history
```

Confidence:

```text
Moderate
```

---

## Data 6–12 months

Add:

```text
category trend
month-level pattern
```

---

## Data 12+ months

Potentially test:

```text
ETS
seasonal naive
Holt-Winters
```

if data supports it.

---

# 80. Known Future Transactions

Recurring engine should contribute:

```text
Rent
Phone
Netflix
Insurance
Salary
```

Example:

```text
Already spent               $1,420

Known future:
Rent                           $600
Netflix                         $23
Phone                           $49

Expected variable:
Food                           $310
Transport                      $105
Shopping                       $180

Projected total              $2,687
```

---

# 81. Forecast Output

Do not return only:

```text
point_estimate
```

Return:

```python
ForecastResult(
    expected_minor,
    lower_minor,
    upper_minor,
    confidence,
    method,
    components,
    historical_error
)
```

---

# 82. Forecast UI

```text
PROJECTED MONTH-END

Expected Expense
$2,840

Likely Range
$2,550 – $3,180

Budget
$2,700

Projected variance
+$140
```

---

# 83. Forecast Breakdown

Click:

```text
Why?
```

Display:

```text
Actual spent               $1,420
Upcoming recurring           $672
Expected food                $310
Expected transport           $105
Expected shopping            $180
Expected other               $153
────────────────────────────────
Forecast                   $2,840
```

---

# 84. Budget Forecast Integration

Per-category:

```text
Food Budget
$600

Spent
$420

Projected
$742

Expected over budget
+$142
```

---

# 85. Income Forecast

Separate logic:

```text
scheduled salary
historical salary timing
known recurring income
other irregular income
```

Avoid forecasting irregular refunds as dependable future income.

---

# 86. Savings Forecast

```text
Projected Savings =
Projected Income
− Projected Net Spending
```

Savings rate:

```text
Projected Savings Rate =
Projected Savings / Projected Income
```

---

# 87. Acceptance Criteria — Forecasting v1

- [ ] Explainable components
- [ ] Known recurring transactions included
- [ ] Transfers excluded
- [ ] Refund semantics correct
- [ ] Handles partial month
- [ ] Handles no-history cold start
- [ ] Returns confidence
- [ ] Returns likely range
- [ ] Per-category forecasts supported
- [ ] Budget projection integrated

---

# 88. Phase H — Forecast Backtesting

## Objective

Prove whether the forecast actually improves over simple baselines.

---

# 89. Baseline Models

Always compare against:

```text
Naive previous month
3M mean
3M median
6M EWMA
Seasonal naive
```

---

# 90. Rolling-Origin Backtest

Do not random split time-series data.

Example:

```text
Train through March
→ forecast April

Train through April
→ forecast May

Train through May
→ forecast June
```

Continue.

---

# 91. Backtest Metrics

Recommended:

```text
MAE
Median Absolute Error
WAPE
Bias
```

Avoid depending only on MAPE when actual values can be near zero.

---

# 92. Forecast Selection

Example:

```text
Model                  MAE

Previous month         $238
3M median              $181
EWMA                    $165
Hybrid FinScope         $143
ETS                     $192
```

Select:

```text
Hybrid FinScope
```

Do not choose complex model simply because it is complex.

---

# 93. Store Forecast Accuracy

Possible table:

```sql
forecast_evaluations

id
forecast_date
target_period
metric
method
predicted_minor
actual_minor
absolute_error_minor
created_at
```

Allows:

```text
Forecast accuracy improving over time
```

---

# 94. Forecast Confidence Improvement

Confidence can incorporate:

```text
historical MAE
history length
model stability
forecast horizon
```

---

# 95. Phase I — Insights Engine v2

After anomalies and forecasting exist, Insights Engine gets richer.

Possible top insights:

```text
Shopping drove 46% of this month's expense increase.

Food is 29% above its 12-month norm.

Weekend discretionary spending rose from 27% to 39%.

One unusually large restaurant transaction explains 22% of the Food increase.

Expenses are projected to finish $230 above budget.
```

---

# 96. Insight Hierarchy

Priority order:

```text
1. High-impact anomalies
2. Major What Changed drivers
3. Budget risk
4. Forecast risk
5. Strong historical deviation
6. Behaviour shifts
7. Achievements
8. Low-impact observations
```

---

# 97. Achievement Insights

Not all insights should be warnings.

Examples:

```text
Transport spending is at its lowest level in 6 months.

You stayed within all category budgets this month.

Savings rate improved from 28% to 35%.

Discretionary spending fell 18%.
```

---

# 98. User Feedback on Insights

Add:

```text
Useful
Not useful
Ignore this type
```

Store feedback.

Future ranking can incorporate it.

---

# 99. Insight Suppression

Allow user to suppress:

```text
Rent is largest category
```

if obviously uninteresting.

Suppression key:

```text
insight_type + entity
```

---

# 100. Analytics Database Extensions

Potential additions:

```sql
CREATE TABLE insight_history (
    id INTEGER PRIMARY KEY,
    insight_key TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    times_shown INTEGER NOT NULL DEFAULT 1,
    last_value_minor INTEGER,
    last_score REAL
);
```

---

# 101. Anomaly Feedback Table

```sql
CREATE TABLE anomaly_feedback (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    transaction_id INTEGER,
    anomaly_key TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

Statuses:

```text
confirmed
ignored
expected
```

---

# 102. Forecast Evaluation Table

```sql
CREATE TABLE forecast_evaluations (
    id INTEGER PRIMARY KEY,
    target_period TEXT NOT NULL,
    metric TEXT NOT NULL,
    method TEXT NOT NULL,
    predicted_minor INTEGER NOT NULL,
    actual_minor INTEGER,
    absolute_error_minor INTEGER,
    created_at TEXT NOT NULL
);
```

---

# 103. Analytics Cache

Do not prematurely cache everything.

Potential cache:

```text
monthly category aggregates
monthly merchant aggregates
daily totals
rolling metrics
fingerprint snapshots
```

Cache invalidation:

```text
transaction create
transaction edit
transaction delete
refund edit
transfer edit
category reassignment
```

---

# 104. Cache Strategy

Source of truth:

```text
transactions
```

Cache is disposable.

If corrupted:

```text
rebuild
```

Never make analytics cache authoritative financial data.

---

# 105. Analytics API Roadmap

Suggested endpoints:

```text
GET /analytics/overview
GET /analytics/rolling
GET /analytics/changes
GET /analytics/fingerprint
GET /analytics/anomalies
GET /analytics/forecast
GET /analytics/insights
GET /analytics/normal-range
GET /analytics/backtest
```

---

# 106. Overview API

Should return:

```text
Income
Gross Expense
Refunds
Net Spending
Cash In
Cash Out
Net Cash Flow
Savings
Savings Rate
```

plus comparison.

---

# 107. Insights API

Example response:

```json
{
  "period": "2026-09",
  "insights": [
    {
      "type": "change_driver",
      "title": "Shopping drove this month's increase",
      "summary": "Shopping explains 39% of the increase in spending.",
      "confidence": "high",
      "severity": "medium",
      "drilldown": {
        "category_id": 7
      }
    }
  ]
}
```

---

# 108. Frontend Architecture

Recommended:

```text
pages/
├── overview
├── analytics
├── insights
└── reports

components/
├── insight-card
├── normal-range
├── forecast-band
├── waterfall-chart
├── rolling-line-chart
├── fingerprint-card
└── anomaly-badge
```

---

# 109. Analytics Page Tabs

Possible:

```text
Overview
Changes
Patterns
Anomalies
Forecast
```

---

# 110. Changes Tab

Contains:

```text
What Changed waterfall
Category contribution
Merchant drill-down
Frequency vs ticket decomposition
Weekend vs weekday contribution
```

---

# 111. Patterns Tab

Contains:

```text
Rolling averages
Spending Fingerprint
Weekday pattern
Category persistence
Recurring ratio
Category concentration
```

---

# 112. Anomalies Tab

Contains:

```text
Unusual transactions
Unusual categories
Recurring payment changes
Normal ranges
```

---

# 113. Forecast Tab

Contains:

```text
Month-end expense forecast
Income forecast
Savings forecast
Category forecasts
Budget risk
Forecast range
Forecast components
```

---

# 114. Dashboard Insight Strip

Overview dashboard should show only:

```text
Top 3–5 insights
```

Do not overload.

Example:

```text
INSIGHTS

Shopping drove 39% of this month's increase.
Food is above its typical range.
Current spending pace may exceed budget by $230.
```

---

# 115. Drill-down Interaction Model

Desired flow:

```text
Dashboard KPI
      ↓
What Changed
      ↓
Category
      ↓
Merchant
      ↓
Transactions
```

or:

```text
Insight
      ↓
Evidence
      ↓
Chart
      ↓
Transactions
```

---

# 116. Partial-Month Comparison

Important.

Comparing:

```text
Sep 1–15
```

against full August is misleading.

Default comparison should be:

```text
Sep 1–15
vs
Aug 1–15
```

Optionally show:

```text
Full-month forecast
```

separately.

---

# 117. Month Length Adjustment

For categories that behave daily:

```text
February
vs
March
```

should sometimes use:

```text
per-day average
```

in addition to monthly total.

---

# 118. Recurring vs Variable Separation

Analytics should distinguish:

```text
Fixed recurring
Variable recurring
Variable discretionary
One-off
```

Example insight:

> Most of the increase came from variable discretionary spending, while fixed expenses remained stable.

---

# 119. Essential vs Discretionary Analysis

If transaction/category tags exist:

```text
Essential
Discretionary
```

What Changed can say:

```text
Essential expenses      +$20
Discretionary expenses +$343
```

Much more informative.

---

# 120. Data Sufficiency Policy

Each analytical feature needs minimum data.

Suggested initial rules:

| Feature | Minimum Data |
|---|---|
| Previous-month comparison | 2 months |
| 3M rolling | 3 months |
| 6M rolling | 6 months |
| 12M baseline | 12 months |
| Transaction anomaly | 10 similar transactions |
| Merchant anomaly | 5 merchant transactions |
| Fingerprint | 30 transactions |
| Persistence | 3 months |
| Forecast v1 | none, degraded mode |
| Forecast historical | 3+ months |
| Seasonal methods | 12+ months |

---

# 121. Cold-Start UX

Do not show blank or unreliable analytics.

Example:

```text
Build your financial baseline

FinScope needs about 3 months of history
for stronger trend analysis.

Current data:
1.4 months
```

Still provide:

```text
current month
previous period
basic budget
basic forecast
```

---

# 122. Confidence UX

Use labels:

```text
Early estimate
Moderate confidence
High confidence
```

Do not overuse numeric probability.

---

# 123. Analytics Testing Strategy

Tests should cover:

```text
financial semantics
rolling calculations
partial month
refund behaviour
transfer exclusion
frequency decomposition
normal range
MAD
anomaly threshold
forecast components
insight ranking
deduplication
confidence
```

---

# 124. Golden Dataset

Create a deterministic fixture dataset with known outcomes.

Example:

```text
6 months
fixed rent
salary
food
shopping
transport
one refund
one transfer
one large anomaly
one recurring price increase
```

Calculate expected outputs manually.

Use this dataset across analytics tests.

---

# 125. What Changed Test Example

Given:

```text
August Shopping
8 × $40 = $320

September Shopping
10 × $50 = $500
```

Expected:

```text
delta = $180
```

Frequency + ticket decomposition must sum exactly to:

```text
$180
```

within integer rounding.

---

# 126. Anomaly Test Example

History:

```text
20
22
21
24
19
23
22
21
```

New:

```text
100
```

Expected:

```text
flagged
```

---

# 127. Forecast Test Example

Given:

```text
15 days elapsed
actual spend = $1,000
known future rent = $600
expected remaining variable = $500
```

Expected:

```text
forecast = $2,100
```

---

# 128. Insight Ranking Test

Candidates:

```text
Coffee +400% = +$8
Shopping +35% = +$350
```

Expected:

```text
Shopping ranks higher
```

---

# 129. Performance Targets

Personal finance scale should feel instant.

Targets:

```text
Dashboard analytics < 250 ms typical
Insight generation < 500 ms typical
Month switch < 300 ms
12M analysis < 500 ms
Forecast < 500 ms
```

These are product targets, not strict guarantees.

---

# 130. Background Computation

Potentially calculate:

```text
fingerprint
forecast backtest
12M anomalies
```

when:

```text
app idle
transaction imported
month changed
```

But basic UI analytics should remain fast synchronously.

---

# 131. Logging

Analytics logs should record:

```text
calculation type
period
duration
errors
cache usage
```

Do not log sensitive transaction descriptions unnecessarily.

---

# 132. Sprint Roadmap

---

# Sprint 1 — Analytics Foundation

## Goal

Create reusable analytics package and canonical semantics.

Tasks:

- [ ] Create `backend/analytics/`
- [ ] Implement semantics layer
- [ ] Create analytics models
- [ ] Move reusable calculations out of large service
- [ ] Add canonical daily/monthly aggregates
- [ ] Add golden test dataset
- [ ] Add baseline unit tests

Definition of Done:

> Advanced analytics can rely on one consistent definition of income, spending, refunds, transfers, and cashflow.

---

# Sprint 2 — Rolling Analytics

Tasks:

- [ ] 3M mean
- [ ] 3M median
- [ ] 6M mean
- [ ] 6M median
- [ ] 12M mean
- [ ] 12M median
- [ ] rolling standard deviation
- [ ] rolling MAD
- [ ] EWMA
- [ ] history sufficiency metadata
- [ ] rolling analytics API
- [ ] rolling chart UI

Definition of Done:

> Any major category can be compared against recent and long-term personal norms.

---

# Sprint 3 — What Changed? v2

Tasks:

- [ ] Total variance
- [ ] Category contribution
- [ ] Merchant contribution
- [ ] Frequency vs ticket decomposition
- [ ] Weekend vs weekday contribution
- [ ] Partial-month matching
- [ ] Waterfall chart
- [ ] Drill-down
- [ ] Transaction filters

Definition of Done:

> User can answer not only “how much did spending change?” but “what caused the change?”

---

# Sprint 4 — Spending Fingerprint

Tasks:

- [ ] Typical transaction
- [ ] variability
- [ ] weekend concentration
- [ ] recurring ratio
- [ ] essential/discretionary ratio
- [ ] category diversity
- [ ] category concentration
- [ ] merchant concentration
- [ ] burstiness
- [ ] category persistence
- [ ] fingerprint UI
- [ ] insufficient-data states

Definition of Done:

> FinScope can describe the user's spending structure and rhythm without making personality claims.

---

# Sprint 5 — Insights Engine v1

Tasks:

- [ ] Insight model
- [ ] rule registry
- [ ] candidate generators
- [ ] impact scoring
- [ ] confidence scoring
- [ ] novelty scoring
- [ ] ranking
- [ ] deduplication
- [ ] templates
- [ ] evidence drawer
- [ ] drill-down
- [ ] insight history table

Definition of Done:

> FinScope automatically selects and explains the 3–8 most meaningful financial observations.

---

# Sprint 6 — Anomaly Detection v1

Tasks:

- [ ] robust median baseline
- [ ] MAD
- [ ] transaction anomaly
- [ ] category anomaly
- [ ] merchant anomaly
- [ ] recurring price anomaly
- [ ] typical range
- [ ] severity scoring
- [ ] dismiss/expected feedback
- [ ] anomaly UI

Definition of Done:

> FinScope can identify unusual spending relative to the user's own history with low false-positive risk.

---

# Sprint 7 — Forecasting v1

Tasks:

- [ ] forecast result model
- [ ] recurring future expenses
- [ ] remaining variable spending
- [ ] weekday adjustment
- [ ] category projections
- [ ] total expense forecast
- [ ] income forecast
- [ ] savings forecast
- [ ] budget risk
- [ ] likely range
- [ ] confidence level
- [ ] forecast UI

Definition of Done:

> FinScope can produce an explainable month-end projection even with limited history.

---

# Sprint 8 — Backtesting

Tasks:

- [ ] rolling-origin evaluation
- [ ] previous-month baseline
- [ ] moving average baseline
- [ ] median baseline
- [ ] EWMA baseline
- [ ] hybrid FinScope forecast
- [ ] MAE
- [ ] WAPE
- [ ] bias
- [ ] forecast evaluation storage
- [ ] best-model selection

Definition of Done:

> FinScope can prove whether its forecast is better than simple methods.

---

# Sprint 9 — Seasonal Anomalies / Advanced Forecasting

Only when enough history exists.

Tasks:

- [ ] seasonal decomposition
- [ ] residual anomalies
- [ ] Holt trend
- [ ] ETS
- [ ] seasonal naive
- [ ] category-level model eligibility
- [ ] automatic model comparison

Definition of Done:

> FinScope can use seasonality only when data supports it and only when it improves out-of-sample accuracy.

---

# Sprint 10 — Analytics UX Polish

Tasks:

- [ ] global cross-filtering
- [ ] click chart → filter
- [ ] active filter chips
- [ ] compare-period control
- [ ] normal-range visual
- [ ] forecast band visual
- [ ] waterfall transitions
- [ ] insight deep links
- [ ] loading states
- [ ] empty states
- [ ] explanations
- [ ] accessibility

Definition of Done:

> Analytics feels like a small personal BI application rather than a collection of static charts.

---

# 133. Recommended Feature Release Mapping

## v0.6

```text
Rolling Analytics
What Changed v2
```

---

## v0.7

```text
Spending Fingerprint
Insights Engine v1
```

---

## v0.8

```text
Anomaly Detection
Normal Range
```

---

## v0.9

```text
Forecasting
Budget Forecast
Forecast Backtesting
```

---

## v1.0

```text
Cross-filtering
Full drill-down
Insight confidence
Polish
Testing
Production reliability
```

---

# 134. Example Final Analytics Experience

User opens September.

FinScope sees:

```text
Expense
$2,940

August
$2,577

Difference
+$363
```

Then:

```text
Shopping +$142
Food +$96
Travel +$83
Transport -$41
```

Then:

```text
Shopping:
+5 extra purchases
average purchase +$7
```

Then:

```text
Food:
$684
6M median $531
outside typical range
```

Then:

```text
Weekend discretionary share:
27% → 39%
```

Then forecast:

```text
Projected month-end expense
$3,140

Budget
$2,900
```

Insights Engine chooses:

```text
1. Shopping drove 39% of the increase in spending.

2. Food is $153 above its 6-month typical level.

3. Most of the additional spending occurred on weekends.

4. Expenses are currently projected to finish about
   $240 over budget.
```

This is the target FinScope analytics experience.

---

# 135. Product Rule for Every New Analytics Feature

Before adding any metric, ask:

```text
What user question does this answer?
```

Valid examples:

```text
Is this increasing?
Is this unusual?
What caused the change?
When does it happen?
What is likely to happen next?
What should I inspect?
```

If the metric does not answer a meaningful question:

```text
do not add it
```

---

# 136. Final Recommended Architecture

```text
                    FIN SCOPE
                        │
                        ▼
                 Transactions DB
                        │
                        ▼
              Financial Semantics
                        │
                        ▼
               Aggregate Metrics
                        │
         ┌──────────────┼──────────────┐
         │              │              │
         ▼              ▼              ▼
      Rolling      What Changed    Fingerprint
         │              │              │
         └──────────────┼──────────────┘
                        │
                  Normal Baselines
                        │
               ┌────────┴────────┐
               ▼                 ▼
          Anomalies          Forecasts
               │                 │
               └────────┬────────┘
                        ▼
                  Insight Engine
                        │
                  Rank + Explain
                        │
                        ▼
                   User Interface
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
     Dashboard       Analytics         Reports
                        │
                        ▼
                   Transactions
```

---

# 137. Final Priority

The recommended immediate development sequence is:

```text
NOW
│
├── 1. Analytics semantics and models
├── 2. Rolling metrics
├── 3. What Changed v2
├── 4. Spending Fingerprint
├── 5. Insights Engine
├── 6. MAD-based anomalies
├── 7. Hybrid forecasting
├── 8. Forecast backtesting
├── 9. Seasonal / advanced models
└── 10. Full BI interaction polish
```

The system should evolve from:

```text
Finance Tracker
```

into:

```text
Personal Finance Analytics
```

and eventually into:

```text
Personal Financial Intelligence
```

without sacrificing:

```text
accuracy
explainability
privacy
offline operation
data ownership
```

---

# 138. Definition of Success

This analytics roadmap is successful when FinScope can reliably say:

```text
You spent $363 more than last month.

Shopping explains 39% of that increase.

Most of the Shopping increase came from buying more often,
not from larger purchase sizes.

Food is also unusually high compared with your six-month norm.

Your discretionary spending has shifted toward weekends.

Based on your current pace and upcoming recurring bills,
you are likely to finish the month about $240 over budget.

Here are the transactions responsible.
```

At that point, FinScope is no longer merely recording money.

It is **explaining financial behaviour from the user's own data**.
