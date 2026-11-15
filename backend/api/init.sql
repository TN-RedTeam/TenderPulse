-- TenderPulse — schéma PostgreSQL 16 (idempotent : peut être rejoué sans risque).

CREATE TABLE IF NOT EXISTS tenants (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL UNIQUE CHECK (length(btrim(name)) > 0),
    contact_email TEXT,
    api_key_hash  TEXT NOT NULL UNIQUE,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS company_profiles (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                 TEXT NOT NULL CHECK (length(btrim(name)) > 0),
    description          TEXT NOT NULL DEFAULT '',
    skills               TEXT[] NOT NULL DEFAULT '{}',
    keywords_include     TEXT[] NOT NULL DEFAULT '{}',
    keywords_exclude     TEXT[] NOT NULL DEFAULT '{}',
    cpv_codes            TEXT[] NOT NULL DEFAULT '{}',
    departments          TEXT[] NOT NULL DEFAULT '{}',
    certifications       TEXT[] NOT NULL DEFAULT '{}',
    annual_revenue_eur   NUMERIC(16, 2) CHECK (annual_revenue_eur IS NULL OR annual_revenue_eur >= 0),
    min_contract_eur     NUMERIC(16, 2) CHECK (min_contract_eur IS NULL OR min_contract_eur >= 0),
    max_contract_eur     NUMERIC(16, 2) CHECK (max_contract_eur IS NULL OR max_contract_eur >= 0),
    min_response_days    INTEGER NOT NULL DEFAULT 7 CHECK (min_response_days BETWEEN 0 AND 180),
    eliminatory_criteria TEXT[] NOT NULL DEFAULT '{}',
    alert_threshold      INTEGER NOT NULL DEFAULT 60 CHECK (alert_threshold BETWEEN 0 AND 100),
    digest_email         TEXT,
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
CREATE INDEX IF NOT EXISTS idx_company_profiles_tenant ON company_profiles (tenant_id);

CREATE TABLE IF NOT EXISTS tenders (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    idweb         TEXT NOT NULL UNIQUE,
    objet         TEXT NOT NULL DEFAULT '',
    acheteur      TEXT NOT NULL DEFAULT '',
    famille       TEXT NOT NULL DEFAULT '',
    nature        TEXT NOT NULL DEFAULT '',
    procedure     TEXT NOT NULL DEFAULT '',
    type_marche   TEXT[] NOT NULL DEFAULT '{}',
    departments   TEXT[] NOT NULL DEFAULT '{}',
    cpv_codes     TEXT[] NOT NULL DEFAULT '{}',
    descripteurs  TEXT[] NOT NULL DEFAULT '{}',
    date_parution DATE,
    date_limite   TIMESTAMPTZ,
    budget_estime NUMERIC(18, 2),
    url_avis      TEXT NOT NULL DEFAULT '',
    full_text     TEXT NOT NULL DEFAULT '',
    lots          JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_hash  TEXT NOT NULL DEFAULT '',
    collected_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tenders_date_limite ON tenders (date_limite);
CREATE INDEX IF NOT EXISTS idx_tenders_date_parution ON tenders (date_parution DESC);
CREATE INDEX IF NOT EXISTS idx_tenders_departments ON tenders USING GIN (departments);

CREATE TABLE IF NOT EXISTS tender_scores (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    profile_id        UUID NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    tender_id         BIGINT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
    score             INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    decision          TEXT NOT NULL CHECK (decision IN ('go', 'a_verifier', 'no_go')),
    criteria          JSONB NOT NULL DEFAULT '[]'::jsonb,
    eliminatory       JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary           TEXT NOT NULL DEFAULT '',
    date_limite       TIMESTAMPTZ,
    budget_estime     NUMERIC(18, 2),
    analysis_source   TEXT NOT NULL DEFAULT 'heuristique' CHECK (analysis_source IN ('heuristique', 'llm')),
    model             TEXT,
    status            TEXT NOT NULL DEFAULT 'nouveau' CHECK (status IN ('nouveau', 'a_etudier', 'go', 'ignore')),
    status_updated_at TIMESTAMPTZ,
    first_scored_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    scored_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (profile_id, tender_id)
);
CREATE INDEX IF NOT EXISTS idx_tender_scores_ranking ON tender_scores (profile_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_tender_scores_tenant ON tender_scores (tenant_id);
CREATE INDEX IF NOT EXISTS idx_tender_scores_tender ON tender_scores (tender_id);

CREATE TABLE IF NOT EXISTS collection_runs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trigger         TEXT NOT NULL CHECK (trigger IN ('planifie', 'manuel')),
    status          TEXT NOT NULL DEFAULT 'en_cours' CHECK (status IN ('en_cours', 'termine', 'echec')),
    filters         JSONB NOT NULL DEFAULT '{}'::jsonb,
    tenders_fetched INTEGER NOT NULL DEFAULT 0,
    tenders_new     INTEGER NOT NULL DEFAULT 0,
    tenders_updated INTEGER NOT NULL DEFAULT 0,
    scores_written  INTEGER NOT NULL DEFAULT 0,
    llm_calls       INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_collection_runs_started ON collection_runs (started_at DESC);
