"""
Rolling Analytics Engine for FinScope.
Implements robust historical baselines:
- Mean (3M, 6M, 12M)
- Median (robust against one-off anomalies)
- Median Absolute Deviation (MAD) & Scaled MAD
- Exponentially Weighted Moving Average (EWMA: spans 3 and 6)
- Sample sufficiency guards and history completeness checks
All internal math uses integer minor units.
"""

import math
from typing import Dict, Any, List, Optional, Union

def calculate_mean(values: List[int]) -> int:
    """Returns integer mean in minor units."""
    if not values:
        return 0
    return round(sum(values) / len(values))

def calculate_median(values: List[int]) -> int:
    """Returns median in minor units."""
    if not values:
        return 0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    else:
        return round((sorted_vals[mid - 1] + sorted_vals[mid]) / 2)

def calculate_mad(values: List[int]) -> int:
    """
    Median Absolute Deviation:
    MAD = median(|x_i - median(x)|)
    """
    if not values:
        return 0
    med = calculate_median(values)
    abs_deviations = [abs(x - med) for x in values]
    return calculate_median(abs_deviations)

def calculate_scaled_mad(values: List[int]) -> int:
    """
    Normal-consistent scaled MAD:
    MAD_scaled ≈ 1.4826 * MAD
    """
    mad = calculate_mad(values)
    return round(1.4826 * mad)

def calculate_ewma(values: List[int], span: int = 3) -> int:
    """
    Exponentially Weighted Moving Average:
    alpha = 2 / (span + 1)
    S_1 = x_1
    S_t = alpha * x_t + (1 - alpha) * S_{t-1}
    """
    if not values:
        return 0
    if len(values) == 1:
        return values[0]

    alpha = 2.0 / (span + 1.0)
    ewma = float(values[0])
    for x in values[1:]:
        ewma = alpha * float(x) + (1.0 - alpha) * ewma
    return round(ewma)

def calculate_std_dev(values: List[int]) -> int:
    """Standard deviation in minor units."""
    if len(values) < 2:
        return 0
    mean_val = sum(values) / len(values)
    variance = sum((x - mean_val) ** 2 for x in values) / (len(values) - 1)
    return round(math.sqrt(variance))

class RollingAnalyticsEngine:
    @staticmethod
    def compute_rolling_baselines(history_series: List[int], current_value_minor: int) -> Dict[str, Any]:
        """
        Given chronological historical monthly values (prior to current month)
        and the current month's value, calculates 3M, 6M, 12M baselines.
        """
        n = len(history_series)

        # Slice historical windows
        h3 = history_series[-3:] if n >= 3 else history_series
        h6 = history_series[-6:] if n >= 6 else history_series
        h12 = history_series[-12:] if n >= 12 else history_series

        res = {
            "current_minor": current_value_minor,
            "current": round(current_value_minor / 100.0, 2),
            "sample_size_months": n,
            "has_3m_history": n >= 3,
            "has_6m_history": n >= 6,
            "has_12m_history": n >= 12,

            # 3M
            "mean_3_minor": calculate_mean(h3) if h3 else current_value_minor,
            "median_3_minor": calculate_median(h3) if h3 else current_value_minor,
            "mad_3_minor": calculate_mad(h3) if h3 else 0,
            "ewma_3_minor": calculate_ewma(h3, span=3) if h3 else current_value_minor,

            # 6M
            "mean_6_minor": calculate_mean(h6) if h6 else current_value_minor,
            "median_6_minor": calculate_median(h6) if h6 else current_value_minor,
            "mad_6_minor": calculate_mad(h6) if h6 else 0,
            "scaled_mad_6_minor": calculate_scaled_mad(h6) if h6 else 0,
            "ewma_6_minor": calculate_ewma(h6, span=6) if h6 else current_value_minor,

            # 12M
            "mean_12_minor": calculate_mean(h12) if h12 else current_value_minor,
            "median_12_minor": calculate_median(h12) if h12 else current_value_minor,
            "mad_12_minor": calculate_mad(h12) if h12 else 0,
            "std_12_minor": calculate_std_dev(h12) if len(h12) >= 2 else 0
        }

        # Human decimal representations for convenient consumption
        res["mean_3"] = round(res["mean_3_minor"] / 100.0, 2)
        res["median_3"] = round(res["median_3_minor"] / 100.0, 2)
        res["ewma_3"] = round(res["ewma_3_minor"] / 100.0, 2)
        res["mean_6"] = round(res["mean_6_minor"] / 100.0, 2)
        res["median_6"] = round(res["median_6_minor"] / 100.0, 2)
        res["mad_6"] = round(res["mad_6_minor"] / 100.0, 2)
        res["mean_12"] = round(res["mean_12_minor"] / 100.0, 2)
        res["median_12"] = round(res["median_12_minor"] / 100.0, 2)

        # Delta against 3M and 6M robust median
        res["delta_vs_median_3_minor"] = current_value_minor - res["median_3_minor"]
        res["delta_vs_median_3"] = round(res["delta_vs_median_3_minor"] / 100.0, 2)
        res["delta_vs_median_6_minor"] = current_value_minor - res["median_6_minor"]
        res["delta_vs_median_6"] = round(res["delta_vs_median_6_minor"] / 100.0, 2)

        return res
