"use client";

// Competitor radar (Ausbau A5): YouTube channels of the niche and what runs far above
// their usual views. Stand-outs go to the idea lab as hints, never as copies.

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type { CompetitorRadar, ContentProject } from "@/lib/types";

const num = (n: number) => new Intl.NumberFormat("de-DE").format(n);

export function CompetitorsView() {
  const { user } = useAuth();
  const canEdit = hasRole(user?.role, "operator");
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [filter, setFilter] = useState<number | undefined>(undefined);
  const [radar, setRadar] = useState<CompetitorRadar | null>(null);
  const [projectId, setProjectId] = useState<number | "">("");
  const [handle, setHandle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .competitorRadar(filter)
      .then(setRadar)
      .catch((e: Error) => setError(e.message));
  }, [filter]);

  useEffect(() => {
    api
      .projects()
      .then((all) => setProjects(all.filter((p) => p.status !== "archived")))
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (projectId === "") return;
    setError(null);
    try {
      await api.addCompetitor(projectId, handle);
      setHandle("");
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function remove(id: number) {
    setError(null);
    try {
      await api.removeCompetitor(id);
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function run() {
    setError(null);
    try {
      await api.runCompetitorRadar();
      setNotice("Prüfung gestartet. Ergebnisse erscheinen in ein bis zwei Minuten.");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <>
      <PageHeader
        title="Konkurrenz-Radar"
        description="YouTube-Kanäle aus deiner Nische im Blick. Läuft ein Video weit über dem üblichen Niveau des Kanals, landet das Thema als Hinweis im Ideenlabor. Kopiert wird nichts."
      />
      {radar && !radar.live && (
        <p className="small">
          <Badge tone="info">Testbetrieb</Badge> Ohne YouTube-Schlüssel zeigt das Radar
          Beispielvideos.
        </p>
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      <ErrorText error={error} />
      <div className="toolbar">
        <label className="inline-label">
          Themenbereich
          <select
            value={filter ?? ""}
            onChange={(e) => setFilter(e.target.value ? Number(e.target.value) : undefined)}
          >
            <option value="">Alle</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        {canEdit && (
          <button type="button" className="btn" onClick={() => void run()}>
            Jetzt prüfen
          </button>
        )}
      </div>

      <Section title="Läuft gerade auffällig gut">
        {!radar || radar.standouts.length === 0 ? (
          <p className="muted small">
            Noch nichts Auffälliges. Das Radar prüft alle 12 Stunden.
          </p>
        ) : (
          <ul className="feed" aria-label="Auffällige Videos">
            {radar.standouts.map((v) => (
              <li key={v.id}>
                <div className="feed-body">
                  <div className="feed-title">
                    {v.url ? (
                      <a href={v.url} target="_blank" rel="noreferrer">
                        {v.title}
                      </a>
                    ) : (
                      v.title
                    )}
                  </div>
                  <div className="muted small">
                    {v.channel} · {num(v.views)} Aufrufe
                    {v.outlier ? ` · ${v.outlier.toFixed(1).replace(".", ",")}× üblich` : ""}
                    {v.published_at ? ` · ${formatDateTime(v.published_at)}` : ""}
                  </div>
                </div>
                <div className="row-actions">
                  {v.in_idea_lab && <Badge tone="ok">Im Ideenlabor</Badge>}
                  {v.is_mock && <Badge tone="info">Test</Badge>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Beobachtete Kanäle">
        {!radar || radar.competitors.length === 0 ? (
          <p className="muted small">Noch kein Kanal eingetragen.</p>
        ) : (
          <ul className="feed" aria-label="Beobachtete Kanäle">
            {radar.competitors.map((c) => (
              <li key={c.id}>
                <div className="feed-body">
                  <div className="feed-title">
                    <a href={c.url} target="_blank" rel="noreferrer">
                      {c.name ?? c.handle}
                    </a>{" "}
                    <span className="chip">{c.project}</span>
                  </div>
                  <div className="muted small">
                    {c.handle} · {c.videos} Videos geprüft · {c.standouts} auffällig
                    {c.last_checked_at ? ` · zuletzt ${formatDateTime(c.last_checked_at)}` : " · noch nicht geprüft"}
                  </div>
                  {c.last_error && <div className="small error">{c.last_error}</div>}
                </div>
                {canEdit && (
                  <div className="row-actions">
                    <button
                      type="button"
                      className="btn btn-ghost btn-small"
                      aria-label={`${c.handle} nicht mehr beobachten`}
                      onClick={() => void remove(c.id)}
                    >
                      Entfernen
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        {canEdit && (
          <form className="focus-form" aria-label="Kanal beobachten" onSubmit={add}>
            <label>
              Themenbereich
              <select
                value={projectId}
                onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : "")}
                required
              >
                <option value="">Bitte wählen</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              YouTube-Kanal
              <input
                value={handle}
                placeholder="@kanalname oder Link"
                maxLength={200}
                onChange={(e) => setHandle(e.target.value)}
                required
              />
            </label>
            <button type="submit" className="btn btn-ghost">
              Beobachten
            </button>
          </form>
        )}
        <p className="muted small">
          Nur YouTube: TikTok und Instagram erlauben keinen offiziellen Abruf fremder Konten.
          Eine Prüfung kostet etwa 3 von 10.000 kostenlosen YouTube-Einheiten am Tag.
        </p>
      </Section>
    </>
  );
}
