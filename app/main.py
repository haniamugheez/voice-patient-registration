"""FastAPI application entry point.

Wires together: logging -> database -> routers -> error handling.
Run locally with:  uvicorn app.main:app --reload
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import init_db
from app.routers import dashboard, patients, vapi

# ---------------------------------------------------------------------------
# Logging — everything to stdout so hosting platforms capture it.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.SEED_ON_STARTUP:
        from app.seed import seed

        seed()
    logger.info("%s started (env=%s)", settings.APP_NAME, settings.ENV)
    yield
    logger.info("shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description=(
        "Voice-driven patient registration. A Vapi voice agent collects U.S. "
        "patient demographics over the phone and persists them through this API."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(patients.router)
app.include_router(vapi.router)
app.include_router(dashboard.router)


# ---------------------------------------------------------------------------
# Error handling — every error comes back in the { data, error } envelope.
# ---------------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    details = [
        {
            "field": ".".join(str(p) for p in err["loc"] if p not in ("body", "query")),
            "message": err["msg"].replace("Value error, ", ""),
        }
        for err in exc.errors()
    ]
    logger.warning("validation_error path=%s details=%s", request.url.path, details)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "data": None,
            "error": {
                "type": "validation_error",
                "message": "One or more fields failed validation",
                "details": details,
            },
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        error = detail
    else:
        error = {"type": "error", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content={"data": None, "error": error})


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.exception("unhandled_error path=%s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "data": None,
            "error": {"type": "internal_error", "message": "Something went wrong"},
        },
    )


# ---------------------------------------------------------------------------
# Meta endpoints
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/dashboard")


@app.get("/health", tags=["meta"])
def health():
    return {"data": {"status": "ok", "service": settings.APP_NAME}, "error": None}
