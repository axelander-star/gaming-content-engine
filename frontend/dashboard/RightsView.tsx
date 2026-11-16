"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { PLATFORM_LABELS, formatDateTime } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type {
  CheckOutcome,
  Creator,
  Game,
  License,
  LicenseDocument,
  LicenseStatus,
  LicenseTerms,
  Material,
  MaterialStatus,
  PlatformCode,
  PolicyStatus,
  PublisherPolicy,
  Source,
  SourceType,
} from "@/lib/types";

type Tone = "neutral" | "ok" | "warn" | "danger";

const MATERIAL_STATUS: Record<MaterialStatus, [string, Tone]> = {
  DISCOVERED: ["Neu erfasst", "neutral"],
  RIGHTS_PENDING: ["Rechteprüfung", "warn"],
  RIGHTS_APPROVED: ["Freigegeben", "ok"],
  RIGHTS_REJECTED: ["Abgelehnt", "danger"],
  ANALYZED: ["Analysiert", "ok"],
  FAILED: ["Fehler", "danger"],
};
const LICENSE_STATUS: Record<LicenseStatus, [string, Tone]> = {
  pending: ["Offen", "warn"],
  approved: ["Freigegeben", "ok"],
  rejected: ["Abgelehnt", "danger"],
  expired: ["Abgelaufen", "danger"],
  revoked: ["Widerrufen", "danger"],
};
const POLICY_STATUS: Record<PolicyStatus, [string, Tone]> = {
  permitted: ["Erlaubt", "ok"],
  license_required: ["Nur mit Erlaubnis", "warn"],
  forbidden: ["Untersagt", "danger"],
};
const OUTCOME: Record<CheckOutcome, [string, Tone]> = {
  ok: ["erfüllt", "ok"],
  missing: ["Nachweis fehlt", "warn"],
  denied: ["nicht erlaubt", "danger"],
};
const SOURCE_TYPES: Record<SourceType, string> = {
  own_upload: "Eigener Upload",
  licensed_creator: "Lizenzierter Creator",
  partner: "Partner",
  contract: "Vertrag",
  other_licensed: "Sonstige Lizenz",
  campaign: "Clipping-Kampagne",
};
const PERMISSIONS: [keyof LicenseTerms, string][] = [
  ["allows_commercial_use", "Kommerziell"],
  ["allows_editing", "Bearbeitung"],
  ["allows_short_form", "Kurzvideos"],
  ["allows_monetization", "Monetarisierung"],
  ["music_cleared", "Musik freigegeben"],
  ["publisher_permission", "Erlaubnis Rechteinhaber"],
];
const PLATFORMS = Object.keys(PLATFORM_LABELS) as PlatformCode[];

const status = <K extends string>(map: Record<K, [string, Tone]>, key: K) => (
  <Badge tone={map[key][1]}>{map[key][0]}</Badge>
);

/** Runs an action, shows its error and reloads the page data afterwards. */
function useAction(reload: () => Promise<void>, setError: (e: string | null) => void) {
  return useCallback(
    async (fn: () => Promise<unknown>) => {
      setError(null);
      try {
        await fn();
        await reload();
      } catch (err) {
        setError((err as Error).message);
      }
    },
    [reload, setError],
  );
}

export function RightsView() {
  const { user } = useAuth();
  const operator = hasRole(user?.role, "operator");
  const admin = hasRole(user?.role, "admin");
  const [materials, setMaterials] = useState<Material[]>([]);
  const [licenses, setLicenses] = useState<License[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [creators, setCreators] = useState<Creator[]>([]);
  const [policies, setPolicies] = useState<PublisherPolicy[]>([]);
  const [games, setGames] = useState<Game[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const [m, l, s, c, p, g] = await Promise.all([
      api.materials(),
      api.licenses(),
      api.sources(),
      api.creators(),
      api.policies(),
      api.games(),
    ]);
    setMaterials(m);
    setLicenses(l);
    setSources(s);
    setCreators(c);
    setPolicies(p);
    setGames(g);
  }, []);

  useEffect(() => {
    reload().catch((e: Error) => setError(e.message));
  }, [reload]);

  const act = useAction(reload, setError);
  const sourceName = (id: number) => sources.find((s) => s.id === id)?.name ?? `#${id}`;

  return (
    <>
      <PageHeader
        title="Rechte und Lizenzen"
        description="Nur Material mit vollständig nachgewiesenen Rechten wird verarbeitet (deny by default)."
      />
      <ErrorText error={error} />
      <MaterialSection
        materials={materials}
        licenses={licenses}
        games={games}
        sourceName={sourceName}
        canEdit={operator}
        act={act}
      />
      <LicenseSection
        licenses={licenses}
        sources={sources}
        sourceName={sourceName}
        operator={operator}
        admin={admin}
        act={act}
      />
      <SourceSection
        sources={sources}
        creators={creators}
        operator={operator}
        admin={admin}
        act={act}
      />
      <PolicySection
        policies={policies}
        games={games}
        admin={admin}
        operator={operator}
        act={act}
      />
    </>
  );
}

type Act = (fn: () => Promise<unknown>) => Promise<void>;

// --- material -----------------------------------------------------------------

function MaterialSection({
  materials,
  licenses,
  games,
  sourceName,
  canEdit,
  act,
}: {
  materials: Material[];
  licenses: License[];
  games: Game[];
  sourceName: (id: number) => string;
  canEdit: boolean;
  act: Act;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const [licenseId, setLicenseId] = useState("");
  const [gameId, setGameId] = useState("");
  const [title, setTitle] = useState("");
  const [uri, setUri] = useState("");
  const [sha, setSha] = useState("");

  function register(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const lic = licenses.find((l) => l.id === Number(licenseId));
    if (!lic) return;
    void act(async () => {
      await api.registerMaterial({
        source_id: lic.source_id,
        license_id: lic.id,
        game_id: gameId ? Number(gameId) : null,
        title: title || undefined,
        storage_uri: uri,
        sha256: sha.trim().toLowerCase(),
      });
      setTitle("");
      setUri("");
      setSha("");
    });
  }

  return (
    <Section title="Material">
      {materials.length === 0 ? (
        <p className="muted">Noch kein Material registriert.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Titel</th>
                <th>Spiel</th>
                <th>Quelle</th>
                <th>Lizenz</th>
                <th>Status</th>
                <th>Letzte Prüfung</th>
              </tr>
            </thead>
            <tbody>
              {materials.map((m) => (
                <Fragment key={m.id}>
                  <tr>
                    <td>{m.id}</td>
                    <td>
                      <button
                        type="button"
                        className="link-btn"
                        aria-expanded={open === m.id}
                        onClick={() => setOpen(open === m.id ? null : m.id)}
                      >
                        {m.title ?? m.storage_uri}
                      </button>
                    </td>
                    <td>{m.game ?? <span className="muted">nicht zugeordnet</span>}</td>
                    <td>{m.source}</td>
                    <td>#{m.license_id}</td>
                    <td>{status(MATERIAL_STATUS, m.status)}</td>
                    <td className="small">
                      {m.last_check ? formatDateTime(m.last_check.checked_at) : "–"}
                    </td>
                  </tr>
                  {open === m.id && (
                    <tr>
                      <td />
                      <td colSpan={6}>
                        <CheckTable material={m} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canEdit && (
        <form className="inline-form" onSubmit={register} aria-label="Material registrieren">
          <select
            aria-label="Lizenz"
            required
            value={licenseId}
            onChange={(e) => setLicenseId(e.target.value)}
          >
            <option value="">Lizenz wählen …</option>
            {licenses.map((l) => (
              <option key={l.id} value={l.id}>
                #{l.id} · {sourceName(l.source_id)}
              </option>
            ))}
          </select>
          <select aria-label="Spiel" value={gameId} onChange={(e) => setGameId(e.target.value)}>
            <option value="">Spiel (optional)</option>
            {games.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
          <input placeholder="Titel" value={title} onChange={(e) => setTitle(e.target.value)} />
          <input
            placeholder="Speicherort (z. B. r2://…)"
            required
            value={uri}
            onChange={(e) => setUri(e.target.value)}
          />
          <input
            placeholder="SHA-256 der Datei"
            required
            pattern="[0-9a-fA-F]{64}"
            value={sha}
            onChange={(e) => setSha(e.target.value)}
          />
          <button className="btn btn-primary" type="submit">
            Material registrieren
          </button>
        </form>
      )}
    </Section>
  );
}

function CheckTable({ material }: { material: Material }) {
  const check = material.last_check;
  if (!check) {
    return (
      <p className="muted small">
        Noch nicht geprüft. Material Scout und Rights &amp; License Agent übernehmen das
        automatisch.
      </p>
    );
  }
  return (
    <table className="small" aria-label={`Rechteprüfung Material ${material.id}`}>
      <tbody>
        {check.checks.map((c) => (
          <tr key={c.key}>
            <td>{c.label}</td>
            <td>{status(OUTCOME, c.outcome)}</td>
            <td className="muted">{c.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// --- licenses -----------------------------------------------------------------

function LicenseSection({
  licenses,
  sources,
  sourceName,
  operator,
  admin,
  act,
}: {
  licenses: License[];
  sources: Source[];
  sourceName: (id: number) => string;
  operator: boolean;
  admin: boolean;
  act: Act;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const [sourceId, setSourceId] = useState("");

  function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    void act(async () => {
      const lic = await api.createLicense({ source_id: Number(sourceId) });
      setOpen(lic.id);
    });
  }

  return (
    <Section title="Lizenzen">
      {licenses.length === 0 ? (
        <p className="muted">Noch keine Lizenzen.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Quelle</th>
                <th>Status</th>
                <th>Gültig bis</th>
                <th>Rechte</th>
                <th>Dokumente</th>
              </tr>
            </thead>
            <tbody>
              {licenses.map((l) => (
                <Fragment key={l.id}>
                  <tr>
                    <td>
                      <button
                        type="button"
                        className="link-btn"
                        aria-expanded={open === l.id}
                        onClick={() => setOpen(open === l.id ? null : l.id)}
                      >
                        Lizenz #{l.id}
                      </button>
                    </td>
                    <td>{sourceName(l.source_id)}</td>
                    <td>{status(LICENSE_STATUS, l.status)}</td>
                    <td>{l.valid_until ?? "unbefristet"}</td>
                    <td className="small">
                      {PERMISSIONS.filter(([k]) => l[k])
                        .map(([, label]) => label)
                        .join(", ") || "keine"}
                    </td>
                    <td>{l.documents}</td>
                  </tr>
                  {open === l.id && (
                    <tr>
                      <td />
                      <td colSpan={5}>
                        <LicenseEditor license={l} operator={operator} admin={admin} act={act} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {operator && (
        <form className="inline-form" onSubmit={create} aria-label="Lizenz anlegen">
          <select
            aria-label="Quelle der Lizenz"
            required
            value={sourceId}
            onChange={(e) => setSourceId(e.target.value)}
          >
            <option value="">Quelle wählen …</option>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <button className="btn btn-primary" type="submit">
            Lizenz anlegen
          </button>
        </form>
      )}
    </Section>
  );
}

function termsOf(l: License): LicenseTerms {
  return {
    valid_from: l.valid_from,
    valid_until: l.valid_until,
    allows_commercial_use: l.allows_commercial_use,
    allows_editing: l.allows_editing,
    allows_short_form: l.allows_short_form,
    allows_monetization: l.allows_monetization,
    music_cleared: l.music_cleared,
    allowed_platforms: l.allowed_platforms,
    allowed_languages: l.allowed_languages,
    restrictions: l.restrictions,
    publisher_permission: l.publisher_permission,
  };
}

function toggle(list: string[], value: string, on: boolean): string[] {
  return on ? [...new Set([...list, value])] : list.filter((v) => v !== value);
}

function Check({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled: boolean;
}) {
  return (
    <label className="check">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />{" "}
      {label}
    </label>
  );
}

function LicenseEditor({
  license,
  operator,
  admin,
  act,
}: {
  license: License;
  operator: boolean;
  admin: boolean;
  act: Act;
}) {
  const [terms, setTerms] = useState<LicenseTerms>(termsOf(license));
  const [docs, setDocs] = useState<LicenseDocument[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const set = (patch: Partial<LicenseTerms>) => setTerms((t) => ({ ...t, ...patch }));

  useEffect(() => {
    setTerms(termsOf(license));
    api
      .licenseDocuments(license.id)
      .then(setDocs)
      .catch(() => setDocs([]));
  }, [license]);

  const ro = !operator;
  return (
    <div className="license-editor small">
      {license.status === "approved" && operator && (
        <p className="muted">
          Änderungen an einer freigegebenen Lizenz setzen sie auf „Offen“ zurück; betroffenes
          Material wird neu geprüft.
        </p>
      )}
      <div className="form-grid">
        <label>
          Gültig ab
          <input
            type="date"
            disabled={ro}
            value={terms.valid_from ?? ""}
            onChange={(e) => set({ valid_from: e.target.value || null })}
          />
        </label>
        <label>
          Gültig bis
          <input
            type="date"
            disabled={ro}
            value={terms.valid_until ?? ""}
            onChange={(e) => set({ valid_until: e.target.value || null })}
          />
        </label>
      </div>
      <fieldset>
        <legend>Rechte</legend>
        {PERMISSIONS.map(([key, label]) => (
          <Check
            key={key}
            label={label}
            disabled={ro}
            checked={Boolean(terms[key])}
            onChange={(v) => set({ [key]: v })}
          />
        ))}
      </fieldset>
      <fieldset>
        <legend>Plattformen</legend>
        {PLATFORMS.map((p) => (
          <Check
            key={p}
            label={PLATFORM_LABELS[p]}
            disabled={ro}
            checked={terms.allowed_platforms.includes(p)}
            onChange={(v) => set({ allowed_platforms: toggle(terms.allowed_platforms, p, v) })}
          />
        ))}
      </fieldset>
      <fieldset>
        <legend>Sprachfassungen</legend>
        {(["de", "en"] as const).map((lang) => (
          <Check
            key={lang}
            label={lang === "de" ? "Deutsch" : "Englisch"}
            disabled={ro}
            checked={terms.allowed_languages.includes(lang)}
            onChange={(v) => set({ allowed_languages: toggle(terms.allowed_languages, lang, v) })}
          />
        ))}
      </fieldset>
      <label>
        Einschränkungen
        <textarea
          rows={2}
          disabled={ro}
          value={terms.restrictions ?? ""}
          onChange={(e) => set({ restrictions: e.target.value || null })}
        />
      </label>
      {operator && (
        <div className="form-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void act(() => api.updateLicense(license.id, terms))}
          >
            Bedingungen speichern
          </button>
        </div>
      )}

      <h3>Lizenznachweise</h3>
      {docs.length === 0 ? (
        <p className="muted">Kein Dokument hochgeladen. Ohne Nachweis keine Freigabe.</p>
      ) : (
        <ul>
          {docs.map((d) => (
            <li key={d.id}>
              <a href={api.documentUrl(license.id, d.id)} target="_blank" rel="noreferrer">
                Version {d.version}: {d.filename}
              </a>{" "}
              <span className="muted">
                ({Math.ceil(d.size_bytes / 1024)} KB, {formatDateTime(d.uploaded_at)}, SHA-256{" "}
                <span className="mono">{d.sha256.slice(0, 12)}…</span>)
              </span>
            </li>
          ))}
        </ul>
      )}
      {operator && (
        <div className="inline-form">
          <input
            type="file"
            aria-label="Lizenzdokument"
            accept="application/pdf,image/png,image/jpeg"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            className="btn"
            disabled={!file}
            onClick={() =>
              file &&
              void act(async () => {
                await api.uploadLicenseDocument(license.id, file);
                setFile(null);
              })
            }
          >
            Dokument hochladen
          </button>
        </div>
      )}

      <div className="form-actions">
        {admin && (license.status === "pending" || license.status === "rejected") && (
          <>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void act(() => api.setLicenseStatus(license.id, "approve"))}
            >
              Lizenz freigeben
            </button>
            {license.status === "pending" && (
              <button
                type="button"
                className="btn"
                onClick={() => void act(() => api.setLicenseStatus(license.id, "reject"))}
              >
                Ablehnen
              </button>
            )}
          </>
        )}
        {operator && license.status === "approved" && (
          <button
            type="button"
            className="btn"
            onClick={() => void act(() => api.setLicenseStatus(license.id, "revoke"))}
          >
            Widerrufen
          </button>
        )}
        {license.verified_at && (
          <span className="muted">Geprüft am {formatDateTime(license.verified_at)}</span>
        )}
      </div>
    </div>
  );
}

// --- sources and creators -----------------------------------------------------

function SourceSection({
  sources,
  creators,
  operator,
  admin,
  act,
}: {
  sources: Source[];
  creators: Creator[];
  operator: boolean;
  admin: boolean;
  act: Act;
}) {
  const [creatorName, setCreatorName] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState<SourceType>("licensed_creator");
  const [creatorId, setCreatorId] = useState("");
  const [url, setUrl] = useState("");
  const [notes, setNotes] = useState("");

  const blockButton = (blocked: boolean, onClick: () => void) =>
    blocked
      ? admin && (
          <button type="button" className="btn btn-ghost" onClick={onClick}>
            Entsperren
          </button>
        )
      : operator && (
          <button type="button" className="btn btn-ghost" onClick={onClick}>
            Sperren
          </button>
        );

  return (
    <Section title="Quellen und Creator">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Quelle</th>
              <th>Art</th>
              <th>Creator</th>
              <th>Herkunft</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.id}>
                <td>{s.name}</td>
                <td>{SOURCE_TYPES[s.type]}</td>
                <td>{creators.find((c) => c.id === s.creator_id)?.name ?? "–"}</td>
                <td className="small">
                  {s.url ?? s.provenance_notes ?? <Badge tone="warn">nicht dokumentiert</Badge>}
                </td>
                <td>
                  {s.is_blocked ? (
                    <Badge tone="danger">Gesperrt</Badge>
                  ) : (
                    <Badge tone="ok">Aktiv</Badge>
                  )}
                </td>
                <td>
                  {blockButton(
                    s.is_blocked,
                    () => void act(() => api.setSourceBlocked(s.id, !s.is_blocked)),
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {operator && (
        <form
          className="inline-form"
          aria-label="Quelle anlegen"
          onSubmit={(e) => {
            e.preventDefault();
            void act(async () => {
              await api.createSource({
                creator_id: creatorId ? Number(creatorId) : null,
                type,
                name,
                url: url || undefined,
                provenance_notes: notes || undefined,
              });
              setName("");
              setUrl("");
              setNotes("");
            });
          }}
        >
          <input
            placeholder="Name der Quelle"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <select
            aria-label="Art der Quelle"
            value={type}
            onChange={(e) => setType(e.target.value as SourceType)}
          >
            {Object.entries(SOURCE_TYPES).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
          <select
            aria-label="Creator"
            value={creatorId}
            onChange={(e) => setCreatorId(e.target.value)}
          >
            <option value="">ohne Creator</option>
            {creators.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <input
            type="url"
            placeholder="URL (Vertrag, Kanal)"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <input
            placeholder="Herkunftsnotiz"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <button className="btn btn-primary" type="submit">
            Quelle anlegen
          </button>
        </form>
      )}

      <h3>Creator</h3>
      <ul className="plain-list">
        {creators.map((c) => (
          <li key={c.id}>
            {c.name} {c.is_blocked && <Badge tone="danger">Gesperrt</Badge>}{" "}
            {blockButton(
              c.is_blocked,
              () => void act(() => api.setCreatorBlocked(c.id, !c.is_blocked)),
            )}
          </li>
        ))}
      </ul>
      {operator && (
        <form
          className="inline-form"
          aria-label="Creator anlegen"
          onSubmit={(e) => {
            e.preventDefault();
            void act(async () => {
              await api.createCreator({ name: creatorName });
              setCreatorName("");
            });
          }}
        >
          <input
            placeholder="Name des Creators"
            required
            value={creatorName}
            onChange={(e) => setCreatorName(e.target.value)}
          />
          <button className="btn" type="submit">
            Creator anlegen
          </button>
        </form>
      )}
    </Section>
  );
}

// --- publisher policies -------------------------------------------------------

function PolicySection({
  policies,
  games,
  admin,
  operator,
  act,
}: {
  policies: PublisherPolicy[];
  games: Game[];
  admin: boolean;
  operator: boolean;
  act: Act;
}) {
  const [gameId, setGameId] = useState("");
  const [policyStatus, setPolicyStatus] = useState<PolicyStatus>("license_required");
  const [notes, setNotes] = useState("");
  const [gameName, setGameName] = useState("");

  return (
    <Section title="Publisher-Richtlinien">
      <p className="muted small">
        Ohne geprüfte Richtlinie wird Material eines Spiels nicht freigegeben.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Spiel</th>
              <th>Richtlinie</th>
              <th>Hinweis</th>
              <th>Geprüft</th>
            </tr>
          </thead>
          <tbody>
            {policies.map((p) => (
              <tr key={p.id}>
                <td>
                  {p.game}
                  {p.publisher && <div className="muted small">{p.publisher}</div>}
                </td>
                <td>{status(POLICY_STATUS, p.status)}</td>
                <td className="small">
                  {p.notes}
                  {p.policy_url && (
                    <>
                      {" "}
                      <a href={p.policy_url} target="_blank" rel="noreferrer">
                        Quelle
                      </a>
                    </>
                  )}
                </td>
                <td className="small">{p.checked_at ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {admin && (
        <form
          className="inline-form"
          aria-label="Richtlinie festlegen"
          onSubmit={(e) => {
            e.preventDefault();
            void act(async () => {
              await api.setPolicy(Number(gameId), { status: policyStatus, notes });
              setNotes("");
            });
          }}
        >
          <select
            aria-label="Spiel der Richtlinie"
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
          <select
            aria-label="Richtlinie"
            value={policyStatus}
            onChange={(e) => setPolicyStatus(e.target.value as PolicyStatus)}
          >
            {Object.entries(POLICY_STATUS).map(([k, [label]]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
          <input
            placeholder="Begründung / Fundstelle"
            required
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <button className="btn btn-primary" type="submit">
            Richtlinie speichern
          </button>
        </form>
      )}
      {operator && (
        <form
          className="inline-form"
          aria-label="Spiel anlegen"
          onSubmit={(e) => {
            e.preventDefault();
            void act(async () => {
              await api.createGame({ name: gameName });
              setGameName("");
            });
          }}
        >
          <input
            placeholder="Neues Spiel"
            required
            value={gameName}
            onChange={(e) => setGameName(e.target.value)}
          />
          <button className="btn" type="submit">
            Spiel anlegen
          </button>
        </form>
      )}
    </Section>
  );
}
