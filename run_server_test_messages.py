import asyncio
import json
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


def test_messages():
    time.sleep(3)
    body = json.dumps(
        {
            "model": "opencode_zen/big-pickle",
            "max_tokens": 50,
            "messages": [{"role": "user", "content": "Say OK"}],
        }
    )
    try:
        result = subprocess.run(
            [
                "curl.exe",
                "-s",
                "-X",
                "POST",
                f"http://127.0.0.1:{s.port}/v1/messages",
                "-H",
                "Content-Type: application/json",
                "-H",
                "x-api-key: freecc",
                "-H",
                "anthropic-version: 2023-06-01",
                "-d",
                body,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        print(f"Messages response: {result.stdout[:500]}")
        if result.stderr:
            print(f"  stderr: {result.stderr.strip()}")
        sys.stdout.flush()
    except Exception as e:
        print(f"Messages test failed: {type(e).__name__}: {e}")
        sys.stdout.flush()


threading.Thread(target=test_messages, daemon=True).start()


def stop_server():
    time.sleep(15)
    print("Timeout, shutting down...")
    server.should_exit = True


threading.Thread(target=stop_server, daemon=True).start()

try:
    asyncio.run(server.serve())
except KeyboardInterrupt:
    pass
print("Server stopped")
