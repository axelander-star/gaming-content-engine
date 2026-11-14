"use client";

import { useState } from "react";
import type { FormEvent } from "react";

import { ErrorText, Section } from "@/components/ui";
import { api } from "@/lib/api";
import type { OperationsSettings } from "@/lib/types";

type NumericKey = {
  [K in keyof OperationsSettings]: OperationsSettings[K] extends number ? K : never;
}[keyof OperationsSettings];

const FIELDS: { key: NumericKey; label: string; step: number; min: number; max?: number }[] = [
  { key: "monthly_budget_eur", label: "Monatsbudget (€)", step: 1, min: 0 },
  { key: "max_daily_production_jobs", label: "Max. tägliche Produktionsjobs", step: 1, min: 0 },
  { key: "max_parallel_render_jobs", label: "Max. parallele Renderjobs", step: 1, min: 1, max: 64 },
  { key: "min_quality_score", label: "Mindestqualität (0–1)", step: 0.05, min: 0, max: 1 },
  {
    key: "min_publish_interval_minutes",
    label: "Mindestabstand zwischen Veröffentlichungen (Min.)",
    step: 5,
    min: 0,
  },
];

export function OperationsForm({
  initial,
  editable,
}: {
  initial: OperationsSettings;
  editable: boolean;
}) {
  const [values, setValues] = useState<OperationsSettings>(initial);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const changes = Object.fromEntries(FIELDS.map((f) => [f.key, values[f.key]]));
      setValues(await api.updateOperations(changes));
      setSaved(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Betrieb und Budget">
      <form className="form-grid" onSubmit={onSubmit}>
        {FIELDS.map((f) => (
          <label key={f.key}>
            {f.label}
            <input
              type="number"
              step={f.step}
              min={f.min}
              max={f.max}
              value={values[f.key]}
              disabled={!editable}
              onChange={(e) => setValues({ ...values, [f.key]: Number(e.target.value) })}
            />
          </label>
        ))}
        <label>
          KI-Anbieter
          <input value={values.ai_provider} disabled />
        </label>
        <label>
          TTS-Anbieter
          <input value={values.tts_provider} disabled />
        </label>
        <div className="form-actions">
          {editable ? (
            <button className="btn btn-primary" type="submit" disabled={busy}>
              Speichern
            </button>
          ) : (
            <span className="muted small">Nur Admins können diese Werte ändern.</span>
          )}
          {saved && <span className="ok small">Gespeichert.</span>}
        </div>
      </form>
      <p className="muted small">
        KI- und TTS-Anbieter werden erst nach Preisprüfung und Freigabe gewählt (Phase 8/9). Bis
        dahin laufen alle Dienste als Mock.
      </p>
      <ErrorText error={error} />
    </Section>
  );
}
