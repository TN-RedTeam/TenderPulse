import { formatEuros } from "../format";
import type { Opportunity } from "../types";
import { Countdown, DecisionBadge, ScoreRing, StatusBadge } from "./ui";

interface OpportunityTableProps {
  items: Opportunity[];
  selectedId: number | null;
  now: number;
  onSelect: (opportunity: Opportunity) => void;
}

/** Liste des opportunités, déjà triées par score décroissant par l'API. */
export function OpportunityTable({ items, selectedId, now, onSelect }: OpportunityTableProps) {
  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 text-left">
          <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th scope="col" className="px-4 py-3">Score</th>
              <th scope="col" className="px-4 py-3">Opportunité</th>
              <th scope="col" className="px-4 py-3">Avis IA</th>
              <th scope="col" className="px-4 py-3">Échéance</th>
              <th scope="col" className="px-4 py-3 text-right">Budget estimé</th>
              <th scope="col" className="px-4 py-3">Suivi</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {items.map((item) => {
              const blocking = item.eliminatory.filter((flag) => flag.severity === "bloquant").length;
              const selected = item.id === selectedId;
              return (
                <tr
                  key={item.id} tabIndex={0} aria-selected={selected}
                  className={`cursor-pointer transition hover:bg-sky-50/60 focus:outline-none focus-visible:bg-sky-50 ${selected ? "bg-sky-50" : ""} ${item.status === "ignore" ? "opacity-60" : ""}`}
                  onClick={() => onSelect(item)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect(item);
                    }
                  }}
                >
                  <td className="px-4 py-3"><ScoreRing score={item.score} decision={item.decision} /></td>
                  <td className="max-w-md px-4 py-3">
                    <p className="line-clamp-2 text-sm font-medium text-slate-900">{item.objet || "Objet non précisé"}</p>
                    <p className="mt-0.5 truncate text-xs text-slate-500">
                      {item.acheteur || "Acheteur non précisé"}
                      {item.departments.length > 0 && ` · Dép. ${item.departments.join(", ")}`}
                      {item.lots.length > 0 && ` · ${item.lots.length} lot${item.lots.length > 1 ? "s" : ""}`}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <DecisionBadge decision={item.decision} />
                    {blocking > 0 && (
                      <p className="mt-1 whitespace-nowrap text-xs font-medium text-red-700">
                        ⚠ {blocking} critère{blocking > 1 ? "s" : ""} éliminatoire{blocking > 1 ? "s" : ""}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3"><Countdown deadline={item.date_limite} now={now} /></td>
                  <td className="whitespace-nowrap px-4 py-3 text-right text-sm tabular-nums text-slate-700">{formatEuros(item.budget_estime)}</td>
                  <td className="px-4 py-3"><StatusBadge status={item.status} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
