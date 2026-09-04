import urllib.request
import json

def post(endpoint, payload={}):
    req = urllib.request.Request(
        f"http://127.0.0.1:8088/api/{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    return json.loads(res.read())

print("Testing Accounts...")
accounts = post("get_accounts")["data"]
print("Accounts found:", len(accounts))
acc1_id = accounts[0]["id"]
acc2_id = accounts[1]["id"]

print("\nTesting Categories...")
categories = post("get_categories")["data"]
print("Categories found:", len(categories))
groceries_id = next(c["id"] for c in categories if c["name"] == "Groceries")

print("\n1. Testing Smart Capture - Create Expense with Payee Memory...")
tx1 = post("create_transaction", {
    "account_id": acc1_id,
    "category_id": groceries_id,
    "merchant_name": "Woolworths Store #452",
    "transaction_type": "expense",
    "amount": 78.50,
    "transaction_date": "2026-09-04",
    "description": "Weekly essentials"
})
print("Created tx1:", tx1)

print("\n2. Testing Merchant Autocomplete & Smart Defaults...")
sugg = post("get_merchant_suggestions", {"query": "wool"})["data"]
print("Suggestions count:", len(sugg))
print("Top suggestion:", sugg[0]["name"], "| Confidence:", sugg[0]["confidence"], "| Category:", sugg[0].get("category_name"))
assert sugg[0]["name"] == "Woolworths"
assert sugg[0]["confidence"] == "high"

print("\n3. Testing Uncategorized Fallback & Review Queue...")
tx_uncat_id = post("create_transaction", {
    "account_id": acc1_id,
    "category_id": None,
    "merchant_name": "Mysterious Vendor",
    "transaction_type": "expense",
    "amount": 25.00,
    "transaction_date": "2026-09-04",
    "description": "Unknown purchase"
})["data"]
print("Created uncat tx ID:", tx_uncat_id)

rq = post("get_review_queue")["data"]
print("Review Queue count:", rq["total"])
assert any(item["id"] == tx_uncat_id for item in rq["items"])

print("Resolving Review...")
post("resolve_review", {
    "tx_id": tx_uncat_id,
    "category_id": groceries_id,
    "merchant_name": "Mysterious Vendor"
})
rq_after = post("get_review_queue")["data"]
assert not any(item["id"] == tx_uncat_id for item in rq_after["items"])
print("Resolved! Review Queue items remaining:", rq_after["total"])

print("\n4. Testing Double-Entry Transfer with Explicit Roles...")
transfer = post("create_transfer", {
    "from_account_id": acc1_id,
    "to_account_id": acc2_id,
    "amount": 100.00,
    "transaction_date": "2026-09-04",
    "description": "Savings Allocation"
})["data"]
print("Transfer created, group:", transfer["transfer_group_id"])
source_tx = transfer["source_transaction"]
dest_tx = transfer["destination_transaction"]
print("Source role:", source_tx["transfer_role"], "| Dest role:", dest_tx["transfer_role"])
assert source_tx["transfer_role"] == "source"
assert dest_tx["transfer_role"] == "destination"

print("\n5. Testing Linked Refund...")
refund_id = post("create_refund", {
    "original_transaction_id": tx1["data"],
    "amount": 20.00,
    "account_id": acc1_id,
    "transaction_date": "2026-09-04"
})["data"]
print("Created linked refund ID:", refund_id)

print("\n6. Testing Soft Delete & 5-Second Undo...")
post("delete_transaction", {"tx_id": refund_id})
tx_del = post("get_transaction", {"tx_id": refund_id})["data"]
assert tx_del is None, "Deleted transaction should return None"
print("Transaction soft-deleted successfully (excluded from queries).")

post("undo_delete_transaction", {"tx_id": refund_id})
tx_restored = post("get_transaction", {"tx_id": refund_id})["data"]
assert tx_restored is not None, "Transaction should be restored"
print("Transaction successfully restored via undo_delete!")

print("\n[SUCCESS] ALL LIVE CORE API TESTS PASSED 100%!")
