from __future__ import annotations

import asyncio
import sys
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router as api_router
from app.core.config import get_settings
from app.core.container import ServiceContainer
from app.core.logging import configure_logging

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    container = ServiceContainer(settings)
    await container.initialize()
    app.state.container = container
    try:
        yield
    finally:
        await container.close()


app = FastAPI(title="I.R.I.S.", lifespan=lifespan)
app.include_router(api_router)


@app.get("/healthz", tags=["health"])
async def healthz():
    return {"status": "ok"}


# Serve static files from the React frontend build
frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")

if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="frontend-assets")
    
    @app.exception_handler(StarletteHTTPException)
    async def _spa_404_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404 and not request.url.path.startswith("/api/"):
            index_path = os.path.join(frontend_dist, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path)
        return await http_exception_handler(request, exc)

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # Allow serving explicit files in the root like favicon.ico if they exist
        path = os.path.join(frontend_dist, full_path)
        if os.path.isfile(path):
            return FileResponse(path)
        return FileResponse(os.path.join(frontend_dist, "index.html"))


class ProactorServer(uvicorn.Server):
    def run(self, sockets=None) -> None:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        asyncio.run(self.serve(sockets=sockets))


def main() -> None:
    config = uvicorn.Config(
        app="app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
    server = ProactorServer(config=config)
    server.run()


if __name__ == "__main__":
    main()
