"use client";

import { useEffect, useState } from "react";

import { Badge, Section, StatCard } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import type { DeployHookStatus } from "@/lib/types";

const RESULT: Record<string, string> = {
  ok: "Eingespielt",
  rolled_back: "Fehlgeschlagen, alte Version läuft",
  failed: "Fehlgeschlagen",
};

/** Webhook address on the sibling host: studio.example.de -> update.example.de. */
function hookUrl(): string {
  if (typeof window === "undefined") return "https://update.<deine-domain>/github";
  const labels = window.location.hostname.split(".");
  const base = labels.length > 2 ? labels.slice(1).join(".") : labels.join(".");
  return `https://update.${base}/github`;
}

function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <p>
      <span className="muted small">{label}</span>
      <br />
      <code style={{ wordBreak: "break-all" }}>{value}</code>{" "}
      <button
        type="button"
        className="btn btn-ghost small"
        onClick={() => {
          void navigator.clipboard
            .writeText(value)
            .then(() => setCopied(true))
            .catch(() => setCopied(false));
        }}
      >
        {copied ? "Kopiert" : "Kopieren"}
      </button>
    </p>
  );
}

/** Instant server update after a merge (GitHub webhook). Only visible to admins. */
export function InstantUpdatePanel() {
  const [data, setData] = useState<DeployHookStatus | null>(null);
  useEffect(() => {
    api
      .deployHookStatus()
      .then(setData)
      .catch(() => setData(null)); // not an admin, or older backend: no panel
  }, []);
  if (!data) return null;

  const connected = data.last_hook !== null;
  const ready = data.secret_ready && data.watcher_active;
  const lu = data.last_update;
  return (
    <Section title="Sofort-Update nach einem Merge">
      <p role="status">
        {ready && connected ? (
          <Badge tone="ok">Aktiv</Badge>
        ) : ready ? (
          <Badge tone="warn">Server bereit, GitHub noch nicht verbunden</Badge>
        ) : (
          <Badge tone="neutral">Wird auf dem Server eingerichtet</Badge>
        )}{" "}
        <span className="muted small">
          Neue Versionen kommen Sekunden nach dem Merge auf den Server. Die Prüfung alle 5 Minuten
          bleibt als Rückfall.
        </span>
      </p>
      <div className="grid stats">
        <StatCard
          label="Server-Wächter"
          value={data.watcher_active ? "Läuft" : "Noch nicht gestartet"}
          hint={data.watcher_seen_at ? `zuletzt ${formatDateTime(data.watcher_seen_at)}` : undefined}
        />
        <StatCard
          label="Letzte Meldung von GitHub"
          value={data.last_hook ? formatDateTime(data.last_hook.at) : "Noch keine"}
          hint={data.pending ? "Update wird gerade gestartet" : data.last_hook?.detail}
        />
        <StatCard
          label="Letztes Update"
          value={lu ? (RESULT[lu.result] ?? lu.result) : "–"}
          hint={lu ? `${formatDateTime(lu.at)} · ${lu.to} ${lu.subject}` : undefined}
        />
      </div>
      {data.secret && !connected && (
        <details open>
          <summary>In GitHub verbinden (einmalig)</summary>
          <ol>
            <li>
              In Cloudflare Zero Trust beim Tunnel einen öffentlichen Hostnamen{" "}
              <code>update.…</code> mit Ziel <code>http://caddy:8083</code> anlegen, ohne
              Access-Anwendung.
            </li>
            <li>
              In GitHub im Repository unter Settings → Webhooks → Add webhook diese Werte
              eintragen, Content type <code>application/json</code>, nur das Push-Ereignis.
            </li>
          </ol>
          <CopyField label="Payload URL" value={hookUrl()} />
          <CopyField label="Secret" value={data.secret} />
        </details>
      )}
    </Section>
  );
}
