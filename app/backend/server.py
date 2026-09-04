import os
import json
import mimetypes
import logging
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from app.backend.config import FRONTEND_DIR
from app.backend.api.handler import ApiHandler

logger = logging.getLogger(__name__)

api_handler = ApiHandler()

class FinScopeHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def log_message(self, format, *args):
        # Silence routine static asset logs
        return

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            method_name = parsed.path.replace("/api/", "").strip()
            content_len = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_len) if content_len > 0 else b"{}"

            try:
                params = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            except Exception:
                params = {}

            if hasattr(api_handler, method_name):
                try:
                    fn = getattr(api_handler, method_name)
                    if isinstance(params, dict):
                        result = fn(**params)
                    elif isinstance(params, list):
                        result = fn(*params)
                    else:
                        result = fn(params)

                    response_data = {"success": True, "data": result}
                    self._send_json(200, response_data)
                except Exception as e:
                    logger.exception("Error executing API method %s", method_name)
                    self._send_json(500, {"success": False, "error": str(e)})
            else:
                self._send_json(404, {"success": False, "error": f"API method '{method_name}' not found"})
        else:
            self._send_json(404, {"success": False, "error": "Endpoint not found"})

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/export_csv":
            try:
                csv_path = api_handler.export_csv()
                with open(csv_path, "rb") as f:
                    csv_content = f.read()

                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f"attachment; filename={Path(csv_path).name}")
                self.send_header("Content-Length", str(len(csv_content)))
                self.end_headers()
                self.wfile.write(csv_content)
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
            return

        # Default static file serving from FRONTEND_DIR
        return super().do_GET()

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

def start_server(port: int = 8080) -> tuple[ThreadingHTTPServer, int]:
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("image/svg+xml", ".svg")

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
