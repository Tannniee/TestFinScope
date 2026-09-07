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
