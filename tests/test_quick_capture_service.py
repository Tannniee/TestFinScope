import pytest
from app.backend.capture.service import QuickCaptureService
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository

def test_quick_capture_preview_and_commit(isolated_db):
    acc_id = AccountRepository.create("Wallet Cash", "cash", currency="USD")
    cat_id = CategoryRepository.create("Food & Dining", "expense")

    # 1. Preview
    preview = QuickCaptureService.preview("85k grab #Food @Wallet", default_account_id=acc_id)
    assert preview.can_commit is True
    assert preview.parse.amount == 85000.0
    assert preview.enrichment.account_id == acc_id
    assert preview.enrichment.category_id == cat_id
    assert preview.enrichment.category_source == "explicit"
    assert preview.enrichment.preview_hash != ""

    # 2. Commit
    res = QuickCaptureService.commit({
        "raw_text": "85k grab #Food @Wallet",
        "account_id": acc_id
    })
    assert res["success"] is True
    tx_id = res["transaction_id"]
    tx = TransactionRepository.get_by_id(tx_id)
    assert tx is not None
    assert tx["amount"] == 85000.0
    assert tx["merchant_name"] == "Grab"
    assert tx["capture_method"] == "quick_capture"
    assert tx["category_id"] == cat_id
    assert tx["category_source"] == "explicit"
    assert tx["parser_version"] == "qc_v1"

def test_quick_capture_fallback_uncategorized(isolated_db):
    acc_id = AccountRepository.create("Bank Account", "checking", currency="USD")
    # Uncategorized category is created by migrations
    preview = QuickCaptureService.preview("50.50 obscure_shop_99", default_account_id=acc_id)
    assert preview.can_commit is True
    assert preview.enrichment.category_source == "fallback"
    assert preview.enrichment.needs_review is True
    assert preview.enrichment.review_reason == "uncategorized"

    # Commit and verify needs_review
    res = QuickCaptureService.commit({
        "raw_text": "50.50 obscure_shop_99",
        "account_id": acc_id
    })
    tx = TransactionRepository.get_by_id(res["transaction_id"])
    assert tx["needs_review"] == 1
    assert tx["review_reason"] == "uncategorized"


def test_quick_capture_hash_guard_tamper_rejected(isolated_db):
    acc_id = AccountRepository.create("Wallet Cash", "cash", currency="USD")
    preview = QuickCaptureService.preview("25 book @Wallet", default_account_id=acc_id)
    assert preview.can_commit is True

    # Valid commit with correct hash
    res = QuickCaptureService.commit({
        "raw_text": "25 book @Wallet",
        "account_id": acc_id,
        "preview_hash": preview.enrichment.preview_hash
    })
    assert res["success"] is True

    # Tampered / invalid hash must be rejected
    with pytest.raises(ValueError, match="Preview hash mismatch"):
        QuickCaptureService.commit({
            "raw_text": "25 book @Wallet",
            "account_id": acc_id,
            "preview_hash": "tampered_fake_hash_12345"
        })


def test_quick_capture_cross_currency_resolution(isolated_db):
    # USD account (matches base currency USD so settlement amount directly populates base)
    acc_id = AccountRepository.create("USD Main Account", "checking", currency="USD")

    # 10 EUR purchase on USD account without cached rate
    preview = QuickCaptureService.preview("10 EUR digital product", default_account_id=acc_id)
    assert preview.enrichment.input_currency == "EUR"
    assert preview.enrichment.account_currency == "USD"
    assert preview.enrichment.requires_settlement_resolution is True
    assert preview.can_commit is False

    # Attempting to commit without settlement amount raises ValueError
    with pytest.raises(ValueError, match="Requires settlement amount"):
        QuickCaptureService.commit({
            "raw_text": "10 EUR digital product",
            "account_id": acc_id
        })

    # Providing explicit settlement amount succeeds
    res = QuickCaptureService.commit({
        "raw_text": "10 EUR digital product",
        "account_id": acc_id,
        "settlement_amount": 11.20
    })
    assert res["success"] is True
    tx = TransactionRepository.get_by_id(res["transaction_id"])
    assert tx["original_currency"] == "EUR"
    assert tx["original_amount"] == 10.0
    assert tx["currency"] == "USD"
    assert tx["amount"] == 11.20
    assert tx["fx_status"] == "user_settlement"

