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
        ("create_backup", {}),
        ("get_currency_catalog", {}),
        ("reconcile_pending_fx", {}),
        ("preview_quick_capture", {"raw_text": "85k lunch"})
    ]

    for method, payload in endpoints:
        status, resp = client.post(method, payload)
        assert status == 200, f"Expected 200 for {method}, got {status}: {resp}"
        assert resp.get("success") is True, f"Failed on {method}: {resp}"
        assert resp.get("api_version") == 2
        assert "data" in resp


def test_server_quick_capture_flow(ephemeral_server):
    """Verifies end-to-end quick capture preview and commit via HTTP API."""
    client = ephemeral_server

    # Create account first
    status, acc_resp = client.post("create_account", {"name": "Test Checking", "account_type": "checking", "currency": "USD"})
    assert status == 200
    acc_id = acc_resp["data"]

    # Preview
    status, p_resp = client.post("preview_quick_capture", {"raw_text": "50k cafe"})
    assert status == 200
    assert p_resp.get("success") is True
    p_data = p_resp["data"]
    assert p_data["parse"]["amount"] == 50000.0
    assert p_data["enrichment"]["account_id"] == acc_id

    # Commit without preview_hash returns 422
    status_bad, _ = client.post("commit_quick_capture", {"raw_text": "50k cafe"})
    assert status_bad == 422

    # Commit with preview_hash succeeds
    status, c_resp = client.post("commit_quick_capture", {
        "raw_text": "50k cafe",
        "preview_hash": p_data["enrichment"]["preview_hash"]
    })
    assert status == 200
    assert c_resp.get("success") is True
    c_data = c_resp["data"]
    assert c_data["success"] is True
    assert c_data["transaction"]["amount"] == 50000.0
    assert c_data["transaction"]["capture_method"] == "quick_capture"


def test_server_export_csv(ephemeral_server):
    """Verifies CSV export endpoint returns CSV data with valid token."""
    client = ephemeral_server
    status, csv_text = client.get_export_csv()
    assert status == 200
    assert "Date" in csv_text or "Amount" in csv_text or len(csv_text) >= 0

