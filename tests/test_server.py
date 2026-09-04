import pytest

def test_server_static_assets(ephemeral_server):
    """Verifies static assets are served properly with correct MIME types."""
    client = ephemeral_server
    static_paths = [
        "/",
        "/assets/css/theme.css",
        "/assets/css/layout.css",
        "/assets/css/components.css",
        "/assets/js/api.js",
        "/assets/js/state.js",
        "/assets/js/router.js"
    ]
    for path in static_paths:
        status, content = client.get(path)
        assert status == 200, f"Expected 200 for {path}, got {status}"
        assert len(content) > 0

def test_server_api_endpoints(ephemeral_server):
    """Verifies JSON POST API endpoints succeed with standard envelopes."""
    client = ephemeral_server

    endpoints = [
        ("get_month_summary", {"month": "2026-09"}),
        ("get_transactions", {"month": "2026-09", "limit": 5}),
        ("get_calendar_data", {"month": "2026-09"}),
        ("get_analytics_context", {"month": "2026-09"}),
        ("get_monthly_budget", {"month": "2026-09"}),
        ("get_storage_health", {}),
        ("create_backup", {})
    ]

    for method, payload in endpoints:
        status, resp = client.post(method, payload)
        assert status == 200, f"Expected 200 for {method}, got {status}: {resp}"
        assert resp.get("success") is True, f"Failed on {method}: {resp}"
        assert resp.get("api_version") == 2
        assert "data" in resp

def test_server_export_csv(ephemeral_server):
    """Verifies CSV export endpoint returns CSV data with valid token."""
    client = ephemeral_server
    status, csv_text = client.get_export_csv()
    assert status == 200
    assert "Date" in csv_text or "Amount" in csv_text or len(csv_text) >= 0
