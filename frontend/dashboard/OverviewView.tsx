"use client";

import { useEffect, useState } from "react";

import { Badge, ErrorText, PageHeader, PhasePlaceholder, Section, StatCard } from "@/components/ui";
import { api } from "@/lib/api";
import type { Overview, Readiness } from "@/lib/types";

export function OverviewView() {
  const [data, setData] = useState<Overview | null>(null);
  const [ready, setReady] = useState<Readiness | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.overview().then(setData).catch((e: Error) => setError(e.message));
    api
      .readiness()
      .then(setReady)
      .catch(() => setReady({ status: "degraded", database: false, redis: false }));
  }, []);

  const c = data?.controls;
  return (
    <>
      <PageHeader title="Übersicht" description="Gesamtzustand des Systems auf einen Blick." />
      <ErrorText error={error} />

      <div className="grid stats">
        <StatCard label="Veröffentlichte Videos" value={data?.published_videos ?? "–"} />
        <StatCard label="In Produktion" value={data?.videos_in_production ?? "–"} />
        <StatCard label="In Qualitätskontrolle" value={data?.videos_in_quality_check ?? "–"} />
        <StatCard label="Veröffentlichungsfreigabe" value={data?.videos_ready_to_publish ?? "–"} />
        <StatCard
          label="Aktive Kanäle"
          value={data ? `${data.channels_active} / ${data.channels_total}` : "–"}
          hint="Kanäle sind bis zur Einrichtung pausiert"
        />
        <StatCard label="Fehlerhafte Videos" value={data?.videos_failed ?? "–"} />
      </div>

      <div className="grid two">
        <Section title="Systemstatus">
          <dl className="kv">
            <dt>Backend</dt>
            <dd>
              {ready ? (
                <Badge tone={ready.status === "ok" ? "ok" : "danger"}>
                  {ready.status === "ok" ? "Bereit" : "Gestört"}
                </Badge>
              ) : (
                "–"
              )}
            </dd>
            <dt>Datenbank</dt>
            <dd>{ready ? <Badge tone={ready.database ? "ok" : "danger"}>{ready.database ? "OK" : "Fehler"}</Badge> : "–"}</dd>
            <dt>Warteschlange (Redis)</dt>
            <dd>{ready ? <Badge tone={ready.redis ? "ok" : "danger"}>{ready.redis ? "OK" : "Fehler"}</Badge> : "–"}</dd>
            <dt>Not-Aus</dt>
            <dd>{c ? <Badge tone={c.emergency_stop ? "danger" : "ok"}>{c.emergency_stop ? "Aktiv" : "Aus"}</Badge> : "–"}</dd>
            <dt>Automatische Veröffentlichung</dt>
            <dd>{c ? <Badge tone={c.publishing_allowed ? "warn" : "neutral"}>{c.publishing_allowed ? "Aktiv" : "Aus"}</Badge> : "–"}</dd>
            <dt>Publishing-Modus</dt>
            <dd>{c ? <Badge tone={c.publishing_mode === "live" ? "warn" : "neutral"}>{c.publishing_mode === "live" ? "Live" : "Mock (Test)"}</Badge> : "–"}</dd>
          </dl>
        </Section>
        <Section title="Reichweite, Trends und Kosten">
          <PhasePlaceholder
            phase="Phase 5 und Phase 14"
            items={[
              "Gesamtaufrufe, heute, 7 und 30 Tage",
              "Beste Videos, Spiele und Formate",
              "Aktuelle Trends",
              "Monatliche Kosten",
            ]}
          />
        </Section>
      </div>
    </>
  );
}
