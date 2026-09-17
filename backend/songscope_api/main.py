from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import init_db
from .routes import router

log = logging.getLogger("songscope.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    init_db()
    dispatcher = None
    if settings.embedded_worker:
        from .dispatcher import Dispatcher

        dispatcher = Dispatcher()
        dispatcher.start()
        log.info("embedded worker started (%d concurrent jobs)", settings.max_concurrent_jobs)
    app.state.dispatcher = dispatcher
    yield
    if dispatcher is not None:
        dispatcher.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SongScope API", version="1.0.0", lifespan=lifespan,
                  description="Technical music analysis: tempo, meter, key, chords, structure, pitch, loudness.")
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Range"],
        expose_headers=["Content-Disposition", "Content-Length", "Content-Range", "Accept-Ranges"],
    )

    @app.middleware("http")
    async def limits_and_headers(request: Request, call_next):
        # reject oversized uploads before the body is read
        if request.method == "POST" and request.url.path.endswith("/upload"):
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > settings.max_upload_bytes + 64 * 1024:
                return JSONResponse(status_code=413, content={"error": {
                    "code": "file_too_large", "message": f"File exceeds the {settings.max_upload_mb} MB limit."}})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content={"error": detail}, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        return JSONResponse(status_code=422, content={"error": {
            "code": "invalid_request", "message": f"Invalid request: {first.get('msg', 'validation failed')}"}})

    app.include_router(router)
    return app


app = create_app()
