from __future__ import annotations

from typing import Any, Callable

import httpx
import pytest

from backend.collector import Tender, parse_record
from backend.scoring import CompanyProfile
from tests import boamp_fixtures as fx


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def profile() -> CompanyProfile:
    return CompanyProfile(**fx.PROFILE_DATA)


@pytest.fixture
def tenders() -> dict[str, Tender]:
    """Avis simulés, parsés, indexés par idweb."""
    return {record["idweb"]: parse_record(record) for record in fx.ALL_RECORDS}


def paginated_boamp_handler(records: list[dict[str, Any]], page_size: int = 3) -> Callable[[httpx.Request], httpx.Response]:
    """Simule l'API BOAMP : pagination par `offset`, `total_count` et journal des requêtes reçues."""
    def handler(request: httpx.Request) -> httpx.Response:
        handler.requests.append(request)  # type: ignore[attr-defined]
        offset = int(request.url.params.get("offset", "0"))
        return httpx.Response(200, json={"total_count": len(records), "results": records[offset: offset + page_size]})

    handler.requests = []  # type: ignore[attr-defined]
    return handler
