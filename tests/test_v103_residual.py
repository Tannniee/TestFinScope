"""
FinScope v1.0.4 Residual Issues & Hardening Regression Tests
Covers V103-01 through V103-07 in strict integrity risk order.
"""

import pytest
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock
from app.backend import config
from app.backend.database.connection import get_db_connection
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.services.settings_service import SettingsService
from app.backend.services.transfer_service import TransferService
from app.backend.analytics.forecasting import ForecastingEngine, recurring_key


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    test_db_dir = tmp_path / "finscope_data"
    test_db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FINSCOPE_DATA_DIR", str(test_db_dir))
    config.set_data_dir(test_db_dir)

    from app.backend.database.connection import init_db
    init_db()

    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ==============================================================================
# V103-01: Currency frontend state consistency
# ==============================================================================

def test_currency_state_changes_only_after_success():
    """
    V103-01: state.setCurrency must await api.updateSettings BEFORE setting this.currency.
    If the API call fails, this.currency must NOT be mutated.
    """
    state_js_path = Path(__file__).resolve().parent.parent / "app" / "frontend" / "assets" / "js" / "state.js"
    content = state_js_path.read_text(encoding="utf-8")

    # Verify setCurrency structure
    assert "await api.updateSettings({ currency: currencyCode });" in content
    assert "this.currency = currencyCode;" in content
    # api.updateSettings must precede this.currency = currencyCode
    idx_api = content.index("await api.updateSettings({ currency: currencyCode });")
    idx_assign = content.index("this.currency = currencyCode;")
    assert idx_api < idx_assign, "api.updateSettings must be awaited before this.currency is assigned"


def test_currency_reverts_when_backend_rejects():
    """
    V103-01: In settings.js, when state.setCurrency fails, the select dropdown must
    revert to previousCurrency and an error toast must be shown.
    """
    settings_js_path = Path(__file__).resolve().parent.parent / "app" / "frontend" / "assets" / "js" / "pages" / "settings.js"
    content = settings_js_path.read_text(encoding="utf-8")

    assert "currSelect.value = previousCurrency;" in content
    assert "showToast(err.message || 'Unable to change currency', 'error');" in content


def test_currency_failure_does_not_show_success_message():
    """
    V103-01: The success toast in settings.js must be inside the try block,
    so failure does not show a success message.
    """
    settings_js_path = Path(__file__).resolve().parent.parent / "app" / "frontend" / "assets" / "js" / "pages" / "settings.js"
    content = settings_js_path.read_text(encoding="utf-8")

    # In settings.js, success toast must precede catch block
    try_idx = content.index("try {")
    success_toast_idx = content.index("showToast(`Currency changed to ${newCurr}`, 'success');")
    catch_idx = content.index("} catch (err) {")
    error_toast_idx = content.index("showToast(err.message || 'Unable to change currency', 'error');")

    assert try_idx < success_toast_idx < catch_idx < error_toast_idx


def test_currency_failure_preserves_dashboard_format(isolated_db):
    """
    V103-01: When currency change fails on backend, persisted setting remains unchanged.
    """
    acc_id = AccountRepository.create("Primary Acc", "checking", opening_balance=500.0)
    TransactionRepository.create({
        "account_id": acc_id,
        "amount": 50.0,
        "transaction_type": "expense",
        "transaction_date": "2026-09-01"
    })

    assert SettingsService.get_setting("currency") == "USD"

    # Attempt to change to VND should fail
    with pytest.raises(ValueError, match="Base currency cannot be changed after financial transactions"):
        SettingsService.update_settings({"currency": "VND"})

    # Must remain USD
    assert SettingsService.get_setting("currency") == "USD"
    acc = AccountRepository.get_by_id(acc_id)
    assert acc["currency"] == "USD"


# ==============================================================================
# V103-02: Settings API validates currency code before persisting
# ==============================================================================

def test_settings_reject_invalid_currency_code(isolated_db):
    """
    V103-02: SettingsService must reject malformed currency strings.
    """
    with pytest.raises(ValueError, match="Invalid currency code"):
        SettingsService.update_settings({"currency": "BANANA"})

    with pytest.raises(ValueError, match="Invalid currency code"):
        SettingsService.update_settings({"currency": "<script>"})

    with pytest.raises(ValueError, match="Invalid currency code"):
        SettingsService.update_settings({"currency": "US"})


def test_settings_reject_unsupported_currency(isolated_db):
    """
    V103-02: SettingsService must reject 3-letter codes that are not supported by FinScope.
    """
    with pytest.raises(ValueError, match="Unsupported currency"):
        SettingsService.update_settings({"currency": "ZZZ"})

    with pytest.raises(ValueError, match="Unsupported currency"):
        SettingsService.update_settings({"currency": "ABC"})


def test_settings_currency_validation_happens_before_database_write(isolated_db):
    """
    V103-02: Even when no transactions exist, invalid/unsupported currency must be rejected
    before any account or setting is touched.
    """
    acc_id = AccountRepository.create("Test Acc", "checking", opening_balance=100.0)

    with pytest.raises(ValueError, match="Invalid currency code"):
        SettingsService.update_settings({"currency": "INVALID"})

    # Setting remains default USD
    assert SettingsService.get_setting("currency") == "USD"
    # Account currency was NOT touched
    acc = AccountRepository.get_by_id(acc_id)
    assert acc["currency"] == "USD"


def test_valid_currency_update_succeeds_when_database_empty(isolated_db):
    """
    V103-02: Valid supported currency (case-normalized) succeeds when no transactions exist.
    """
    acc_id = AccountRepository.create("Test Acc", "checking", opening_balance=100.0)

    # Lowercase 'eur' is normalized to uppercase 'EUR'
    SettingsService.update_settings({"currency": "eur"})
    assert SettingsService.get_setting("currency") == "EUR"

    acc = AccountRepository.get_by_id(acc_id)
    assert acc["currency"] == "EUR"


# ==============================================================================
# V103-03: Transfer create/update validates ISO transaction date
# ==============================================================================

def test_transfer_create_rejects_invalid_date(isolated_db):
    """
    V103-03: TransferService.create_transfer must reject malformed or impossible dates.
    """
    acc1 = AccountRepository.create("Acc 1", "checking", opening_balance=500.0)
    acc2 = AccountRepository.create("Acc 2", "savings", opening_balance=500.0)

    # Malformed text
    with pytest.raises(ValueError, match="Expected YYYY-MM-DD"):
        TransferService.create_transfer(
            from_account_id=acc1,
            to_account_id=acc2,
            amount=50.0,
            transaction_date="banana"
        )

    # Impossible date (Feb 31)
    with pytest.raises(ValueError, match="Expected YYYY-MM-DD"):
        TransferService.create_transfer(
            from_account_id=acc1,
            to_account_id=acc2,
            amount=50.0,
            transaction_date="2026-02-31"
        )

    # Empty date string
    with pytest.raises(ValueError, match="date string is required"):
        TransferService.create_transfer(
            from_account_id=acc1,
            to_account_id=acc2,
            amount=50.0,
            transaction_date=""
        )


def test_transfer_update_rejects_invalid_date(isolated_db):
    """
    V103-03: TransferService.update_transfer must reject malformed dates.
    """
    acc1 = AccountRepository.create("Acc 1", "checking", opening_balance=500.0)
    acc2 = AccountRepository.create("Acc 2", "savings", opening_balance=500.0)

    res = TransferService.create_transfer(
        from_account_id=acc1,
        to_account_id=acc2,
        amount=50.0,
        transaction_date="2026-09-01"
    )

    with pytest.raises(ValueError, match="Expected YYYY-MM-DD"):
        TransferService.update_transfer(
            transfer_group_id=res["transfer_group_id"],
            transaction_date="invalid-date"
        )

    with pytest.raises(ValueError, match="Expected YYYY-MM-DD"):
        TransferService.update_transfer(
            tx_id=res["outflow_tx_id"],
            transaction_date="2026-13-45"
        )


def test_transfer_create_accepts_iso_date(isolated_db):
    """
    V103-03: Valid ISO date YYYY-MM-DD creates both legs successfully.
    """
    acc1 = AccountRepository.create("Acc 1", "checking", opening_balance=500.0)
    acc2 = AccountRepository.create("Acc 2", "savings", opening_balance=500.0)

    res = TransferService.create_transfer(
        from_account_id=acc1,
        to_account_id=acc2,
        amount=75.0,
        transaction_date="2026-09-15"
    )
    assert res["success"] is True
    assert res["source_transaction"]["transaction_date"] == "2026-09-15"
    assert res["destination_transaction"]["transaction_date"] == "2026-09-15"


def test_transfer_pair_has_identical_date(isolated_db):
    """
    V103-03: Both legs of a transfer pair always share the identical validated date.
    """
    acc1 = AccountRepository.create("Acc 1", "checking", opening_balance=500.0)
    acc2 = AccountRepository.create("Acc 2", "savings", opening_balance=500.0)

    res = TransferService.create_transfer(
        from_account_id=acc1,
        to_account_id=acc2,
        amount=120.0,
        transaction_date="2026-09-10"
    )

    # Update date
    TransferService.update_transfer(
        transfer_group_id=res["transfer_group_id"],
        transaction_date="2026-09-20"
    )

    tx1 = TransactionRepository.get_by_id(res["outflow_tx_id"])
    tx2 = TransactionRepository.get_by_id(res["inflow_tx_id"])
    assert tx1["transaction_date"] == "2026-09-20"
    assert tx2["transaction_date"] == "2026-09-20"


def test_invalid_transfer_update_is_atomic(isolated_db):
    """
    V103-03: If date validation fails during update, neither leg is modified.
    """
    acc1 = AccountRepository.create("Acc 1", "checking", opening_balance=500.0)
    acc2 = AccountRepository.create("Acc 2", "savings", opening_balance=500.0)

    res = TransferService.create_transfer(
        from_account_id=acc1,
        to_account_id=acc2,
        amount=60.0,
        transaction_date="2026-09-05"
    )

    with pytest.raises(ValueError, match="Expected YYYY-MM-DD"):
        TransferService.update_transfer(
            transfer_group_id=res["transfer_group_id"],
            amount=90.0,
            transaction_date="bad-date"
        )

    # Verify amount and date on both legs remained unchanged
    tx1 = TransactionRepository.get_by_id(res["outflow_tx_id"])
    tx2 = TransactionRepository.get_by_id(res["inflow_tx_id"])
    assert tx1["amount_minor"] == 6000
    assert tx2["amount_minor"] == 6000
    assert tx1["transaction_date"] == "2026-09-05"
    assert tx2["transaction_date"] == "2026-09-05"

