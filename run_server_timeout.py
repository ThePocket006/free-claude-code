import asyncio

import uvicorn

from free_claude_code.config.loader import get_settings
from free_claude_code.runtime.bootstrap import build_asgi_app

s = get_settings()
print(f"port: {s.port}, host: {s.host}, model: {s.model}")
app = build_asgi_app(s)
config = uvicorn.Config(app, host=s.host, port=s.port, log_level="info")
server = uvicorn.Server(config)


async def run_with_timeout():
    # Run server for 10 seconds then gracefully shutdown
    serve_task = asyncio.create_task(server.serve())
    await asyncio.sleep(10)
    print("Shutting down...")
    server.should_exit = True
    await serve_task


asyncio.run(run_with_timeout())
