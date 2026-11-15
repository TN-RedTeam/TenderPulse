import type { Decision, FollowUpStatus } from "./types";

export const DECISION_LABEL: Record<Decision, string> = {
  go: "Go",
  a_verifier: "À vérifier",
  no_go: "No-Go",
};

export const DECISION_STYLE: Record<Decision, { badge: string; dot: string; ring: string }> = {
  go: { badge: "bg-emerald-100 text-emerald-800 ring-emerald-600/20", dot: "bg-emerald-500", ring: "text-emerald-600" },
  a_verifier: { badge: "bg-amber-100 text-amber-800 ring-amber-600/20", dot: "bg-amber-500", ring: "text-amber-500" },
  no_go: { badge: "bg-red-100 text-red-800 ring-red-600/20", dot: "bg-red-500", ring: "text-red-500" },
};

export const STATUS_LABEL: Record<FollowUpStatus, string> = {
  nouveau: "Nouveau",
  a_etudier: "À étudier",
  go: "Go — on répond",
  ignore: "Ignoré",
};

export const STATUS_STYLE: Record<FollowUpStatus, string> = {
  nouveau: "bg-sky-100 text-sky-800",
  a_etudier: "bg-violet-100 text-violet-800",
  go: "bg-emerald-100 text-emerald-800",
  ignore: "bg-slate-200 text-slate-600",
};

const euros = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
// Les échéances des marchés publics français s'entendent en heure de Paris, quel que soit le fuseau du navigateur.
const dateTime = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Paris" });
const dateOnly = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeZone: "Europe/Paris" });

export function formatEuros(amount: number | null): string {
  return amount === null ? "Non précisé" : euros.format(amount);
}

export function formatDateTime(iso: string | null): string {
  return iso ? dateTime.format(new Date(iso)) : "Non précisée";
}

export function formatDate(iso: string | null): string {
  return iso ? dateOnly.format(new Date(iso)) : "—";
}

export interface CountdownInfo {
  label: string;
  tone: "none" | "ok" | "soon" | "urgent" | "closed";
}

export function countdown(iso: string | null, now: number): CountdownInfo {
  if (!iso) {
    return { label: "Sans date limite", tone: "none" };
  }
  const remainingMs = new Date(iso).getTime() - now;
  if (remainingMs <= 0) {
    return { label: "Clôturé", tone: "closed" };
  }
  const minutes = Math.floor(remainingMs / 60000);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  if (days >= 7) {
    return { label: `J-${days}`, tone: "ok" };
  }
  if (days >= 3) {
    return { label: `J-${days} · ${hours} h`, tone: "soon" };
  }
  if (days >= 1) {
    return { label: `${days} j ${hours} h`, tone: "urgent" };
  }
  return { label: `${hours} h ${minutes % 60} min`, tone: "urgent" };
}
