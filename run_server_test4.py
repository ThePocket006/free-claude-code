import asyncio
import sys
import threading
import time

import httpx
import uvicorn

from free_claude_code.config.loader import get_settings
from free_claude_code.runtime.bootstrap import build_asgi_app

s = get_settings()
print(f"port: {s.port}, host: {s.host}, model: {s.model}")
app = build_asgi_app(s)
config = uvicorn.Config(app, host=s.host, port=s.port, log_level="debug")
server = uvicorn.Server(config)


def test_health():
    time.sleep(2)
    try:
        resp = httpx.get(f"http://127.0.0.1:{s.port}/health", timeout=5)
        print(f"Health check: {resp.status_code}, body: {resp.text}")
        sys.stdout.flush()
    except Exception as e:
        print(f"Health check failed: {type(e).__name__}: {e}")
        sys.stdout.flush()


threading.Thread(target=test_health, daemon=True).start()


def stop_server():
    time.sleep(10)
    print("Timeout, shutting down...")
    server.should_exit = True


th.Thread(target=stop_server, daemon=True).start()

try:
    asyncio.run(server.serve())
except KeyboardInterrupt:
    pass
print("Server stopped")
