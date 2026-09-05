"""
Historical Replay Runner for FinScope Forecasting v1.0.5.
Executes the actual production forecasting engine at historical cutoffs
(e.g., Day 7, Day 14, Day 21) across completed historical months,
evaluates real forecast accuracy against naive baselines, and collects
empirical residuals for calibrated confidence intervals.
"""

import calendar
from datetime import date, datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from app.backend.database.connection import get_db_connection
from app.backend.analytics.rolling import calculate_mean, calculate_median, calculate_ewma

# Cache structure: (account_id, max_tx_date, tx_count) -> replay_results
_REPLAY_CACHE: Dict[Tuple[Optional[int], str, int], Dict[str, Any]] = {}
_RESIDUALS_BY_BUCKET_CACHE: Dict[Tuple[Optional[int], str, int], Dict[int, List[int]]] = {}


def get_progress_bucket(progress: float) -> int:
    """
    Maps progress (0.0 to 1.0) into 4 discrete buckets:
    0: 0% <= p < 25%
    1: 25% <= p < 50%
    2: 50% <= p < 75%
    3: 75% <= p <= 100%
    """
    if progress < 0.25:
        return 0
    elif progress < 0.50:
        return 1
    elif progress < 0.75:
        return 2
    else:
        return 3


def calculate_percentile(values: List[int], percentile: float) -> int:
    """Calculates nearest-rank percentile for a list of integer amounts."""
    if not values:
        return 0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = (percentile / 100.0) * (n - 1)
    low = int(idx)
    high = min(n - 1, low + 1)
    weight = idx - low
    return round(sorted_vals[low] * (1.0 - weight) + sorted_vals[high] * weight)


def generate_calendar_months(start_m: str, end_m: str) -> List[str]:
    """Generates continuous sequence of calendar months YYYY-MM from start_m to end_m."""
    sy, sm = map(int, start_m.split("-"))
    ey, em = map(int, end_m.split("-"))
    res = []
    cy, cm = sy, sm
    while (cy < ey) or (cy == ey and cm <= em):
        res.append(f"{cy:04d}-{cm:02d}")
        cm += 1
        if cm > 12:
            cm = 1
            cy += 1
    return res


class HistoricalReplayRunner:
    @staticmethod
    def _get_cache_key(account_id: Optional[int]) -> Tuple:
        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " WHERE account_id = ?" if account_id else ""
            params = [account_id] if account_id else []
            cur.execute(f"""
                SELECT 
                    MAX(COALESCE(updated_at, transaction_date)) as max_u,
                    MAX(transaction_date) as max_d,
                    COUNT(id) as c,
                    COALESCE(SUM(amount_minor), 0) as s
                FROM active_transactions{acc_clause}
            """, params)
            tx_row = cur.fetchone()

            rec_acc_clause = " WHERE account_id = ?" if account_id else ""
            cur.execute(f"""
                SELECT COUNT(id) as rc, COALESCE(SUM(amount_minor), 0) as rs
                FROM recurring_rules{rec_acc_clause}
            """, params)
            rec_row = cur.fetchone()

            return (
                "1.0.7",
                account_id,
                tx_row["max_u"] or "",
                tx_row["max_d"] or "",
                tx_row["c"] or 0,
                tx_row["s"] or 0,
                rec_row["rc"] or 0,
                rec_row["rs"] or 0
            )


    @staticmethod
    def get_actual_month_end_net_spend(month_str: str, account_id: Optional[int] = None) -> int:
        """Computes true historical month-end net spending (expense - refunds) for `month_str`."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND account_id = ?" if account_id else ""
            params = [f"{month_str}%"] + ([account_id] if account_id else [])
            cur.execute(f"""
                SELECT 
                    COALESCE(SUM(CASE WHEN transaction_type = 'expense' THEN amount_minor ELSE 0 END), 0) -
                    COALESCE(SUM(CASE WHEN transaction_type = 'refund' THEN amount_minor ELSE 0 END), 0) as net_spend
                FROM active_transactions
                WHERE transaction_date LIKE ? {acc_clause}
            """, params)
            row = cur.fetchone()
            return max(0, row["net_spend"] if row and row["net_spend"] is not None else 0)

    @staticmethod
    def get_completed_historical_months(account_id: Optional[int] = None, as_of_date: Optional[str] = None) -> List[str]:
        """
        Returns continuous calendar sequence of completed historical months
        strictly before current month or `as_of_date`, zero-filling any missing months.
        """
        cutoff_date = as_of_date or date.today().isoformat()
        current_month = cutoff_date[:7]

        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND account_id = ?" if account_id else ""
            params = [cutoff_date] + ([account_id] if account_id else [])
            cur.execute(f"""
                SELECT MIN(transaction_date) as min_d
                FROM active_transactions
                WHERE transaction_date < ? {acc_clause}
            """, params)
            row = cur.fetchone()
            if not row or not row["min_d"]:
                return []

            min_month = row["min_d"][:7]
            cy, cm = map(int, current_month.split("-"))
            if cm == 1:
                end_month = f"{cy - 1:04d}-12"
            else:
                end_month = f"{cy:04d}-{cm - 1:02d}"

            if min_month > end_month:
                return []

            return generate_calendar_months(min_month, end_month)

    @staticmethod
    def run_replay(account_id: Optional[int] = None, as_of_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes rolling historical replay of the production forecasting engine across
        all available completed months at Day 7, Day 14, and Day 21 cutoffs.
        Evaluates against standard baselines: current_pace, naive_previous, mean_3, median_3, ewma_3, seasonal_naive.
        """
        from app.backend.analytics.forecasting import ForecastingEngine

        cache_key = HistoricalReplayRunner._get_cache_key(account_id)
        if cache_key in _REPLAY_CACHE and as_of_date is None:
            return _REPLAY_CACHE[cache_key]

        completed_months = HistoricalReplayRunner.get_completed_historical_months(account_id, as_of_date=as_of_date)
        if len(completed_months) < 3:
            res = {
                "available": False,
                "reason": "Insufficient completed history for production replay (requires at least 3 completed months)",
                "evaluations_count": 0,
                "models": {},
                "best_model": "current_pace",
                "hybrid_is_best": False,
                "residuals": []
            }
            if as_of_date is None:
                _REPLAY_CACHE[cache_key] = res
            return res

        # Monthly actual net spending lookup for baseline evaluations
        month_actuals: Dict[str, int] = {}
        for m in completed_months:
            month_actuals[m] = HistoricalReplayRunner.get_actual_month_end_net_spend(m, account_id)

        model_preds: Dict[str, List[int]] = {
            "production_policy": [],
            "finscope_hybrid": [],
            "robust_weekly": [],
            "current_pace": [],
            "naive_previous": [],
            "mean_3": [],
            "median_3": [],
            "ewma_3": []
        }
        has_seasonal = (len(completed_months) >= 13)
        if has_seasonal:
            model_preds["seasonal_naive"] = []

        model_actuals: Dict[str, List[int]] = {k: [] for k in model_preds}
        all_residuals: List[Dict[str, Any]] = []
        residuals_by_bucket: Dict[int, List[int]] = {0: [], 1: [], 2: [], 3: []}

        # Need at least 2 completed prior months before the target replay month
        for i in range(2, len(completed_months)):
            target_month = completed_months[i]
            target_actual = month_actuals[target_month]
            prior_months = completed_months[:i]
            prior_actuals = [month_actuals[pm] for pm in prior_months]

            y_str, m_str = target_month.split("-")
            num_days = calendar.monthrange(int(y_str), int(m_str))[1]

            # Replay cutoffs: Day 7, Day 14, Day 21 (or 25%, 50%, 75% elapsed)
            cutoffs = [7, 14, 21]

            for cutoff_day in cutoffs:
                cutoff_d_str = f"{target_month}-{cutoff_day:02d}"
                progress = cutoff_day / float(num_days)
                bucket = get_progress_bucket(progress)

                # 1a. Run candidate finscope_hybrid
                fc_hybrid = ForecastingEngine.forecast_month(
                    month=target_month,
                    account_id=account_id,
                    as_of_date=cutoff_d_str,
                    replay_mode=True,
                    forced_method="weekday_hybrid"
                )
                pred_hybrid = fc_hybrid["projected_expense_minor"]
                model_preds["finscope_hybrid"].append(pred_hybrid)
                model_actuals["finscope_hybrid"].append(target_actual)

                # 1b. Run candidate robust_weekly (Phase 3)
                fc_rw = ForecastingEngine.forecast_month(
                    month=target_month,
                    account_id=account_id,
                    as_of_date=cutoff_d_str,
                    replay_mode=True,
                    forced_method="robust_weekly"
                )
                pred_rw = fc_rw["projected_expense_minor"]
                model_preds["robust_weekly"].append(pred_rw)
                model_actuals["robust_weekly"].append(target_actual)

                # 1c. Run actual production decision policy ladder (natural behavior)
                fc_prod = ForecastingEngine.forecast_month(
                    month=target_month,
                    account_id=account_id,
                    as_of_date=cutoff_d_str,
                    replay_mode=True,
                    forced_method=None
                )
                pred_prod = fc_prod["projected_expense_minor"]
                model_preds["production_policy"].append(pred_prod)
                model_actuals["production_policy"].append(target_actual)


                residual = target_actual - pred_prod
                residuals_by_bucket[bucket].append(residual)
                all_residuals.append({
                    "target_month": target_month,
                    "as_of_date": cutoff_d_str,
                    "progress": progress,
                    "predicted_minor": pred_prod,
                    "actual_minor": target_actual,
                    "residual_minor": residual,
                    "abs_error_minor": abs(residual)
                })

                # 2. Current Pace baseline at cutoff
                actual_spent_cutoff = fc_prod["actual_spent_to_date_minor"]
                p_pace = round((actual_spent_cutoff / float(cutoff_day)) * num_days) if cutoff_day > 0 else target_actual
                model_preds["current_pace"].append(p_pace)
                model_actuals["current_pace"].append(target_actual)

                # 3. Naive Previous Month baseline
                p_naive = prior_actuals[-1]
                model_preds["naive_previous"].append(p_naive)
                model_actuals["naive_previous"].append(target_actual)

                # 4. 3-Month Mean baseline
                p_mean = calculate_mean(prior_actuals[-3:])
                model_preds["mean_3"].append(p_mean)
                model_actuals["mean_3"].append(target_actual)

                # 5. 3-Month Median baseline
                p_med = calculate_median(prior_actuals[-3:])
                model_preds["median_3"].append(p_med)
                model_actuals["median_3"].append(target_actual)

                # 6. EWMA baseline
                p_ewma = calculate_ewma(prior_actuals[-3:], span=3)
                model_preds["ewma_3"].append(p_ewma)
                model_actuals["ewma_3"].append(target_actual)

                # 7. Seasonal Naive baseline (if history >= 13 months, i >= 12)
                if has_seasonal and i >= 12:
                    p_seasonal = prior_actuals[i - 12]
                    model_preds["seasonal_naive"].append(p_seasonal)
                    model_actuals["seasonal_naive"].append(target_actual)

        # Aggregate metrics for each model
        metrics: Dict[str, Any] = {}
        for m_name, preds in model_preds.items():
            actuals = model_actuals[m_name]
            if not preds:
                continue

            errors = [p - a for p, a in zip(preds, actuals)]
            abs_errors = [abs(e) for e in errors]

            mae_minor = round(sum(abs_errors) / float(len(abs_errors)))
            med_ae_minor = calculate_median(abs_errors)
            tot_actual = sum(actuals)
            wape = round((sum(abs_errors) / float(tot_actual) * 100.0), 2) if tot_actual > 0 else 0.0
            bias_minor = round(sum(errors) / float(len(errors)))

            metrics[m_name] = {
                "name": m_name,
                "mae_minor": mae_minor,
                "mae": round(mae_minor / 100.0, 2),
                "median_ae_minor": med_ae_minor,
                "median_ae": round(med_ae_minor / 100.0, 2),
                "wape_pct": wape,
                "bias_minor": bias_minor,
                "bias": round(bias_minor / 100.0, 2),
                "sample_origins": len(preds)
            }

        max_samples = max(m["sample_origins"] for m in metrics.values()) if metrics else 0
        comparable_models = {k: v for k, v in metrics.items() if v["sample_origins"] >= 0.70 * max_samples}
        best_model = min(comparable_models.items(), key=lambda x: x[1]["mae_minor"])[0] if comparable_models else (
            min(metrics.items(), key=lambda x: x[1]["mae_minor"])[0] if metrics else "production_policy"
        )

        result = {
            "available": True,
            "evaluations_count": len(model_preds["production_policy"]),
            "best_model": best_model,
            "best_baseline": best_model,
            "hybrid_is_best": (best_model in ("finscope_hybrid", "production_policy")),
            "models": metrics,
            "residuals": all_residuals,
            "residuals_by_bucket": residuals_by_bucket
        }

        if as_of_date is None:
            _REPLAY_CACHE[cache_key] = result
            _RESIDUALS_BY_BUCKET_CACHE[cache_key] = residuals_by_bucket

        return result

    @staticmethod
    def get_calibrated_residuals(account_id: Optional[int] = None, progress: float = 0.5) -> Tuple[str, List[int]]:
        """
        Returns (range_type, residuals) for the current progress bucket.
        If >= 6 samples exist in this bucket, returns ('calibrated_range', bucket_residuals).
        Otherwise returns ('early_estimate', []).
        """
        cache_key = HistoricalReplayRunner._get_cache_key(account_id)
        if cache_key not in _RESIDUALS_BY_BUCKET_CACHE:
            # Run replay once to populate residuals
            HistoricalReplayRunner.run_replay(account_id)

        bucket_map = _RESIDUALS_BY_BUCKET_CACHE.get(cache_key, {})
        bucket = get_progress_bucket(progress)
        residuals = bucket_map.get(bucket, [])

        # Threshold from roadmap: at least 6-8 samples
        if len(residuals) >= 6:
            return ("calibrated_range", residuals)
        return ("early_estimate", residuals)
