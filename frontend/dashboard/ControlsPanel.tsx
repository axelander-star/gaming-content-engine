"use client";

import { useState } from "react";

import { Badge, ErrorText, Section, Switch } from "@/components/ui";
import { api } from "@/lib/api";
import { emitEmergencyStop } from "@/lib/events";
import { hasRole } from "@/lib/roles";
import type { EffectiveControls, UserRole } from "@/lib/types";

/** Emergency stop and auto-publish switch. Rules mirror backend/api/settings.py. */
export function ControlsPanel({
  controls,
  role,
  onChange,
}: {
  controls: EffectiveControls;
  role: UserRole;
  onChange: (c: EffectiveControls) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isAdmin = hasRole(role, "admin");
  const isOperator = hasRole(role, "operator");

  async function update(changes: Parameters<typeof api.updateControls>[0]) {
    setBusy(true);
    setError(null);
    try {
      const next = await api.updateControls(changes);
      onChange(next);
      emitEmergencyStop(next.emergency_stop);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const stopLocked = controls.env_emergency_stop;
  const canToggleStop = controls.emergency_stop ? isAdmin && !stopLocked : isOperator;
  const canToggleAuto = isAdmin && controls.env_auto_publish_enabled && !controls.emergency_stop;

  return (
    <Section title="Steuerung">
      <div className="control-row">
        <div>
          <strong>Not-Aus</strong>
          <p className="muted small">
            Stoppt alle Agenten und Veröffentlichungen sofort. Operatoren dürfen ihn auslösen, nur
            Admins dürfen ihn wieder lösen.
            {stopLocked && " Der Not-Aus ist zusätzlich in der Serverkonfiguration gesetzt."}
          </p>
        </div>
        <Switch
          label="Not-Aus"
          tone="danger"
          checked={controls.emergency_stop}
          disabled={busy || !canToggleStop}
          onChange={(next) => void update({ emergency_stop: next })}
        />
      </div>
      <div className="control-row">
        <div>
          <strong>Automatische Veröffentlichung</strong>
          <p className="muted small">
            Standardmäßig aus. Wirksam nur, wenn zusätzlich die Serverkonfiguration es erlaubt und
            der Publishing-Modus auf „Live“ steht.
            {!controls.env_auto_publish_enabled &&
              " Aktuell durch die Serverkonfiguration gesperrt (AUTO_PUBLISH_ENABLED=false)."}
          </p>
        </div>
        <Switch
          label="Automatische Veröffentlichung"
          checked={controls.auto_publish_enabled}
          disabled={busy || !canToggleAuto}
          onChange={(next) => void update({ auto_publish_enabled: next })}
        />
      </div>
      <dl className="kv">
        <dt>Publishing-Modus</dt>
        <dd>
          <Badge tone={controls.publishing_mode === "live" ? "warn" : "neutral"}>
            {controls.publishing_mode === "live" ? "Live" : "Mock (keine echten Posts)"}
          </Badge>
        </dd>
        <dt>Veröffentlichung tatsächlich erlaubt</dt>
        <dd>
          <Badge tone={controls.publishing_allowed ? "warn" : "ok"}>
            {controls.publishing_allowed ? "Ja" : "Nein"}
          </Badge>
        </dd>
        <dt>Kostenpflichtige API-Aufrufe</dt>
        <dd>
          <Badge tone={controls.paid_api_calls_enabled ? "warn" : "ok"}>
            {controls.paid_api_calls_enabled ? "Erlaubt" : "Gesperrt"}
          </Badge>
        </dd>
      </dl>
      <ErrorText error={error} />
    </Section>
  );
}
