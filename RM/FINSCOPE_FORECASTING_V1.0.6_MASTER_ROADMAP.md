# FinScope Forecasting Upgrade Master Roadmap

**Proposed target:** `v1.0.6`  
**Scope:** Forecasting architecture, correctness, adaptability, robustness, and validation  
**Status:** Proposed implementation roadmap  
**Core philosophy:** **No ML. No giant rule tree. Explainable, local-first, low-data forecasting.**

---

# 1. Executive Summary

FinScope is a **personal finance application**, so per-user data is inherently small and sparse. Training a user-specific ML model is therefore not justified for the current product direction.

The target forecasting system should instead combine:

```text
Deterministic Financial Knowledge
+ Robust Statistical Forecasting
+ Multiple Small Forecast Strategies
+ Historical Replay
+ Adaptive Model Selection / Blending
+ Explicit User-Known Future Events
+ Empirical Uncertainty
```

The objective is **not** to imitate ML using hundreds of `if/else` cases.

The objective is to build a forecasting system where a small number of generic statistical strategies can adapt to different user behaviours through historical validation.

The design principle for FinScope should be:

> **Known future cashflows are calculated deterministically. Unknown future behaviour is estimated statistically. Historical replay decides which statistical strategy works best.**

---

# 2. Why FinScope Should Not Use ML

## 2.1 Personal data is too small

Typical user history may contain:

```text
1 month
3 months
6 months
12 months
```

A monthly ML model would therefore have only:

```text
1–12 training observations
```

Even daily modelling would remain:

- sparse
- highly user-specific
- full of zero-spend days
- affected by irregular purchases
- affected by lifestyle changes
- difficult to validate robustly

This creates a high overfitting risk.

---

## 2.2 ML does not solve unknown future events

No model can reliably infer future events that are absent from historical information, for example:

```text
buying a laptop
booking a flight
unexpected medical expense
car repair
one-off bonus
moving house
holiday
large gift
```

A statistical system with explicit planned-event support may outperform a black-box model in these cases.

---

## 2.3 Explainability is more valuable than sophistication

For a personal finance app, the user should be able to understand:

```text
Projected spend: $3,240

$1,820 already spent
+ $620 scheduled recurring bills
+ $800 expected variable spending
```

This is more trustworthy than:

```text
AI predicts: $3,240
```

---

# 3. Final Product Principle

FinScope forecasting should be based on three layers.

```text
┌──────────────────────────────────────────┐
│          FIN SCOPE FORECAST              │
├──────────────────────────────────────────┤
│ 1. Deterministic Layer                   │
│    - recurring bills                     │
│    - salary                              │
│    - scheduled transactions              │
│    - refunds                             │
│    - manual planned events               │
├──────────────────────────────────────────┤
│ 2. Statistical Behaviour Layer           │
│    - current pace                        │
│    - recent median                       │
│    - robust weekly residual              │
│    - weekday pattern                     │
│    - seasonal naive                      │
│    - recent-trend adjustments            │
├──────────────────────────────────────────┤
│ 3. Validation / Uncertainty Layer        │
│    - historical replay                   │
│    - comparable model scoring            │
│    - adaptive selection / ensemble       │
│    - confidence                          │
│    - calibrated range                    │
└──────────────────────────────────────────┘
```

---

# 4. Lessons from Other Open-Source Forecasting Repositories

Several useful patterns were identified from comparable open-source projects.

---

## 4.1 BudgetPilot

### Relevant design

BudgetPilot separates:

```text
Recurring cashflows
vs
Residual non-recurring behaviour
```

Recurring streams include concepts such as:

```text
cadence
confidence
staleness
amount variability
interval variability
```

It does not blindly forecast every detected recurring stream.

### Important residual-spending approach

After removing recurring transactions, BudgetPilot creates a dense historical series and estimates residual behaviour using weekly aggregation.

Example:

```text
Week 1: $320
Week 2: $280
Week 3: $350
Week 4: $1,400
Week 5: $300
```

Instead of using a simple mean:

```text
median(weekly spend) / 7
```

produces a robust daily residual rate.

### FinScope takeaway

Add a candidate strategy:

```text
RobustWeeklyResidual
```

This should be tested against the current Weekday Hybrid.

---

## 4.2 Leeway

### Relevant design

Leeway uses multiple small forecasting methods such as:

```text
Static
Previous Month
Average Previous 3
Same Month Last Year
Overall Average
```

A method is only available if sufficient data exists.

### FinScope takeaway

Use a **Strategy Pattern** rather than central `if/else` logic.

Each forecasting model should define:

```python
is_eligible(context)
predict(context)
explain(context)
```

The engine should not contain model-specific decision trees.

---

## 4.3 Budget Projection

### Relevant design

This project focuses on deterministic projection rather than behavioural prediction.

Key idea:

```text
Projected future balance
=
latest actual balance
+ known future cashflow
```

Actual snapshots re-anchor future projections.

### FinScope takeaway

FinScope already has an advantage because transaction data continuously re-anchors month-to-date actuals.

Do not chain:

```text
forecast → forecast → forecast
```

Always anchor on real observed transactions.

---

## 4.4 Ledgerly

### Relevant design

Although the application includes AI features, its financial forecasting remains statistical.

The forecast uses:

```text
historical category medians
+
recurring baseline
```

### FinScope takeaway

AI branding does not imply that numerical finance forecasting requires AI.

Robust statistics remain appropriate for personal finance.

---

## 4.5 Butterfly Effect

### Relevant design

Butterfly Effect combines:

```text
recurring schedule
calendar events
manual scenarios
overrides
```

into a future cashflow timeline.

Users can explicitly:

```text
skip a payment
change an amount
change a date
add a one-off future expense
add a one-off future income
```

### FinScope takeaway

Do not try to statistically infer every future event.

Add support for:

```text
Planned Events / What-if Events
```

Explicit user knowledge is better than prediction when the future event is known.

---

# 5. Current FinScope State

The current forecasting implementation already contains several strong components.

## Implemented strengths

```text
actual-to-date anchoring
recurring schedule expansion
weekly / fortnightly support
recurring-income separation
weekday-aware variable forecast
normalized category allocation
historical replay
confidence scoring
residual-based range support
data-sufficiency-aware forecasting
v1.0.5 regression tests
```

These should be preserved.

---

# 6. Remaining Correctness Issues Before Further Model Expansion

Before introducing more forecast strategies, the validation infrastructure must be trustworthy.

---

## F106-01 — Point-in-Time Recurring Rule History

### Current risk

Historical replay can still read the current state of recurring rules.

Example:

```text
January:
Rent rule = $500

June:
Rent edited to $600

Replay January today:
may incorrectly see $600
```

Deletion creates a similar issue.

### Required solution

Recurring rules need historical validity.

Preferred design:

```text
recurring_rule_versions
```

Suggested fields:

```text
id
rule_id
valid_from
valid_to
account_id
transaction_type
amount_minor
frequency
next_due_date
active
created_at
```

Historical replay must resolve:

```text
rule version valid at as_of_date
```

Alternative:

```text
recurring_rule_events
```

with create/update/delete events.

### Acceptance criterion

Historical replay must reproduce the recurring information that existed at the historical cutoff.

---

## F106-02 — Replay the Production Policy, Not Only One Candidate Model

Historical replay should evaluate two different concepts.

### A. Production Policy

This represents exactly what FinScope would have shown to the user at that historical date.

Example:

```text
low history → Current Pace
medium history → Recent Median
enough history → selected statistical strategy
```

### B. Candidate Strategy Evaluation

This evaluates individual models independently:

```text
CurrentPace
RecentMedian
RobustWeeklyResidual
WeekdayHybrid
SeasonalNaive
```

These must not be confused.

### Recommended model IDs

```text
production_policy
current_pace
recent_median
robust_weekly
weekday_hybrid
seasonal_naive
```

### Acceptance criterion

The main historical accuracy metric shown for FinScope must represent:

```text
production_policy
```

not a forced candidate.

---

## F106-03 — Dense Calendar Series / Zero-Filled Months

Historical data must preserve calendar continuity.

Bad:

```text
Jan
Mar
Apr
```

Correct:

```text
Jan
Feb = 0
Mar
Apr
```

Otherwise:

```text
previous month
seasonal naive
trend
```

can reference the wrong period.

### Required utilities

```python
build_dense_daily_series(...)
build_dense_weekly_series(...)
build_dense_monthly_series(...)
```

---

## F106-04 — Replay Cache Invalidation

Cache keys based only on:

```text
MAX(transaction_date)
COUNT(transactions)
```

are insufficient.

Editing:

```text
$100 → $500
```

may not invalidate the cache.

### Preferred design

Create:

```text
analytics_revision
```

Increment whenever relevant data changes:

```text
transaction create
transaction edit
transaction delete
recurring rule create
recurring rule update
recurring rule delete
```

Cache key:

```text
forecast_model_version
+ analytics_revision
+ scope
```

---

## F106-05 — Confidence Must Follow Selected Forecast Strategy

Confidence should evaluate the actual model/policy being displayed.

Bad:

```text
Current forecast = RecentMedian
Confidence error component = WeekdayHybrid historical MAE
```

Correct:

```text
Current forecast = RecentMedian
Confidence error component = RecentMedian / production-policy historical error
```

---

## F106-06 — Shared Recurring Scheduler

Recurring forecast and Upcoming Bills UI must use the same scheduler.

Create one source of truth:

```text
recurring/
    scheduler.py
```

Suggested interface:

```python
generate_occurrences(
    rule,
    start_date,
    end_date
)
```

Both:

```text
ForecastingEngine
UpcomingBillsService
```

must call it.

---

## F106-07 — Uncategorized and Refund Reconciliation

Category forecast must include:

```text
Uncategorised
```

as a synthetic category where necessary.

Suggested:

```text
category_id = 0
name = "Uncategorised"
```

Refunds must not silently break category-to-overall reconciliation.

Required invariant:

```text
SUM(category_projected)
≈ overall_projected
```

within rounding/accounting tolerance.

---

# 7. Avoiding the Giant `if/else` Problem

The central forecasting engine should never become:

```python
if history < 2:
    ...
elif history < 6:
    ...
elif weekday_pattern:
    ...
elif payday:
    ...
elif volatile:
    ...
elif category == "...":
    ...
```

Instead use:

```text
Strategy Registry
+
Forecast Context
+
Historical Scoring
```

---

# 8. Proposed Architecture

```text
analytics/
│
├── forecasting/
│   ├── engine.py
│   ├── context.py
│   ├── result.py
│   ├── reconciliation.py
│   ├── uncertainty.py
│   │
│   ├── models/
│   │   ├── base.py
│   │   ├── current_pace.py
│   │   ├── recent_median.py
│   │   ├── robust_weekly.py
│   │   ├── weekday_hybrid.py
│   │   └── seasonal_naive.py
│   │
│   ├── signals/
│   │   ├── trend.py
│   │   ├── volatility.py
│   │   ├── change_detection.py
│   │   ├── weekday_strength.py
│   │   └── recurring_coverage.py
│   │
│   ├── selection/
│   │   ├── registry.py
│   │   ├── scorer.py
│   │   ├── selector.py
│   │   └── ensemble.py
│   │
│   └── series/
│       ├── daily.py
│       ├── weekly.py
│       └── monthly.py
│
├── backtesting/
│   ├── replay.py
│   ├── evaluator.py
│   ├── metrics.py
│   └── cache.py
│
└── recurring/
    ├── scheduler.py
    └── history.py
```

---

# 9. Forecast Context

Models should not query the database independently.

Build one reusable immutable context.

Example:

```python
ForecastContext(
    target_month,
    as_of_date,

    actual_expense_to_date,
    actual_income_to_date,

    historical_daily_non_recurring,
    historical_weekly_non_recurring,
    historical_monthly_non_recurring,

    recurring_future_expense,
    recurring_future_income,

    remaining_days,
    remaining_weekdays,

    history_months,
    transaction_count,

    volatility,
    recent_trend,
    weekday_strength,
    recurring_coverage,

    category_history,
)
```

Benefits:

```text
less duplicate SQL
less leakage
easier tests
consistent model inputs
simpler model implementation
```

---

# 10. Forecast Strategy Interface

```python
class ForecastStrategy:
    id: str

    def is_eligible(self, context) -> bool:
        ...

    def predict(self, context) -> ForecastEstimate:
        ...

    def explain(self, context) -> str:
        ...
```

Suggested result:

```python
ForecastEstimate(
    model_id,
    remaining_variable_minor,
    diagnostics,
)
```

---

# 11. Initial Statistical Model Pool

Do **not** start with 15 models.

Use a small, interpretable pool.

---

## 11.1 Current Pace

### Purpose

Fallback for very limited history.

```text
Observed non-recurring spend
÷ elapsed days
× remaining days
```

Use robust safeguards for very early month dates.

---

## 11.2 Recent Monthly Median

### Purpose

Stable fallback for users without strong weekday patterns.

Example:

```text
median(last 3 complete comparable months)
```

Adjust for actual-to-date and recurring separation.

---

## 11.3 Robust Weekly Residual

Inspired by BudgetPilot.

### Pipeline

```text
Transactions
↓
remove recurring
↓
dense daily series
↓
aggregate complete weeks
↓
median weekly total
↓
daily equivalent
↓
remaining days
```

Formula:

```text
expected_daily_variable
=
median(complete_week_totals) / 7
```

Advantages:

```text
robust to one-off purchases
handles sparse transaction days
simple
easy to explain
```

---

## 11.4 Weekday Hybrid

Keep the existing weekday-aware strategy.

Estimate behaviour by calendar weekday.

Possible robust form:

```text
weekday_estimate
=
median weekday behaviour
+
recent trend adjustment
```

Avoid relying only on means.

---

## 11.5 Seasonal Naive

Only eligible with sufficient history.

Example:

```text
same calendar month last year
```

Minimum:

```text
>= 12 complete calendar months
```

This must use dense calendar months.

---

# 12. Signals Instead of Cases

FinScope should not encode every lifestyle scenario.

Extract generic signals.

---

## 12.1 Volatility

Possible metric:

```text
MAD
coefficient of variation
IQR
```

Used for:

```text
confidence
outlier sensitivity
model weighting
```

---

## 12.2 Recent Trend

Example:

```text
recent_30_day_rate
/
historical_rate
```

Do not interpret why spending changed.

Only detect that it changed.

---

## 12.3 Weekday Strength

Measure whether weekday behaviour is sufficiently consistent to justify a weekday model.

Example:

```text
between-weekday variance
vs
within-weekday variance
```

---

## 12.4 Change Detection

Detect regime shift.

Example:

```text
recent median
vs
historical median
```

If materially different:

```text
increase recency weight
```

This can handle many lifestyle changes without knowing the cause.

---

## 12.5 Recurring Coverage

Example:

```text
known recurring future cashflow
/
expected total future cashflow
```

Higher recurring coverage generally increases forecast confidence.

---

# 13. Model Eligibility

Each model owns its own eligibility criteria.

Example:

```python
class SeasonalNaive:
    def is_eligible(self, ctx):
        return ctx.complete_history_months >= 12
```

Central engine:

```python
eligible_models = [
    model
    for model in registry
    if model.is_eligible(context)
]
```

No central method-specific rule tree.

---

# 14. Historical Replay as the Decision Engine

The most important adaptive component should be historical replay.

For each candidate:

```text
Historical cutoff
↓
forecast using only historical information
↓
compare with actual month end
↓
record error
```

Metrics:

```text
MAE
Median Absolute Error
Bias
WAPE / sMAPE where valid
Overforecast rate
Underforecast rate
Sample count
```

---

# 15. Comparable-Origin Model Scoring

Do not label a model “Best” if it was tested on only a small/easier subset.

Example:

```text
Weekday Hybrid
MAE = $180
36 origins

Seasonal Naive
MAE = $150
3 origins
```

This is not a fair direct comparison.

Preferred ranking:

```text
common historical origins
```

or require:

```text
minimum comparable sample count
```

UI wording:

```text
Lowest MAE on comparable periods
```

rather than:

```text
Best Model
```

---

# 16. Adaptive Model Selection

Initial implementation should remain simple.

### Selection rule

1. Find eligible models.
2. Get historical replay scores.
3. Restrict to comparable origins.
4. Reject models with insufficient samples.
5. Select the lowest robust error.

Possible ranking metric:

```text
Median Absolute Error
```

with MAE and bias as diagnostics.

### Fallback

If replay evidence is insufficient:

```text
choose simplest eligible robust strategy
```

---

# 17. Optional Ensemble

Ensemble should be introduced **after** individual model replay is trustworthy.

Do not hardcode:

```text
50% weekday
30% EWMA
20% median
```

Possible weight:

```text
weight_i ∝ 1 / error_i
```

with safeguards:

```text
minimum samples
weight cap
bias penalty
stability penalty
```

Example:

```text
Weekday Hybrid  45%
Robust Weekly   35%
Recent Median   20%
```

### Important

Ensemble is optional for `v1.0.6`.

A strong automatic single-model selector is acceptable first.

---

# 18. Irregular Spending

Do not write merchant-specific rules such as:

```python
if merchant == "Apple":
if category == "Flights":
```

Use statistical irregularity.

Possible candidate:

```text
amount
>
median + k × MAD
```

or daily-total anomaly detection.

### Important rule

Do not delete irregular transactions from history blindly.

Classify them as:

```text
irregular_candidate
```

Then prevent a single one-off from dominating regular variable behaviour.

A repeated change should eventually be treated as new behaviour.

---

# 19. Explicit Planned Events

Some future information cannot be inferred from history.

Add optional user-planned events:

```text
Planned Expense
Planned Income
Skip Recurring Occurrence
Override Recurring Amount
Override Recurring Date
```

Example:

```text
Flight
-$1,200
2026-09-25
```

This is superior to trying to statistically predict an event the app cannot know.

---

# 20. Planned Event Data Model

Possible table:

```sql
forecast_planned_events
```

Fields:

```text
id
account_id
event_date
transaction_type
amount_minor
category_id
description
source
active
created_at
updated_at
```

Possible source:

```text
manual
scenario
calendar
```

These should be merged into known future cashflow.

---

# 21. Final Forecast Equation

Expense:

```text
Projected Expense
=
Actual Expense To Date
+ Confirmed Future Recurring Expense
+ Planned Future Expense
+ Expected Remaining Variable Expense
+ Expected Irregular Adjustment
- Expected Refunds
```

Income:

```text
Projected Income
=
Actual Income To Date
+ Confirmed Future Recurring Income
+ Planned Future Income
+ Expected Remaining Variable Income
```

Net flow:

```text
Projected Net Flow
=
Projected Income
-
Projected Expense
```

---

# 22. Reconciliation Rules

Required invariants:

```text
projected_expense
=
actual
+ recurring
+ planned
+ variable
+ irregular
- refunds
```

```text
projected_income
=
actual
+ recurring
+ planned
+ variable
```

```text
projected_net_flow
=
projected_income
- projected_expense
```

Category:

```text
SUM(category_variable)
=
overall_variable
```

and where possible:

```text
SUM(category_projected_expense)
≈ overall_projected_expense
```

---

# 23. Forecast Range

Historical residual:

```text
residual
=
actual_month_end
-
forecast_month_end
```

Store residuals by forecast progress bucket:

```text
0–25%
25–50%
50–75%
75–100%
```

When sufficient data exists:

```text
empirical interval
```

Example:

```text
P10 residual = -$220
P90 residual = +$370
```

Forecast:

```text
$3,000
```

Range:

```text
$2,780 – $3,370
```

---

# 24. Range Wording

Insufficient replay samples:

```text
Early estimate
```

Sufficient calibrated replay samples:

```text
Likely range
```

Do not imply calibration when it does not exist.

---

# 25. Confidence

Confidence should combine:

```text
Data Sufficiency
Historical Forecast Error
Behavioural Stability
Recurring / Known Cashflow Coverage
```

Possible structure:

```text
30% data sufficiency
35% historical error
20% stability
15% known-cashflow coverage
```

Exact weights are tunable.

Confidence must use the selected strategy or production-policy replay performance.

---

# 26. Configuration Instead of Scattered Constants

Centralize thresholds.

Example:

```yaml
forecast:
  history:
    seasonal_min_months: 12
    weekday_min_samples: 6

  replay:
    minimum_model_origins: 6
    calibrated_range_min_origins: 8

  outlier:
    method: mad
    threshold: 3.0

  change_detection:
    recent_window_days: 30
    threshold_ratio: 1.35

  ensemble:
    enabled: false
    max_models: 3
```

Do not scatter values across many functions.

---

# 27. Target Forecast Engine

The engine should become orchestration only.

Conceptually:

```python
context = context_builder.build(...)

known_cashflow = known_cashflow_service.calculate(context)

eligible = model_registry.get_eligible(context)

scores = replay_evaluator.get_scores(
    eligible,
    context.scope,
)

strategy = selector.select(
    eligible,
    scores,
)

variable_estimate = strategy.predict(context)

result = reconciliation.build(
    actual=context.actual,
    known=known_cashflow,
    variable=variable_estimate,
)

result = uncertainty.attach(
    result,
    strategy,
    scores,
)

return result
```

The engine should not know the internal formula of each strategy.

---

# 28. Diagnostics

Return useful internal diagnostics.

Example:

```json
{
  "selected_model": "robust_weekly",
  "selection_reason": "Lowest median absolute error on 8 comparable replay origins",
  "history_months": 9,
  "transaction_count": 382,
  "weekday_strength": 0.42,
  "volatility": 0.31,
  "recurring_coverage": 0.58,
  "replay_origins": 8,
  "median_absolute_error_minor": 17200
}
```

Use for:

```text
tests
developer debugging
tooltips
future forecast accuracy screen
```

---

# 29. Recommended UI

Main forecast:

```text
Projected Month-End Spend
$3,240
```

Breakdown:

```text
$1,820 spent so far
+ $620 scheduled
+ $800 expected variable spending
```

Model:

```text
Forecast method: Robust Weekly
```

Selection explanation:

```text
Selected from your recent historical performance.
```

Confidence:

```text
Moderate confidence
```

Range:

```text
Likely range: $2,980 – $3,460
```

or:

```text
Early estimate: $2,850 – $3,620
```

---

# 30. Rollout Plan

---

## Phase 1 — Validation Integrity

Priority: **P0**

Implement:

```text
point-in-time recurring history
production-policy historical replay
dense calendar series
cache invalidation
shared recurring scheduler
uncategorised/refund reconciliation
```

Do not introduce new statistical models before this phase is reliable.

### Exit criteria

Historical replay must represent what FinScope genuinely knew at the historical cutoff.

---

## Phase 2 — Forecast Strategy Architecture

Priority: **P0/P1**

Refactor into:

```text
ForecastContext
ForecastStrategy
ModelRegistry
ModelSelector
```

Migrate current logic into:

```text
CurrentPace
RecentMedian
WeekdayHybrid
SeasonalNaive
```

No behaviour change required initially.

### Exit criteria

Adding a new forecast model must not require modifying the central forecast engine.

---

## Phase 3 — Robust Weekly Residual

Priority: **P1**

Implement:

```text
dense daily residual series
complete weekly aggregation
median weekly estimator
```

Add:

```text
RobustWeeklyResidual
```

Backtest against existing strategies.

### Exit criteria

Do not promote the new strategy unless replay performance supports it.

---

## Phase 4 — Adaptive Selection

Priority: **P1**

Implement comparable-origin scoring.

Select the historically strongest eligible strategy.

Fallback to simplest stable strategy when evidence is insufficient.

### Exit criteria

Displayed model name must exactly match the method generating the forecast.

---

## Phase 5 — Statistical Signals

Priority: **P1/P2**

Add:

```text
volatility
recent trend
weekday strength
change detection
recurring coverage
```

Use signals to:

```text
control eligibility
adjust recency
calculate confidence
improve diagnostics
```

Avoid behaviour-specific case trees.

---

## Phase 6 — Planned Events / Overrides

Priority: **P2**

Allow user to provide future knowledge.

Implement:

```text
planned expense
planned income
skip recurring event
override amount
override date
```

### Exit criteria

Planned event must reconcile into the same forecast equation and category totals.

---

## Phase 7 — Optional Ensemble

Priority: **P2**

Only implement after single-model historical evaluation is stable.

Use empirical model performance for weights.

Do not hardcode permanent mixture weights.

---

# 31. Test Plan

Create / extend:

```text
tests/test_v106_forecasting.py
```

---

## A. Historical integrity

```text
test_replay_uses_rule_version_valid_at_cutoff
test_replay_does_not_use_future_rule_creation
test_replay_does_not_use_future_rule_edit
test_replay_handles_deleted_historical_rule
test_replay_ignores_future_transaction
test_replay_cache_invalidates_on_transaction_edit
test_replay_cache_invalidates_on_rule_edit
```

---

## B. Dense series

```text
test_dense_daily_zero_fill
test_dense_monthly_zero_fill
test_previous_month_respects_calendar_gap
test_seasonal_naive_uses_exact_prior_year_month
```

---

## C. Strategy architecture

```text
test_registry_returns_only_eligible_models
test_engine_does_not_require_model_specific_branch
test_displayed_model_matches_selected_strategy
test_fallback_when_replay_insufficient
```

---

## D. Robust weekly model

```text
test_weekly_model_uses_complete_weeks
test_weekly_model_zero_fills_no_spend_days
test_weekly_median_resists_single_large_outlier
test_weekly_model_excludes_recurring_transactions
```

---

## E. Comparable scoring

```text
test_models_ranked_on_common_origins
test_low_sample_model_not_declared_best
test_bias_reported
test_production_policy_replay_uses_real_selector
```

---

## F. Category reconciliation

```text
test_uncategorised_expense_included
test_uncategorised_refund_included
test_category_sum_matches_overall
test_rounding_drift_reconciled
```

---

## G. Planned events

```text
test_planned_expense_added_once
test_planned_income_added_once
test_skip_recurring_occurrence
test_override_recurring_amount
```

---

## H. Confidence / range

```text
test_confidence_uses_selected_model_error
test_no_replay_does_not_produce_false_high_confidence
test_early_estimate_without_enough_residuals
test_calibrated_range_with_enough_residuals
test_range_uses_matching_progress_bucket
```

---

# 32. Definition of Done

The forecasting upgrade is considered successful when:

## Architecture

- [ ] No giant model-selection `if/else` tree exists.
- [ ] Every statistical strategy implements a shared interface.
- [ ] New models can be added independently.
- [ ] Thresholds are centrally configured.

## Correctness

- [ ] Recurring schedules use one shared scheduler.
- [ ] Historical recurring data is point-in-time correct.
- [ ] Replay does not use future information.
- [ ] Dense calendar series are used where required.
- [ ] Category and overall projections reconcile.

## Validation

- [ ] Production-policy forecast is historically replayed.
- [ ] Candidate models are evaluated separately.
- [ ] Model comparisons use comparable origins.
- [ ] Low-sample models are not incorrectly promoted.
- [ ] Replay cache invalidates on relevant data mutation.

## Forecasting

- [ ] Current Pace available.
- [ ] Recent Median available.
- [ ] Robust Weekly Residual available.
- [ ] Weekday Hybrid available.
- [ ] Seasonal Naive only eligible with enough history.
- [ ] Historical evidence drives model selection.

## Reliability

- [ ] Confidence reflects actual selected-model performance.
- [ ] Residual-based range is calibrated when possible.
- [ ] Early estimate wording is used when calibration is insufficient.

## Product

- [ ] User can understand forecast composition.
- [ ] Known future events are deterministic.
- [ ] Planned events can be manually included.
- [ ] No unsupported claim of AI or guaranteed accuracy is made.

---

# 33. What FinScope Should Not Become

Avoid:

```text
hundreds of spending-specific rules
merchant-specific forecasting logic
category-specific hardcoded behaviour
black-box AI forecast
user-specific ML training
one giant hybrid formula
a leaderboard comparing models on different periods
confidence based only on history length
```

---

# 34. Long-Term Forecasting Philosophy

FinScope should not attempt to answer:

> “Can the code predict every possible future behaviour?”

That is impossible for both statistical systems and ML.

FinScope should instead answer:

> “Given what is currently known, what is the most defensible estimate of the rest of this month, how was it calculated, and how uncertain has this type of estimate historically been?”

That framing produces a system that is:

```text
personal
local-first
low-data friendly
explainable
maintainable
testable
adaptive
statistically defensible
```

---

# 35. Final Target Architecture

```text
                       TRANSACTIONS
                            │
                            ↓
                    ForecastContext
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
         ↓                  ↓                  ↓
   Known Cashflow      Behaviour Series    User Plans
     / Recurring       / Statistical       / Overrides
         │                  │                  │
         │       ┌──────────┼──────────┐       │
         │       ↓          ↓          ↓       │
         │     Pace       Weekly     Weekday    │
         │                 Median     Hybrid    │
         │       └──────────┼──────────┘       │
         │                  ↓                  │
         │          Historical Replay          │
         │                  ↓                  │
         │        Selection / Ensemble         │
         │                  │                  │
         └──────────────────┼──────────────────┘
                            ↓
                     Reconciliation
                            ↓
                  Month-End Projection
                            ↓
                    Error Calibration
                            ↓
                   Confidence + Range
```

---

# 36. Recommended Immediate Next Step

Do **not** start by adding another forecast formula.

Start with the structural foundation:

```text
1. Make historical replay fully point-in-time safe.
2. Separate production-policy replay from candidate-model replay.
3. Introduce ForecastStrategy + ModelRegistry.
4. Move existing forecast methods behind the strategy interface.
5. Add RobustWeeklyResidual as the first new candidate.
6. Let historical replay determine whether it deserves selection.
```

This is the cleanest path to improving FinScope forecasting without ML and without allowing the codebase to grow into an unmaintainable rule system.
