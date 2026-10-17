from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.api.payments import router as payments_router
from app.config import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Payment Processor API",
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_openapi else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_openapi else None,
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(payments_router)
    return app


app = create_app()
