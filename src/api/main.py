"""FastAPI app factory; mounts routers and exposes /healthz."""

from __future__ import annotations

from fastapi import FastAPI

from src.api.routers import customers, data_quality, error_events, metrics, orders
from src.common.logging import configure


def create_app() -> FastAPI:
    configure()
    app = FastAPI(title="Ecommerce Data Pipeline API", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(customers.router)
    app.include_router(orders.router)
    app.include_router(metrics.router)
    app.include_router(data_quality.router)
    app.include_router(error_events.router)
    return app


app = create_app()
