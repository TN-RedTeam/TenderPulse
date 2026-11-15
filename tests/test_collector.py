"""Collecteur BOAMP : requêtes, pagination, limitation de débit, déduplication et parsing — sans réseau."""
from __future__ import annotations

from datetime import date, datetime, timezone

import httpx
import pytest

from backend.collector import BoampClient, BoampError, CollectFilters, build_where, parse_record
from tests import boamp_fixtures as fx
from tests.conftest import paginated_boamp_handler

pytestmark = pytest.mark.anyio

TODAY = date(2026, 11, 14)


async def _no_sleep(_: float) -> None:
    return None


def _client(handler, **kwargs) -> BoampClient:
    return BoampClient(transport=httpx.MockTransport(handler), min_interval_s=0, sleep=_no_sleep, **kwargs)


def test_build_where_combines_all_filters():
    filters = CollectFilters(cpv_codes=["45321000"], departments=["69", "1"], keywords=['isolation "ITE"'])
    where = build_where(filters, date(2026, 11, 12), date(2026, 11, 14))
    assert "dateparution >= date'2026-11-12'" in where
    assert "dateparution <= date'2026-11-14'" in where
    assert 'nature in ("APPEL_OFFRE")' in where
    assert 'code_departement in ("69", "01")' in where
    assert 'search("isolation \\"ITE\\"")' in where
    assert 'search(donnees, "45321000")' in where


def test_build_where_keeps_cpv_prefixes_client_side():
    where = build_where(CollectFilters(cpv_codes=["4532"], keywords=["isolation"]), TODAY, TODAY)
    assert "search(" not in where


async def test_pagination_fetches_every_page_and_deduplicates_by_idweb():
    # Le même avis réapparaît en fin de liste (cas réel : chevauchement de pages pendant une publication).
    records = fx.ALL_RECORDS + [fx.RENOVATION_ECOLE]
    handler = paginated_boamp_handler(records, page_size=3)
    async with _client(handler) as client:
        tenders = await client.collect(CollectFilters(), TODAY)
    assert [r.url.params["offset"] for r in handler.requests] == ["0", "3", "6"]
    assert len(tenders) == len(fx.ALL_RECORDS)
    assert len({t.idweb for t in tenders}) == len(tenders)


async def test_rate_limit_is_retried_after_the_delay_requested_by_the_api():
    waits: list[float] = []
    calls = {"count": 0}

    async def record_sleep(delay: float) -> None:
        waits.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, json={"error": "Too many requests"})
        return httpx.Response(200, json={"total_count": 1, "results": [fx.RENOVATION_ECOLE]})

    async with BoampClient(transport=httpx.MockTransport(handler), min_interval_s=0, sleep=record_sleep) as client:
        tenders = await client.collect(CollectFilters(), TODAY)
    assert calls["count"] == 2
    assert waits == [7.0]
    assert [t.idweb for t in tenders] == ["26-200001"]


async def test_network_errors_are_retried_then_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion réinitialisée")

    async with _client(handler, max_retries=2, backoff_base_s=0) as client:
        with pytest.raises(BoampError, match="3 tentatives"):
            await client.collect(CollectFilters(), TODAY)
        assert client.request_count == 3


async def test_client_error_is_not_retried():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error_code": "ODSQLError", "message": "clause where invalide"})

    async with _client(handler) as client:
        with pytest.raises(BoampError, match="HTTP 400"):
            await client.collect(CollectFilters(), TODAY)
        assert client.request_count == 1


async def test_window_is_split_when_api_offset_limit_would_be_exceeded():
    seen_windows: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        where = request.url.params["where"]
        seen_windows.append(where.split(" and nature")[0])
        single_day = where.count("2026-11-13") == 2 or where.count("2026-11-14") == 2
        if not single_day:
            return httpx.Response(200, json={"total_count": 25000, "results": [fx.RENOVATION_ECOLE]})
        record = fx.RENOVATION_ECOLE if "2026-11-14" in where else fx.MENUISERIES_ISO
        return httpx.Response(200, json={"total_count": 1, "results": [record]})

    filters = CollectFilters(date_from=date(2026, 11, 13), date_to=date(2026, 11, 14))
    async with _client(handler) as client:
        tenders = await client.collect(filters, TODAY)
    assert len(seen_windows) == 3  # fenêtre complète refusée, puis une requête par jour
    assert {t.idweb for t in tenders} == {"26-200001", "26-200007"}


async def test_filters_are_enforced_locally_even_if_api_returns_more():
    handler = paginated_boamp_handler(fx.ALL_RECORDS, page_size=100)
    async with _client(handler) as client:
        by_cpv_prefix = await client.collect(CollectFilters(cpv_codes=["4542"]), TODAY)
        by_keyword = await client.collect(CollectFilters(keywords=["toiture"], departments=["69"]), TODAY)
    assert {t.idweb for t in by_cpv_prefix} == {"26-200001", "26-200007"}
    assert {t.idweb for t in by_keyword} == {"26-200002"}


def test_parse_eforms_notice_extracts_lots_cpv_budget_and_deadline():
    tender = parse_record(fx.RENOVATION_ECOLE)
    assert tender.idweb == "26-200001"
    assert tender.acheteur == "Ville de Villeurbanne"
    assert tender.departments == ["69"]
    assert tender.cpv_codes == ["45321000", "45421000"]
    assert tender.budget_estime == 480000
    assert tender.date_limite == datetime(2026, 12, 15, 11, 0, tzinfo=timezone.utc)
    assert [(lot.numero, lot.intitule, lot.budget_estime) for lot in tender.lots] == [
        ("1", "Isolation thermique par l'extérieur", 310000.0), ("2", "Menuiseries extérieures", 170000.0),
    ]
    assert "Lot 2 : Menuiseries extérieures — Remplacement de 86 menuiseries" in tender.full_text
    assert "réalisés en site occupé" in tender.full_text
    assert "not-allowed" not in tender.full_text  # les codes techniques ne polluent pas le texte


def test_parse_fnsimple_notice_extracts_requirements_and_estimated_value():
    tender = parse_record(fx.TOITURE_CA_MINIMUM)
    assert tender.cpv_codes == ["45261000"]
    assert tender.budget_estime == 650000
    assert tender.date_limite == datetime(2026, 12, 18, 11, 0, tzinfo=timezone.utc)
    assert "chiffre d'affaires annuel minimum de 5 000 000 euros" in tender.full_text
    assert "https://marches.example.org" not in tender.full_text


def test_parse_fnsimple_lots_and_mapa_budget_from_free_text():
    alloti = parse_record(fx.MENUISERIES_ISO)
    assert [lot.intitule for lot in alloti.lots] == ["Menuiseries extérieures bois-aluminium", "Occultations et stores"]
    assert alloti.cpv_codes == ["45421000", "45421100", "45421140"]

    mapa = parse_record(fx.COMBLES_DELAI_COURT)
    assert mapa.budget_estime == 45000  # extrait de « Montant estimé des travaux : 45 000 euros HT »
    # Date sans fuseau dans la source : interprétée en heure de Paris (12h00 → 11h00 UTC en hiver).
    assert mapa.date_limite == datetime(2026, 11, 17, 11, 0, tzinfo=timezone.utc)


def test_parse_record_survives_missing_or_broken_payload():
    assert parse_record({"objet": "sans identifiant"}) is None
    tender = parse_record({"idweb": "26-1", "objet": "Avis minimal", "donnees": "{json cassé"})
    assert tender.idweb == "26-1" and tender.lots == [] and "Avis minimal" in tender.full_text


def test_content_hash_changes_only_when_notice_changes():
    original = parse_record(fx.RENOVATION_ECOLE)
    assert parse_record(dict(fx.RENOVATION_ECOLE)).content_hash == original.content_hash
    rectified = dict(fx.RENOVATION_ECOLE, datelimitereponse="2026-12-22T11:00:00+00:00")
    assert parse_record(rectified).content_hash != original.content_hash
