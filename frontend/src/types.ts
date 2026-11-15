export type Decision = "go" | "a_verifier" | "no_go";
export type FollowUpStatus = "nouveau" | "a_etudier" | "go" | "ignore";
export type Severity = "bloquant" | "a_verifier";

export interface Tenant {
  id: string;
  name: string;
  contact_email: string | null;
  is_active: boolean;
  created_at: string;
}

export interface TenantCreated extends Tenant {
  api_key: string;
}

export interface Me {
  role: "admin" | "tenant";
  tenant: Tenant | null;
}

export interface ProfileInput {
  name: string;
  description: string;
  skills: string[];
  keywords_include: string[];
  keywords_exclude: string[];
  cpv_codes: string[];
  departments: string[];
  certifications: string[];
  annual_revenue_eur: number | null;
  min_contract_eur: number | null;
  max_contract_eur: number | null;
  min_response_days: number;
  eliminatory_criteria: string[];
  alert_threshold: number;
  digest_email: string | null;
  is_active: boolean;
}

export interface Profile extends ProfileInput {
  id: string;
  tenant_id: string;
  created_at: string;
  updated_at: string;
}

export interface CriterionScore {
  key: string;
  label: string;
  score: number;
  max_score: number;
  justification: string;
}

export interface EliminatoryFlag {
  type: string;
  label: string;
  detail: string;
  severity: Severity;
  source: string;
}

export interface Lot {
  numero: string;
  intitule: string;
  description: string;
  cpv_codes: string[];
  budget_estime: number | null;
}

export interface Opportunity {
  id: number;
  profile_id: string;
  idweb: string;
  objet: string;
  acheteur: string;
  procedure: string;
  type_marche: string[];
  departments: string[];
  cpv_codes: string[];
  url_avis: string;
  date_parution: string | null;
  date_limite: string | null;
  budget_estime: number | null;
  score: number;
  decision: Decision;
  criteria: CriterionScore[];
  eliminatory: EliminatoryFlag[];
  summary: string;
  analysis_source: string;
  model: string | null;
  status: FollowUpStatus;
  status_updated_at: string | null;
  scored_at: string;
  lots: Lot[];
}

export interface OpportunityCounts {
  total: number;
  go: number;
  a_verifier: number;
  no_go: number;
  nouveau: number;
}

export interface OpportunityList {
  items: Opportunity[];
  total: number;
  counts: OpportunityCounts;
}

export interface CollectionRun {
  id: number;
  trigger: string;
  status: "en_cours" | "termine" | "echec";
  tenders_fetched: number;
  tenders_new: number;
  tenders_updated: number;
  scores_written: number;
  llm_calls: number;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface OpportunityFilters {
  decision: Decision | null;
  status: FollowUpStatus | null;
  includeExpired: boolean;
}
