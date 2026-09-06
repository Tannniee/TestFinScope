import unittest
from datetime import date
from app.backend.analytics.context import resolve_analytics_context
from app.backend.analytics.forecasting import ForecastingEngine
from app.backend.analytics.forecast_replay import LRUCache
from app.backend.database.connection import get_db_connection, init_db

class TestFuturePeriodsAndReplay(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_future_period_context_resolution(self):
        """Future month must resolve to period_state='future', max_day=0, full month comparison."""
        mock_today = date(2026, 9, 6)
        ctx = resolve_analytics_context(month="2026-11", today=mock_today)

        self.assertEqual(ctx.period_state, "future")
        self.assertFalse(ctx.is_current_month)
        self.assertFalse(ctx.is_completed)
        self.assertEqual(ctx.max_day, 0)
        self.assertEqual(ctx.start_date, date(2026, 11, 1))
        self.assertEqual(ctx.end_date, date(2026, 11, 30))
        self.assertEqual(ctx.comparison_mode, "previous_month_full")
        self.assertEqual(ctx.comparison_start, date(2026, 10, 1))
        self.assertEqual(ctx.comparison_end, date(2026, 10, 31))
        self.assertIn("Future Period", ctx.period_label)

    def test_context_explicit_comparison_month_and_max_day(self):
        """resolve_analytics_context supports explicit comparison_month and max_day."""
        mock_today = date(2026, 9, 6)
        ctx = resolve_analytics_context(
            month="2026-09",
            comparison_month="2026-06",
            max_day=15,
            today=mock_today
        )
        self.assertEqual(ctx.as_of_month, "2026-09")
        self.assertEqual(ctx.max_day, 15)
        self.assertEqual(ctx.comparison_start, date(2026, 6, 1))
        self.assertEqual(ctx.comparison_end, date(2026, 6, 15))

    def test_future_forecast_runs_without_error(self):
        """Forecasting for a future period operates with 0 elapsed days and full month remaining."""
        mock_today = date(2026, 9, 6)
        ctx = resolve_analytics_context(month="2026-12", today=mock_today)
        fc = ForecastingEngine.forecast_month("2026-12", context=ctx)
        self.assertIsNotNone(fc)
        self.assertEqual(fc["actual_spent_to_date_minor"], 0)
        self.assertGreaterEqual(fc["components"]["remaining_days"], 30)

    def test_lru_cache_bounded_eviction(self):
        """LRUCache evicts oldest items when exceeding maxsize."""
        cache = LRUCache(maxsize=3)
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3
        self.assertEqual(len(cache), 3)

        # Access "a" to make it most recently used
        _ = cache["a"]

        # Insert "d", should evict "b" (oldest unaccessed)
        cache["d"] = 4
        self.assertEqual(len(cache), 3)
        self.assertIn("a", cache)
        self.assertIn("c", cache)
        self.assertIn("d", cache)
        self.assertNotIn("b", cache)

if __name__ == "__main__":
    unittest.main()
