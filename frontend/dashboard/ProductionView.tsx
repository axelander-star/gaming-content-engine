"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section, StatCard } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import { FORMAT_LABELS, HOOK_LABELS } from "@/lib/creative";
import { hasRole } from "@/lib/roles";
import type {
  Clip,
  Game,
  License,
  LicenseStatus,
  RenderCapacity,
  VariantBrief,
  VideoStatus,
} from "@/lib/types";

type Tone = "neutral" | "ok" | "warn" | "danger";

const VARIANT_STATUS: Partial<Record<VideoStatus, [string, Tone]>> = {
  SCENE_SELECTED: ["Wartet auf Rendering", "warn"],
  EDITING: ["Gerendert, Konzept folgt", "ok"],
  LOCALIZATION: ["Skript fertig, Lokalisierung folgt", "ok"],
  VOICEOVER: ["Lokalisiert, Stimme folgt", "ok"],
  SUBTITLES: ["Stimme fertig, Untertitel folgen", "ok"],
  QUALITY_CHECK: ["Fertig, Qualitätsprüfung läuft", "ok"],
  QUALITY_APPROVED: ["Qualität geprüft", "ok"],
  QUALITY_REJECTED: ["Von Qualitätsprüfung abgelehnt", "danger"],
  READY_TO_PUBLISH: ["Bereit zur Veröffentlichung", "ok"],
  FAILED: ["Fehler", "danger"],
};
const LICENSE_LABELS: Record<LicenseStatus, string> = {
  pending: "offen",
  approved: "freigegeben",
  rejected: "abgelehnt",
  expired: "abgelaufen",
  revoked: "widerrufen",
};
const SCORE_LABELS: Record<string, string> = {
  motion: "Bewegung",
  audio: "Lautstärke",
  surprise: "Überraschung",
  cuts: "Schnitte",
  buildup: "Spannungsaufbau",
};
const TAG_LABELS: Record<string, string> = {
  action: "Action",
  ueberraschung: "Überraschung",
  spannung: "Spannung",
  ruhig: "Ruhig",
};
const LAYOUT_LABELS: Record<string, string> = {
  crop: "Ausschnitt um die Action",
  blur_fit: "Ganzes Bild, unscharfer Hintergrund",
};

function seconds(value: number | null, digits = 1): string {
  return value === null ? "–" : `${value.toFixed(digits)} s`;
}

function megabytes(bytes: number | null): string {
  return bytes === null ? "–" : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function ProductionView() {
  const { user } = useAuth();
  const operator = hasRole(user?.role, "operator");
  const [clips, setClips] = useState<Clip[]>([]);
  const [capacity, setCapacity] = useState<RenderCapacity | null>(null);
  const [licenses, setLicenses] = useState<License[]>([]);
  const [games, setGames] = useState<Game[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const [c, cap, l, g] = await Promise.all([
      api.productionClips(),
      api.renderCapacity(),
      api.licenses(),
      api.games(),
    ]);
    setClips(c);
    setCapacity(cap);
    setLicenses(l);
    setGames(g);
  }, []);

  useEffect(() => {
    reload().catch((e: Error) => setError(e.message));
  }, [reload]);

  return (
    <>
      <PageHeader
        title="Videoproduktion"
        description="Szenen aus freigegebenem Material, gerenderte Hochformat-Clips und Renderkapazität."
      />
      <ErrorText error={error} />
      {capacity && <CapacityCards capacity={capacity} />}
      {operator && <UploadSection licenses={licenses} games={games} onDone={reload} />}
      <ClipSection clips={clips} />
    </>
  );
}

function CapacityCards({ capacity }: { capacity: RenderCapacity }) {
  return (
    <div className="grid stats" aria-label="Renderkapazität">
      <StatCard
        label="Clips gerendert (7 Tage)"
        value={capacity.clips_rendered_7d}
        hint={`${capacity.clip_seconds_7d} s Video in ${capacity.render_seconds_7d} s Rechenzeit`}
      />
      <StatCard
        label="Echtzeitfaktor"
        value={capacity.realtime_factor === null ? "–" : `${capacity.realtime_factor}×`}
        hint="Videosekunden pro Rechensekunde"
      />
      <StatCard
        label="Clips pro Stunde"
        value={capacity.clips_per_hour ?? "–"}
        hint={`gemessen, bei ${capacity.parallel_slots} parallelen Renderjobs`}
      />
      <StatCard
        label="Warten auf Rendering"
        value={capacity.waiting_for_render}
        hint="Varianten im Status Szene gewählt"
      />
    </div>
  );
}

function UploadSection({
  licenses,
  games,
  onDone,
}: {
  licenses: License[];
  games: Game[];
  onDone: () => Promise<void>;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [licenseId, setLicenseId] = useState("");
  const [gameId, setGameId] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    const lic = licenses.find((l) => l.id === Number(licenseId));
    if (!file || !lic) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const material = await api.uploadMaterial(file, {
        source_id: lic.source_id,
        license_id: lic.id,
        game_id: gameId ? Number(gameId) : null,
        title: title || undefined,
      });
      setMessage(
        `Material #${material.id} hochgeladen (${seconds(material.duration_s)}). ` +
          "Rechteprüfung, Szenenanalyse und Rendering laufen automatisch.",
      );
      setTitle("");
      if (fileRef.current) fileRef.current.value = "";
      await onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Gameplay hochladen">
      <p className="muted">
        MP4, MOV oder MKV mit mindestens 720p. Die Datei wird technisch geprüft, bevor sie
        gespeichert wird. Ohne freigegebene Lizenz und Spielzuordnung wird nichts geschnitten.
      </p>
      <form className="inline-form" onSubmit={submit} aria-label="Gameplay hochladen">
        <input
          ref={fileRef}
          type="file"
          aria-label="Videodatei"
          accept="video/mp4,video/quicktime,video/x-matroska,.mkv"
          required
        />
        <select
          aria-label="Lizenz"
          required
          value={licenseId}
          onChange={(e) => setLicenseId(e.target.value)}
        >
          <option value="">Lizenz wählen …</option>
          {licenses.map((l) => (
            <option key={l.id} value={l.id}>
              #{l.id} · {LICENSE_LABELS[l.status]}
            </option>
          ))}
        </select>
        <select
          aria-label="Spiel"
          required
          value={gameId}
          onChange={(e) => setGameId(e.target.value)}
        >
          <option value="">Spiel wählen …</option>
          {games.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
        <input placeholder="Titel" value={title} onChange={(e) => setTitle(e.target.value)} />
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Wird hochgeladen …" : "Hochladen"}
        </button>
      </form>
      {message && (
        <p className="muted" role="status">
          {message}
        </p>
      )}
      <ErrorText error={error} />
    </Section>
  );
}

function ClipSection({ clips }: { clips: Clip[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (clips.length === 0) {
    return (
      <Section title="Clips">
        <p className="muted">
          Noch keine Clips. Sie entstehen automatisch, sobald freigegebenes Material analysiert
          wurde.
        </p>
      </Section>
    );
  }
  return (
    <Section title="Clips">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Material</th>
              <th>Szene</th>
              <th>Bewertung</th>
              <th>Technik</th>
              <th>Rendering</th>
              <th>Varianten</th>
            </tr>
          </thead>
          <tbody>
            {clips.map((c) => (
              <Fragment key={c.id}>
                <tr>
                  <td>
                    <button
                      type="button"
                      className="link-btn"
                      aria-expanded={open === c.id}
                      onClick={() => setOpen(open === c.id ? null : c.id)}
                    >
                      Clip {c.id}
                    </button>
                  </td>
                  <td>
                    {c.material_title ?? `Material #${c.material_id}`}
                    <div className="muted">
                      #{c.material_id} · {c.game ?? "ohne Spiel"}
                    </div>
                  </td>
                  <td>
                    {c.start_s.toFixed(1)}–{c.end_s.toFixed(1)} s
                    <div className="muted">Rang {c.scene.rank ?? "–"}</div>
                  </td>
                  <td>
                    {c.scene.score?.toFixed(2) ?? "–"}{" "}
                    {c.scene.tags.map((t) => (
                      <Badge key={t}>{TAG_LABELS[t] ?? t}</Badge>
                    ))}
                  </td>
                  <td>
                    {c.rendered ? (
                      <>
                        {c.width}×{c.height}, {c.fps} fps
                        <div className="muted">
                          {seconds(c.duration_s)} · {megabytes(c.size_bytes)}
                        </div>
                      </>
                    ) : (
                      <span className="muted">noch nicht gerendert</span>
                    )}
                  </td>
                  <td>
                    {c.rendered ? (
                      <>
                        {seconds(c.render_seconds)}
                        <div className="muted">
                          {c.realtime_factor === null ? "" : `${c.realtime_factor}× Echtzeit`}
                        </div>
                      </>
                    ) : (
                      "–"
                    )}
                  </td>
                  <td>
                    {c.variants.map((v) => {
                      const [label, tone] = VARIANT_STATUS[v.status] ?? [v.status, "neutral"];
                      return (
                        <div key={v.id}>
                          {v.language.toUpperCase()} {v.label}: <Badge tone={tone}>{label}</Badge>
                          {v.video_format && (
                            <div className="muted">
                              {FORMAT_LABELS[v.video_format] ?? v.video_format} ·{" "}
                              {HOOK_LABELS[v.hook_type ?? ""] ?? v.hook_type}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </td>
                </tr>
                {open === c.id && (
                  <tr className="detail-row">
                    <td colSpan={7}>
                      <ClipDetails clip={c} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function ClipDetails({ clip }: { clip: Clip }) {
  return (
    <div className="grid two">
      <div>
        <h3>Szenenbewertung</h3>
        <ul className="plain-list">
          {Object.entries(clip.scene.scores).map(([key, value]) => (
            <li key={key}>
              {SCORE_LABELS[key] ?? key}: {value.toFixed(2)}
            </li>
          ))}
        </ul>
        <p className="muted">
          Bildaufbau: {clip.layout ? (LAYOUT_LABELS[clip.layout] ?? clip.layout) : "–"}. Codec:{" "}
          {clip.video_codec ?? "–"} / {clip.audio_codec ?? "–"}. Gerendert:{" "}
          {formatDateTime(clip.rendered_at)}.
        </p>
        {clip.variants
          .filter((v) => v.error_message)
          .map((v) => (
            <p key={v.id} className="error">
              {v.language.toUpperCase()}: {v.error_message}
            </p>
          ))}
      </div>
      <div>
        {clip.variants.some((v) => v.script || v.video_format) && (
          <>
            <h3>Konzepte und Skripte</h3>
            {clip.variants.map((v) => (
              <VariantScriptCard key={v.id} variant={v} />
            ))}
          </>
        )}
        {clip.rendered ? (
          <video
            className="clip-preview"
            controls
            preload="metadata"
            src={api.clipFileUrl(clip.id)}
            aria-label={`Vorschau Clip ${clip.id}`}
          />
        ) : (
          <p className="muted">Vorschau erscheint nach dem Rendering.</p>
        )}
      </div>
    </div>
  );
}

const BEAT_LABELS: Record<string, string> = {
  hook: "Hook",
  setup: "Einstieg",
  buildup: "Spannung",
  payoff: "Auflösung",
  cta: "Aufruf",
};

const CHECK_LABELS: Record<string, string> = {
  file: "Datei",
  integrity: "Unverändert",
  decode: "Dekodierbar",
  format: "Format",
  platform: "Plattformgrenzen",
  rights: "Rechte",
  voice: "Stimmrechte",
  voice_overflow: "Sprechtext-Länge",
  subtitles: "Untertitel",
  subtitle_issue: "Lesbarkeit",
  language: "Sprache",
  loudness: "Lautheit",
  true_peak: "Spitzenpegel",
  silent: "Ton",
  black: "Schwarzbild",
  frozen: "Standbild",
  measure: "Messung",
  duplicate_exact: "Identische Datei",
  duplicate_visual: "Ähnliches Video",
  duplicate_scene: "Gleiche Szene",
  ab_test: "A/B-Test",
};

function QualityBox({ variant: v }: { variant: VariantBrief }) {
  const q = v.quality;
  if (!q) return null;
  const failed = q.checks.filter((c) => !c.passed);
  return (
    <div
      className="quality-box"
      aria-label={`Qualitätsprüfung ${v.language.toUpperCase()} ${v.label}`}
    >
      <p>
        <Badge tone={q.passed ? "ok" : "danger"}>{q.passed ? "Freigegeben" : "Abgelehnt"}</Badge>{" "}
        Qualitätswert <strong>{q.score?.toFixed(2) ?? "–"}</strong>
        {q.min_score !== null && <span className="muted"> (Minimum {q.min_score.toFixed(2)})</span>}
        {" · "}
        {q.checks.length - failed.length} von {q.checks.length} Prüfungen bestanden
      </p>
      {q.reasons.length > 0 && (
        <ul className="quality-reasons" aria-label={q.passed ? "Hinweise" : "Gründe"}>
          {q.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      <p className="muted">
        {q.measured.lufs !== undefined && `Lautheit ${q.measured.lufs.toFixed(1)} LUFS · `}
        {q.measured.true_peak !== undefined && `Spitze ${q.measured.true_peak.toFixed(1)} dBTP · `}
        {q.checks
          .filter((c) => c.passed && c.name !== "ab_test")
          .map((c) => CHECK_LABELS[c.name] ?? c.name)
          .join(", ")}{" "}
        ✓
      </p>
      {q.checks
        .filter((c) => c.name === "ab_test")
        .map((c) => (
          <p key={c.name} className="muted">
            {c.detail}
          </p>
        ))}
    </div>
  );
}

function VariantScriptCard({ variant: v }: { variant: VariantBrief }) {
  if (!v.video_format) return null;
  const script = v.script;
  return (
    <div className="script-card" aria-label={`Skript ${v.language.toUpperCase()} ${v.label}`}>
      <div>
        <strong>
          {v.language.toUpperCase()} {v.label}
        </strong>{" "}
        {FORMAT_LABELS[v.video_format] ?? v.video_format} ·{" "}
        {HOOK_LABELS[v.hook_type ?? ""] ?? v.hook_type}{" "}
        {v.concept.experiment ? (
          <Badge tone="warn">Test</Badge>
        ) : (
          <Badge tone="ok">Hauptvariante</Badge>
        )}
      </div>
      {script ? (
        <>
          <p>
            <strong>{script.title}</strong>
          </p>
          <ol className="plain-list">
            {script.beats.map((b) => (
              <li key={`${b.kind}-${b.start_s}`}>
                <span className="muted">
                  {b.start_s.toFixed(1)}–{b.end_s.toFixed(1)} s · {BEAT_LABELS[b.kind] ?? b.kind}:
                </span>{" "}
                {b.text}
              </li>
            ))}
          </ol>
          {v.voice && (
            <p className="muted">
              Stimme: {v.voice.provider === "mock" ? "Test-Stimme (still)" : v.voice.provider} ·
              Tempo bis {v.voice.max_tempo}×
              {v.voice.overflow.length > 0 && ` · zu lang: ${v.voice.overflow.join(", ")}`}
            </p>
          )}
          {v.subtitle_formats.length > 0 && (
            <p className="muted">
              Untertitel eingebrannt · <a href={api.variantSubtitlesUrl(v.id, "srt")}>SRT</a> ·{" "}
              <a href={api.variantSubtitlesUrl(v.id, "vtt")}>VTT</a>
              {v.subtitle_issues.length > 0 && ` · Hinweise: ${v.subtitle_issues.join("; ")}`}
            </p>
          )}
          {v.quality && <QualityBox variant={v} />}
          {v.final_video && (
            <video
              className="clip-preview"
              controls
              preload="metadata"
              src={api.variantFileUrl(v.id)}
              aria-label={`Fertiges Video ${v.language.toUpperCase()} ${v.label}`}
            />
          )}
          <p className="muted">
            Version {script.version} ·{" "}
            {script.source.startsWith("template") ? "Vorlage (kostenlos)" : script.source}
            {script.source.endsWith("+localized") && " · lokalisiert"}
          </p>
        </>
      ) : (
        <p className="muted">Skript folgt.</p>
      )}
    </div>
  );
}
