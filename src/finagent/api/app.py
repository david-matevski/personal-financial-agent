"""FastAPI application factory."""

import importlib.resources
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.responses import Response
from starlette.types import Scope

from finagent import __version__
from finagent.api.errors import register_exception_handlers
from finagent.api.routes.accounts import router as accounts_router
from finagent.api.routes.categories import router as categories_router
from finagent.api.routes.health import router as health_router
from finagent.api.routes.statements import router as statements_router
from finagent.api.routes.transactions import router as transactions_router
from finagent.api.routes.uploads import router as uploads_router
from finagent.core.config import build_categorizer, build_extractor, get_settings
from finagent.core.logging import configure_logging
from finagent.core.static_assets import compute_build_id, rewrite_index_html
from finagent.db.session import session_scope
from finagent.worker import UploadWorker, requeue_stale

logger = logging.getLogger(__name__)


class ApiInfo(BaseModel):
    """Response body for GET /api-info."""

    name: str
    version: str


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    stop_event = threading.Event()
    thread: threading.Thread | None = None

    if settings.run_worker:
        requeue_stale(session_scope)
        worker = UploadWorker(
            session_scope,
            lambda: build_extractor(settings),
            lambda: build_categorizer(settings),
            model=settings.extraction_model,
        )
        thread = threading.Thread(target=worker.run, args=(stop_event,), daemon=True)
        thread.start()

    yield

    if thread is not None:
        stop_event.set()
        thread.join(timeout=10)


class _ImmutableStaticFiles(StaticFiles):
    """Static files served under a content-versioned URL prefix.

    Because the URL (``/static/{build_id}/...``) changes whenever any file's
    contents change, these responses can be cached forever: a stale cached
    copy is simply never requested again once the build id moves on.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    configure_logging(get_settings().log_level)
    app = FastAPI(title="finagent", lifespan=_lifespan)
    register_exception_handlers(app)
    app.include_router(health_router)

    @app.get("/api-info", response_model=ApiInfo, tags=["health"])
    def get_api_info() -> ApiInfo:
        """Unauthenticated identity check so the UI can confirm the server it's talking to."""
        return ApiInfo(name="finagent", version=__version__)

    app.include_router(statements_router)
    app.include_router(uploads_router)
    app.include_router(accounts_router)
    app.include_router(transactions_router)
    app.include_router(categories_router)

    # Registered last so API routes above take precedence, and only when the
    # directory exists: the browser UI (built separately, under
    # web/static/) may not be present yet, e.g. during tests or before the
    # frontend has shipped.
    static_dir = importlib.resources.files("finagent") / "web" / "static"
    if static_dir.is_dir():
        static_path = Path(str(static_dir))
        build_id = compute_build_id(static_path)
        index_html = rewrite_index_html(
            (static_path / "index.html").read_text(encoding="utf-8"), build_id
        )

        @app.get("/", include_in_schema=False)
        @app.get("/index.html", include_in_schema=False)
        def get_index() -> Response:
            """Serve the versioned index.html, never cached.

            This is the one URL every deploy keeps stable, so it must always
            be revalidated: it's the only thing that can tell a client which
            build id's assets to fetch.
            """
            return HTMLResponse(index_html, headers={"Cache-Control": "no-store"})

        app.mount(
            f"/static/{build_id}",
            _ImmutableStaticFiles(directory=str(static_path)),
            name="static-assets",
        )

    return app


app = create_app()
