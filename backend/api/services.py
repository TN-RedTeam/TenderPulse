"""Orchestration : collecte BOAMP, scoring par profil, digests et planification quotidienne."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import asyncpg
import httpx

from backend.api import repository as repo
from backend.api.digest import digest_subject, render_digest
from backend.api.mailer import send_html_email
from backend.collector import BoampClient, CollectFilters, Tender
from backend.config import Settings
from backend.scoring import CompanyProfile, LLMClient, ScoringPipeline

logger = logging.getLogger("tenderpulse.services")


class CollectionBusyError(RuntimeError):
    """Une collecte est déjà en cours."""


class LLMBudget:
    """Plafonne le nombre d'appels LLM d'une exécution pour maîtriser les coûts."""

    def __init__(self, limit: int) -> None:
        self.remaining = max(limit, 0)
        self.used = 0

    def take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        self.used += 1
        return True


class TenderPulseService:
    def __init__(
        self, pool: asyncpg.Pool, settings: Settings, *,
        boamp_transport: httpx.AsyncBaseTransport | None = None,
        llm_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.pool = pool
        self.settings = settings
        self._boamp_transport = boamp_transport
        self._collect_lock = asyncio.Lock()
        self._background: set[asyncio.Task[Any]] = set()
        self._llm: LLMClient | None = None
        if settings.llm_enabled:
            self._llm = LLMClient(
                settings.llm_provider, settings.llm_base_url, settings.llm_model, settings.llm_api_key,
                timeout_s=settings.llm_timeout_s, max_input_chars=settings.llm_max_input_chars, transport=llm_transport,
            )
        self.pipeline = ScoringPipeline(self._llm)

    async def aclose(self) -> None:
        for task in list(self._background):
            task.cancel()
        if self._background:
            await asyncio.gather(*self._background, return_exceptions=True)
        if self._llm is not None:
            await self._llm.aclose()

    def spawn(self, coro: Any) -> None:
        """Lance une tâche de fond en conservant une référence jusqu'à sa fin."""
        task = asyncio.get_running_loop().create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    @property
    def collection_running(self) -> bool:
        return self._collect_lock.locked()

    # ------------------------------------------------------------------ scoring

    async def score_tenders(
        self, tenant_id: UUID, profile_id: UUID, profile: CompanyProfile,
        tenders: list[tuple[int, Tender]], budget: LLMBudget, now: datetime,
    ) -> list[int]:
        """Analyse les avis pour un profil et enregistre les scores. Retourne les ids d'avis retenus."""
        semaphore = asyncio.Semaphore(max(self.settings.llm_concurrency, 1))

        async def analyze_one(tender_id: int, tender: Tender) -> int | None:
            if not self.pipeline.prefilter(profile, tender, now).passed:
                return None
            async with semaphore:
                analysis = await self.pipeline.analyze(profile, tender, now, use_llm=self._llm is not None and budget.take())
            if analysis is None:
                return None
            await repo.upsert_score(self.pool, tenant_id, profile_id, tender_id, analysis)
            return tender_id

        results = await asyncio.gather(*(analyze_one(tid, tender) for tid, tender in tenders))
        return [tid for tid in results if tid is not None]

    async def rescore_profile(self, tenant_id: UUID, profile_id: UUID) -> dict[str, int]:
        """Ré-analyse tous les avis ouverts pour un profil (après création ou modification du profil)."""
        row = await repo.get_profile(self.pool, tenant_id, profile_id)
        if row is None:
            return {"tenders_examined": 0, "scores_written": 0}
        now = datetime.now(timezone.utc)
        # Repère pris AVANT la lecture des avis : tout score écrit ensuite par une collecte
        # concurrente est postérieur à ce repère et sera préservé par le nettoyage final.
        started_at = await repo.current_timestamp(self.pool)
        tenders = await repo.list_open_tenders(self.pool, now)
        kept = await self.score_tenders(tenant_id, profile_id, repo.profile_from_row(row), tenders,
                                        LLMBudget(self.settings.llm_max_per_run), now)
        await repo.delete_untouched_scores(self.pool, profile_id, kept, started_at)
        logger.info("Profil %s : %d avis examinés, %d scores", profile_id, len(tenders), len(kept))
        return {"tenders_examined": len(tenders), "scores_written": len(kept)}

    # ------------------------------------------------------------------ collecte

    async def default_filters(self) -> CollectFilters:
        """Périmètre de la collecte planifiée : union des départements des profils actifs."""
        profiles = await repo.list_active_profiles(self.pool)
        departments: set[str] = set()
        nationwide = not profiles
        for row in profiles:
            if row["departments"]:
                departments.update(row["departments"])
            else:
                nationwide = True
        return CollectFilters(
            departments=[] if nationwide else sorted(departments),
            max_records=self.settings.collect_max_records,
        )

    async def start_collection(self, filters: CollectFilters | None, trigger: str) -> dict[str, Any]:
        """Crée l'exécution et lance la collecte en tâche de fond. Lève CollectionBusyError si déjà en cours."""
        if self.collection_running:
            raise CollectionBusyError("Une collecte est déjà en cours")
        filters = filters or await self.default_filters()
        run = await repo.create_run(self.pool, trigger, filters.model_dump(mode="json"))
        self.spawn(self._run_collection(run["id"], filters))
        return run

    async def run_collection_now(self, filters: CollectFilters | None, trigger: str) -> dict[str, Any]:
        """Variante bloquante (planificateur, tests) : attend la fin de la collecte."""
        if self.collection_running:
            raise CollectionBusyError("Une collecte est déjà en cours")
        filters = filters or await self.default_filters()
        run = await repo.create_run(self.pool, trigger, filters.model_dump(mode="json"))
        return await self._run_collection(run["id"], filters)

    async def _run_collection(self, run_id: int, filters: CollectFilters) -> dict[str, Any]:
        stats = {"tenders_fetched": 0, "tenders_new": 0, "tenders_updated": 0, "scores_written": 0, "llm_calls": 0}
        async with self._collect_lock:
            try:
                today = datetime.now(ZoneInfo(self.settings.collect_timezone)).date()
                async with BoampClient(
                    self.settings.boamp_base_url, self.settings.boamp_dataset,
                    min_interval_s=self.settings.boamp_min_interval_s, max_retries=self.settings.boamp_max_retries,
                    timeout_s=self.settings.boamp_timeout_s, transport=self._boamp_transport,
                ) as client:
                    tenders = await client.collect(filters, today, self.settings.collect_lookback_days)
                stats["tenders_fetched"] = len(tenders)

                changed: list[tuple[int, Tender]] = []
                for tender in tenders:
                    tender_id, state = await repo.upsert_tender(self.pool, tender)
                    if state == "nouveau":
                        stats["tenders_new"] += 1
                    elif state == "modifie":
                        stats["tenders_updated"] += 1
                    if state != "inchange":
                        changed.append((tender_id, tender))

                now = datetime.now(timezone.utc)
                budget = LLMBudget(self.settings.llm_max_per_run)
                for row in await repo.list_active_profiles(self.pool):
                    kept = await self.score_tenders(row["tenant_id"], row["id"], repo.profile_from_row(row), changed, budget, now)
                    stats["scores_written"] += len(kept)
                stats["llm_calls"] = budget.used
                logger.info("Collecte %d terminée : %s", run_id, stats)
                return await repo.finish_run(self.pool, run_id, status="termine", stats=stats)
            except asyncio.CancelledError:
                await repo.finish_run(self.pool, run_id, status="echec", stats=stats, error="Collecte annulée")
                raise
            except Exception as exc:
                logger.exception("Collecte %d en échec", run_id)
                return await repo.finish_run(self.pool, run_id, status="echec", stats=stats, error=str(exc)[:1000])

    # ------------------------------------------------------------------ digest

    async def build_digest(self, tenant_id: UUID, profile_id: UUID, since_hours: int | None) -> tuple[str, str, int, str | None] | None:
        """Retourne (html, sujet, nombre d'opportunités, destinataire) ou None si le profil est introuvable."""
        profile = await repo.get_profile(self.pool, tenant_id, profile_id)
        tenant = await repo.get_tenant(self.pool, tenant_id)
        if profile is None or tenant is None:
            return None
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=since_hours) if since_hours else None
        candidates = await repo.list_digest_candidates(self.pool, tenant_id, profile_id, since)
        html, count = render_digest(
            tenant_name=tenant["name"], profile_name=profile["name"], threshold=profile["alert_threshold"],
            candidates=candidates, now=now, app_url=self.settings.public_app_url, since_hours=since_hours,
        )
        recipient = profile["digest_email"] or tenant["contact_email"]
        return html, digest_subject(profile["name"], count, now), count, recipient

    async def send_digest(self, tenant_id: UUID, profile_id: UUID, since_hours: int | None) -> dict[str, Any] | None:
        built = await self.build_digest(tenant_id, profile_id, since_hours)
        if built is None:
            return None
        html, subject, count, recipient = built
        if not self.settings.smtp_enabled:
            return {"sent": False, "recipient": recipient, "opportunities": count,
                    "detail": "SMTP non configuré : définissez SMTP_HOST et SMTP_FROM pour activer l'envoi."}
        if not recipient:
            return {"sent": False, "recipient": None, "opportunities": count,
                    "detail": "Aucune adresse de destination : renseignez l'e-mail du digest dans le profil."}
        if count == 0:
            return {"sent": False, "recipient": recipient, "opportunities": 0,
                    "detail": "Aucune opportunité au-dessus du seuil : aucun e-mail envoyé."}
        try:
            await send_html_email(self.settings, recipient, subject, html)
        except Exception as exc:
            logger.exception("Envoi du digest impossible pour le profil %s", profile_id)
            return {"sent": False, "recipient": recipient, "opportunities": count, "detail": f"Échec de l'envoi : {exc}"}
        return {"sent": True, "recipient": recipient, "opportunities": count, "detail": "Digest envoyé."}

    async def send_all_digests(self) -> None:
        for row in await repo.list_active_profiles(self.pool):
            result = await self.send_digest(row["tenant_id"], row["id"], 24)
            if result:
                logger.info("Digest du profil %s : %s", row["name"], result["detail"])

    # ------------------------------------------------------------------ planification

    def next_run_at(self, now: datetime) -> datetime:
        """Prochaine échéance de la collecte quotidienne, dans le fuseau configuré."""
        local = now.astimezone(ZoneInfo(self.settings.collect_timezone))
        target = local.replace(hour=self.settings.collect_hour, minute=self.settings.collect_minute, second=0, microsecond=0)
        if target <= local:
            target += timedelta(days=1)
        return target

    async def scheduler_loop(self) -> None:
        """Boucle du planificateur : une collecte par jour, puis l'envoi des digests si activé."""
        while True:
            now = datetime.now(timezone.utc)
            target = self.next_run_at(now)
            logger.info("Prochaine collecte planifiée : %s", target.isoformat())
            await asyncio.sleep(max((target - now.astimezone(target.tzinfo)).total_seconds(), 1.0))
            try:
                run = await self.run_collection_now(None, "planifie")
                if run["status"] == "termine" and self.settings.digest_auto_send and self.settings.smtp_enabled:
                    await self.send_all_digests()
            except CollectionBusyError:
                logger.warning("Collecte planifiée ignorée : une collecte est déjà en cours")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Erreur inattendue dans le planificateur")


def filters_from_request(payload: dict[str, Any], default_max: int) -> CollectFilters:
    """Construit les filtres d'une collecte manuelle à partir du corps de requête."""
    data = {k: v for k, v in payload.items() if v not in (None, [], "")}
    data.setdefault("max_records", default_max)
    return CollectFilters(**data)


def has_custom_filters(payload: dict[str, Any]) -> bool:
    return any(payload.get(key) for key in ("cpv_codes", "departments", "keywords", "date_from", "date_to"))


__all__ = ["CollectionBusyError", "LLMBudget", "TenderPulseService", "filters_from_request", "has_custom_filters"]
