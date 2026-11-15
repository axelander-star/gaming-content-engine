// Small presentational building blocks shared by all dashboard pages.

import type { ReactNode } from "react";

export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div className="page-header">
      <h1>{title}</h1>
      {description && <p className="muted">{description}</p>}
    </div>
  );
}

export function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <div className="card stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint muted">{hint}</div>}
    </div>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="card section">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "ok" | "warn" | "danger" | "info";
  children: ReactNode;
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

/** Marks an area whose data is produced by a later development phase. */
export function PhasePlaceholder({ phase, items }: { phase: string; items: string[] }) {
  return (
    <div className="placeholder">
      <p>
        Diese Ansicht wird mit <strong>{phase}</strong> mit echten Daten gefüllt. Geplant:
      </p>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export function ErrorText({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p className="error" role="alert">
      {error}
    </p>
  );
}

export function Switch({
  checked,
  onChange,
  disabled,
  label,
  tone = "default",
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  label: string;
  tone?: "default" | "danger";
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className={`switch ${checked ? "on" : ""} ${tone === "danger" ? "switch-danger" : ""}`}
      onClick={() => onChange(!checked)}
    >
      <span className="knob" />
    </button>
  );
}
