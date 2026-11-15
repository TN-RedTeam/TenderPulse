import { useEffect, useState } from "react";
import type { Profile, ProfileInput } from "../types";
import { TagInput } from "./TagInput";
import { Alert, Spinner } from "./ui";

interface ProfileFormProps {
  profile: Profile | null;
  saving: boolean;
  error: string | null;
  onSave: (input: ProfileInput) => void;
  onDelete?: () => void;
  onCancel?: () => void;
}

interface FormState {
  name: string;
  description: string;
  skills: string[];
  keywordsInclude: string[];
  keywordsExclude: string[];
  cpvCodes: string[];
  departments: string[];
  certifications: string[];
  annualRevenue: string;
  minContract: string;
  maxContract: string;
  minResponseDays: number;
  eliminatoryCriteria: string[];
  alertThreshold: number;
  digestEmail: string;
  isActive: boolean;
}

function toState(profile: Profile | null): FormState {
  const amount = (value: number | null | undefined) => (value === null || value === undefined ? "" : String(value));
  return {
    name: profile?.name ?? "",
    description: profile?.description ?? "",
    skills: profile?.skills ?? [],
    keywordsInclude: profile?.keywords_include ?? [],
    keywordsExclude: profile?.keywords_exclude ?? [],
    cpvCodes: profile?.cpv_codes ?? [],
    departments: profile?.departments ?? [],
    certifications: profile?.certifications ?? [],
    annualRevenue: amount(profile?.annual_revenue_eur),
    minContract: amount(profile?.min_contract_eur),
    maxContract: amount(profile?.max_contract_eur),
    minResponseDays: profile?.min_response_days ?? 7,
    eliminatoryCriteria: profile?.eliminatory_criteria ?? [],
    alertThreshold: profile?.alert_threshold ?? 60,
    digestEmail: profile?.digest_email ?? "",
    isActive: profile?.is_active ?? true,
  };
}

function parseAmount(raw: string): number | null {
  const cleaned = raw.replace(/[\s €]/g, "").replace(",", ".");
  if (cleaned === "") {
    return null;
  }
  const value = Number(cleaned);
  return Number.isFinite(value) && value >= 0 ? value : Number.NaN;
}

/** Formulaire de création / édition du profil d'une PME. */
export function ProfileForm({ profile, saving, error, onSave, onDelete, onCancel }: ProfileFormProps) {
  const [state, setState] = useState<FormState>(() => toState(profile));
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    setState(toState(profile));
    setLocalError(null);
  }, [profile]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setState((previous) => ({ ...previous, [key]: value }));
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const annualRevenue = parseAmount(state.annualRevenue);
    const minContract = parseAmount(state.minContract);
    const maxContract = parseAmount(state.maxContract);
    if ([annualRevenue, minContract, maxContract].some((value) => Number.isNaN(value))) {
      setLocalError("Les montants doivent être des nombres positifs (en euros).");
      return;
    }
    if (minContract !== null && maxContract !== null && minContract > maxContract) {
      setLocalError("Le montant de marché minimum ne peut pas dépasser le montant maximum.");
      return;
    }
    setLocalError(null);
    onSave({
      name: state.name.trim(),
      description: state.description.trim(),
      skills: state.skills,
      keywords_include: state.keywordsInclude,
      keywords_exclude: state.keywordsExclude,
      cpv_codes: state.cpvCodes,
      departments: state.departments,
      certifications: state.certifications,
      annual_revenue_eur: annualRevenue,
      min_contract_eur: minContract,
      max_contract_eur: maxContract,
      min_response_days: state.minResponseDays,
      eliminatory_criteria: state.eliminatoryCriteria,
      alert_threshold: state.alertThreshold,
      digest_email: state.digestEmail.trim() || null,
      is_active: state.isActive,
    });
  };

  const message = localError ?? error;

  return (
    <form className="space-y-6" onSubmit={submit}>
      <section className="card p-6">
        <h3 className="text-base font-semibold text-slate-900">Identité de l'entreprise</h3>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="profile-name" className="label">Nom du profil</label>
            <input id="profile-name" required maxLength={200} className="field" value={state.name} onChange={(event) => set("name", event.target.value)} />
          </div>
          <div className="flex items-end">
            <label className="flex items-center gap-2 pb-2 text-sm text-slate-700">
              <input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500" checked={state.isActive} onChange={(event) => set("isActive", event.target.checked)} />
              Profil actif (inclus dans la collecte quotidienne)
            </label>
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="profile-description" className="label">Activité</label>
            <textarea id="profile-description" rows={2} maxLength={4000} className="field" placeholder="Ex. PME de 18 salariés spécialisée en isolation thermique et menuiseries extérieures" value={state.description} onChange={(event) => set("description", event.target.value)} />
            <p className="hint">Transmise à l'IA pour apprécier l'adéquation métier.</p>
          </div>
        </div>
      </section>

      <section className="card p-6">
        <h3 className="text-base font-semibold text-slate-900">Ciblage des marchés</h3>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <TagInput id="keywords-include" label="Mots-clés inclus" tone="positive" placeholder="isolation, menuiserie" values={state.keywordsInclude} onChange={(values) => set("keywordsInclude", values)} hint="Un avis doit contenir au moins un mot-clé, une compétence ou un code CPV. Entrée ou virgule pour valider." />
          <TagInput id="keywords-exclude" label="Mots-clés exclus" tone="negative" placeholder="désamiantage, démolition" values={state.keywordsExclude} onChange={(values) => set("keywordsExclude", values)} hint="Un avis contenant l'un de ces mots est écarté d'office." />
          <TagInput id="skills" label="Compétences métier" placeholder="isolation thermique par l'extérieur" values={state.skills} onChange={(values) => set("skills", values)} />
          <TagInput id="cpv" label="Codes CPV" placeholder="45321000, 4542" values={state.cpvCodes} onChange={(values) => set("cpvCodes", values)} hint="Codes complets (8 chiffres) ou préfixes (2 à 7 chiffres)." />
          <TagInput id="departments" label="Départements d'intervention" placeholder="69, 38, 01" values={state.departments} onChange={(values) => set("departments", values)} hint="Numéros de département. Laisser vide pour la France entière." />
          <TagInput id="certifications" label="Certifications détenues" placeholder="Qualibat 7131, RGE, ISO 9001" values={state.certifications} onChange={(values) => set("certifications", values)} hint="Une certification exigée par un avis et absente d'ici déclenche une alerte." />
        </div>
      </section>

      <section className="card p-6">
        <h3 className="text-base font-semibold text-slate-900">Capacités et critères éliminatoires</h3>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor="annual-revenue" className="label">Chiffre d'affaires annuel (€)</label>
            <input id="annual-revenue" inputMode="decimal" className="field" placeholder="2400000" value={state.annualRevenue} onChange={(event) => set("annualRevenue", event.target.value)} />
          </div>
          <div>
            <label htmlFor="min-contract" className="label">Marché minimum (€)</label>
            <input id="min-contract" inputMode="decimal" className="field" placeholder="20000" value={state.minContract} onChange={(event) => set("minContract", event.target.value)} />
          </div>
          <div>
            <label htmlFor="max-contract" className="label">Marché maximum (€)</label>
            <input id="max-contract" inputMode="decimal" className="field" placeholder="800000" value={state.maxContract} onChange={(event) => set("maxContract", event.target.value)} />
          </div>
          <div>
            <label htmlFor="min-days" className="label">Délai minimum pour répondre (jours)</label>
            <input id="min-days" type="number" min={0} max={180} required className="field" value={state.minResponseDays} onChange={(event) => set("minResponseDays", Number(event.target.value))} />
          </div>
          <div className="sm:col-span-2">
            <TagInput id="eliminatory" label="Critères éliminatoires personnalisés" tone="negative" placeholder="visite obligatoire, habilitation défense" values={state.eliminatoryCriteria} onChange={(values) => set("eliminatoryCriteria", values)} hint="Expressions qui, présentes dans un avis, constituent pour vous un motif d'abandon." />
          </div>
        </div>
      </section>

      <section className="card p-6">
        <h3 className="text-base font-semibold text-slate-900">Alertes</h3>
        <div className="mt-4 grid gap-6 sm:grid-cols-2">
          <div>
            <label htmlFor="threshold" className="label">
              Seuil d'alerte du digest : <span className="font-semibold tabular-nums text-slate-900">{state.alertThreshold} / 100</span>
            </label>
            <input id="threshold" type="range" min={0} max={100} step={5} className="mt-2 w-full accent-sky-600" value={state.alertThreshold} onChange={(event) => set("alertThreshold", Number(event.target.value))} />
            <p className="hint">Seules les opportunités atteignant ce score figurent dans le digest quotidien.</p>
          </div>
          <div>
            <label htmlFor="digest-email" className="label">E-mail de réception du digest</label>
            <input id="digest-email" type="email" maxLength={320} className="field" placeholder="direction@entreprise.fr" value={state.digestEmail} onChange={(event) => set("digestEmail", event.target.value)} />
          </div>
        </div>
      </section>

      {message && <Alert tone="error">{message}</Alert>}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          {onDelete && (
            <button type="button" className="btn-danger" disabled={saving} onClick={onDelete}>Supprimer ce profil</button>
          )}
        </div>
        <div className="flex gap-3">
          {onCancel && <button type="button" className="btn-secondary" disabled={saving} onClick={onCancel}>Annuler</button>}
          <button type="submit" className="btn-primary" disabled={saving || !state.name.trim()}>
            {saving && <Spinner className="h-4 w-4" />}
            {profile ? "Enregistrer et ré-analyser" : "Créer le profil"}
          </button>
        </div>
      </div>
    </form>
  );
}
