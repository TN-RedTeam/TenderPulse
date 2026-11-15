"""Configuration centralisée, lue depuis les variables d'environnement."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

PLACEHOLDER_ADMIN_KEY = "change-me-admin-key"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "oui"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_api_key: str
    cors_origins: list[str]
    public_app_url: str

    boamp_base_url: str
    boamp_dataset: str
    boamp_min_interval_s: float
    boamp_max_retries: int
    boamp_timeout_s: float

    collect_enabled: bool
    collect_hour: int
    collect_minute: int
    collect_timezone: str
    collect_lookback_days: int
    collect_max_records: int

    llm_provider: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_s: float
    llm_max_input_chars: int
    llm_max_per_run: int
    llm_concurrency: int

    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_starttls: bool
    digest_auto_send: bool

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider in {"openai", "ollama"}

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)


def load_settings() -> Settings:
    provider = os.environ.get("LLM_PROVIDER", "none").strip().lower() or "none"
    if provider not in {"none", "openai", "ollama"}:
        raise ValueError(f"LLM_PROVIDER invalide : {provider!r} (attendu : none, openai, ollama)")
    default_llm_url = "http://localhost:11434" if provider == "ollama" else "https://api.openai.com/v1"
    default_llm_model = "llama3.1" if provider == "ollama" else "gpt-4o-mini"
    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:8080").split(",")]
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "postgresql://tenderpulse:tenderpulse@localhost:5432/tenderpulse"),
        admin_api_key=os.environ.get("ADMIN_API_KEY", PLACEHOLDER_ADMIN_KEY),
        cors_origins=[o for o in origins if o],
        public_app_url=os.environ.get("PUBLIC_APP_URL", "http://localhost:8080").rstrip("/"),
        boamp_base_url=os.environ.get("BOAMP_BASE_URL", "https://boamp-datadila.opendatasoft.com").rstrip("/"),
        boamp_dataset=os.environ.get("BOAMP_DATASET", "boamp"),
        boamp_min_interval_s=_env_float("BOAMP_MIN_INTERVAL_S", 0.4),
        boamp_max_retries=_env_int("BOAMP_MAX_RETRIES", 5),
        boamp_timeout_s=_env_float("BOAMP_TIMEOUT_S", 45.0),
        collect_enabled=_env_bool("COLLECT_ENABLED", True),
        collect_hour=_env_int("COLLECT_HOUR", 6),
        collect_minute=_env_int("COLLECT_MINUTE", 30),
        collect_timezone=os.environ.get("COLLECT_TIMEZONE", "Europe/Paris"),
        collect_lookback_days=_env_int("COLLECT_LOOKBACK_DAYS", 2),
        collect_max_records=_env_int("COLLECT_MAX_RECORDS", 5000),
        llm_provider=provider,
        llm_base_url=os.environ.get("LLM_BASE_URL", default_llm_url).rstrip("/"),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_model=os.environ.get("LLM_MODEL", default_llm_model),
        llm_timeout_s=_env_float("LLM_TIMEOUT_S", 90.0),
        llm_max_input_chars=_env_int("LLM_MAX_INPUT_CHARS", 12000),
        llm_max_per_run=_env_int("LLM_MAX_PER_RUN", 200),
        llm_concurrency=_env_int("LLM_CONCURRENCY", 3),
        smtp_host=os.environ.get("SMTP_HOST", ""),
        smtp_port=_env_int("SMTP_PORT", 587),
        smtp_user=os.environ.get("SMTP_USER", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        smtp_from=os.environ.get("SMTP_FROM", ""),
        smtp_starttls=_env_bool("SMTP_STARTTLS", True),
        digest_auto_send=_env_bool("DIGEST_AUTO_SEND", False),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
