import urllib.request
import json

base = "http://127.0.0.1:8088"

def test_get(path):
    url = f"{base}{path}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as r:
        content = r.read()
        print(f"GET {path} -> Status {r.status}, Content-Type: {r.headers.get('Content-Type')}, Size: {len(content):,} bytes")

def test_post(path, body):
    url = f"{base}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read().decode("utf-8"))
        print(f"POST {path} -> Success: {resp.get('success')}")

if __name__ == "__main__":
    print("Testing static assets...")
    test_get("/")
    test_get("/assets/css/theme.css")
    test_get("/assets/css/layout.css")
    test_get("/assets/css/components.css")
    test_get("/assets/vendor/echarts.min.js")
    test_get("/assets/vendor/lucide.min.js")
    test_get("/assets/js/api.js")
    test_get("/assets/js/state.js")
    test_get("/assets/js/router.js")

    print("\nTesting API endpoints...")
    test_post("/api/get_month_summary", {"month": "2026-09"})
    test_post("/api/get_transactions", {"month": "2026-09", "limit": 5})
    test_post("/api/get_calendar_data", {"month": "2026-09"})
    test_post("/api/get_analytics_deep_dive", {"month": "2026-09"})
    test_post("/api/get_monthly_budget", {"month": "2026-09"})
    test_post("/api/get_storage_health", {})
    test_post("/api/create_backup", {})
    test_get("/api/export_csv")
    print("\nAll HTTP & API endpoints tested successfully!")
