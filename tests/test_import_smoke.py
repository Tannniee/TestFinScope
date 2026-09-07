"""Smoke tests for key backend modules and imports."""
import pytest


def test_import_api_handler():
    from app.backend.api.handler import ApiHandler
    assert ApiHandler is not None


def test_import_money_context_completeness():
    from app.backend.analytics.money_context import get_portfolio_fx_completeness
    assert callable(get_portfolio_fx_completeness)
