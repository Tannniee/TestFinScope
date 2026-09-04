import os
import sys
import shutil
import tempfile
import threading
import urllib.request
import json
from pathlib import Path
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backend import config
from app.backend.database.connection import init_db, get_db_connection
from app.backend.server import start_server, get_current_session_token

@pytest.fixture
def isolated_data_dir():
    """Provides an isolated temporary data directory for tests to prevent touching real user data."""
    temp_dir = Path(tempfile.mkdtemp(prefix="finscope_test_"))
    old_env = os.environ.get("FINSCOPE_DATA_DIR")
    os.environ["FINSCOPE_DATA_DIR"] = str(temp_dir)
    config.set_data_dir(temp_dir)

    yield temp_dir

    # Cleanup
    if old_env:
        os.environ["FINSCOPE_DATA_DIR"] = old_env
        config.set_data_dir(Path(old_env))
    else:
        os.environ.pop("FINSCOPE_DATA_DIR", None)
    shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.fixture
def isolated_db(isolated_data_dir):
    """Initializes a fresh, clean database in an isolated directory."""
    init_db()
    with get_db_connection() as conn:
        yield conn

@pytest.fixture
def ephemeral_server(isolated_data_dir):
    """Starts the FinScope HTTP server on an OS-assigned ephemeral port (port 0) and yields (base_url, token)."""
    init_db()
    httpd, port = start_server(port=0)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    token = get_current_session_token()
    base_url = f"http://127.0.0.1:{port}"

    class TestClient:
        def __init__(self, url, auth_token):
            self.base_url = url
            self.token = auth_token

        def post(self, method, payload=None, headers=None):
            req_headers = {
                "Content-Type": "application/json",
                "X-FinScope-Token": self.token,
                "Origin": self.base_url
            }
            if headers:
                req_headers.update(headers)
            body = json.dumps(payload or {}).encode("utf-8")
            req = urllib.request.Request(f"{self.base_url}/api/{method}", data=body, headers=req_headers, method="POST")
            try:
                with urllib.request.urlopen(req) as resp:
                    return resp.status, json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                try:
                    err_data = json.loads(e.read().decode("utf-8"))
                except Exception:
                    err_data = {"error": str(e)}
                return e.code, err_data

        def get(self, path, headers=None):
            req_headers = {
                "Origin": self.base_url
            }
            if headers:
                req_headers.update(headers)
            req = urllib.request.Request(f"{self.base_url}{path}", headers=req_headers, method="GET")
            try:
                with urllib.request.urlopen(req) as resp:
                    raw = resp.read()
                    try:
                        return resp.status, json.loads(raw.decode("utf-8"))
                    except Exception:
                        return resp.status, raw.decode("utf-8")
            except urllib.error.HTTPError as e:
                try:
                    err_data = json.loads(e.read().decode("utf-8"))
                except Exception:
                    err_data = {"error": str(e)}
                return e.code, err_data

        def get_export_csv(self, headers=None):
            req_headers = {
                "X-FinScope-Token": self.token,
                "Origin": self.base_url
            }
            if headers:
                req_headers.update(headers)
            req = urllib.request.Request(f"{self.base_url}/api/export_csv", headers=req_headers, method="GET")
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read().decode("utf-8")

    client = TestClient(base_url, token)
    yield client

    httpd.shutdown()
    server_thread.join(timeout=2.0)
