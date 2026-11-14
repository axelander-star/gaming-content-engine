"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import type { Language, TrendHistoryPoint } from "@/lib/types";

const METRIC_LABELS: Record<string, string> = {
  video_views: "YouTube-Aufrufe",
  live_viewers: "Twitch-Zuschauer",
  players: "Steam-Spieler",
};

const W = 520;
const H = 140;
const PAD = { top: 10, right: 12, bottom: 22, left: 30 };
const number = new Intl.NumberFormat("de-DE");

/** Trend score of one game over the last 30 days (one point per trend run). */
export function TrendHistory({ gameId, language }: { gameId: number; language: Language }) {
  const [points, setPoints] = useState<TrendHistoryPoint[] | null>(null);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    api
      .gameHistory(gameId, language)
      .then(setPoints)
      .catch(() => setPoints([]));
  }, [gameId, language]);

  if (points === null) return null;
  if (points.length < 2) {
    return <p className="muted small">Verlauf erscheint ab dem zweiten Trendlauf.</p>;
  }

  const times = points.map((p) => new Date(p.detected_at).getTime());
  const at = (i: number): number => times[i] ?? 0;
  const t0 = at(0);
  const span = Math.max(1, at(times.length - 1) - t0);
  const x = (t: number) => PAD.left + ((t - t0) / span) * (W - PAD.left - PAD.right);
  const y = (score: number) => PAD.top + (1 - score / 100) * (H - PAD.top - PAD.bottom);
  const path = points
    .map((p, i) => `${i ? "L" : "M"}${x(at(i)).toFixed(1)},${y(p.score).toFixed(1)}`)
    .join("");
  const tick = (t: number) =>
    span < 2 * 86_400_000
      ? formatDateTime(new Date(t).toISOString())
      : new Date(t).toLocaleDateString("de-DE");
  const active = hover !== null ? points[hover] : null;

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    let best = 0;
    times.forEach((t, i) => {
      if (Math.abs(x(t) - px) < Math.abs(x(at(best)) - px)) best = i;
    });
    setHover(best);
  }

  return (
    <figure className="trend-history">
      <figcaption className="small">
        <strong>Trend-Score, letzte 30 Tage</strong>
        {points.some((p) => p.is_mock) && <span className="muted"> · Testdaten</span>}
      </figcaption>
      <div className="chart-box">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`Trend-Score von ${(points[0]?.score ?? 0).toFixed(0)} auf ${(points[points.length - 1]?.score ?? 0).toFixed(0)}`}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        >
          {[0, 50, 100].map((v) => (
            <g key={v}>
              <line className="grid" x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} />
              <text className="axis" x={PAD.left - 6} y={y(v) + 4} textAnchor="end">
                {v}
              </text>
            </g>
          ))}
          <text className="axis" x={PAD.left} y={H - 4}>
            {tick(t0)}
          </text>
          <text className="axis" x={W - PAD.right} y={H - 4} textAnchor="end">
            {tick(at(times.length - 1))}
          </text>
          <path className="series" d={path} />
          {active && hover !== null && (
            <>
              <line
                className="crosshair"
                x1={x(at(hover))}
                x2={x(at(hover))}
                y1={PAD.top}
                y2={H - PAD.bottom}
              />
              <circle className="marker" cx={x(at(hover))} cy={y(active.score)} r={4.5} />
            </>
          )}
          <rect x={0} y={0} width={W} height={H} fill="transparent" />
        </svg>
        {active && hover !== null && (
          <div
            className="chart-tooltip small"
            style={{ left: `${(x(at(hover)) / W) * 100}%` }}
            role="status"
          >
            <div className="muted">{formatDateTime(active.detected_at)}</div>
            <div>
              Score <strong>{active.score.toFixed(0)}</strong>
            </div>
            {Object.entries(active.metrics).map(([k, v]) => (
              <div key={k}>
                {METRIC_LABELS[k] ?? k}: {number.format(v)}
                {active.growth_pct[k] !== undefined && (
                  <span className="muted">
                    {" "}
                    ({active.growth_pct[k] > 0 ? "+" : ""}
                    {active.growth_pct[k].toFixed(0)} %)
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      <details className="small">
        <summary>Werte als Tabelle</summary>
        <table>
          <thead>
            <tr>
              <th>Zeitpunkt</th>
              <th>Score</th>
              {Object.keys(METRIC_LABELS).map((k) => (
                <th key={k}>{METRIC_LABELS[k]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.detected_at}>
                <td>{formatDateTime(p.detected_at)}</td>
                <td>{p.score.toFixed(0)}</td>
                {Object.keys(METRIC_LABELS).map((k) => (
                  <td key={k}>{p.metrics[k] !== undefined ? number.format(p.metrics[k]) : "–"}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
