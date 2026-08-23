import asyncio
import threading
import time

import httpx
import uvicorn

from free_claude_code.config.loader import get_settings
from free_claude_code.runtime.bootstrap import build_asgi_app

s = get_settings()
print(f"port: {s.port}, host: {s.host}, model: {s.model}")
app = build_asgi_app(s)
config = uvicorn.Config(app, host=s.host, port=s.port, log_level="info")
server = uvicorn.Server(config)


def test_health():
    time.sleep(3)  # wait for server to start
    try:
        resp = httpx.get(f"http://127.0.0.1:{s.port}/health", timeout=5)
        print(f"Health check: {resp.status_code}")
    except Exception as e:
        print(f"Health check failed: {e}")


threading.Thread(target=test_health, daemon=True).start()

try:
    asyncio.run(server.serve())
except KeyboardInterrupt:
    pass
