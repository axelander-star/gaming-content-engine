"use client";

import { type FormEvent, useEffect, useState } from "react";

import { Badge, ErrorText, Section } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { PlatformAppStatus } from "@/lib/types";

/** Redirect URI TikTok must know: the dashboard's own address + the callback path. */
function suggestedRedirect(): string {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/api/oauth/tiktok/callback`;
}

/** TikTok app keys (client key, secret, redirect URI) without SSH. Admins only. */
export function TikTokAppPanel() {
  const [data, setData] = useState<PlatformAppStatus | null>(null);
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [redirect, setRedirect] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .platformApp("tiktok")
      .then((d) => {
        setData(d);
        setKey(d.client_key);
        setRedirect(d.redirect_uri_ok ? d.redirect_uri : suggestedRedirect());
      })
      .catch(() => setData(null)); // not an admin, or older backend: no panel
  }, []);
  if (!data) return null;

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const d = await api.savePlatformApp("tiktok", {
        client_key: key.trim(),
        client_secret: secret.trim(),
        redirect_uri: redirect.trim(),
      });
      setData(d);
      setSecret("");
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Speichern fehlgeschlagen");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="TikTok-App">
      <p role="status">
        {data.configured ? (
          <Badge tone="ok">Eingerichtet</Badge>
        ) : (
          <Badge tone="warn">Noch nicht eingerichtet</Badge>
        )}{" "}
        <span className="muted small">
          Die Schlüssel stehen bei developers.tiktok.com in deiner App. Danach kannst du
          TikTok-Kanäle über „Verbinden“ anmelden. Das Geheimnis wird verschlüsselt gespeichert
          und nie wieder angezeigt.
          {data.source === "env" && " Zurzeit gelten die Werte aus der Server-Datei .env."}
        </span>
      </p>
      <form className="acc-rev-form" onSubmit={save} aria-label="TikTok-App-Schlüssel">
        <label>
          Client Key
          <input
            value={key}
            onChange={(e) => setKey(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            required
          />
        </label>
        <label>
          Client Secret
          <input
            type="password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            autoComplete="new-password"
            placeholder={data.secret_set ? "gespeichert, leer lassen zum Behalten" : ""}
            required={!data.secret_set}
          />
        </label>
        <label>
          Weiterleitungs-URI (genau so bei TikTok eintragen)
          <input
            value={redirect}
            onChange={(e) => setRedirect(e.target.value)}
            spellCheck={false}
            required
          />
        </label>
        <button className="btn btn-primary" disabled={busy}>
          {busy ? "Speichert …" : "Speichern"}
        </button>
      </form>
      {saved && (
        <p className="muted small" role="status">
          Gespeichert. Du kannst den TikTok-Kanal jetzt verbinden.
        </p>
      )}
      <ErrorText error={error} />
    </Section>
  );
}
