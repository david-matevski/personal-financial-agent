"""FastAPI application factory."""

from fastapi import FastAPI

from finagent.api.errors import register_exception_handlers
from finagent.api.routes.accounts import router as accounts_router
from finagent.api.routes.categories import router as categories_router
from finagent.api.routes.health import router as health_router
from finagent.api.routes.statements import router as statements_router
from finagent.api.routes.transactions import router as transactions_router
from finagent.core.config import get_settings
from finagent.core.logging import configure_logging


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    configure_logging(get_settings().log_level)
    app = FastAPI(title="finagent")
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(statements_router)
    app.include_router(accounts_router)
    app.include_router(transactions_router)
    app.include_router(categories_router)
    return app


app = create_app()
