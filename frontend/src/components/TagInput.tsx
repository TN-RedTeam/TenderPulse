import { useState } from "react";

interface TagInputProps {
  id: string;
  label: string;
  hint?: string;
  placeholder?: string;
  values: string[];
  onChange: (values: string[]) => void;
  tone?: "neutral" | "positive" | "negative";
}

const TONES = {
  neutral: "bg-slate-100 text-slate-800",
  positive: "bg-emerald-100 text-emerald-800",
  negative: "bg-red-100 text-red-800",
} as const;

/** Saisie d'une liste de libellés : Entrée ou virgule pour valider, Retour arrière pour retirer le dernier. */
export function TagInput({ id, label, hint, placeholder, values, onChange, tone = "neutral" }: TagInputProps) {
  const [draft, setDraft] = useState("");

  const commit = (raw: string) => {
    const additions = raw
      .split(/[,;\n]/)
      .map((part) => part.trim())
      .filter((part) => part.length > 0);
    if (additions.length === 0) {
      setDraft("");
      return;
    }
    const known = new Set(values.map((value) => value.toLowerCase()));
    const merged = values.slice();
    additions.forEach((item) => {
      if (!known.has(item.toLowerCase())) {
        known.add(item.toLowerCase());
        merged.push(item);
      }
    });
    onChange(merged);
    setDraft("");
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      commit(draft);
    } else if (event.key === "Backspace" && draft === "" && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  };

  return (
    <div>
      <label htmlFor={id} className="label">{label}</label>
      <div className="flex min-h-[42px] flex-wrap items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-2 py-1.5 shadow-sm focus-within:border-sky-500 focus-within:ring-1 focus-within:ring-sky-500">
        {values.map((value) => (
          <span key={value} className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-sm ${TONES[tone]}`}>
            {value}
            <button
              type="button" className="opacity-60 hover:opacity-100" aria-label={`Retirer ${value}`}
              onClick={() => onChange(values.filter((item) => item !== value))}
            >
              ✕
            </button>
          </span>
        ))}
        <input
          id={id} value={draft} placeholder={values.length === 0 ? placeholder : ""}
          className="min-w-[8rem] flex-1 border-0 bg-transparent p-1 text-sm placeholder:text-slate-400 focus:outline-none focus:ring-0"
          onChange={(event) => setDraft(event.target.value)} onKeyDown={onKeyDown} onBlur={() => commit(draft)}
          onPaste={(event) => {
            const text = event.clipboardData.getData("text");
            if (/[,;\n]/.test(text)) {
              event.preventDefault();
              commit(text);
            }
          }}
        />
      </div>
      {hint && <p className="hint">{hint}</p>}
    </div>
  );
}
