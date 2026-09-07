import pytest
from app.backend.services.import_service import ImportService
from app.backend.services.merchant_service import MerchantService
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.database.connection import get_db_connection


def test_import_v2_header_signature_and_profile_storage(isolated_db):
    headers = ["Transaction Date", "Payee Description", "Outflow", "Inflow", "Account Category"]
    sig = ImportService.compute_header_signature(headers)
    assert len(sig) == 32
    assert sig == ImportService.compute_header_signature([h.upper() for h in headers])

    mapping = {
        "date": "Transaction Date",
        "payee": "Payee Description",
        "debit": "Outflow",
        "credit": "Inflow",
        "category": "Account Category"
    }

    prof_id = ImportService.save_import_profile(
        name="Chase Bank Profile",
        headers=headers,
        mapping=mapping,
        date_format="MM/DD/YYYY",
        delimiter=","
    )
    assert prof_id > 0

    # Retrieve profile
    found = ImportService.find_profile_by_headers(headers)
    assert found is not None
    assert found["name"] == "Chase Bank Profile"
    assert found["mapping"]["date"] == "Transaction Date"
    assert found["date_format"] == "MM/DD/YYYY"


def test_import_v2_preview_auto_matches_profile_and_predicts_categories(isolated_db):
    acc_id = AccountRepository.create("Primary Account", "checking", currency="USD")
    cat_dining = CategoryRepository.create("Dining & Coffee", cat_type="expense", icon="coffee", color="#FF9F43")
    cat_salary = CategoryRepository.create("Salary", cat_type="income", icon="briefcase", color="#2ECC71")

    # Set up merchant memory for Starbucks
    with get_db_connection() as conn:
        MerchantService.get_or_create_merchant_in_conn(
            conn=conn,
            raw_name="Starbucks",
            category_id=cat_dining,
            account_id=acc_id,
            essentiality="discretionary"
        )
        conn.commit()

    csv_data = """TxDate,Merchant,Debit,Credit,BankCategory
2026-08-01,Starbucks,6.50,,
2026-08-02,Acme Corp,,3000.00,Salary
2026-08-03,Unknown Mystery Vendor,19.99,,
"""
    headers = ["TxDate", "Merchant", "Debit", "Credit", "BankCategory"]
    mapping = {
        "date": "TxDate",
        "payee": "Merchant",
        "debit": "Debit",
        "credit": "Credit",
        "category": "BankCategory"
    }
    ImportService.save_import_profile("Acme Layout", headers, mapping, date_format="YYYY-MM-DD")

    # Preview without passing mapping
    preview = ImportService.preview_csv(csv_data, account_id=acc_id)
    assert preview["detected_profile"] == "Acme Layout"
    assert preview["valid_count"] == 3
    assert len(preview["preview_rows"]) == 3

    # Row 1: Starbucks predicted via merchant memory
    r1 = preview["preview_rows"][0]
    assert r1["payee"] == "Starbucks"
    assert r1["category_suggestion"]["id"] == cat_dining
    assert r1["category_suggestion"]["source"] == "merchant_memory"
    assert r1["category_suggestion"]["confidence"] == 0.9

    # Row 2: Acme Corp mapped via CSV column "Salary"
    r2 = preview["preview_rows"][1]
    assert r2["category_suggestion"]["id"] == cat_salary
    assert r2["category_suggestion"]["source"] == "csv_column"
    assert r2["category_suggestion"]["confidence"] == 1.0

    # Row 3: Unknown vendor falls back to Uncategorized
    r3 = preview["preview_rows"][2]
    assert r3["category_suggestion"]["source"] == "fallback"
    assert r3["category_suggestion"]["confidence"] == 0.0


def test_import_v2_commit_stores_provenance_and_audit_fields(isolated_db):
    acc_id = AccountRepository.create("Main Checking", "checking", currency="USD")
    cat_dining = CategoryRepository.create("Dining & Coffee", cat_type="expense", icon="coffee", color="#FF9F43")

    with get_db_connection() as conn:
        MerchantService.get_or_create_merchant_in_conn(
            conn=conn,
            raw_name="Chipotle",
            category_id=cat_dining,
            account_id=acc_id,
            essentiality="discretionary"
        )
        conn.commit()

    csv_data = """Date,Payee,Amount
2026-08-10,Chipotle,-14.25
2026-08-11,Mystery Gas Station,-50.00
"""
    mapping = {"date": "Date", "payee": "Payee", "amount": "Amount"}

    res = ImportService.commit_import(
        csv_content=csv_data,
        mapping=mapping,
        account_id=acc_id,
        deduplicate=True,
        save_profile_name="Standard Export"
    )
    assert res["success"] is True
    assert res["imported_count"] == 2

    # Verify saved profile was created
    found_prof = ImportService.find_profile_by_headers(["Date", "Payee", "Amount"])
    assert found_prof is not None
    assert found_prof["name"] == "Standard Export"

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, description, merchant_name, raw_merchant_name, category_id,
                   category_source, category_confidence, essentiality_source, essentiality_confidence,
                   needs_review, review_reason, parser_version, capture_method
            FROM transactions
            WHERE account_id = ?
            ORDER BY transaction_date ASC
        """, (acc_id,))
        txs = [dict(r) for r in cur.fetchall()]
        assert len(txs) == 2

        # Chipotle: recognized from memory
        assert txs[0]["merchant_name"] == "Chipotle"
        assert txs[0]["raw_merchant_name"] == "Chipotle"
        assert txs[0]["category_id"] == cat_dining
        assert txs[0]["category_source"] == "merchant_memory"
        assert txs[0]["category_confidence"] == 0.9
        assert txs[0]["essentiality_source"] == "merchant_memory"
        assert txs[0]["needs_review"] == 0
        assert txs[0]["parser_version"] == "import_v2"
        assert txs[0]["capture_method"] == "csv_import"

        # Mystery vendor: fallback needs review
        assert txs[1]["category_source"] == "fallback"
        assert txs[1]["category_confidence"] == 0.0
        assert txs[1]["needs_review"] == 1
        assert txs[1]["review_reason"] == "uncategorized"
        assert txs[1]["parser_version"] == "import_v2"
