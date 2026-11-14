"use client";

/**
 * Small single-series charts (no library): one hue, one axis, recessive grid,
 * hover tooltip per mark, values readable without color. Every chart sits next
 * to a table with the same numbers.
 */

export interface Point {
  label: string;
  value: number | null;
}

function nice(max: number): number {
  if (max <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(max));
  const steps = [1, 2, 2.5, 5, 10];
  return (steps.find((s) => s * pow >= max) ?? 10) * pow;
}

export function ColumnChart({
  title,
  points,
  format = (v) => v.toLocaleString("de-DE"),
}: {
  title: string;
  points: Point[];
  format?: (v: number) => string;
}) {
  const values = points.map((p) => p.value ?? 0);
  const top = nice(Math.max(0, ...values));
  const w = 320;
  const h = 120;
  const pad = { l: 36, r: 4, t: 8, b: 18 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const slot = points.length ? innerW / points.length : innerW;
  const bar = Math.max(2, Math.min(18, slot - 2));
  const y = (v: number) => pad.t + innerH - (v / top) * innerH;
  return (
    <figure className="chart" aria-label={title}>
      <figcaption>{title}</figcaption>
      {points.length === 0 ? (
        <p className="muted small">Noch keine Messwerte.</p>
      ) : (
        <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={title}>
          {[0, 0.5, 1].map((f) => (
            <g key={f}>
              <line
                x1={pad.l}
                x2={w - pad.r}
                y1={y(top * f)}
                y2={y(top * f)}
                className="chart-grid"
              />
              <text x={pad.l - 4} y={y(top * f) + 3} className="chart-axis" textAnchor="end">
                {format(top * f)}
              </text>
            </g>
          ))}
          {points.map((p, i) => {
            const v = p.value;
            const x = pad.l + i * slot + (slot - bar) / 2;
            return (
              <g key={p.label} className="chart-mark">
                {/* hit target larger than the mark */}
                <rect
                  x={pad.l + i * slot}
                  y={pad.t}
                  width={slot}
                  height={innerH}
                  fill="transparent"
                >
                  <title>{`${p.label}: ${v === null ? "keine Daten" : format(v)}`}</title>
                </rect>
                {v !== null && v > 0 && (
                  <rect
                    x={x}
                    y={y(v)}
                    width={bar}
                    height={Math.max(1, pad.t + innerH - y(v))}
                    rx={Math.min(4, bar / 2)}
                    className="chart-bar"
                    pointerEvents="none"
                  />
                )}
              </g>
            );
          })}
          <text x={pad.l} y={h - 4} className="chart-axis">
            {points[0]?.label}
          </text>
          {points.length > 1 && (
            <text x={w - pad.r} y={h - 4} className="chart-axis" textAnchor="end">
              {points[points.length - 1]?.label}
            </text>
          )}
        </svg>
      )}
    </figure>
  );
}

export function BarList({
  title,
  rows,
  format = (v) => v.toLocaleString("de-DE"),
}: {
  title: string;
  rows: { label: string; value: number; note?: string }[];
  format?: (v: number) => string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <figure className="chart" aria-label={title}>
      <figcaption>{title}</figcaption>
      {rows.length === 0 ? (
        <p className="muted small">Noch keine Messwerte.</p>
      ) : (
        <ul className="barlist">
          {rows.map((r) => (
            <li
              key={r.label}
              title={`${r.label}: ${format(r.value)}${r.note ? ` · ${r.note}` : ""}`}
            >
              <span className="barlist-label">{r.label}</span>
              <span className="barlist-track">
                <span className="barlist-bar" style={{ width: `${(r.value / max) * 100}%` }} />
              </span>
              <span className="barlist-value">{format(r.value)}</span>
            </li>
          ))}
        </ul>
      )}
    </figure>
  );
}
