import { useState } from "react";
import { Alert, Spinner } from "./ui";

interface LoginProps {
  error: string | null;
  busy: boolean;
  onSubmit: (apiKey: string) => void;
}

export function Login({ error, busy, onSubmit }: LoginProps) {
  const [apiKey, setApiKey] = useState("");
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form
        className="card w-full max-w-sm p-8"
        onSubmit={(event) => {
          event.preventDefault();
          if (apiKey.trim()) {
            onSubmit(apiKey.trim());
          }
        }}
      >
        <div className="flex items-center gap-3">
          <Logo />
          <div>
            <h1 className="text-xl font-semibold text-slate-900">TenderPulse</h1>
            <p className="text-sm text-slate-500">Veille des marchés publics pour PME</p>
          </div>
        </div>
        <label htmlFor="api-key" className="label mt-8">Clé d'API</label>
        <input
          id="api-key" type="password" autoComplete="current-password" autoFocus className="field"
          placeholder="Clé d'administration ou clé client" value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
        />
        <p className="hint">
          La clé d'administration donne accès à tous les clients ; une clé client (préfixe « tp_ ») ne donne accès qu'à ses propres données.
        </p>
        {error && <div className="mt-4"><Alert tone="error">{error}</Alert></div>}
        <button type="submit" className="btn-primary mt-6 w-full" disabled={busy || !apiKey.trim()}>
          {busy && <Spinner className="h-4 w-4" />}
          Se connecter
        </button>
      </form>
    </div>
  );
}

export function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="h-10 w-10 shrink-0" aria-hidden="true">
      <rect width="32" height="32" rx="7" className="fill-slate-900" />
      <path d="M5 17h5l3-8 5 14 3-6h6" fill="none" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="stroke-sky-400" />
    </svg>
  );
}
