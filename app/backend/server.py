import os
import json
import secrets
import mimetypes
import logging
from typing import Dict, Callable, Any, Optional
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from app.backend.config import FRONTEND_DIR
from app.backend.api.handler import ApiHandler

logger = logging.getLogger(__name__)

# Global singletons
api_handler = ApiHandler()
CURRENT_SESSION_TOKEN = secrets.token_urlsafe(32)

def get_current_session_token() -> str:
    """Returns the current active in-memory session token."""
    return CURRENT_SESSION_TOKEN

def reset_session_token() -> str:
    """Regenerates the session token (used during server restarts/testing)."""
    global CURRENT_SESSION_TOKEN
    CURRENT_SESSION_TOKEN = secrets.token_urlsafe(32)
    return CURRENT_SESSION_TOKEN

@dataclass
class Route:
    handler: Callable
    capability: str  # READ, WRITE, DESTRUCTIVE, PRIVILEGED_DESKTOP

# Explicit Route Registry - No dynamic reflection allowed
ROUTES: Dict[str, Route] = {
    # Accounts
    "get_accounts": Route(api_handler.get_accounts, "READ"),
    "create_account": Route(api_handler.create_account, "WRITE"),
    "update_account": Route(api_handler.update_account, "WRITE"),
    "delete_account": Route(api_handler.delete_account, "DESTRUCTIVE"),

    # Categories
    "get_categories": Route(api_handler.get_categories, "READ"),
    "create_category": Route(api_handler.create_category, "WRITE"),
    "update_category": Route(api_handler.update_category, "WRITE"),
    "delete_category": Route(api_handler.delete_category, "DESTRUCTIVE"),

    # Transactions
    "get_transactions": Route(api_handler.get_transactions, "READ"),
    "get_transaction": Route(api_handler.get_transaction, "READ"),
    "create_transaction": Route(api_handler.create_transaction, "WRITE"),
    "create_transfer": Route(api_handler.create_transfer, "WRITE"),
    "update_transfer": Route(api_handler.update_transfer, "WRITE"),
    "create_refund": Route(api_handler.create_refund, "WRITE"),
    "update_refund": Route(api_handler.update_refund, "WRITE"),
    "update_transaction": Route(api_handler.update_transaction, "WRITE"),
    "delete_transaction": Route(api_handler.delete_transaction, "DESTRUCTIVE"),
    "undo_delete_transaction": Route(api_handler.undo_delete_transaction, "WRITE"),
    "duplicate_transaction": Route(api_handler.duplicate_transaction, "WRITE"),

    # Merchant Intelligence
    "get_merchant_suggestions": Route(api_handler.get_merchant_suggestions, "READ"),
    "get_recent_payees": Route(api_handler.get_recent_payees, "READ"),

    # Review Queue & Data Quality
    "get_review_queue": Route(api_handler.get_review_queue, "READ"),
    "resolve_review": Route(api_handler.resolve_review, "WRITE"),

    # Analytics & BI V2
    "get_analytics_context": Route(api_handler.get_analytics_context, "READ"),
    "get_month_summary": Route(api_handler.get_month_summary, "READ"),
    "get_calendar_data": Route(api_handler.get_calendar_data, "READ"),
    "get_analytics_deep_dive": Route(api_handler.get_analytics_deep_dive, "READ"),
    "get_rolling_metrics": Route(api_handler.get_rolling_metrics, "READ"),
    "get_what_changed": Route(api_handler.get_what_changed, "READ"),
    "get_merchant_drilldown": Route(api_handler.get_merchant_drilldown, "READ"),
    "get_spending_fingerprint": Route(api_handler.get_spending_fingerprint, "READ"),
    "get_anomalies": Route(api_handler.get_anomalies, "READ"),
    "get_normal_ranges": Route(api_handler.get_normal_ranges, "READ"),
    "get_forecast": Route(api_handler.get_forecast, "READ"),
    "get_ranked_insights": Route(api_handler.get_ranked_insights, "READ"),
    "dismiss_insight": Route(api_handler.dismiss_insight, "WRITE"),
    "get_backtest_evaluation": Route(api_handler.get_backtest_evaluation, "READ"),

    # Budgets
    "get_monthly_budget": Route(api_handler.get_monthly_budget, "READ"),
    "set_category_budget": Route(api_handler.set_category_budget, "WRITE"),

    # Backup & Storage
    "create_backup": Route(api_handler.create_backup, "WRITE"),
    "list_backups": Route(api_handler.list_backups, "READ"),
    "restore_backup": Route(api_handler.restore_backup, "DESTRUCTIVE"),
    "get_storage_health": Route(api_handler.get_storage_health, "READ"),
    "seed_demo_data": Route(api_handler.seed_demo_data, "WRITE"),
    "open_data_dir": Route(api_handler.open_data_dir, "PRIVILEGED_DESKTOP"),

    # Bank CSV Import Wizard
    "preview_csv_import": Route(api_handler.preview_csv_import, "READ"),
    "commit_csv_import": Route(api_handler.commit_csv_import, "WRITE"),

    # Recurring Rules & Bills
    "get_recurring_rules": Route(api_handler.get_recurring_rules, "READ"),
    "create_recurring_rule": Route(api_handler.create_recurring_rule, "WRITE"),
    "update_recurring_rule": Route(api_handler.update_recurring_rule, "WRITE"),
    "delete_recurring_rule": Route(api_handler.delete_recurring_rule, "DESTRUCTIVE"),
    "get_upcoming_bills": Route(api_handler.get_upcoming_bills, "READ"),

    # Settings
    "get_settings": Route(api_handler.get_settings, "READ"),
    "update_settings": Route(api_handler.update_settings, "WRITE"),
}

MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB limit

def authorize_request(
    handler: "FinScopeHTTPHandler",
    route: Route,
    method_name: str
) -> Optional[tuple[int, str, str]]:
    """
    Central authorization policy enforcing route capability constraints (V103-07 / Model A).
    Tiers:
    - READ: Local loopback host, valid origin if provided, valid session token.
    - WRITE: Local loopback host, valid loopback origin, valid session token.
    - DESTRUCTIVE: Local loopback host, verified local origin, valid session token,
      and rejection of cross-site request contexts.
    - PRIVILEGED_DESKTOP: Local loopback host, verified local origin, valid session token,
      and strict direct local client execution (rejects cross-site and browser element contexts).
    """
    # 1. Base host validation
    if not handler._is_allowed_host():
        return (403, "FORBIDDEN_HOST", "Invalid Host header")

    # 2. Session Token validation
    token = handler.headers.get("X-FinScope-Token")
    if token != CURRENT_SESSION_TOKEN:
        return (403, "UNAUTHORIZED", "Missing or invalid session token")

    # 3. Base origin validation
    if not handler._is_allowed_origin():
        return (403, "FORBIDDEN_ORIGIN", "Invalid Origin header")

    capability = route.capability

    # 4. Capability-specific policies
    if capability == "DESTRUCTIVE":
        sec_site = handler.headers.get("Sec-Fetch-Site")
        if sec_site and sec_site not in ("same-origin", "none"):
            return (403, "FORBIDDEN_ORIGIN", "Destructive operations blocked from cross-origin/cross-site requests.")

    elif capability == "PRIVILEGED_DESKTOP":
        sec_site = handler.headers.get("Sec-Fetch-Site")
        if sec_site and sec_site not in ("same-origin", "none"):
            return (403, "FORBIDDEN_CAPABILITY", "Privileged desktop operations are restricted to direct local client.")
        sec_dest = handler.headers.get("Sec-Fetch-Dest")
        if sec_dest and sec_dest not in ("empty", ""):
            return (403, "FORBIDDEN_CAPABILITY", "Privileged desktop operations rejected from browser element context.")

    return None

class FinScopeHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def log_message(self, format, *args):
        # Silence routine static asset logs
        return

    def _is_allowed_host(self) -> bool:
        host = self.headers.get("Host", "")
        if not host:
            return False
        hostname = host.split(":")[0].strip().lower()
        return hostname in ("127.0.0.1", "localhost")

    def _is_allowed_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True  # Native desktop / same-origin without Origin header
        try:
            parsed = urlparse(origin)
            hostname = (parsed.hostname or "").lower()
            if hostname not in ("127.0.0.1", "localhost"):
                return False
            # AUD-010: Enforce scheme and port match actual FinScope listening port
            if parsed.scheme not in ("http", "https"):
                return False
            expected_port = self.server.server_address[1]
            origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            return origin_port == expected_port
        except Exception:
            return False

    def _send_json_error(self, status_code: int, code: str, message: str):
        payload = {
            "api_version": 2,
            "success": False,
            "error": {
                "code": code,
                "message": message
            }
        }
        self._send_json(status_code, payload)

    def do_OPTIONS(self):
        """Handles CORS preflight requests securely for local loopback only."""
        if not self._is_allowed_host() or not self._is_allowed_origin():
            self.send_response(403)
            self.end_headers()
            return

        origin = self.headers.get("Origin") or "http://127.0.0.1"
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-FinScope-Token")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        # 1. Host security check
        if not self._is_allowed_host():
            self._send_json_error(403, "FORBIDDEN_HOST", "Invalid Host header")
            return

        # 2. Local Session Bootstrap API (only callable from loopback)
        if parsed.path == "/api/bootstrap":
            if not self._is_allowed_origin():
                self._send_json_error(403, "FORBIDDEN_ORIGIN", "Invalid Origin")
                return
            port = self.server.server_address[1]
            data = {
                "token": CURRENT_SESSION_TOKEN,
                "port": port,
                "api_version": 2
            }
            self._send_json(200, {"api_version": 2, "success": True, "data": data})
            return

        # 3. CSV Export
        if parsed.path == "/api/export_csv":
            if not self._is_allowed_origin():
                self._send_json_error(403, "FORBIDDEN_ORIGIN", "Invalid Origin")
                return
            
            # Check session token for export
            query_params = parse_qs(parsed.query)
            token = self.headers.get("X-FinScope-Token") or (query_params.get("token", [None])[0])
            if token != CURRENT_SESSION_TOKEN:
                self._send_json_error(403, "UNAUTHORIZED", "Missing or invalid session token")
                return

            try:
                month = query_params.get("month", [None])[0]
                account_id_val = query_params.get("account_id", [None])[0]
                account_id = int(account_id_val) if account_id_val and account_id_val.isdigit() else None
                start_date = query_params.get("start_date", [None])[0]
                end_date = query_params.get("end_date", [None])[0]

                csv_path = api_handler.export_csv(
                    month=month,
                    account_id=account_id,
                    start_date=start_date,
                    end_date=end_date
                )
                with open(csv_path, "rb") as f:
                    csv_content = f.read()

                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f"attachment; filename={Path(csv_path).name}")
                self.send_header("Content-Length", str(len(csv_content)))
                self.end_headers()
                self.wfile.write(csv_content)
            except Exception as e:
                logger.exception("Error exporting CSV")
                self._send_json_error(500, "EXPORT_ERROR", str(e))
            return

        # 4. HTML Serving with Dynamic Token Injection
        if parsed.path in ("/", "/index.html"):
            index_path = FRONTEND_DIR / "index.html"
            if index_path.exists():
                try:
                    with open(index_path, "r", encoding="utf-8") as f:
                        html_content = f.read()

                    port = self.server.server_address[1]
                    token_script = f"""
    <script>
      window.__FINSCOPE_TOKEN__ = "{CURRENT_SESSION_TOKEN}";
      window.__FINSCOPE_PORT__ = {port};
    </script>
</head>"""
                    if "</head>" in html_content:
                        html_content = html_content.replace("</head>", token_script, 1)

                    content_bytes = html_content.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content_bytes)))
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    self.wfile.write(content_bytes)
                    return
                except Exception as e:
                    logger.exception("Error injecting session token into index.html")

        # 5. Default static file serving from FRONTEND_DIR
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)

        # 1. Host validation
        if not self._is_allowed_host():
            self._send_json_error(403, "FORBIDDEN_HOST", "Invalid Host header")
            return

        # 2. Origin validation
        if not self._is_allowed_origin():
            self._send_json_error(403, "FORBIDDEN_ORIGIN", "Invalid Origin header")
            return

        # 3. Route matching
        if not parsed.path.startswith("/api/"):
            self._send_json_error(404, "NOT_FOUND", "Endpoint not found")
            return

        method_name = parsed.path.replace("/api/", "").strip()
        if method_name not in ROUTES:
            self._send_json_error(404, "ROUTE_NOT_FOUND", f"API method '{method_name}' not found")
            return

        route = ROUTES[method_name]

        # 4. V103-07: Central Route Capability Authorization
        auth_error = authorize_request(self, route, method_name)
        if auth_error:
            status_code, err_code, err_msg = auth_error
            self._send_json_error(status_code, err_code, err_msg)
            return

        # 5. Payload size cap
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len > MAX_BODY_BYTES:
            self._send_json_error(413, "PAYLOAD_TOO_LARGE", f"Request payload exceeds {MAX_BODY_BYTES} bytes")
            return

        # 6. Parse JSON body
        body_bytes = self.rfile.read(content_len) if content_len > 0 else b""
        params = {}
        if body_bytes:
            content_type = self.headers.get("Content-Type", "")
            if "application/json" not in content_type:
                self._send_json_error(400, "INVALID_CONTENT_TYPE", "Content-Type must be application/json")
                return
            try:
                params = json.loads(body_bytes.decode("utf-8"))
            except Exception as e:
                self._send_json_error(400, "MALFORMED_JSON", f"Invalid JSON payload: {str(e)}")
                return

        # 7. Execute Route Handler
        try:
            fn = route.handler
            if isinstance(params, dict):
                result = fn(**params)
            elif isinstance(params, list):
                result = fn(*params)
            else:
                result = fn(params)

            response_data = {
                "api_version": 2,
                "success": True,
                "data": result
            }
            self._send_json(200, response_data)
        except (ValueError, TypeError) as e:
            logger.warning("Validation error on API method %s: %s", method_name, e)
            self._send_json_error(422, "VALIDATION_ERROR", str(e))
        except FileNotFoundError as e:
            logger.warning("Resource not found on API method %s: %s", method_name, e)
            self._send_json_error(404, "NOT_FOUND", str(e))
        except Exception as e:
            logger.exception("Unexpected error executing API method %s", method_name)
            self._send_json_error(500, "INTERNAL_ERROR", "An unexpected internal server error occurred.")

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Only reflect Origin if local loopback, never send wildcard '*'
        origin = self.headers.get("Origin")
        if origin and self._is_allowed_origin():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
        self.end_headers()
        self.wfile.write(body)

def start_server(port: int = 8080) -> tuple[ThreadingHTTPServer, int]:
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("image/svg+xml", ".svg")

    if port == 0:
        server_address = ("127.0.0.1", 0)
        httpd = ThreadingHTTPServer(server_address, FinScopeHTTPHandler)
        actual_port = httpd.server_address[1]
        logger.info("FinScope test server running on ephemeral http://127.0.0.1:%d", actual_port)
        return httpd, actual_port

    candidate_ports = [port, 8080, 8088, 8888, 5500, 5000]
    for p in candidate_ports:
        try:
            server_address = ("127.0.0.1", p)
            httpd = ThreadingHTTPServer(server_address, FinScopeHTTPHandler)
            logger.info("FinScope local server running on http://127.0.0.1:%d", p)
            return httpd, p
        except OSError as e:
            logger.warning("Port %d unavailable (%s), trying next...", p, e)

    # Fallback to ephemeral free port
    server_address = ("127.0.0.1", 0)
    httpd = ThreadingHTTPServer(server_address, FinScopeHTTPHandler)
    actual_port = httpd.server_address[1]
    logger.info("FinScope local server running on http://127.0.0.1:%d", actual_port)
    return httpd, actual_port
