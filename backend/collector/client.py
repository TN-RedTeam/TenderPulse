"""Client asynchrone de l'API OpenData du BOAMP (Opendatasoft Explore v2.1)."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import date, timedelta
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

from backend.collector.models import CollectFilters, Tender
from backend.collector.parser import parse_record

logger = logging.getLogger("tenderpulse.collector")

PAGE_SIZE = 100          # maximum accepté par l'API (limit <= 100)
MAX_WINDOW = 10000       # l'API refuse offset + limit > 10 000
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
SELECT_FIELDS = (
    "idweb,objet,nomacheteur,famille,nature,type_procedure,procedure_libelle,type_marche,"
    "code_departement,descripteur_libelle,dateparution,datelimitereponse,criteres,donnees,url_avis"
)


class BoampError(RuntimeError):
    """Erreur définitive lors d'un appel à l'API BOAMP."""


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_where(filters: CollectFilters, date_from: date, date_to: date) -> str:
    """Construit la clause ODSQL `where` correspondant aux filtres.

    Les mots-clés et les codes CPV complets (8 chiffres) sont combinés en OU et poussés côté
    serveur via `search()`. Les préfixes CPV ne sont pas exprimables côté API : dans ce cas le
    filtrage texte est fait localement par `CollectFilters.matches`.
    """
    clauses = [
        f"dateparution >= date'{date_from.isoformat()}'",
        f"dateparution <= date'{date_to.isoformat()}'",
    ]
    if filters.natures:
        clauses.append("nature in (" + ", ".join(_quote(n) for n in filters.natures) + ")")
    if filters.departments:
        clauses.append("code_departement in (" + ", ".join(_quote(d) for d in filters.departments) + ")")
    cpv_digits = ["".join(ch for ch in code if ch.isdigit()) for code in filters.cpv_codes]
    all_cpv_complete = all(len(code) == 8 for code in cpv_digits)
    if (filters.keywords or cpv_digits) and all_cpv_complete:
        terms = [f"search({_quote(kw)})" for kw in filters.keywords]
        terms += [f"search(donnees, {_quote(code)})" for code in cpv_digits]
        clauses.append("(" + " or ".join(terms) + ")")
    return " and ".join(clauses)


class BoampClient:
    """Client HTTP avec limitation de débit, reprises exponentielles, pagination et déduplication."""

    def __init__(
        self,
        base_url: str = "https://boamp-datadila.opendatasoft.com",
        dataset: str = "boamp",
        *,
        min_interval_s: float = 0.4,
        max_retries: int = 5,
        timeout_s: float = 45.0,
        backoff_base_s: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/api/explore/v2.1/catalog/datasets/{dataset}/records"
        self._min_interval_s = min_interval_s
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._sleep = sleep
        self._last_request_at = 0.0
        self._throttle_lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s, connect=15.0),
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": "TenderPulse/1.0"},
        )
        self.request_count = 0

    async def __aenter__(self) -> "BoampClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _throttle(self) -> None:
        async with self._throttle_lock:
            wait = self._last_request_at + self._min_interval_s - time.monotonic()
            if wait > 0:
                await self._sleep(wait)
            self._last_request_at = time.monotonic()

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                return min(float(retry_after), 120.0)
            reset = response.headers.get("X-RateLimit-Reset", "")
            if reset.isdigit() and float(reset) > time.time():
                return min(float(reset) - time.time(), 120.0)
        return min(self._backoff_base_s * (2 ** attempt), 60.0) + random.uniform(0, 0.25)

    async def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        last_error = "aucune tentative"
        for attempt in range(self._max_retries + 1):
            await self._throttle()
            self.request_count += 1
            response: httpx.Response | None = None
            try:
                response = await self._client.get(self._url, params=params)
            except httpx.TransportError as exc:
                last_error = f"erreur réseau : {exc!r}"
            else:
                if response.status_code == 200:
                    try:
                        payload = response.json()
                    except ValueError:
                        last_error = "réponse JSON invalide"
                    else:
                        if isinstance(payload, dict):
                            return payload
                        last_error = "réponse JSON inattendue"
                elif response.status_code in RETRYABLE_STATUS:
                    last_error = f"HTTP {response.status_code}"
                else:
                    raise BoampError(f"API BOAMP : HTTP {response.status_code} — {response.text[:300]}")
            if attempt < self._max_retries:
                delay = self._retry_delay(attempt, response)
                logger.warning("BOAMP : %s, nouvelle tentative %d/%d dans %.1fs", last_error, attempt + 1, self._max_retries, delay)
                await self._sleep(delay)
        raise BoampError(f"API BOAMP injoignable après {self._max_retries + 1} tentatives ({last_error})")

    async def _iter_window(self, filters: CollectFilters, date_from: date, date_to: date) -> AsyncIterator[dict[str, Any]]:
        """Pagine une fenêtre de dates ; la découpe en deux si elle dépasse la limite d'offset de l'API."""
        where = build_where(filters, date_from, date_to)
        offset = 0
        while True:
            payload = await self._get(
                {
                    "select": SELECT_FIELDS,
                    "where": where,
                    "order_by": "dateparution desc, idweb desc",
                    "limit": PAGE_SIZE,
                    "offset": offset,
                }
            )
            total = int(payload.get("total_count") or 0)
            if offset == 0 and total > MAX_WINDOW and date_from < date_to:
                middle = date_from + timedelta(days=(date_to - date_from).days // 2)
                logger.info("BOAMP : %d avis sur %s → %s, découpage de la fenêtre", total, date_from, date_to)
                async for record in self._iter_window(filters, middle + timedelta(days=1), date_to):
                    yield record
                async for record in self._iter_window(filters, date_from, middle):
                    yield record
                return
            results = payload.get("results") or []
            for record in results:
                if isinstance(record, dict):
                    yield record
            offset += len(results)
            if not results or offset >= total:
                return
            if offset + PAGE_SIZE > MAX_WINDOW:
                logger.warning("BOAMP : fenêtre %s → %s tronquée à %d avis (limite d'offset de l'API)", date_from, date_to, MAX_WINDOW)
                return

    async def iter_records(self, filters: CollectFilters, today: date | None = None, lookback_days: int = 2) -> AsyncIterator[dict[str, Any]]:
        date_from, date_to = filters.resolved_dates(today or date.today(), lookback_days)
        async for record in self._iter_window(filters, date_from, date_to):
            yield record

    async def collect(self, filters: CollectFilters, today: date | None = None, lookback_days: int = 2) -> list[Tender]:
        """Collecte, parse, déduplique (par `idweb`) et applique les filtres localement."""
        tenders: dict[str, Tender] = {}
        async for record in self.iter_records(filters, today, lookback_days):
            try:
                tender = parse_record(record)
            except Exception:  # un avis mal formé ne doit jamais interrompre la collecte
                logger.exception("BOAMP : avis %r illisible, ignoré", record.get("idweb"))
                continue
            if tender is None or tender.idweb in tenders:
                continue
            if not filters.matches(tender):
                continue
            tenders[tender.idweb] = tender
            if len(tenders) >= filters.max_records:
                logger.warning("BOAMP : plafond de %d avis atteint, collecte interrompue", filters.max_records)
                break
        return list(tenders.values())
