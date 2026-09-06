import pytest
from app.backend.services.import_service import ImportService
from app.backend.services.merchant_service import MerchantService
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.database.connection import get_db_connection


def test_csv_import_persists_merchants_and_assigns_merchant_id(isolated_db):
    acc_id = AccountRepository.create("Checking", "checking", currency="USD")
    csv_content = """Date,Payee,Amount
2026-07-10,Whole Foods Market,-45.50
2026-07-11,Whole Foods Market,-15.20
"""
    mapping = {"date": "Date", "payee": "Payee", "amount": "Amount"}
    res = ImportService.commit_import(csv_content, mapping, account_id=acc_id, deduplicate=False)
    assert res["success"] is True
    assert res["imported_count"] == 2

    # Verify merchant was persisted into merchants table (FSC-H04)
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM merchants WHERE name = 'Whole Foods Market'")
        m_row = cur.fetchone()
        assert m_row is not None
        merchant_id = m_row["id"]

        # Verify transaction has merchant_id set
        cur.execute("SELECT merchant_id, merchant_name FROM transactions WHERE account_id = ?", (acc_id,))
        rows = cur.fetchall()
        assert len(rows) == 2
        for r in rows:
            assert r["merchant_id"] == merchant_id
            assert r["merchant_name"] == "Whole Foods Market"


def test_csv_import_semantic_category_fallback(isolated_db):
    acc_id = AccountRepository.create("Checking", "checking", currency="USD")

    csv_content = """Date,Description,Amount
2026-07-12,Coffee Shop,-4.50
2026-07-13,Freelance Payment,250.00
"""
    mapping = {"date": "Date", "description": "Description", "amount": "Amount"}
    res = ImportService.commit_import(csv_content, mapping, account_id=acc_id, deduplicate=False)
    assert res["success"] is True
    assert res["imported_count"] == 2

    # Verify semantic category assignment (FSC-H03)
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM categories WHERE name = 'Uncategorized'")
        uncat_row = cur.fetchone()
        uncat_id = uncat_row["id"] if uncat_row else 1

        cur.execute("SELECT id FROM categories WHERE name = 'Other Income'")
        inc_row = cur.fetchone()
        inc_id = inc_row["id"]

        cur.execute("""
            SELECT t.transaction_type, t.amount_minor, t.category_id, c.type as category_type
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE t.account_id = ?
            ORDER BY t.transaction_date ASC
        """, (acc_id,))
        rows = [dict(r) for r in cur.fetchall()]
        assert len(rows) == 2

        # Expense row has expense category
        assert rows[0]["transaction_type"] == "expense"
        assert rows[0]["category_type"] == "expense"
        assert rows[0]["category_id"] == uncat_id

        # Income row has income category, NEVER expense
        assert rows[1]["transaction_type"] == "income"
        assert rows[1]["category_type"] == "income"
        assert rows[1]["category_id"] == inc_id


def test_merchant_creation_on_conflict_idempotence(isolated_db):
    with get_db_connection() as conn:
        m1 = MerchantService.get_or_create_merchant_in_conn(conn, "Acme Supplies")
        m2 = MerchantService.get_or_create_merchant_in_conn(conn, "Acme Supplies")
        assert m1 > 0
        assert m1 == m2

        # Verify only 1 row in database
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM merchants WHERE name = 'Acme Supplies'")
        assert cur.fetchone()[0] == 1


def test_learn_defaults_overwrite_on_review(isolated_db):
    cat_old = CategoryRepository.create("Shopping", "expense")
    cat_new = CategoryRepository.create("Groceries", "expense")
    acc_id = AccountRepository.create("Checking", "checking", currency="USD")

    # Merchant created initially with cat_old
    m_id = MerchantService.get_or_create_merchant("Trader Joe's", category_id=cat_old)
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT default_category_id FROM merchants WHERE id = ?", (m_id,))
        assert cur.fetchone()[0] == cat_old

    # Overwrite defaults via learn_defaults (FSC-M14)
    MerchantService.learn_defaults(m_id, category_id=cat_new, overwrite=True)
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT default_category_id FROM merchants WHERE id = ?", (m_id,))
        assert cur.fetchone()[0] == cat_new

    # Creating an unreviewed transaction and resolving it also updates merchant defaults
    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "transaction_type": "expense",
        "amount": 35.0,
        "transaction_date": "2026-07-15",
        "merchant_name": "Trader Joe's",
        "needs_review": 1
    })
    cat_final = CategoryRepository.create("Supermarket", "expense")
    TransactionRepository.resolve_review(tx_id, category_id=cat_final)

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT default_category_id FROM merchants WHERE id = ?", (m_id,))
        assert cur.fetchone()[0] == cat_final


def test_review_queue_filters_by_account(isolated_db):
    acc1 = AccountRepository.create("Checking", "checking", currency="USD")
    acc2 = AccountRepository.create("Credit Card", "credit", currency="USD")
    cat_id = CategoryRepository.create("Misc", "expense")

    # Transaction 1 on Account 1 needing review
    TransactionRepository.create({
        "account_id": acc1,
        "category_id": cat_id,
        "transaction_type": "expense",
        "amount": 20.0,
        "transaction_date": "2026-07-01",
        "needs_review": 1
    })

    # Transaction 2 on Account 2 needing review
    TransactionRepository.create({
        "account_id": acc2,
        "category_id": cat_id,
        "transaction_type": "expense",
        "amount": 40.0,
        "transaction_date": "2026-07-02",
        "needs_review": 1
    })

    # Total review queue
    all_queue = TransactionRepository.get_review_queue()
    assert all_queue["total"] == 2

    # Filtered by acc1 (FSC-M09)
    acc1_queue = TransactionRepository.get_review_queue(account_id=acc1)
    assert acc1_queue["total"] == 1
    assert acc1_queue["items"][0]["account_id"] == acc1

    # Filtered by acc2
    acc2_queue = TransactionRepository.get_review_queue(account_id=acc2)
    assert acc2_queue["total"] == 1
    assert acc2_queue["items"][0]["account_id"] == acc2
