"""Health check endpoint."""

from fastapi import APIRouter
from pydantic import BaseModel

from finagent import __version__

router = APIRouter()


class HealthResponse(BaseModel):
    """Response body for GET /health."""

    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Report service liveness and version."""
    return HealthResponse(status="ok", version=__version__)
