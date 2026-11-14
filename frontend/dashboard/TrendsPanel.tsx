"use client";

import { Fragment, useEffect, useState } from "react";

import { Badge, ErrorText, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import type { Game, Language, TrendItem, TrendReport } from "@/lib/types";

const SOURCE_LABELS: Record<string, string> = {
  youtube: "YouTube",
  twitch: "Twitch",
  steam: "Steam",
};

function growth(pct: number | null) {
  if (pct === null) return <span className="muted">–</span>;
  const tone = pct > 5 ? "ok" : pct < -5 ? "danger" : "neutral";
  return <Badge tone={tone}>{`${pct > 0 ? "+" : ""}${pct.toFixed(0)} %`}</Badge>;
}

function GameDetails({ id, language }: { id: number; language: Language }) {
  const [game, setGame] = useState<Game | null>(null);
  useEffect(() => {
    api
      .game(id)
      .then(setGame)
      .catch(() => setGame(null));
  }, [id]);
  const p = game?.profile;
  if (!game) return <p className="muted small">Lädt …</p>;
  if (!p?.video_ideas) return <p className="muted small">Noch kein Spielprofil.</p>;
  return (
    <div className="game-details small">
      <p>
        <strong>Zielgruppe:</strong> {language === "de" ? p.audience?.de : p.audience?.en}
        {p.modes && p.modes.length > 0 && (
          <>
            {" "}
            · <strong>Spielmodi:</strong> {p.modes.join(", ")}
          </>
        )}
      </p>
      <ul>
        {p.video_ideas.map((idea) => (
          <li key={idea.format}>
            {language === "de" ? idea.title_de : idea.title_en}{" "}
            <span className="muted">({idea.format_label})</span>
            {idea.priority === "high" && (
              <>
                {" "}
                <Badge tone="ok">Priorität</Badge>
              </>
            )}
          </li>
        ))}
      </ul>
      {p.rights_note && <p className="muted">{p.rights_note}</p>}
    </div>
  );
}

export function TrendsPanel() {
  const [language, setLanguage] = useState<Language>("de");
  const [items, setItems] = useState<TrendItem[]>([]);
  const [report, setReport] = useState<TrendReport | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.trends(language, 10), api.trendReport(language)])
      .then(([t, r]) => {
        setItems(t);
        setReport(r);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [language]);

  const mock = items.some((i) => i.is_mock);
  return (
    <Section title="Aktuelle Trends">
      <div className="trend-head">
        <div className="segmented" role="group" aria-label="Sprache">
          {(["de", "en"] as const).map((lang) => (
            <button
              key={lang}
              type="button"
              className={lang === language ? "active" : undefined}
              aria-pressed={lang === language}
              onClick={() => {
                setLanguage(lang);
                setOpen(null);
              }}
            >
              {lang === "de" ? "Deutsch" : "Englisch"}
            </button>
          ))}
        </div>
        {mock && <Badge tone="warn">Testdaten</Badge>}
        {report && <span className="muted small">Stand {formatDateTime(report.created_at)}</span>}
      </div>
      <ErrorText error={error} />
      {report && <p className="trend-summary">{report.summary}</p>}
      {items.length === 0 ? (
        <p className="muted">
          Noch keine Trends. Der Trend Research Agent läuft automatisch alle 6 Stunden oder sofort
          über die Seite „Agenten“.
        </p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Spiel</th>
                <th>Zielgruppe</th>
                <th>Score</th>
                <th>7 Tage</th>
                <th>Quellen</th>
              </tr>
            </thead>
            <tbody>
              {items.map((t, i) => (
                <Fragment key={t.game_id}>
                  <tr>
                    <td>{i + 1}</td>
                    <td>
                      <button
                        type="button"
                        className="link-btn"
                        aria-expanded={open === t.game_id}
                        onClick={() => setOpen(open === t.game_id ? null : t.game_id)}
                      >
                        {t.game}
                      </button>
                      {t.is_new && (
                        <>
                          {" "}
                          <Badge tone="ok">Neu</Badge>
                        </>
                      )}
                      {t.top_idea && <div className="muted small">Idee: {t.top_idea}</div>}
                    </td>
                    <td>{t.audience_label}</td>
                    <td>
                      <strong>{t.score.toFixed(0)}</strong>
                    </td>
                    <td>{growth(t.growth_pct)}</td>
                    <td className="small">
                      {t.sources.map((s) => SOURCE_LABELS[s] ?? s).join(", ")}
                    </td>
                  </tr>
                  {open === t.game_id && (
                    <tr>
                      <td />
                      <td colSpan={5}>
                        <GameDetails id={t.game_id} language={language} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
