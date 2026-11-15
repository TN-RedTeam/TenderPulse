import { useEffect } from "react";
import { formatDate, formatDateTime, formatEuros, STATUS_LABEL } from "../format";
import type { FollowUpStatus, Opportunity } from "../types";
import { Countdown, DecisionBadge, ScoreRing, Spinner } from "./ui";

interface DetailPanelProps {
  opportunity: Opportunity;
  now: number;
  updating: boolean;
  onStatusChange: (status: FollowUpStatus) => void;
  onClose: () => void;
}

const STATUS_ORDER: FollowUpStatus[] = ["nouveau", "a_etudier", "go", "ignore"];
const STATUS_ACTIVE: Record<FollowUpStatus, string> = {
  nouveau: "border-sky-600 bg-sky-600 text-white",
  a_etudier: "border-violet-600 bg-violet-600 text-white",
  go: "border-emerald-600 bg-emerald-600 text-white",
  ignore: "border-slate-600 bg-slate-600 text-white",
};

/** Panneau latéral : synthèse IA, justification du score, alertes éliminatoires et statut de suivi. */
export function DetailPanel({ opportunity, now, updating, onStatusChange, onClose }: DetailPanelProps) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const blocking = opportunity.eliminatory.filter((flag) => flag.severity === "bloquant");
  const toCheck = opportunity.eliminatory.filter((flag) => flag.severity !== "bloquant");
  const summaryLines = opportunity.summary.split("\n").filter((line) => line.trim().length > 0);

  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Détail de l'opportunité">
      <div className="absolute inset-0 bg-slate-900/40" onClick={onClose} />
      <aside className="absolute inset-y-0 right-0 flex w-full max-w-2xl flex-col bg-white shadow-2xl">
        <header className="flex items-start gap-4 border-b border-slate-200 px-6 py-5">
          <ScoreRing score={opportunity.score} decision={opportunity.decision} size={64} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <DecisionBadge decision={opportunity.decision} />
              <span className="text-xs text-slate-500">Avis {opportunity.idweb} · publié le {formatDate(opportunity.date_parution)}</span>
            </div>
            <h2 className="mt-1.5 text-base font-semibold leading-snug text-slate-900">{opportunity.objet || "Objet non précisé"}</h2>
            <p className="mt-0.5 text-sm text-slate-600">{opportunity.acheteur || "Acheteur non précisé"}</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Fermer le panneau">
            ✕
          </button>
        </header>

        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
          <dl className="grid grid-cols-2 gap-4 rounded-xl bg-slate-50 p-4 text-sm sm:grid-cols-4">
            <div className="col-span-2">
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Date limite de remise</dt>
              <dd className="mt-1 font-medium text-slate-900">{formatDateTime(opportunity.date_limite)}</dd>
              <dd><Countdown deadline={opportunity.date_limite} now={now} /></dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Budget estimé</dt>
              <dd className="mt-1 font-medium text-slate-900">{formatEuros(opportunity.budget_estime)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Lieu</dt>
              <dd className="mt-1 font-medium text-slate-900">
                {opportunity.departments.length > 0 ? `Dép. ${opportunity.departments.join(", ")}` : "Non précisé"}
              </dd>
            </div>
          </dl>

          {blocking.length > 0 && (
            <section className="rounded-xl border border-red-300 bg-red-50 p-4" role="alert">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-red-800">
                <span aria-hidden="true">⛔</span>
                {blocking.length > 1 ? `${blocking.length} critères éliminatoires détectés` : "Critère éliminatoire détecté"}
              </h3>
              <ul className="mt-2 space-y-2">
                {blocking.map((flag) => (
                  <li key={flag.label} className="text-sm text-red-900">
                    <p className="font-medium">{flag.label}</p>
                    <p className="text-red-800">{flag.detail}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {toCheck.length > 0 && (
            <section className="rounded-xl border border-amber-300 bg-amber-50 p-4">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-amber-900">
                <span aria-hidden="true">⚠</span> Points à vérifier avant de décider
              </h3>
              <ul className="mt-2 space-y-2">
                {toCheck.map((flag) => (
                  <li key={flag.label} className="text-sm text-amber-900">
                    <p className="font-medium">{flag.label}</p>
                    <p>{flag.detail}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <h3 className="text-sm font-semibold text-slate-900">Synthèse décisionnelle</h3>
            <ol className="mt-2 space-y-1.5 rounded-xl border border-slate-200 p-4 text-sm leading-relaxed text-slate-700">
              {summaryLines.map((line, index) => (
                <li key={index} className={index === summaryLines.length - 1 ? "font-medium text-slate-900" : ""}>{line}</li>
              ))}
            </ol>
            <p className="mt-1.5 text-xs text-slate-500">
              {opportunity.analysis_source === "llm"
                ? `Analyse générée par IA (${opportunity.model ?? "LLM"}) et contrôlée par des règles déterministes.`
                : "Analyse par règles déterministes (aucun LLM configuré ou LLM indisponible)."}
              {" "}À confirmer sur le règlement de consultation.
            </p>
          </section>

          <section>
            <h3 className="text-sm font-semibold text-slate-900">Justification du score</h3>
            <ul className="mt-2 space-y-3">
              {opportunity.criteria.map((criterion) => {
                const ratio = criterion.score / criterion.max_score;
                const bar = ratio >= 0.75 ? "bg-emerald-500" : ratio >= 0.4 ? "bg-amber-500" : "bg-red-500";
                return (
                  <li key={criterion.key}>
                    <div className="flex items-baseline justify-between gap-3 text-sm">
                      <span className="font-medium text-slate-800">{criterion.label}</span>
                      <span className="tabular-nums text-slate-600">{criterion.score} / {criterion.max_score}</span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200">
                      <div className={`h-full rounded-full ${bar}`} style={{ width: `${Math.round(ratio * 100)}%` }} />
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-slate-600">{criterion.justification}</p>
                  </li>
                );
              })}
            </ul>
          </section>

          {opportunity.lots.length > 0 && (
            <section>
              <h3 className="text-sm font-semibold text-slate-900">Lots ({opportunity.lots.length})</h3>
              <ul className="mt-2 divide-y divide-slate-100 rounded-xl border border-slate-200 text-sm">
                {opportunity.lots.map((lot, index) => (
                  <li key={`${lot.numero}-${index}`} className="flex items-start justify-between gap-4 px-4 py-2.5">
                    <div className="min-w-0">
                      <p className="font-medium text-slate-800">Lot {lot.numero} — {lot.intitule || "Sans intitulé"}</p>
                      {lot.description && lot.description !== lot.intitule && (
                        <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{lot.description}</p>
                      )}
                    </div>
                    {lot.budget_estime !== null && (
                      <span className="shrink-0 tabular-nums text-slate-600">{formatEuros(lot.budget_estime)}</span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="text-xs text-slate-500">
            {opportunity.procedure && <p>Procédure : {opportunity.procedure}</p>}
            {opportunity.cpv_codes.length > 0 && <p>Codes CPV : {opportunity.cpv_codes.join(", ")}</p>}
            <a href={opportunity.url_avis} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-sky-700 hover:underline">
              Consulter l'avis officiel sur boamp.fr ↗
            </a>
          </section>
        </div>

        <footer className="border-t border-slate-200 bg-slate-50 px-6 py-4">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Statut de suivi</p>
            {updating && <Spinner className="h-4 w-4" />}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {STATUS_ORDER.map((status) => {
              const active = opportunity.status === status;
              return (
                <button
                  key={status} type="button" disabled={updating} aria-pressed={active}
                  className={`btn border ${active ? STATUS_ACTIVE[status] : "border-slate-300 bg-white text-slate-700 hover:bg-slate-100"}`}
                  onClick={() => {
                    if (!active) {
                      onStatusChange(status);
                    }
                  }}
                >
                  {STATUS_LABEL[status]}
                </button>
              );
            })}
          </div>
        </footer>
      </aside>
    </div>
  );
}
