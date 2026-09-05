"""
Forecast Backtesting Engine V2 for FinScope (v1.0.5).
Implements rolling-origin historical evaluation to prove forecast accuracy:
- Evaluates the actual FinScope production forecast engine via HistoricalReplayRunner
- Supports legacy series-based evaluation for backward compatibility
- Models: FinScope Hybrid, Current Pace, Previous Month Naive, 3M Mean, 3M Median, EWMA, Seasonal Naive
- Standard metrics: MAE, Median Absolute Error, WAPE, Bias
- Fully offline and deterministic
"""

from typing import Dict, Any, List, Optional
from app.backend.analytics.rolling import calculate_mean, calculate_median, calculate_ewma
from app.backend.analytics.forecast_replay import HistoricalReplayRunner


class BacktestingEngine:
    @staticmethod
    def evaluate_production_replay(account_id: Optional[int] = None, as_of_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes rolling historical replay of the actual production forecasting engine
        at historical cutoffs (Day 7, 14, 21) across completed historical months.
        """
        return HistoricalReplayRunner.run_replay(account_id=account_id, as_of_date=as_of_date)

    @staticmethod
    def evaluate_models(series: List[int]) -> Dict[str, Any]:
        """
        Takes chronological monthly integer minor amounts and runs
        rolling-origin evaluation for origins t >= 3.
        Kept for backward compatibility with series-based callers.
        """
        n = len(series)
        if n < 4:
            return {
                "available": False,
                "error": "Insufficient history for backtesting (requires at least 4 monthly points)",
                "evaluations_count": 0
            }

        models: Dict[str, Dict[str, List[int]]] = {
            "finscope_hybrid": {"preds": [], "actuals": []},
            "naive_previous": {"preds": [], "actuals": []},
            "mean_3": {"preds": [], "actuals": []},
            "median_3": {"preds": [], "actuals": []},
            "ewma_3": {"preds": [], "actuals": []}
        }

        has_seasonal = (n >= 13)
        if has_seasonal:
            models["seasonal_naive"] = {"preds": [], "actuals": []}

        for t in range(3, n):
            train = series[:t]
            actual = series[t]

            # 1. Naive Previous Month
            p_naive = train[-1]
            models["naive_previous"]["preds"].append(p_naive)
            models["naive_previous"]["actuals"].append(actual)

            # 2. 3M Mean
            p_mean = calculate_mean(train[-3:])
            models["mean_3"]["preds"].append(p_mean)
            models["mean_3"]["actuals"].append(actual)

            # 3. 3M Median
            p_med = calculate_median(train[-3:])
            models["median_3"]["preds"].append(p_med)
            models["median_3"]["actuals"].append(actual)

            # 4. EWMA 3
            p_ewma = calculate_ewma(train[-3:], span=3)
            models["ewma_3"]["preds"].append(p_ewma)
            models["ewma_3"]["actuals"].append(actual)

            # 5. FinScope Hybrid: Blends median baseline with momentum
            p_hybrid = round(0.50 * p_med + 0.30 * p_ewma + 0.20 * p_naive)
            models["finscope_hybrid"]["preds"].append(p_hybrid)
            models["finscope_hybrid"]["actuals"].append(actual)

            # 6. Seasonal Naive (if history >= 12 months)
            if has_seasonal and t >= 12:
                models["seasonal_naive"]["preds"].append(train[t - 12])
                models["seasonal_naive"]["actuals"].append(actual)

        results = {}
        for m_name, data in models.items():
            preds = data["preds"]
            actuals = data["actuals"]
            if not preds:
                continue

            errors = [p - a for p, a in zip(preds, actuals)]
            abs_errors = [abs(e) for e in errors]

            mae_minor = round(sum(abs_errors) / float(len(abs_errors)))
            med_ae_minor = calculate_median(abs_errors)
            total_actual = sum(actuals)
            wape = round((sum(abs_errors) / float(total_actual) * 100.0), 2) if total_actual > 0 else 0.0
            bias_minor = round(sum(errors) / float(len(errors)))

            results[m_name] = {
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

        # Expose legacy_series_hybrid alias and remove duplicate finscope_hybrid (F109-10)
        if "finscope_hybrid" in results:
            results["legacy_series_hybrid"] = dict(results["finscope_hybrid"])
            results["legacy_series_hybrid"]["name"] = "legacy_series_hybrid"
            results.pop("finscope_hybrid", None)

        # Identify best model by lowest MAE
        best_model = min(results.items(), key=lambda x: x[1]["mae_minor"])[0]

        return {
            "available": True,
            "evaluation_type": "legacy_series_baseline",
            "evaluations_count": len(series) - 3,
            "best_model": best_model,
            "best_baseline": best_model,
            "hybrid_is_best": (best_model == "legacy_series_hybrid"),
            "models": results
        }
