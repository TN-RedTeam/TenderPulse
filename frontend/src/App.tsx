import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiClient, ApiError, loadApiKey, saveApiKey } from "./api";
import { DetailPanel } from "./components/DetailPanel";
import { Login, Logo } from "./components/Login";
import { OpportunityTable } from "./components/OpportunityTable";
import { ProfileForm } from "./components/ProfileForm";
import { Alert, Modal, Spinner, useNow } from "./components/ui";
import { DECISION_LABEL, STATUS_LABEL } from "./format";
import type {
  CollectionRun, Decision, FollowUpStatus, Me, OpportunityFilters, OpportunityList, Profile, ProfileInput, Tenant,
} from "./types";

type View = "opportunities" | "profile" | "new-profile";
interface Notice {
  tone: "success" | "error" | "info";
  text: string;
}

const DECISIONS: Decision[] = ["go", "a_verifier", "no_go"];
const STATUSES: FollowUpStatus[] = ["nouveau", "a_etudier", "go", "ignore"];
const EMPTY_FILTERS: OpportunityFilters = { decision: null, status: null, includeExpired: false };

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Erreur inattendue";
}

export default function App() {
  const [apiKey, setApiKey] = useState<string>(() => loadApiKey());
  const [me, setMe] = useState<Me | null>(null);
  const [authBusy, setAuthBusy] = useState<boolean>(apiKey !== "");
  const [authError, setAuthError] = useState<string | null>(null);

  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profilesLoading, setProfilesLoading] = useState(false);
  const [profileId, setProfileId] = useState<string | null>(null);

  const [view, setView] = useState<View>("opportunities");
  const [filters, setFilters] = useState<OpportunityFilters>(EMPTY_FILTERS);
  const [list, setList] = useState<OpportunityList | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [statusUpdating, setStatusUpdating] = useState(false);

  const [notice, setNotice] = useState<Notice | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [run, setRun] = useState<CollectionRun | null>(null);
  const [digestHtml, setDigestHtml] = useState<string | null>(null);
  const [digestLoading, setDigestLoading] = useState(false);
  const [tenantModal, setTenantModal] = useState(false);
  const [createdKey, setCreatedKey] = useState<{ name: string; apiKey: string } | null>(null);

  const now = useNow();
  const api = useMemo(() => new ApiClient(apiKey), [apiKey]);
  const reloadTimers = useRef<number[]>([]);

  const logout = useCallback(() => {
    saveApiKey("");
    setApiKey("");
    setMe(null);
    setTenants([]);
    setTenantId(null);
    setProfiles([]);
    setProfileId(null);
    setList(null);
    setSelectedId(null);
    setNotice(null);
  }, []);

  // --- Authentification : valide la clé et détermine le périmètre (opérateur ou client).
  useEffect(() => {
    if (!apiKey) {
      setAuthBusy(false);
      return;
    }
    let cancelled = false;
    setAuthBusy(true);
    (async () => {
      try {
        const identity = await api.me();
        const tenantList = identity.role === "admin" ? await api.listTenants() : identity.tenant ? [identity.tenant] : [];
        if (cancelled) {
          return;
        }
        saveApiKey(apiKey);
        setMe(identity);
        setTenants(tenantList);
        setTenantId((current) => (current && tenantList.some((t) => t.id === current) ? current : tenantList[0]?.id ?? null));
        setAuthError(null);
      } catch (error) {
        if (cancelled) {
          return;
        }
        const invalid = error instanceof ApiError && (error.status === 401 || error.status === 403);
        setAuthError(invalid ? "Clé d'API invalide." : errorText(error));
        saveApiKey("");
        setApiKey("");
        setMe(null);
      } finally {
        if (!cancelled) {
          setAuthBusy(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [api, apiKey]);

  // --- Profils du client sélectionné.
  useEffect(() => {
    if (!me || !tenantId) {
      setProfiles([]);
      setProfileId(null);
      return;
    }
    let cancelled = false;
    setProfilesLoading(true);
    api.listProfiles(tenantId)
      .then((items) => {
        if (cancelled) {
          return;
        }
        setProfiles(items);
        setProfileId((current) => (current && items.some((p) => p.id === current) ? current : items[0]?.id ?? null));
        setView(items.length === 0 ? "new-profile" : "opportunities");
      })
      .catch((error) => !cancelled && setNotice({ tone: "error", text: errorText(error) }))
      .finally(() => !cancelled && setProfilesLoading(false));
    return () => {
      cancelled = true;
    };
  }, [api, me, tenantId]);

  // --- Opportunités du profil sélectionné.
  const loadOpportunities = useCallback(async (silent = false) => {
    if (!tenantId || !profileId) {
      setList(null);
      return;
    }
    if (!silent) {
      setListLoading(true);
    }
    try {
      setList(await api.listOpportunities(tenantId, profileId, filters));
    } catch (error) {
      setNotice({ tone: "error", text: errorText(error) });
    } finally {
      setListLoading(false);
    }
  }, [api, tenantId, profileId, filters]);

  useEffect(() => {
    setSelectedId(null);
    void loadOpportunities();
  }, [loadOpportunities]);

  useEffect(() => () => reloadTimers.current.forEach((timer) => window.clearTimeout(timer)), []);

  const scheduleReloads = useCallback(() => {
    reloadTimers.current.forEach((timer) => window.clearTimeout(timer));
    reloadTimers.current = [2000, 8000, 20000].map((delay) => window.setTimeout(() => void loadOpportunities(true), delay));
  }, [loadOpportunities]);

  // --- Suivi d'une collecte en cours.
  useEffect(() => {
    if (!run || run.status !== "en_cours") {
      return;
    }
    const timer = window.setInterval(async () => {
      try {
        const latest = await api.getRun(run.id);
        if (latest.status === "en_cours") {
          return;
        }
        setRun(latest);
        if (latest.status === "termine") {
          setNotice({
            tone: "success",
            text: `Collecte terminée : ${latest.tenders_fetched} avis récupérés, ${latest.tenders_new} nouveaux, ${latest.scores_written} opportunités analysées.`,
          });
          void loadOpportunities(true);
        } else {
          setNotice({ tone: "error", text: `La collecte a échoué : ${latest.error ?? "erreur inconnue"}` });
        }
      } catch (error) {
        setRun(null);
        setNotice({ tone: "error", text: errorText(error) });
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [api, run, loadOpportunities]);

  const profile = profiles.find((item) => item.id === profileId) ?? null;
  const tenant = tenants.find((item) => item.id === tenantId) ?? null;
  const selected = list?.items.find((item) => item.id === selectedId) ?? null;

  const startCollection = async () => {
    try {
      setRun(await api.startCollection());
      setNotice({ tone: "info", text: "Collecte BOAMP lancée. Les nouvelles opportunités apparaîtront à la fin de l'analyse." });
    } catch (error) {
      setNotice({ tone: "error", text: errorText(error) });
    }
  };

  const openDigest = async () => {
    if (!tenantId || !profileId) {
      return;
    }
    setDigestLoading(true);
    try {
      setDigestHtml(await api.digestHtml(tenantId, profileId, 0));
    } catch (error) {
      setNotice({ tone: "error", text: errorText(error) });
    } finally {
      setDigestLoading(false);
    }
  };

  const changeStatus = async (status: FollowUpStatus) => {
    if (!tenantId || !selected) {
      return;
    }
    setStatusUpdating(true);
    try {
      const updated = await api.updateStatus(tenantId, selected.id, status);
      setList((current) => current && {
        ...current,
        items: current.items.map((item) => (item.id === updated.id ? { ...item, status: updated.status, status_updated_at: updated.status_updated_at } : item)),
      });
      void loadOpportunities(true);
    } catch (error) {
      setNotice({ tone: "error", text: errorText(error) });
    } finally {
      setStatusUpdating(false);
    }
  };

  const saveProfile = async (input: ProfileInput) => {
    if (!tenantId) {
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const creating = view === "new-profile" || !profile;
      const saved = creating ? await api.createProfile(tenantId, input) : await api.updateProfile(tenantId, profile.id, input);
      setProfiles((current) => (creating ? [...current, saved] : current.map((item) => (item.id === saved.id ? saved : item)))
        .sort((a, b) => a.name.localeCompare(b.name, "fr")));
      setProfileId(saved.id);
      setView("opportunities");
      setNotice({ tone: "success", text: `Profil « ${saved.name} » enregistré. Ré-analyse des avis ouverts en cours.` });
      scheduleReloads();
    } catch (error) {
      setFormError(errorText(error));
    } finally {
      setSaving(false);
    }
  };

  const deleteProfile = async () => {
    if (!tenantId || !profile || !window.confirm(`Supprimer le profil « ${profile.name} » et toutes ses opportunités ?`)) {
      return;
    }
    setSaving(true);
    try {
      await api.deleteProfile(tenantId, profile.id);
      const remaining = profiles.filter((item) => item.id !== profile.id);
      setProfiles(remaining);
      setProfileId(remaining[0]?.id ?? null);
      setView(remaining.length === 0 ? "new-profile" : "opportunities");
      setNotice({ tone: "success", text: "Profil supprimé." });
    } catch (error) {
      setFormError(errorText(error));
    } finally {
      setSaving(false);
    }
  };

  if (!me) {
    return <Login error={authError} busy={authBusy} onSubmit={(key) => { setAuthError(null); setApiKey(key); }} />;
  }

  const collecting = run?.status === "en_cours";

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <Logo />
            <div>
              <p className="text-base font-semibold leading-tight text-slate-900">TenderPulse</p>
              <p className="text-xs text-slate-500">{me.role === "admin" ? "Console opérateur" : tenant?.name}</p>
            </div>
          </div>

          <div className="flex flex-1 flex-wrap items-end gap-3">
            {me.role === "admin" && (
              <div>
                <label htmlFor="tenant-select" className="block text-xs font-medium text-slate-500">PME cliente</label>
                <select id="tenant-select" className="field mt-0.5 w-52 py-1.5" value={tenantId ?? ""} onChange={(event) => setTenantId(event.target.value || null)}>
                  {tenants.length === 0 && <option value="">Aucun client</option>}
                  {tenants.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
              </div>
            )}
            <div>
              <label htmlFor="profile-select" className="block text-xs font-medium text-slate-500">Profil de recherche</label>
              <select id="profile-select" className="field mt-0.5 w-60 py-1.5" value={profileId ?? ""} disabled={profiles.length === 0}
                      onChange={(event) => { setProfileId(event.target.value); setView("opportunities"); }}>
                {profiles.length === 0 && <option value="">Aucun profil</option>}
                {profiles.map((item) => <option key={item.id} value={item.id}>{item.name}{item.is_active ? "" : " (inactif)"}</option>)}
              </select>
            </div>
            {tenantId && (
              <button type="button" className="btn-secondary py-1.5" onClick={() => { setFormError(null); setView("new-profile"); }}>+ Profil</button>
            )}
            {me.role === "admin" && (
              <button type="button" className="btn-secondary py-1.5" onClick={() => setTenantModal(true)}>+ Client</button>
            )}
          </div>

          <div className="flex items-center gap-2">
            {me.role === "admin" && (
              <button type="button" className="btn-primary py-1.5" disabled={collecting} onClick={startCollection}>
                {collecting && <Spinner className="h-4 w-4 text-white" />}
                {collecting ? "Collecte en cours" : "Lancer une collecte"}
              </button>
            )}
            <button type="button" className="btn-secondary py-1.5" onClick={logout}>Déconnexion</button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-5 px-4 py-6 sm:px-6">
        {notice && <Alert tone={notice.tone} onClose={() => setNotice(null)}>{notice.text}</Alert>}

        {!tenantId && (
          <div className="card p-10 text-center">
            <p className="text-base font-medium text-slate-900">Aucune PME cliente pour le moment</p>
            <p className="mt-1 text-sm text-slate-500">Créez un premier client pour configurer son profil de recherche.</p>
            <button type="button" className="btn-primary mt-5" onClick={() => setTenantModal(true)}>Créer un client</button>
          </div>
        )}

        {tenantId && profilesLoading && <div className="flex justify-center py-16"><Spinner className="h-8 w-8" /></div>}

        {tenantId && !profilesLoading && view === "new-profile" && (
          <div>
            <h2 className="mb-4 text-lg font-semibold text-slate-900">Nouveau profil pour {tenant?.name}</h2>
            <ProfileForm profile={null} saving={saving} error={formError} onSave={saveProfile}
                         onCancel={profiles.length > 0 ? () => setView("opportunities") : undefined} />
          </div>
        )}

        {tenantId && !profilesLoading && profile && view !== "new-profile" && (
          <>
            <nav className="flex gap-1 border-b border-slate-200" aria-label="Sections">
              {([["opportunities", "Opportunités"], ["profile", "Profil de l'entreprise"]] as const).map(([key, label]) => (
                <button key={key} type="button" aria-current={view === key ? "page" : undefined}
                        className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-medium ${view === key ? "border-slate-900 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800"}`}
                        onClick={() => { setFormError(null); setView(key); }}>
                  {label}
                  {key === "opportunities" && list && list.counts.nouveau > 0 && (
                    <span className="ml-2 rounded-full bg-sky-100 px-2 py-0.5 text-xs font-semibold text-sky-800">{list.counts.nouveau} nouveau{list.counts.nouveau > 1 ? "x" : ""}</span>
                  )}
                </button>
              ))}
            </nav>

            {view === "profile" && (
              <ProfileForm profile={profile} saving={saving} error={formError} onSave={saveProfile} onDelete={deleteProfile} />
            )}

            {view === "opportunities" && (
              <section className="space-y-4">
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <button type="button" className={`card p-4 text-left transition hover:border-slate-400 ${filters.decision === null ? "ring-2 ring-slate-900" : ""}`}
                          onClick={() => setFilters((current) => ({ ...current, decision: null }))}>
                    <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Consultations ouvertes</p>
                    <p className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{list?.counts.total ?? "—"}</p>
                  </button>
                  {DECISIONS.map((decision) => {
                    const tone = { go: "text-emerald-700", a_verifier: "text-amber-700", no_go: "text-red-700" }[decision];
                    const active = filters.decision === decision;
                    return (
                      <button key={decision} type="button" aria-pressed={active}
                              className={`card p-4 text-left transition hover:border-slate-400 ${active ? "ring-2 ring-slate-900" : ""}`}
                              onClick={() => setFilters((current) => ({ ...current, decision: active ? null : decision }))}>
                        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{DECISION_LABEL[decision]}</p>
                        <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone}`}>{list?.counts[decision] ?? "—"}</p>
                      </button>
                    );
                  })}
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <select className="field w-44 py-1.5" aria-label="Filtrer par statut de suivi" value={filters.status ?? ""}
                            onChange={(event) => setFilters((current) => ({ ...current, status: (event.target.value || null) as FollowUpStatus | null }))}>
                      <option value="">Tous les statuts actifs</option>
                      {STATUSES.map((status) => <option key={status} value={status}>{STATUS_LABEL[status]}</option>)}
                    </select>
                    <label className="flex items-center gap-2 text-sm text-slate-600">
                      <input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500" checked={filters.includeExpired}
                             onChange={(event) => setFilters((current) => ({ ...current, includeExpired: event.target.checked }))} />
                      Inclure les consultations clôturées
                    </label>
                    {listLoading && <Spinner className="h-4 w-4" />}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-slate-500">Seuil d'alerte : {profile.alert_threshold}/100</span>
                    <button type="button" className="btn-secondary py-1.5" disabled={digestLoading} onClick={openDigest}>
                      {digestLoading && <Spinner className="h-4 w-4" />}
                      Aperçu du digest
                    </button>
                  </div>
                </div>

                {list && list.items.length > 0 && (
                  <OpportunityTable items={list.items} selectedId={selectedId} now={now} onSelect={(item) => setSelectedId(item.id)} />
                )}
                {list && list.items.length === 0 && !listLoading && (
                  <div className="card p-10 text-center">
                    <p className="text-base font-medium text-slate-900">Aucune opportunité à afficher</p>
                    <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
                      {filters.decision || filters.status
                        ? "Aucune opportunité ne correspond à ces filtres."
                        : "Aucun avis collecté ne correspond encore à ce profil. Lancez une collecte ou élargissez les mots-clés et départements du profil."}
                    </p>
                  </div>
                )}
                {list && list.total > list.items.length && (
                  <p className="text-center text-xs text-slate-500">{list.items.length} premières opportunités affichées sur {list.total}.</p>
                )}
              </section>
            )}
          </>
        )}
      </main>

      {selected && (
        <DetailPanel opportunity={selected} now={now} updating={statusUpdating} onStatusChange={changeStatus} onClose={() => setSelectedId(null)} />
      )}

      {digestHtml !== null && profile && (
        <DigestPreview html={digestHtml} profileName={profile.name} onClose={() => setDigestHtml(null)} />
      )}

      {tenantModal && (
        <TenantModal
          api={api}
          onClose={() => setTenantModal(false)}
          onCreated={(created) => {
            setTenants((current) => [...current, created].sort((a, b) => a.name.localeCompare(b.name, "fr")));
            setTenantId(created.id);
            setTenantModal(false);
            setCreatedKey({ name: created.name, apiKey: created.api_key });
          }}
        />
      )}

      {createdKey && (
        <Modal title={`Client « ${createdKey.name} » créé`} onClose={() => setCreatedKey(null)}>
          <p className="text-sm text-slate-600">
            Voici la clé d'API de ce client. Elle n'est affichée qu'une seule fois : transmettez-la-lui par un canal sûr.
          </p>
          <code className="mt-3 block select-all break-all rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-900">{createdKey.apiKey}</code>
          <div className="mt-5 flex justify-end">
            <button type="button" className="btn-primary" onClick={() => setCreatedKey(null)}>J'ai copié la clé</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function TenantModal({ api, onClose, onCreated }: {
  api: ApiClient;
  onClose: () => void;
  onCreated: (tenant: Tenant & { api_key: string }) => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal title="Nouvelle PME cliente" onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError(null);
          try {
            onCreated(await api.createTenant(name.trim(), email.trim() || null));
          } catch (failure) {
            setError(errorText(failure));
            setBusy(false);
          }
        }}
      >
        <div>
          <label htmlFor="tenant-name" className="label">Raison sociale</label>
          <input id="tenant-name" required autoFocus maxLength={200} className="field" value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <div>
          <label htmlFor="tenant-email" className="label">E-mail de contact (facultatif)</label>
          <input id="tenant-email" type="email" maxLength={320} className="field" value={email} onChange={(event) => setEmail(event.target.value)} />
        </div>
        {error && <Alert tone="error">{error}</Alert>}
        <div className="flex justify-end gap-3">
          <button type="button" className="btn-secondary" onClick={onClose}>Annuler</button>
          <button type="submit" className="btn-primary" disabled={busy || !name.trim()}>
            {busy && <Spinner className="h-4 w-4" />}
            Créer le client
          </button>
        </div>
      </form>
    </Modal>
  );
}

function DigestPreview({ html, profileName, onClose }: { html: string; profileName: string; onClose: () => void }) {
  const downloadUrl = useMemo(() => URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" })), [html]);
  useEffect(() => () => URL.revokeObjectURL(downloadUrl), [downloadUrl]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label="Aperçu du digest">
      <div className="absolute inset-0 bg-slate-900/50" onClick={onClose} />
      <div className="card relative flex h-[90vh] w-full max-w-3xl flex-col overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Aperçu du digest — {profileName}</h2>
            <p className="text-xs text-slate-500">Consultations ouvertes au-dessus du seuil d'alerte, telles qu'envoyées par e-mail.</p>
          </div>
          <div className="flex items-center gap-2">
            <a className="btn-secondary py-1.5" href={downloadUrl} download="digest-tenderpulse.html">Télécharger le HTML</a>
            <button type="button" className="btn-primary py-1.5" onClick={onClose}>Fermer</button>
          </div>
        </div>
        <iframe title="Digest" sandbox="" srcDoc={html} className="w-full flex-1 bg-slate-100" />
      </div>
    </div>
  );
}
