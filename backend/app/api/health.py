"""GET /health (is the process alive) and GET /ready (can it accept work)."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    body, code = await request.app.state.container.readiness()
    return JSONResponse(body, status_code=code)
