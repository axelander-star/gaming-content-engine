"use client";

import { useEffect, useState } from "react";

import { Badge, ErrorText, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { AUTH_STATUS_LABELS, PLATFORM_LABELS } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type { Channel, UserRole } from "@/lib/types";

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
  const isAdmin = hasRole(role, "admin");
  const isOperator = hasRole(role, "operator");

  useEffect(() => {
    api.channels().then(setChannels).catch((e: Error) => setError(e.message));
  }, []);

  const replace = (c: Channel) => setChannels((all) => all.map((x) => (x.id === c.id ? c : x)));

  async function toggle(c: Channel) {
    try {
      replace(c.is_paused ? await api.resumeChannel(c.id) : await api.pauseChannel(c.id));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Section title="Kanäle und Sicherheitsgrenzen">
      <p className="muted small">
        Die Grenzen sind technische Obergrenzen, keine Tagesziele. Wie viel tatsächlich
        veröffentlicht wird, entscheidet später der Publishing Strategy Agent pro Kanal.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Kanal</th>
              <th>Plattform</th>
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
                <td>{c.language.toUpperCase()}</td>
                <td>
                  <Badge tone={c.auth_status === "authorized" ? "ok" : "neutral"}>
                    {AUTH_STATUS_LABELS[c.auth_status]}
                  </Badge>
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
