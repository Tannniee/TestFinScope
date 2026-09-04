import sys
import os
import threading
import argparse
import webbrowser
import logging
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.backend.database.connection import init_db, get_db_connection
from app.backend.server import start_server
from app.backend.services.sample_data import seed_sample_data
from app.backend.api.handler import ApiHandler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("FinScope")

class DesktopBridge:
    """Narrow native desktop capabilities exposed to PyWebView shell."""
    def is_desktop(self) -> bool:
        return True

    def open_data_folder(self):
        from app.backend.config import open_data_folder
        return open_data_folder()

def main():
    parser = argparse.ArgumentParser(description="FinScope — Personal Finance Analytics")
    parser.add_argument("--browser", action="store_true", help="Launch in default web browser instead of desktop window")
    parser.add_argument("--port", type=int, default=8000, help="Local server port (default: 8000)")
    parser.add_argument("--seed", action="store_true", help="Force populate sample demo data")
    args = parser.parse_args()

    # 1. Initialize SQLite Database
    logger.info("Initializing database...")
    init_db()

    # Seed sample demo data ONLY if explicitly requested via --seed flag
    if args.seed:
        logger.info("Explicit --seed flag passed. Populating realistic demo data...")
        seed_sample_data(clear_existing=True)

    # 2. Start Local Server
    server, actual_port = start_server(port=args.port)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    url = f"http://127.0.0.1:{actual_port}"
    logger.info("FinScope frontend ready at %s", url)

    # 3. Launch App Window or Browser
    if args.browser:
        logger.info("Opening in system web browser...")
        webbrowser.open(url)
        try:
            while True:
                server_thread.join(timeout=1.0)
        except KeyboardInterrupt:
            logger.info("Shutting down FinScope...")
            server.shutdown()
    else:
        try:
            import webview
            logger.info("Opening desktop application window via WebView2...")
            desktop_bridge = DesktopBridge()
            window = webview.create_window(
                title="FinScope — Personal Finance Analytics",
                url=url,
                js_api=desktop_bridge,
                width=1400,
                height=880,
                min_size=(1080, 720),
                background_color="#0E1324"
            )
            webview.start(gui="edgechromium", debug=False)
            server.shutdown()
        except Exception as e:
            logger.warning("Could not launch pywebview window (%s). Falling back to browser mode...", e)
            webbrowser.open(url)
            try:
                while True:
                    server_thread.join(timeout=1.0)
            except KeyboardInterrupt:
                server.shutdown()

if __name__ == "__main__":
    main()
