"""Application FastAPI : API REST multi-tenant + planificateur de collecte quotidienne."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import __version__
from backend.api import repository as repo
from backend.api.db import apply_schema, create_pool
from backend.api.routes import router
from backend.api.services import TenderPulseService
from backend.config import PLACEHOLDER_ADMIN_KEY, Settings, get_settings

logger = logging.getLogger("tenderpulse")


def create_app(
    settings: Settings | None = None, *,
    boamp_transport: httpx.AsyncBaseTransport | None = None,
    llm_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
        if settings.admin_api_key == PLACEHOLDER_ADMIN_KEY:
            logger.warning("ADMIN_API_KEY a sa valeur par défaut : définissez une clé secrète avant toute mise en production.")
        pool = await create_pool(settings.database_url)
        await apply_schema(pool)
        await repo.fail_interrupted_runs(pool)
        service = TenderPulseService(pool, settings, boamp_transport=boamp_transport, llm_transport=llm_transport)
        app.state.service = service
        scheduler: asyncio.Task[None] | None = None
        if settings.collect_enabled:
            scheduler = asyncio.create_task(service.scheduler_loop(), name="tenderpulse-scheduler")
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.cancel()
                await asyncio.gather(scheduler, return_exceptions=True)
            await service.aclose()
            await pool.close()

    app = FastAPI(
        title="TenderPulse API", version=__version__, lifespan=lifespan,
        description="Veille des appels d'offres publics (BOAMP) et scoring d'adéquation personnalisé pour PME.",
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["X-API-Key", "Content-Type"], expose_headers=["X-Digest-Count"],
    )
    app.include_router(router)
    return app


app = create_app()
