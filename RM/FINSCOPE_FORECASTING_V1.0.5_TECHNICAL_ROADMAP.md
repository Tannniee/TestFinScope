# FinScope Forecasting Technical Roadmap — v1.0.5

**Version tag:** `v1.0.5`  
**Primary scope:** Forecasting correctness, validation, calibration, and category reconciliation  
**Status:** Proposed technical roadmap  
**Target area:** Analytics / Forecasting / Backtesting / Forecast UI  
**Priority:** High

---

## 1. Purpose

`v1.0.5` should make FinScope's forecasting feature **correct, internally consistent, historically testable, and safer to present as a reliable month-end projection**.

The current forecasting architecture is directionally strong:

```text
Actual To Date
+ Known Future Recurring
+ Expected Remaining Variable
+ Expected Irregular
- Expected Refund
= Projected Month-End
```

However, several implementation gaps currently prevent FinScope from confidently claiming that the displayed forecast is historically validated.

The main goal of `v1.0.5` is therefore:

> **Make the production forecast engine and the validation system evaluate the same forecast logic, remove known correctness bugs, and introduce calibrated confidence/range outputs based on historical forecast error.**

This release should favour **correctness and explainability over model complexity**.

---

# 2. v1.0.5 Goals

## Core goals

1. Backtest the **actual production forecast engine** instead of a separate proxy model.
2. Fix recurring transaction scheduling so `frequency` and full due dates are respected.
3. Prevent recurring income from being counted twice.
4. Ensure category forecasts reconcile with the overall month-end forecast.
5. Replace history-length-only confidence with a more meaningful forecast reliability score.
6. Calibrate forecast ranges from historical residuals where sufficient evidence exists.
7. Select forecasting methods according to data sufficiency.
8. Improve robustness against irregular or extreme transactions.
9. Add regression tests for all forecast invariants introduced in this version.
10. Keep the forecasting output explainable to the user.

---

# 3. Non-Goals for v1.0.5

The following are intentionally **not required** for this release:

- Prophet
- XGBoost
- LSTM / deep learning
- external AI forecasting APIs
- macroeconomic forecasting
- bank-balance forecasting across multiple future months
- automatic tax forecasting
- advanced probabilistic Bayesian modelling
- multi-year long-range forecasting

These may be considered later if empirical backtesting shows the current lightweight models are insufficient.

For personal-finance data, model sophistication should only increase when sufficient historical data exists.

---

# 4. Current Forecasting Architecture

The current forecasting system conceptually separates month-end projection into:

```text
Projected Expense
= Actual Expense To Date
+ Upcoming Recurring Expense
+ Expected Remaining Variable Expense
```

and similarly for income.

This is a good foundation because each component has a clear financial meaning.

The system should continue to preserve this component structure in `v1.0.5`.

Recommended internal model:

```text
ForecastResult
├── actual_to_date
├── recurring_remaining
├── variable_remaining
├── irregular_expected
├── refunds_expected
├── projected_total
├── lower_bound
├── upper_bound
├── confidence
├── confidence_score
├── model_method
└── diagnostics
```

---

# 5. Current Issues Summary

| ID | Severity | Issue | Impact |
|---|---|---|---|
| F105-01 | P0 | Backtesting does not execute the real production forecast | Model quality cannot currently be proven |
| F105-02 | P0 | Recurring rule frequency is not fully respected | Weekly/fortnightly/month-boundary forecasts may be wrong |
| F105-03 | P0 | Recurring income may be double-counted | Projected income, net flow, and savings rate may be inflated |
| F105-04 | P0 | Category forecasts may not reconcile with overall forecast | Category totals can exceed overall projected spending |
| F105-05 | P1 | Confidence depends mainly on history length | “High confidence” may not mean high accuracy |
| F105-06 | P1 | Forecast range is heuristic rather than calibrated | “Likely range” may imply stronger statistical certainty than exists |
| F105-07 | P1 | Model eligibility is not strongly data-dependent | Sparse-history users may receive an unnecessarily complex model |
| F105-08 | P1 | Irregular/outlier transactions can distort variable-spend estimates | One-off spending can inflate future projections |
| F105-09 | P1 | Historical confidence/backtest logic may leak future information | Retrospective evaluation can appear better informed than real-time usage |
| F105-10 | P2 | Forecast diagnostics are limited | Harder to explain why a forecast changed |

---

# 6. P0 — Forecast Correctness

---

## F105-01 — Backtest the Actual Production Forecast

### Problem

The current backtesting engine evaluates a model labelled similar to a FinScope hybrid forecast, but it is not the same logic as the production month-end forecast.

A proxy model such as:

```text
0.5 × 3-month median
+ 0.3 × EWMA
+ 0.2 × previous month
```

cannot validate a production forecast based on:

```text
Actual To Date
+ Future Recurring
+ Weekday-Adjusted Remaining Variable Spend
```

This creates a validation mismatch.

### Required change

Historical backtesting must execute the **same forecasting service used by the live Forecast page**.

### Proposed design

Introduce an explicit historical replay interface:

```python
ForecastingEngine.forecast_month(
    target_month,
    as_of_date,
    account_ids=None,
    replay_mode=True
)
```

The engine must only use information that would have been available on `as_of_date`.

### Historical replay example

For August 2026:

```text
Target month: 2026-08
As-of date:   2026-08-15
```

The forecast may use:

- transactions dated on or before 15 August
- historical transactions before the cutoff
- recurring rules known by the cutoff
- calendar structure of the remaining month

It must not use:

- transactions after 15 August
- future-created recurring rules
- future forecast errors
- future history when deriving confidence

Then compare the projected month-end total against the actual August month-end total.

### Recommended backtest cutoffs

At minimum:

```text
Day 7
Day 14
Day 21
```

Preferred normalized cutoffs:

```text
25% of month elapsed
50% of month elapsed
75% of month elapsed
```

Optional additional cutoffs:

```text
Day 3
Day 10
Day 17
Day 24
```

### Metrics

Backtesting should report:

```text
MAE
Median Absolute Error
MAPE / sMAPE where valid
Bias
Over-forecast rate
Under-forecast rate
Sample count
```

Recommended:

```text
MAE = mean(abs(predicted - actual))
Bias = mean(predicted - actual)
```

Avoid relying only on percentage error for months with very low spending.

### Baseline models

Compare the production model against:

1. Current pace
2. Previous month
3. 3-month mean
4. 3-month median
5. EWMA
6. Seasonal naive when sufficient history exists

Example:

```text
FinScope Hybrid
vs
Current Pace
vs
3M Median
vs
EWMA
```

### Acceptance criteria

`v1.0.5` must not label FinScope Hybrid as “best” unless:

- the actual production forecast has been evaluated
- sufficient replay samples exist
- its validation metric is better than or competitive with simple baselines

If a simpler method consistently wins, the application should use or prefer the simpler method.

### Suggested affected files

```text
app/backend/analytics/forecasting.py
app/backend/analytics/backtesting.py
tests/test_analytics_v2.py
tests/test_v105_forecasting.py
```

Optional new module:

```text
app/backend/analytics/forecast_replay.py
```

---

## F105-02 — Fix Recurring Schedule Expansion

### Problem

Recurring rules include a `frequency` field, but forecast logic must ensure that frequency is actually respected.

A rule such as:

```text
$20 weekly
```

may have multiple occurrences remaining in the month.

Treating the rule as one future payment underestimates the forecast.

Likewise, comparing only the day-of-month portion of `next_due_date` can incorrectly pull a payment from another month into the target month.

### Required change

Forecasting must expand every recurring rule into all occurrences falling inside:

```text
as_of_date < occurrence_date <= target_month_end
```

### Proposed helper

```python
generate_occurrences(
    next_due_date,
    frequency,
    start_date,
    end_date
)
```

### Supported frequencies

At minimum:

```text
weekly
fortnightly
monthly
quarterly
yearly
```

If existing schema permits additional frequency values, define them centrally.

### Example

Rule:

```text
Amount: $20
Frequency: weekly
Next due date: 2026-09-12
Forecast cutoff: 2026-09-10
Month end: 2026-09-30
```

Expected occurrences:

```text
2026-09-12
2026-09-19
2026-09-26
```

Expected recurring contribution:

```text
$60
```

### Month-boundary rule

If:

```text
next_due_date = 2026-10-20
target_month = 2026-09
```

the September forecast contribution must be:

```text
$0
```

### Acceptance criteria

Tests must verify:

- monthly rule in target month
- rule due next month
- weekly rule with multiple remaining occurrences
- fortnightly rule
- month-end boundary
- leap year if relevant
- account-scoped recurring rule
- inactive recurring rule excluded

### Suggested affected files

```text
app/backend/analytics/forecasting.py
app/backend/database/schema.sql
tests/test_v105_forecasting.py
```

Prefer no schema migration unless the current frequency representation is insufficient.

---

## F105-03 — Prevent Recurring Income Double Counting

### Problem

Recurring income can be explicitly added as upcoming scheduled income while historical income-rate calculations may still include the same recurring salary transactions.

This can result in:

```text
Projected Income
= Actual Income
+ Future Salary
+ Variable Income Estimate Contaminated by Historical Salary
```

### Required change

Recurring income and non-recurring income must be modelled separately, in the same way recurring expenses are separated from variable expenses.

### Recommended rule

Variable income history should use:

```sql
transaction_type = 'income'
AND is_recurring = 0
```

Scheduled recurring income should come from recurring rules only.

### Preferred model

```text
Projected Income
= Actual Income To Date
+ Upcoming Recurring Income
+ Expected Remaining Non-Recurring Income
```

### Edge case

If recurring rules are incomplete or unreliable, the system should not silently estimate the same salary through two components.

### Acceptance criteria

Create a test dataset containing:

```text
Monthly salary: $5,000 recurring
Freelance income: variable
```

The salary must contribute exactly once to the remaining income forecast.

### Downstream fields to verify

```text
projected_income
projected_net_flow
projected_savings_rate
```

### Suggested affected files

```text
app/backend/analytics/forecasting.py
tests/test_v105_forecasting.py
```

---

## F105-04 — Reconcile Category Forecasts with Overall Forecast

### Problem

Category forecast weights may currently mix:

- current-month observed share
- historical category share

without normalization.

This can produce category weights summing above 100%.

Example:

```text
Food current share = 100%
Travel historical share = 20%
Total implied share = 120%
```

If total remaining variable spend is `$1,000`, category projections could allocate `$1,200`.

### Required invariant

For each forecast scope:

```text
SUM(category_remaining_variable)
= overall_remaining_variable
```

and preferably:

```text
SUM(category_projected_expense)
≈ overall_projected_expense
```

Any intentional difference must be explicitly explainable.

### Recommended implementation option A — normalized blended weights

For every category:

```text
raw_weight =
    alpha × current_month_share
    + beta × historical_share
```

Then normalize:

```text
normalized_weight_i
= raw_weight_i / SUM(raw_weight)
```

Finally:

```text
category_variable_i
= overall_remaining_variable × normalized_weight_i
```

### Recommended implementation option B — category-specific forecast

Preferred long-term approach:

Each category receives its own expected remaining variable estimate based on:

```text
historical weekday behaviour
recent category trend
current-month evidence
category-specific EWMA
```

Then reconcile:

```text
scale_factor
= overall_remaining_variable
/ SUM(raw_category_variable_estimates)
```

Apply:

```text
reconciled_category_i
= raw_category_i × scale_factor
```

This preserves overall forecast consistency while retaining category-level signal.

### Required category reconciliation test

```python
assert abs(
    sum(category.projected_variable for category in categories)
    - overall.remaining_variable
) <= rounding_tolerance
```

### Acceptance criteria

- No category allocation exceeds the total variable forecast.
- Category projections sum back to the overall forecast within rounding tolerance.
- Categories with no current-month spend may still receive projected spend if historical evidence supports it.
- Categories with no evidence should not receive arbitrary allocation.

### Suggested affected files

```text
app/backend/analytics/forecasting.py
app/frontend/assets/js/pages/analytics.js
tests/test_v105_forecasting.py
```

---

# 7. P1 — Forecast Reliability and Calibration

---

## F105-05 — Replace History-Only Confidence

### Problem

Confidence currently risks being interpreted as forecast accuracy even when it only represents history length.

Example problem:

```text
24 months of highly unstable spending → "High"
5 months of very stable spending → "Moderate"
```

This is not an adequate reliability measure.

### Proposed confidence model

Create a numerical score:

```text
confidence_score = 0–100
```

based on four components:

```text
Data Sufficiency
Historical Forecast Error
Behavioural Stability
Recurring Coverage
```

Suggested weighting:

```text
30% Data Sufficiency
35% Historical Forecast Error
20% Behavioural Stability
15% Recurring Coverage
```

Weights should remain configurable.

### Component examples

#### Data sufficiency

Consider:

```text
months of history
transaction count
number of complete historical months
```

#### Historical forecast error

Use the same forecast scope:

```text
same account selection
same transaction type
same category if category-level confidence
```

Example reliability transformation:

```text
lower historical normalized error
→ higher confidence component
```

#### Behavioural stability

Possible metric:

```text
median absolute deviation
coefficient of variation
weekday pattern stability
```

#### Recurring coverage

Confidence is stronger when a large proportion of expected fixed cashflow is represented by known recurring rules.

### Suggested label mapping

```text
0–39   = Low
40–69  = Moderate
70–84  = High
85–100 = Very High
```

Consider avoiding “Very High” until calibration quality is strong.

### UI suggestion

Show:

```text
Confidence: Moderate
```

Optional tooltip:

```text
Based on 8 months of history, 6 replay forecasts, and moderate spending variability.
```

### Important anti-leakage rule

When historically forecasting August from 15 August, confidence calculations must use only data available on or before 15 August.

### Acceptance criteria

Confidence level must change when:

- replay error improves/worsens
- history increases
- spending volatility changes
- recurring coverage changes

It must not depend only on months of history.

---

## F105-06 — Calibrate Forecast Range from Historical Residuals

### Problem

A heuristic range presented as “Likely” can imply statistical calibration that does not yet exist.

### Required change

Use empirical forecast residuals when sufficient historical replay data exists.

Define residual:

```text
residual = actual_month_end - predicted_month_end
```

For each forecast progress bucket:

```text
0–25%
25–50%
50–75%
75–100%
```

store historical residuals.

### Example

For forecasts created around the middle of the month:

```text
P10 residual = -$250
P90 residual = +$420
```

Current forecast:

```text
$3,000
```

Calibrated range:

```text
$2,750 – $3,420
```

### Recommended initial interval

Use an empirical 80% interval where enough samples exist.

Potential threshold:

```text
minimum 8–12 replay residuals
```

Below the threshold:

Use a conservative heuristic band and label it:

```text
Early estimate
```

instead of:

```text
Likely
```

### UI states

#### Insufficient calibration

```text
Early estimate: $2,800 – $3,500
```

#### Sufficient calibration

```text
Likely range: $2,900 – $3,350
```

Optional tooltip:

```text
Based on historical forecast errors from similar points in previous months.
```

### Acceptance criteria

- Range narrows later in the month when historical residuals support that behaviour.
- No claim of calibrated likelihood is shown without sufficient replay history.
- Residual samples must obey as-of-date isolation.

---

## F105-07 — Forecast Method Eligibility by Data Sufficiency

### Problem

One forecasting method should not be forced across every user.

A user with one month of history and a user with 24 months of history should not receive identical modelling logic.

### Proposed method ladder

#### Tier A — Minimal history

Eligibility:

```text
< 2 complete months
```

Use:

```text
Current Pace
+ Known Recurring
```

Confidence:

```text
Low
```

#### Tier B — Early history

Eligibility:

```text
2–5 complete months
```

Use:

```text
Recent Median / EWMA
+ Known Recurring
```

#### Tier C — Established history

Eligibility:

```text
6–11 complete months
```

Use:

```text
Weekday-Aware Hybrid
+ Known Recurring
+ robust recent trend
```

#### Tier D — Seasonal eligibility

Eligibility:

```text
>= 12 complete months
```

May compare:

```text
Weekday Hybrid
Seasonal Naive
EWMA
Recent Median
```

Select method using historical replay performance.

### Selection rule

Prefer the simplest model whose historical error is statistically or practically competitive.

Do not select a more complex method only because it exists.

### Example output

```json
{
  "model_method": "weekday_hybrid",
  "model_reason": "8 complete months; lowest recent replay MAE",
  "eligible_models": [
    "current_pace",
    "three_month_median",
    "ewma",
    "weekday_hybrid"
  ]
}
```

### Acceptance criteria

- Sparse-history users cannot be assigned a model requiring unavailable history.
- Model name displayed in UI matches the method that actually generated the forecast.
- Backtesting and production use identical method definitions.

---

## F105-08 — Robustness Against Irregular and Extreme Transactions

### Problem

Personal finance data is heavy-tailed.

Examples:

```text
holiday
annual insurance
laptop purchase
birthday dinner
medical bill
moving cost
flight purchase
```

A simple mean can interpret a one-off event as normal future behaviour.

### Proposed short-term solution

Before introducing an explicit irregular-spend model, use robust estimators.

Possible approaches:

```text
median
trimmed mean
winsorized mean
EWMA with outlier cap
median + recent-trend blend
```

### Recommended weekday estimator

For sufficiently large samples:

```text
weekday_expected
= 0.6 × weekday_median
+ 0.4 × recent_weekday_EWMA
```

Exact coefficients should be validated through replay.

### Optional outlier rule

Use robust deviation:

```text
median absolute deviation (MAD)
```

Flag strong one-offs as:

```text
irregular_candidate = true
```

Do not automatically delete them.

Instead decide whether they should contribute to:

```text
normal variable forecast
```

or:

```text
expected irregular component
```

### Important

Avoid aggressive outlier removal that hides genuine lifestyle changes.

A large purchase repeated for several weeks may represent a real new spending pattern.

### Acceptance criteria

A single extreme transaction should not dramatically alter the next forecast unless recent behaviour supports a persistent shift.

---

## F105-09 — Eliminate Historical Information Leakage

### Problem

Historical forecast validation is only meaningful if the replay engine sees exactly what the real user would have known at the historical cutoff.

Potential leakage sources include:

```text
transactions after cutoff
recurring rules created later
future months counted as available history
confidence based on future replay results
future category structure
```

### Required design

Every forecast-relevant query must accept:

```text
as_of_date
```

and apply it consistently.

### Recommended rule

Production forecast:

```text
as_of_date = today
```

Historical replay:

```text
as_of_date = historical cutoff
```

### Acceptance criteria

Add a regression test where a future transaction is deliberately inserted.

Historical forecast output must remain unchanged.

---

# 8. P2 — Forecast Quality and Explainability Enhancements

---

## F105-10 — Forecast Diagnostics

Add internal diagnostics to explain forecast composition.

Suggested payload:

```json
{
  "diagnostics": {
    "history_months": 8,
    "transaction_count": 412,
    "recurring_coverage_ratio": 0.61,
    "replay_sample_count": 15,
    "recent_mae_minor": 18400,
    "selected_method": "weekday_hybrid",
    "selection_reason": "Lowest replay MAE among eligible models"
  }
}
```

Do not expose every internal field in the main UI.

Use diagnostics for:

- development
- debugging
- tests
- optional user tooltips
- future model comparison

---

# 9. Recommended Forecasting Pipeline After v1.0.5

```text
1. Validate target month and cutoff
        ↓
2. Load actual transactions available at cutoff
        ↓
3. Separate recurring and non-recurring behaviour
        ↓
4. Expand future recurring schedule
        ↓
5. Determine eligible forecast models
        ↓
6. Estimate remaining variable cashflow
        ↓
7. Handle irregular/outlier evidence
        ↓
8. Build overall projected month-end total
        ↓
9. Produce category-level estimates
        ↓
10. Reconcile category totals to overall forecast
        ↓
11. Calculate historical reliability
        ↓
12. Generate calibrated/early-estimate range
        ↓
13. Return diagnostics + explainable components
```

---

# 10. Proposed Backend Interface

Recommended high-level API:

```python
ForecastingEngine.forecast_month(
    target_month: str,
    as_of_date: date,
    account_ids: list[int] | None = None,
) -> ForecastResult
```

Suggested result:

```python
ForecastResult(
    target_month,
    as_of_date,
    actual_expense_minor,
    recurring_expense_remaining_minor,
    variable_expense_remaining_minor,
    irregular_expense_expected_minor,
    projected_expense_minor,
    actual_income_minor,
    recurring_income_remaining_minor,
    variable_income_remaining_minor,
    projected_income_minor,
    projected_net_flow_minor,
    projected_savings_rate,
    lower_bound_minor,
    upper_bound_minor,
    range_type,
    confidence_score,
    confidence_label,
    model_method,
    category_forecasts,
    diagnostics,
)
```

---

# 11. Proposed Backtesting Architecture

Recommended separation:

```text
ForecastingEngine
    ↓
HistoricalReplayRunner
    ↓
BacktestingEvaluator
```

### ForecastingEngine

Responsible only for generating a forecast from data available at the cutoff.

### HistoricalReplayRunner

Responsible for creating historical forecast origins:

```text
2026-04-07
2026-04-14
2026-04-21
2026-05-07
...
```

### BacktestingEvaluator

Responsible for:

```text
prediction vs actual
metrics
model ranking
residual distributions
confidence calibration inputs
```

This separation avoids implementing another “fake FinScope Hybrid” inside `backtesting.py`.

---

# 12. Optional Backtest Persistence

For better performance and calibration, consider storing replay results.

Possible table:

```sql
forecast_backtest_results
```

Suggested columns:

```text
id
scope_hash
target_month
as_of_date
model_method
predicted_minor
actual_minor
absolute_error_minor
residual_minor
progress_ratio
created_at
```

Optional category fields:

```text
category_id
transaction_type
```

### Benefits

- Faster analytics page loading
- Historical accuracy chart
- Residual-based confidence intervals
- Method selection without rerunning all history
- Debugging model changes between versions

### Versioning

Include:

```text
forecast_model_version = "1.0.5"
```

so replay results can be invalidated after forecast logic changes.

---

# 13. Test Plan

Create a dedicated file:

```text
tests/test_v105_forecasting.py
```

Recommended groups:

---

## A. Recurring schedule tests

```text
test_monthly_rule_occurs_once
test_weekly_rule_occurs_multiple_times
test_fortnightly_rule_occurrences
test_future_month_rule_not_included
test_inactive_rule_not_included
test_recurring_rule_account_scope
```

---

## B. Income reconciliation tests

```text
test_recurring_salary_not_double_counted
test_non_recurring_income_still_forecast
test_projected_net_flow_uses_reconciled_income
```

---

## C. Category reconciliation tests

```text
test_category_variable_sum_matches_overall_variable
test_zero_current_spend_category_can_receive_historical_weight
test_category_weights_normalized
test_category_projected_total_matches_overall_within_rounding
```

---

## D. Historical replay tests

```text
test_replay_ignores_future_transactions
test_replay_uses_actual_forecasting_engine
test_replay_cutoff_day_7
test_replay_cutoff_day_14
test_replay_cutoff_day_21
```

---

## E. Confidence tests

```text
test_confidence_not_based_only_on_history_length
test_high_error_reduces_confidence
test_more_replay_samples_can_improve_confidence
test_historical_confidence_does_not_use_future_data
```

---

## F. Range calibration tests

```text
test_early_estimate_when_residual_history_insufficient
test_calibrated_range_when_residual_history_sufficient
test_range_uses_correct_progress_bucket
```

---

## G. Model eligibility tests

```text
test_sparse_history_uses_simple_model
test_established_history_enables_weekday_hybrid
test_seasonal_model_requires_12_months
test_displayed_method_matches_actual_method
```

---

# 14. Forecast Invariants

The following invariants should be explicitly tested.

### Expense reconciliation

```text
projected_expense
=
actual_expense_to_date
+ recurring_expense_remaining
+ variable_expense_remaining
+ irregular_expense_expected
- expected_refunds
```

### Income reconciliation

```text
projected_income
=
actual_income_to_date
+ recurring_income_remaining
+ variable_income_remaining
```

### Net flow

```text
projected_net_flow
=
projected_income
- projected_expense
```

### Category variable reconciliation

```text
SUM(category_variable_remaining)
=
overall_variable_remaining
```

### Range

```text
lower_bound <= projected_total <= upper_bound
```

### Non-negative components

Where financially appropriate:

```text
recurring_remaining >= 0
variable_remaining >= 0
```

Refunds should remain explicitly represented rather than silently becoming negative expenses if this conflicts with existing accounting semantics.

---

# 15. Frontend Changes

Suggested target:

```text
app/frontend/assets/js/pages/analytics.js
```

### Change confidence wording

Current concept:

```text
High / Moderate / Low
```

Keep label if desired, but support tooltip context.

Example:

```text
Moderate confidence
8 months history · 10 replay samples · medium variability
```

### Change range wording

Before calibrated residuals:

```text
Early estimate: $X – $Y
```

After sufficient calibration:

```text
Likely range: $X – $Y
```

### Method badge

Show only the method that actually generated the forecast.

Example:

```text
Weekday Hybrid
```

Do not show:

```text
Best Model
```

unless the current production method has actually won replay evaluation with sufficient samples.

Safer wording:

```text
Selected from historical performance
```

### Forecast explanation

Recommended expandable section:

```text
Projected month-end spend: $3,240

$1,820 spent so far
+ $620 scheduled bills
+ $800 expected variable spend
```

This preserves FinScope's strongest advantage: explainability.

---

# 16. Logging and Diagnostics

Add structured logging for forecast execution.

Recommended fields:

```text
target_month
as_of_date
account_scope
method
history_months
transaction_count
actual_to_date
recurring_remaining
variable_remaining
projected_total
confidence_score
range_type
```

Historical replay logs should also include:

```text
actual_month_end
absolute_error
residual
```

Avoid logging sensitive transaction descriptions where unnecessary.

---

# 17. Migration / Compatibility Strategy

Prefer `v1.0.5` to remain backward-compatible with existing user data.

### Recommended approach

1. Keep existing recurring rules.
2. Interpret existing `frequency` values centrally.
3. Add optional backtest persistence only if useful.
4. If adding a backtest table, make migration additive.
5. Do not rewrite or mutate historical user transactions.
6. Recompute forecasts from source transactions rather than migrating forecast values.

---

# 18. Performance Considerations

Historical replay can become expensive because one user may require:

```text
12 months × 3 cutoffs × multiple models
```

Recommended strategy:

### Phase 1

Run replay on demand for development/testing.

### Phase 2

Cache results using:

```text
forecast_model_version
scope_hash
target_month
as_of_date
```

### Phase 3

Incrementally recompute only affected replay periods after:

- transaction import
- transaction edit
- recurring rule edit
- forecasting algorithm version change

---

# 19. Rollout Order

Recommended implementation sequence:

---

## Phase 1 — Correctness

### Step 1
Fix recurring rule expansion.

### Step 2
Fix recurring income double counting.

### Step 3
Fix category reconciliation.

### Step 4
Add forecast invariants and regression tests.

**Release gate:** all P0 correctness tests pass.

---

## Phase 2 — Validation

### Step 5
Introduce `as_of_date` historical replay.

### Step 6
Rewrite backtesting to call the production forecast engine.

### Step 7
Add baseline model comparison.

### Step 8
Measure MAE, median AE, bias, and sample count.

**Release gate:** live forecast and backtested forecast use identical model definitions.

---

## Phase 3 — Reliability

### Step 9
Implement confidence score.

### Step 10
Add residual storage/aggregation.

### Step 11
Add calibrated forecast ranges.

### Step 12
Change UI wording for early estimates vs calibrated ranges.

---

## Phase 4 — Model Improvement

### Step 13
Introduce method eligibility.

### Step 14
Add robust median/EWMA weekday estimator.

### Step 15
Enable seasonal comparison for >=12 months of history.

### Step 16
Select best eligible model from historical performance.

---

# 20. Release Acceptance Criteria

`v1.0.5` should be considered complete when all of the following are true.

## Correctness

- [ ] Recurring frequency is respected.
- [ ] Future-month recurring rules are not included in the wrong month.
- [ ] Recurring income is not double counted.
- [ ] Overall and category forecasts reconcile.
- [ ] Forecast invariants pass automated tests.

## Validation

- [ ] Backtesting executes the actual production forecast.
- [ ] Historical replay uses an explicit cutoff date.
- [ ] Future transactions cannot leak into replay forecasts.
- [ ] Production forecast is compared with simple baselines.
- [ ] Model label shown in UI matches the model actually used.

## Reliability

- [ ] Confidence uses historical error, not only history length.
- [ ] Forecast range is labelled “Early estimate” when not calibrated.
- [ ] Residual-based ranges are used once enough replay samples exist.
- [ ] Historical confidence calculations do not use future information.

## Robustness

- [ ] Sparse-history users fall back to a simpler method.
- [ ] Outlier transactions do not excessively distort the forecast.
- [ ] Category forecasts behave sensibly when current-month spend is zero.

## UI

- [ ] Forecast breakdown remains explainable.
- [ ] No unsupported “Best Model” claim is displayed.
- [ ] Range and confidence wording accurately reflect evidence quality.

---

# 21. Suggested v1.0.5 Definition of Done

A forecast should be considered production-ready when FinScope can answer all five questions below:

### 1. What produced this number?

Example:

```text
Actual + recurring + expected variable
```

### 2. Does every component reconcile?

Example:

```text
category totals = overall total
```

### 3. Was this exact forecast logic historically tested?

Answer must be:

```text
Yes
```

### 4. How accurate has it been at similar points in previous months?

Example:

```text
Median absolute error: $180
```

### 5. Is the confidence/range evidence-based?

Example:

```text
Moderate confidence based on 9 replay samples
```

If FinScope can answer these consistently, forecasting becomes more than a visual estimate: it becomes a defensible analytics feature.

---

# 22. Future Candidates After v1.0.5

These should be evaluated only after the core system has sufficient replay evidence.

Possible future roadmap:

```text
v1.0.6
- category-specific forecasting
- improved irregular-spend classification
- historical forecast accuracy chart
- forecast change attribution

v1.0.7
- 3-month cashflow forecast
- seasonal recurring adjustments
- optional scenario planning

v1.1.x
- probabilistic models if data volume justifies them
- learned user-specific model weighting
- explicit income uncertainty modelling
```

---

# 23. Final Technical Direction

The recommended direction for FinScope is:

> **Do not increase model complexity before fixing correctness and validation.**

The current explainable hybrid structure is a strong base.

`v1.0.5` should therefore focus on:

```text
Correctness
→ Historical Replay
→ Calibration
→ Model Selection
→ Robustness
```

rather than:

```text
More Complex Model
→ More Features
→ More UI Claims
```

The key milestone is not “using a more advanced algorithm”.

The key milestone is:

> **The forecast shown to the user is the same forecast that has been historically replayed, measured, reconciled, and calibrated.**

That should be the defining technical standard for FinScope forecasting from `v1.0.5` onward.
