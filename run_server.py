import uvicorn

from free_claude_code.config.loader import get_settings
from free_claude_code.runtime.bootstrap import build_asgi_app

s = get_settings()
print(f"port: {s.port}, host: {s.host}")
app = build_asgi_app(s)
config = uvicorn.Config(app, host=s.host, port=s.port, log_level="info")
server = uvicorn.Server(config)
import asyncio

asyncio.run(server.serve())
