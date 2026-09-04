"""
Forecast Backtesting Engine for FinScope.
Implements rolling-origin historical evaluation to prove forecast accuracy:
- Compares against simple baselines (Previous Month Naive, 3M Mean, 3M Median, EWMA)
- Standard metrics: MAE, Median Absolute Error, WAPE, Bias
- Fully offline and deterministic
"""

from typing import Dict, Any, List, Optional
from app.backend.analytics.rolling import calculate_mean, calculate_median, calculate_ewma

class BacktestingEngine:
    @staticmethod
    def evaluate_models(series: List[int]) -> Dict[str, Any]:
        """
        Takes chronological monthly integer minor amounts and runs
        rolling-origin evaluation for origins t >= 3.
        """
        n = len(series)
        if n < 4:
            return {
                "error": "Insufficient history for backtesting (requires at least 4 monthly points)",
                "evaluations_count": 0
            }

        models = {
            "naive_previous": {"preds": [], "actuals": []},
            "mean_3": {"preds": [], "actuals": []},
            "median_3": {"preds": [], "actuals": []},
            "ewma_3": {"preds": [], "actuals": []}
        }

        for t in range(3, n):
            train = series[:t]
            actual = series[t]

            # 1. Naive Previous Month
            models["naive_previous"]["preds"].append(train[-1])
            models["naive_previous"]["actuals"].append(actual)

            # 2. 3M Mean
            models["mean_3"]["preds"].append(calculate_mean(train[-3:]))
            models["mean_3"]["actuals"].append(actual)

            # 3. 3M Median
            models["median_3"]["preds"].append(calculate_median(train[-3:]))
            models["median_3"]["actuals"].append(actual)

            # 4. EWMA 3
            models["ewma_3"]["preds"].append(calculate_ewma(train[-3:], span=3))
            models["ewma_3"]["actuals"].append(actual)

        results = {}
        for m_name, data in models.items():
            preds = data["preds"]
            actuals = data["actuals"]
            errors = [p - a for p, a in zip(preds, actuals)]
            abs_errors = [abs(e) for e in errors]

            mae_minor = round(sum(abs_errors) / len(abs_errors))
            med_ae_minor = calculate_median(abs_errors)
            total_actual = sum(actuals)
            wape = round((sum(abs_errors) / total_actual * 100.0), 2) if total_actual > 0 else 0.0
            bias_minor = round(sum(errors) / len(errors))

            results[m_name] = {
                "mae_minor": mae_minor,
                "mae": round(mae_minor / 100.0, 2),
                "median_ae_minor": med_ae_minor,
                "median_ae": round(med_ae_minor / 100.0, 2),
                "wape_pct": wape,
                "bias_minor": bias_minor,
                "bias": round(bias_minor / 100.0, 2),
                "sample_origins": len(preds)
            }

        # Identify best baseline model by lowest MAE
        best_model = min(results.items(), key=lambda x: x[1]["mae_minor"])[0]

        return {
            "evaluations_count": len(series) - 3,
            "best_baseline": best_model,
            "models": results
        }
