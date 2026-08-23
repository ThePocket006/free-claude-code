import asyncio
import subprocess
import sys
import threading
import time

import uvicorn

from free_claude_code.config.loader import get_settings
from free_claude_code.runtime.bootstrap import build_asgi_app

s = get_settings()
print(f"port: {s.port}, host: {s.host}, model: {s.model}")
app = build_asgi_app(s)
config = uvicorn.Config(app, host=s.host, port=s.port, log_level="debug")
server = uvicorn.Server(config)


def test_health():
    time.sleep(3)
    try:
        # Use curl.exe to test
        result = subprocess.run(
            [
                "curl.exe",
                "-s",
                "-o",
                "NUL",
                "-w",
                "health=%{http_code}",
                f"http://127.0.0.1:{s.port}/health",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        print(f"Health check (curl): {result.stdout.strip()}")
        if result.stderr:
            print(f"  stderr: {result.stderr.strip()}")
        sys.stdout.flush()
    except Exception as e:
        print(f"Health check failed: {type(e).__name__}: {e}")
        sys.stdout.flush()


threading.Thread(target=test_health, daemon=True).start()


def stop_server():
    time.sleep(10)
    print("Timeout, shutting down...")
    server.should_exit = True


threading.Thread(target=stop_server, daemon=True).start()

try:
    asyncio.run(server.serve())
except KeyboardInterrupt:
    pass
print("Server stopped")
