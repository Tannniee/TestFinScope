"""
Historical Replay Runner for FinScope Forecasting v1.0.8.
Executes candidate strategies and sequential production-policy replay at historical cutoffs
(Day 7, Day 14, Day 21) across completed historical months without future leakage.
Evaluates fair error on exact comparable origins and collects empirical residuals
for calibrated confidence intervals.
"""

import calendar
from datetime import date, datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple, Set
from app.backend.database.connection import get_db_connection
from app.backend.analytics.rolling import calculate_mean, calculate_median, calculate_ewma
from app.backend.analytics.forecast_strategies.config import FORECAST_CONFIG
from app.backend.analytics.forecast_strategies.scoring import (
    ReplayOrigin,
    CandidateReplayRecord,
    compute_comparable_scores
)
from app.backend.analytics.forecast_strategies.series import generate_calendar_months

# Cache structure: (version, revision, account_id, cutoff) -> replay_results
_REPLAY_CACHE: Dict[Tuple[str, int, Optional[int], str], Dict[str, Any]] = {}
_RESIDUALS_BY_BUCKET_CACHE: Dict[Tuple[str, int, Optional[int], str], Dict[int, List[int]]] = {}


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


class HistoricalReplayRunner:
    @staticmethod
    def _get_cache_key(account_id: Optional[int], as_of_date: Optional[str] = None) -> Tuple[str, int, Optional[int], str]:
        """
        Derives an immutable cache identity using analytics_state.revision (F108-15).
        Any mutation to transactions or recurring rules increments revision,
        ensuring replay cache correctness without stale cache leakage.
        """
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT revision FROM analytics_state WHERE id = 1")
            row = cur.fetchone()
            revision = row[0] if row else 0

            return (
                "1.0.8",
                revision,
                account_id,
                as_of_date or "__latest__"
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
        Executes rolling historical replay of candidate forecasting strategies and sequential
        production-policy replay across completed historical months at Day 7, 14, and 21 cutoffs.
        Guarantees zero future leakage: Origin N uses only candidate performance from origins < N.
        """
        from app.backend.analytics.forecasting import ForecastingEngine

        cache_key = HistoricalReplayRunner._get_cache_key(account_id, as_of_date=as_of_date)
        if cache_key in _REPLAY_CACHE:
            return _REPLAY_CACHE[cache_key]

        completed_months = HistoricalReplayRunner.get_completed_historical_months(account_id, as_of_date=as_of_date)
        if len(completed_months) < 3:
            res = {
                "available": False,
                "reason": "Insufficient completed history for production replay (requires at least 3 completed months)",
                "evaluations_count": 0,
                "ranking_metric": "median_absolute_error",
                "minimum_comparable_origins": FORECAST_CONFIG.adaptive_selection_min_origins,
                "comparable_origin_count": 0,
                "best_model": "weekday_hybrid",
                "best_candidate": "weekday_hybrid",
                "hybrid_is_best": True,
                "candidate_models": {},
                "production_policy": {},
                "baselines": {},
                "models": {},
                "residuals": [],
                "residuals_by_bucket": {0: [], 1: [], 2: [], 3: []}
            }
            _REPLAY_CACHE[cache_key] = res
            return res

        # Monthly actual net spending lookup
        month_actuals: Dict[str, int] = {}
        for m in completed_months:
            month_actuals[m] = HistoricalReplayRunner.get_actual_month_end_net_spend(m, account_id)

        candidate_strategies = [
            "current_pace",
            "three_month_median",
            "robust_weekly",
            "weekday_hybrid",
            "seasonal_naive"
        ]

        candidate_records: Dict[str, List[CandidateReplayRecord]] = {m: [] for m in candidate_strategies}
        production_policy_records: List[CandidateReplayRecord] = []
        baseline_records: Dict[str, List[CandidateReplayRecord]] = {
            "current_pace": [],
            "naive_previous": [],
            "mean_3": [],
            "median_3": [],
            "ewma_3": []
        }

        all_residuals: List[Dict[str, Any]] = []
        residuals_by_bucket: Dict[int, List[int]] = {0: [], 1: [], 2: [], 3: []}
        completed_prior_origins: Set[str] = set()

        # Need at least 2 completed prior months before the target replay month
        for i in range(2, len(completed_months)):
            target_month = completed_months[i]
            target_actual = month_actuals[target_month]
            prior_months = completed_months[:i]
            prior_actuals = [month_actuals[pm] for pm in prior_months]

            y_str, m_str = target_month.split("-")
            num_days = calendar.monthrange(int(y_str), int(m_str))[1]

            cutoffs = [7, 14, 21]
            for cutoff_day in cutoffs:
                cutoff_d_str = f"{target_month}-{cutoff_day:02d}"
                origin_id = f"{target_month}|{cutoff_d_str}"
                progress = cutoff_day / float(num_days)
                bucket = get_progress_bucket(progress)

                # 1. Evaluate candidate strategies at Origin N
                for cand_id in candidate_strategies:
                    try:
                        fc_cand = ForecastingEngine.forecast_month(
                            month=target_month,
                            account_id=account_id,
                            as_of_date=cutoff_d_str,
                            replay_mode=True,
                            forced_method=cand_id
                        )
                        # Skip if ineligible at this origin (F108-12)
                        diag = fc_cand.get("diagnostics", {})
                        sel_reason = diag.get("selection_reason", "")
                        if sel_reason.startswith("Ineligible candidate"):
                            continue

                        p_cand = fc_cand["projected_expense_minor"]
                        err = p_cand - target_actual
                        candidate_records[cand_id].append(
                            CandidateReplayRecord(
                                origin_id=origin_id,
                                model_id=cand_id,
                                predicted_minor=p_cand,
                                actual_minor=target_actual,
                                error_minor=err,
                                abs_error_minor=abs(err)
                            )
                        )
                    except Exception:
                        continue

                # 2. Sequential Production-Policy Replay (F108-09)
                # Origin N only receives candidate performance strictly from prior origins (< origin_id)
                prior_candidates = {
                    m: [r for r in recs if r.origin_id in completed_prior_origins]
                    for m, recs in candidate_records.items()
                }
                prior_scores = compute_comparable_scores(prior_candidates, candidate_strategies)
                prior_scores["available"] = (prior_scores["comparable_origin_count"] >= FORECAST_CONFIG.adaptive_selection_min_origins)

                fc_prod = ForecastingEngine.forecast_month(
                    month=target_month,
                    account_id=account_id,
                    as_of_date=cutoff_d_str,
                    replay_mode=True,
                    forced_method=None,
                    replay_evidence=prior_scores
                )
                pred_prod = fc_prod["projected_expense_minor"]
                prod_residual = target_actual - pred_prod
                residuals_by_bucket[bucket].append(prod_residual)

                production_policy_records.append(
                    CandidateReplayRecord(
                        origin_id=origin_id,
                        model_id="production_policy",
                        predicted_minor=pred_prod,
                        actual_minor=target_actual,
                        error_minor=pred_prod - target_actual,
                        abs_error_minor=abs(prod_residual)
                    )
                )
                all_residuals.append({
                    "target_month": target_month,
                    "as_of_date": cutoff_d_str,
                    "progress": progress,
                    "predicted_minor": pred_prod,
                    "actual_minor": target_actual,
                    "residual_minor": prod_residual,
                    "abs_error_minor": abs(prod_residual)
                })

                # 3. Reference baselines for benchmark comparison
                actual_spent_cutoff = fc_prod["actual_spent_to_date_minor"]
                p_pace = round((actual_spent_cutoff / float(cutoff_day)) * num_days) if cutoff_day > 0 else target_actual
                baseline_records["current_pace"].append(CandidateReplayRecord(origin_id, "current_pace", p_pace, target_actual, p_pace - target_actual, abs(p_pace - target_actual)))

                p_naive = prior_actuals[-1]
                baseline_records["naive_previous"].append(CandidateReplayRecord(origin_id, "naive_previous", p_naive, target_actual, p_naive - target_actual, abs(p_naive - target_actual)))

                p_mean = calculate_mean(prior_actuals[-3:])
                baseline_records["mean_3"].append(CandidateReplayRecord(origin_id, "mean_3", p_mean, target_actual, p_mean - target_actual, abs(p_mean - target_actual)))

                p_med = calculate_median(prior_actuals[-3:])
                baseline_records["median_3"].append(CandidateReplayRecord(origin_id, "median_3", p_med, target_actual, p_med - target_actual, abs(p_med - target_actual)))

                p_ewma = calculate_ewma(prior_actuals[-3:], span=3)
                baseline_records["ewma_3"].append(CandidateReplayRecord(origin_id, "ewma_3", p_ewma, target_actual, p_ewma - target_actual, abs(p_ewma - target_actual)))

                completed_prior_origins.add(origin_id)

        # 4. Overall Scoring Across Exact Common Origins (F108-10)
        final_comp_scores = compute_comparable_scores(candidate_records, candidate_strategies)
        comp_count = final_comp_scores["comparable_origin_count"]

        def summarize_records(records: List[CandidateReplayRecord], name: str) -> Dict[str, Any]:
            if not records:
                return {}
            abs_errs = [r.abs_error_minor for r in records]
            errs = [r.error_minor for r in records]
            actuals = [r.actual_minor for r in records]
            tot_act = sum(actuals)
            mae_m = round(calculate_mean(abs_errs))
            med_ae_m = calculate_median(abs_errs)
            bias_m = round(calculate_mean(errs))
            wape = round((sum(abs_errs) / float(tot_act) * 100.0), 2) if tot_act > 0 else 0.0
            return {
                "name": name,
                "mae_minor": mae_m,
                "mae": round(mae_m / 100.0, 2),
                "median_ae_minor": med_ae_m,
                "median_ae": round(med_ae_m / 100.0, 2),
                "wape_pct": wape,
                "bias_minor": bias_m,
                "bias": round(bias_m / 100.0, 2),
                "sample_origins": len(records)
            }

        candidate_metrics: Dict[str, Any] = {}
        for m in candidate_strategies:
            recs = candidate_records[m]
            if recs:
                candidate_metrics[m] = summarize_records(recs, m)
                if m in final_comp_scores["model_scores"]:
                    candidate_metrics[m]["comparable_origins"] = final_comp_scores["model_scores"][m]["comparable_origins"]
                    candidate_metrics[m]["comparable_median_ae_minor"] = final_comp_scores["model_scores"][m]["median_ae_minor"]
                    candidate_metrics[m]["comparable_mae_minor"] = final_comp_scores["model_scores"][m]["mae_minor"]

        prod_metrics = summarize_records(production_policy_records, "production_policy")
        baseline_metrics: Dict[str, Any] = {
            b_name: summarize_records(recs, b_name) for b_name, recs in baseline_records.items() if recs
        }

        # Determine Best Candidate Model
        if comp_count >= FORECAST_CONFIG.adaptive_selection_min_origins and final_comp_scores["model_scores"]:
            sorted_candidates = sorted(
                final_comp_scores["model_scores"].values(),
                key=lambda x: (x["median_ae_minor"], x["mae_minor"], abs(x["bias_minor"]))
            )
            best_candidate = sorted_candidates[0]["model_id"]
            selection_available = True
        elif candidate_metrics:
            sorted_by_mae = sorted(candidate_metrics.values(), key=lambda x: (x["median_ae_minor"], x["mae_minor"]))
            best_candidate = sorted_by_mae[0]["name"]
            selection_available = False
        else:
            best_candidate = "weekday_hybrid"
            selection_available = False

        # Unified models map for backward compatibility
        all_models_map: Dict[str, Any] = {
            "production_policy": prod_metrics,
            **candidate_metrics,
            **baseline_metrics
        }
        # Backward compatibility aliases
        if "weekday_hybrid" in candidate_metrics:
            all_models_map["finscope_hybrid"] = candidate_metrics["weekday_hybrid"]

        result = {
            "available": True,
            "evaluations_count": len(production_policy_records),
            "ranking_metric": "median_absolute_error",
            "minimum_comparable_origins": FORECAST_CONFIG.adaptive_selection_min_origins,
            "comparable_origin_count": comp_count,
            "best_model": best_candidate,
            "best_candidate": best_candidate,
            "selection_available": selection_available,
            "hybrid_is_best": (best_candidate in ("weekday_hybrid", "production_policy")),
            "production_policy": prod_metrics,
            "candidate_models": candidate_metrics,
            "baselines": baseline_metrics,
            "models": all_models_map,
            "residuals": all_residuals,
            "residuals_by_bucket": residuals_by_bucket
        }

        _REPLAY_CACHE[cache_key] = result
        _RESIDUALS_BY_BUCKET_CACHE[cache_key] = residuals_by_bucket

        return result

    @staticmethod
    def get_calibrated_residuals(account_id: Optional[int] = None, progress: float = 0.5) -> Tuple[str, List[int]]:
        """
        Returns (range_type, residuals) for the current progress bucket.
        If >= 8 samples exist in this bucket (F108-18), returns ('calibrated_range', bucket_residuals).
        Otherwise returns ('early_estimate', []).
        """
        cache_key = HistoricalReplayRunner._get_cache_key(account_id, as_of_date=None)
        if cache_key not in _RESIDUALS_BY_BUCKET_CACHE:
            HistoricalReplayRunner.run_replay(account_id)

        bucket_map = _RESIDUALS_BY_BUCKET_CACHE.get(cache_key, {})
        bucket = get_progress_bucket(progress)
        residuals = bucket_map.get(bucket, [])

        if len(residuals) >= FORECAST_CONFIG.calibrated_range_min_residuals:
            return ("calibrated_range", residuals)
        return ("early_estimate", residuals)
