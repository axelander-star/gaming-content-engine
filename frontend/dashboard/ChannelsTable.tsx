"use client";

import { useEffect, useState } from "react";

import { Badge, ErrorText, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { AUTH_STATUS_LABELS, PLATFORM_LABELS } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type { Channel, UserRole } from "@/lib/types";

const PROVIDER_NAMES: Record<string, string> = {
  youtube: "YouTube",
  tiktok: "TikTok",
  meta: "Facebook/Instagram",
  instagram: "Instagram",
};

function connectMessage(provider: string, result: string): string {
  const name = PROVIDER_NAMES[provider] ?? provider;
  switch (result) {
    case "connected":
      return `${name}: Kanal verbunden.`;
    case "restricted":
      return `${name}: verbunden, aber noch eingeschränkt (z. B. App nicht geprüft oder Recht zum Veröffentlichen fehlt). Es wird nichts veröffentlicht.`;
    case "denied":
      return `${name}: Die Anmeldung wurde abgebrochen.`;
    case "in_use":
      return `${name}: Dieses Konto ist schon mit einem anderen Kanal verbunden. Jeder Kanal braucht sein eigenes Konto (z. B. einen eigenen YouTube-Kanal je Themenbereich). Beim Verbinden das passende Konto auswählen.`;
    case "invalid":
      return `${name}: Der Anmeldevorgang war ungültig oder abgelaufen. Bitte erneut verbinden.`;
    default:
      return `${name}: Die Verbindung ist fehlgeschlagen. Details stehen im Protokoll.`;
  }
}

const CONNECT_LABELS: Record<string, string> = {
  youtube: "Mit YouTube verbinden",
  tiktok: "Mit TikTok verbinden",
  instagram: "Mit Instagram verbinden",
  facebook: "Mit Facebook verbinden",
};

type Limits = Pick<Channel, "min_posts_per_day" | "max_posts_per_day" | "min_interval_minutes">;

function LimitsEditor({ channel, onSaved }: { channel: Channel; onSaved: (c: Channel) => void }) {
  const [limits, setLimits] = useState<Limits>({
    min_posts_per_day: channel.min_posts_per_day,
    max_posts_per_day: channel.max_posts_per_day,
    min_interval_minutes: channel.min_interval_minutes,
  });
  const [error, setError] = useState<string | null>(null);
  const field = (key: keyof Limits, label: string) => (
    <input
      aria-label={`${label} ${channel.name}`}
      type="number"
      min={0}
      className="input-sm"
      value={limits[key]}
      onChange={(e) => setLimits({ ...limits, [key]: Number(e.target.value) })}
    />
  );
  return (
    <div className="limits">
      {field("min_posts_per_day", "Minimum")}
      <span className="muted">–</span>
      {field("max_posts_per_day", "Maximum")}
      <span className="muted small">/Tag, Abstand</span>
      {field("min_interval_minutes", "Mindestabstand")}
      <span className="muted small">Min.</span>
      <button
        type="button"
        className="btn btn-ghost"
        onClick={() =>
          api
            .setChannelLimits(channel.id, limits)
            .then((c) => {
              setError(null);
              onSaved(c);
            })
            .catch((e: Error) => setError(e.message))
        }
      >
        Speichern
      </button>
      <ErrorText error={error} />
    </div>
  );
}

export function ChannelsTable({ role }: { role: UserRole }) {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ provider: string; value: string } | null>(null);
  const isAdmin = hasRole(role, "admin");
  const isOperator = hasRole(role, "operator");

  useEffect(() => {
    api
      .channels()
      .then(setChannels)
      .catch((e: Error) => setError(e.message));
    const params = new URLSearchParams(window.location.search);
    const provider = Object.keys(PROVIDER_NAMES).find((p) => params.has(p));
    if (provider) setResult({ provider, value: params.get(provider) ?? "" });
  }, []);

  const replace = (c: Channel) => setChannels((all) => all.map((x) => (x.id === c.id ? c : x)));

  async function toggle(c: Channel) {
    try {
      replace(c.is_paused ? await api.resumeChannel(c.id) : await api.pauseChannel(c.id));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function connect(c: Channel) {
    try {
      const { url } = await api.connectChannel(c.id);
      window.location.assign(url);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function syncProfile(c: Channel) {
    try {
      replace(await api.syncChannelProfile(c.id));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function disconnect(c: Channel) {
    try {
      replace(await api.disconnectChannel(c.id));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Section title="Kanäle und Sicherheitsgrenzen">
      {result && (
        <p role="status" className={result.value === "connected" ? "muted" : "error"}>
          {connectMessage(result.provider, result.value)}
        </p>
      )}
      <p className="muted small">
        Die Grenzen sind technische Obergrenzen, keine Tagesziele. Wie viel tatsächlich
        veröffentlicht wird, entscheidet der Publishing Strategy Agent pro Kanal. Verbinden führt
        zur Anmeldung bei der Plattform; Zugangsschlüssel werden verschlüsselt gespeichert und nie
        angezeigt.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Kanal</th>
              <th>Plattform</th>
              <th>Themenbereich</th>
              <th>Sprache</th>
              <th>Verbindung</th>
              <th>Status</th>
              <th>Grenzen</th>
            </tr>
          </thead>
          <tbody>
            {channels.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td>{PLATFORM_LABELS[c.platform]}</td>
                <td>{c.content_project}</td>
                <td>{c.language.toUpperCase()}</td>
                <td>
                  <Badge tone={c.auth_status === "authorized" ? "ok" : "neutral"}>
                    {AUTH_STATUS_LABELS[c.auth_status]}
                  </Badge>
                  {c.connected_account && (
                    <span className="muted small"> {c.connected_account}</span>
                  )}
                  {isAdmin && CONNECT_LABELS[c.platform] && (
                    <>
                      {" "}
                      {c.auth_status === "not_connected" || c.auth_status === "expired" ? (
                        <button
                          type="button"
                          className="btn btn-ghost small"
                          onClick={() => void connect(c)}
                        >
                          {CONNECT_LABELS[c.platform]}
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-ghost small"
                          onClick={() => void disconnect(c)}
                        >
                          Trennen
                        </button>
                      )}
                    </>
                  )}
                  {c.platform === "youtube" && c.auth_status === "authorized" && (
                    <ProfileSyncLine channel={c} onSync={isAdmin ? () => void syncProfile(c) : null} />
                  )}
                </td>
                <td>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={c.is_paused ? !isAdmin : !isOperator}
                    onClick={() => void toggle(c)}
                    title={c.is_paused ? "Nur Admins können fortsetzen" : "Kanal pausieren"}
                  >
                    {c.is_paused ? "Pausiert · fortsetzen" : "Aktiv · pausieren"}
                  </button>
                </td>
                <td>
                  {isAdmin ? (
                    <LimitsEditor channel={c} onSaved={replace} />
                  ) : (
                    `${c.min_posts_per_day}–${c.max_posts_per_day}/Tag, ${c.min_interval_minutes} Min.`
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ErrorText error={error} />
    </Section>
  );
}

/** What the engine wrote to the YouTube profile, plus what stays manual. */
function ProfileSyncLine({ channel, onSync }: { channel: Channel; onSync: (() => void) | null }) {
  const sync = channel.profile_sync;
  return (
    <p className="small muted" aria-label={`Profil ${channel.name}`}>
      {sync === null
        ? "Profil noch nicht übertragen. "
        : sync.ok
          ? `Profil übertragen: ${sync.applied.join(", ")}. Selbst hochladen: ${sync.manual.join(", ")}. `
          : `Profil nicht übertragen: ${sync.error ?? "unbekannter Fehler"}. `}
      {onSync && (
        <button type="button" className="btn btn-ghost small" onClick={onSync}>
          {sync === null ? "Profil übertragen" : "Erneut übertragen"}
        </button>
      )}
    </p>
  );
}
