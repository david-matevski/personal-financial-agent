"""FastAPI application factory."""

from fastapi import FastAPI

from finagent.api.routes.health import router as health_router
from finagent.core.config import get_settings
from finagent.core.logging import configure_logging


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    configure_logging(get_settings().log_level)
    app = FastAPI(title="finagent")
    app.include_router(health_router)
    return app


app = create_app()
