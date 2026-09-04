import random
import calendar
from datetime import datetime, timedelta, date
from app.backend.database.connection import get_db_connection
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository

SAMPLE_MERCHANTS = {
    "Groceries": [("Woolworths", 65.5, 140.0), ("Coles", 42.0, 110.0), ("Aldi", 35.0, 85.0), ("Fresh Market", 25.0, 60.0)],
    "Dining & Coffee": [("Blue Bottle Coffee", 5.5, 9.0), ("Starbucks", 6.2, 12.5), ("Trattoria Bella", 45.0, 120.0), ("Ramen Nagi", 18.0, 38.0), ("Uber Eats", 24.0, 55.0)],
    "Housing & Rent": [("City Property Lease", 1600.0, 1600.0)],
    "Utilities & Bills": [("Energy Australia", 85.0, 145.0), ("Telstra Mobile", 55.0, 65.0), ("HighSpeed Fiber", 75.0, 75.0), ("City Water", 45.0, 70.0)],
    "Transportation & Fuel": [("BP Fuel Express", 45.0, 85.0), ("Metro Transit Pass", 35.0, 50.0), ("Uber Ride", 14.0, 32.0), ("Shell Gas", 50.0, 90.0)],
    "Shopping & Tech": [("Amazon", 25.0, 150.0), ("Apple Store", 35.0, 200.0), ("Uniqlo", 45.0, 120.0), ("IKEA", 60.0, 220.0)],
    "Entertainment & Subscriptions": [("Netflix", 19.99, 19.99), ("Spotify Premium", 12.99, 12.99), ("Cinema City", 28.0, 48.0), ("Gym Membership", 49.0, 49.0)],
    "Healthcare & Wellness": [("Chemist Warehouse", 18.0, 55.0), ("Dental Care", 120.0, 250.0), ("Physio Studio", 80.0, 95.0)],
}

SAMPLE_BUDGETS = {
    "Groceries": 650.0,
    "Dining & Coffee": 350.0,
    "Housing & Rent": 1600.0,
    "Utilities & Bills": 300.0,
    "Transportation & Fuel": 220.0,
    "Shopping & Tech": 300.0,
    "Entertainment & Subscriptions": 150.0,
    "Healthcare & Wellness": 150.0,
}

def seed_sample_data(clear_existing: bool = False):
    """Generates realistic personal finance data for current and previous 3 months in integer minor units."""
    accounts = AccountRepository.get_all()
    categories = CategoryRepository.get_all()

    if not accounts or not categories:
        return {"success": False, "message": "Missing accounts or categories"}

    acc_everyday = next((a["id"] for a in accounts if a["account_type"] == "Everyday"), accounts[0]["id"])
    acc_savings = next((a["id"] for a in accounts if a["account_type"] == "Savings"), accounts[1]["id"] if len(accounts) > 1 else accounts[0]["id"])
    acc_credit = next((a["id"] for a in accounts if a["account_type"] == "Credit Card"), accounts[0]["id"])

    cat_map = {c["name"]: c["id"] for c in categories}
    cat_salary_id = cat_map.get("Salary / Primary Job")
    cat_freelance_id = cat_map.get("Freelance & Consulting")
    cat_shopping_id = cat_map.get("Shopping & Tech")

    with get_db_connection() as conn:
        cur = conn.cursor()
        if clear_existing:
            cur.execute("DELETE FROM transactions")
            cur.execute("DELETE FROM budgets")

        today = date.today()
        months_to_seed = []
        for i in range(4):
            m = today.month - i
            y = today.year
            while m <= 0:
                m += 12
                y -= 1
            months_to_seed.append((y, m))

        months_to_seed.reverse()

        for y, m in months_to_seed:
            month_str = f"{y}-{m:02d}"
            max_days = calendar.monthrange(y, m)[1]
            limit_day = min(today.day, max_days) if (y == today.year and m == today.month) else max_days

            # 1. Seed Budgets for this month in integer minor units
            for cat_name, b_amt in SAMPLE_BUDGETS.items():
                c_id = cat_map.get(cat_name)
                if c_id:
                    conn.execute("""
                        INSERT INTO budgets (category_id, start_date, amount_minor, period_type)
                        VALUES (?, ?, ?, 'monthly')
                        ON CONFLICT(category_id, start_date) DO UPDATE SET
                            amount_minor = excluded.amount_minor
                    """, (c_id, month_str, int(round(b_amt * 100))))

            # 2. Seed Monthly Incomes: 2 salaries (1st and 15th)
            conn.execute("""
                INSERT INTO transactions (account_id, category_id, merchant_name, transaction_type, amount_minor, transaction_date, transaction_time, description, note, essentiality, payment_method)
                VALUES (?, ?, 'TechCorp Global', 'income', 285000, ?, '09:00', 'Bi-weekly Salary', 'Direct Deposit', 'savings', 'Direct Deposit')
            """, (acc_everyday, cat_salary_id, f"{month_str}-01"))

            if limit_day >= 15:
                conn.execute("""
                    INSERT INTO transactions (account_id, category_id, merchant_name, transaction_type, amount_minor, transaction_date, transaction_time, description, note, essentiality, payment_method)
                    VALUES (?, ?, 'TechCorp Global', 'income', 285000, ?, '09:00', 'Bi-weekly Salary', 'Direct Deposit', 'savings', 'Direct Deposit')
                """, (acc_everyday, cat_salary_id, f"{month_str}-15"))

            # 3. Monthly Savings Transfer on 3rd (Double-entry transfer)
            if limit_day >= 3:
                transfer_uuid = f"sample-transfer-{y}-{m:02d}"
                conn.execute("""
                    INSERT INTO transactions (account_id, merchant_name, transaction_type, amount_minor, transaction_date, transaction_time, description, note, payment_method, essentiality, transfer_group_id)
                    VALUES (?, 'Transfer to High Yield Savings', 'transfer', 50000, ?, '10:00', 'Monthly Savings Transfer', 'High yield savings allocation', 'Transfer', 'savings', ?)
                """, (acc_everyday, f"{month_str}-03", transfer_uuid))
                conn.execute("""
                    INSERT INTO transactions (account_id, merchant_name, transaction_type, amount_minor, transaction_date, transaction_time, description, note, payment_method, essentiality, transfer_group_id)
                    VALUES (?, 'Transfer from Everyday Checking', 'transfer', 50000, ?, '10:00', 'Monthly Savings Transfer (Received)', 'High yield savings allocation', 'Transfer', 'savings', ?)
                """, (acc_savings, f"{month_str}-03", transfer_uuid))

            # 4. Rent on 2nd of each month
            rent_cat_id = cat_map.get("Housing & Rent")
            if rent_cat_id and limit_day >= 2:
                conn.execute("""
                    INSERT INTO transactions (account_id, category_id, merchant_name, transaction_type, amount_minor, transaction_date, transaction_time, description, note, essentiality, payment_method)
                    VALUES (?, ?, 'City Property Lease', 'expense', 160000, ?, '08:00', 'Monthly Apartment Rent', 'Electronic payment', 'essential', 'Bank Transfer')
                """, (acc_everyday, rent_cat_id, f"{month_str}-02"))

            # 5. Recurring Subscriptions
            sub_cat_id = cat_map.get("Entertainment & Subscriptions")
            if sub_cat_id and limit_day >= 5:
                conn.execute("""
                    INSERT INTO transactions (account_id, category_id, merchant_name, transaction_type, amount_minor, transaction_date, transaction_time, description, note, is_recurring, essentiality, payment_method)
                    VALUES (?, ?, 'Netflix', 'expense', 1999, ?, '10:00', 'Standard HD Subscription', 'Automatic billing', 1, 'discretionary', 'Card')
                """, (acc_credit, sub_cat_id, f"{month_str}-05"))

            if sub_cat_id and limit_day >= 12:
                conn.execute("""
                    INSERT INTO transactions (account_id, category_id, merchant_name, transaction_type, amount_minor, transaction_date, transaction_time, description, note, is_recurring, essentiality, payment_method)
                    VALUES (?, ?, 'Spotify Premium', 'expense', 1299, ?, '10:00', 'Family Plan Subscription', 'Automatic billing', 1, 'discretionary', 'Card')
                """, (acc_credit, sub_cat_id, f"{month_str}-12"))

            # 6. Sample Refund on 14th (Shopping item return)
            if limit_day >= 14 and cat_shopping_id:
                conn.execute("""
                    INSERT INTO transactions (account_id, category_id, merchant_name, transaction_type, amount_minor, transaction_date, transaction_time, description, note, essentiality, payment_method)
                    VALUES (?, ?, 'Uniqlo Return', 'refund', 4500, ?, '15:20', 'Clothing item exchange refund', 'Credited to card', 'discretionary', 'Card')
                """, (acc_credit, cat_shopping_id, f"{month_str}-14"))

            # 7. Random daily expenses
            for day in range(1, limit_day + 1):
                date_str = f"{month_str}-{day:02d}"
                if random.random() < 0.70:
                    num_tx = random.choice([1, 1, 2])
                    for _ in range(num_tx):
                        cat_choice = random.choice(["Groceries", "Dining & Coffee", "Transportation & Fuel", "Shopping & Tech", "Healthcare & Wellness"])
                        cat_id = cat_map.get(cat_choice)
                        if not cat_id or cat_choice not in SAMPLE_MERCHANTS:
                            continue

                        merchant_info = random.choice(SAMPLE_MERCHANTS[cat_choice])
                        m_name, min_amt, max_amt = merchant_info
                        amt_minor = int(round(random.uniform(min_amt, max_amt) * 100))
                        account_chosen = acc_credit if random.random() < 0.6 else acc_everyday
                        is_ess = "essential" if cat_choice in ["Groceries", "Transportation & Fuel", "Healthcare & Wellness"] else "discretionary"

                        hour = random.randint(8, 21)
                        minute = random.choice([0, 15, 30, 45])
                        t_time = f"{hour:02d}:{minute:02d}"

                        conn.execute("""
                            INSERT INTO transactions (
                                account_id, category_id, merchant_name, transaction_type,
                                amount_minor, transaction_date, transaction_time, description,
                                note, essentiality, payment_method
                            ) VALUES (?, ?, ?, 'expense', ?, ?, ?, ?, '', ?, 'Card')
                        """, (account_chosen, cat_id, m_name, amt_minor, date_str, t_time, f"{cat_choice} at {m_name}", is_ess))

        conn.commit()

    return {"success": True, "message": "Demo sample data created successfully!"}
