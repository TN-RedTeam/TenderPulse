import { useEffect, useState } from "react";
import { countdown, DECISION_LABEL, DECISION_STYLE, STATUS_LABEL, STATUS_STYLE } from "../format";
import type { Decision, FollowUpStatus } from "../types";

export function DecisionBadge({ decision }: { decision: Decision }) {
  const style = DECISION_STYLE[decision];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${style.badge}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} aria-hidden="true" />
      {DECISION_LABEL[decision]}
    </span>
  );
}

export function StatusBadge({ status }: { status: FollowUpStatus }) {
  return (
    <span className={`inline-flex rounded-md px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}

/** Score sur 100 dans un anneau de progression coloré selon la décision. */
export function ScoreRing({ score, decision, size = 48 }: { score: number; decision: Decision; size?: number }) {
  const radius = 15.9155;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={`Score ${score} sur 100`}>
      <svg viewBox="0 0 36 36" className="h-full w-full -rotate-90">
        <circle cx="18" cy="18" r={radius} fill="none" strokeWidth="3.2" className="stroke-slate-200" />
        <circle
          cx="18" cy="18" r={radius} fill="none" strokeWidth="3.2" strokeLinecap="round" stroke="currentColor"
          strokeDasharray={`${score} ${100 - score}`} className={DECISION_STYLE[decision].ring}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-semibold tabular-nums text-slate-900"
            style={{ fontSize: size * 0.3 }}>
        {score}
      </span>
    </div>
  );
}

/** Horloge partagée : rafraîchit les comptes à rebours toutes les 30 secondes. */
export function useNow(intervalMs = 30000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

const COUNTDOWN_TONE = {
  none: "text-slate-400",
  ok: "text-slate-700",
  soon: "text-amber-700",
  urgent: "text-red-700 font-semibold",
  closed: "text-slate-400 line-through",
} as const;

export function Countdown({ deadline, now }: { deadline: string | null; now: number }) {
  const info = countdown(deadline, now);
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap text-sm tabular-nums ${COUNTDOWN_TONE[info.tone]}`}>
      {info.tone === "urgent" && <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" aria-hidden="true" />}
      {info.label}
    </span>
  );
}

export function Spinner({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg className={`animate-spin text-slate-400 ${className}`} viewBox="0 0 24 24" fill="none" aria-label="Chargement">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" className="opacity-25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Alert({ tone, children, onClose }: { tone: "error" | "success" | "info"; children: React.ReactNode; onClose?: () => void }) {
  const styles = {
    error: "border-red-200 bg-red-50 text-red-800",
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
    info: "border-sky-200 bg-sky-50 text-sky-800",
  } as const;
  return (
    <div className={`flex items-start justify-between gap-3 rounded-lg border px-4 py-3 text-sm ${styles[tone]}`} role={tone === "error" ? "alert" : "status"}>
      <div className="min-w-0">{children}</div>
      {onClose && (
        <button type="button" onClick={onClose} className="shrink-0 rounded p-0.5 opacity-60 hover:opacity-100" aria-label="Fermer">
          ✕
        </button>
      )}
    </div>
  );
}

export function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-slate-900/50" onClick={onClose} />
      <div className="card relative w-full max-w-md p-6">
        <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  );
}
