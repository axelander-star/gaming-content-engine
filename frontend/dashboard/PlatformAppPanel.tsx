"use client";

import { type FormEvent, useEffect, useState } from "react";

import { Badge, ErrorText, Section } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { PlatformAppStatus } from "@/lib/types";

type Provider = "tiktok" | "instagram";

const TEXT: Record<
  Provider,
  { title: string; key: string; secret: string; where: string; platform: string }
> = {
  tiktok: {
    title: "TikTok-App",
    key: "Client Key",
    secret: "Client Secret",
    where: "Die Schlüssel stehen bei developers.tiktok.com in deiner App.",
    platform: "TikTok-Kanäle",
  },
  instagram: {
    title: "Instagram-App",
    key: "Instagram-App-ID",
    secret: "Instagram-App-Geheimcode",
    where:
      "Die Werte stehen bei developers.facebook.com in deiner App unter Instagram → API-Einrichtung mit Instagram-Login.",
    platform: "Instagram-Kanäle",
  },
};

/** Redirect URI the platform must know: the dashboard's own address + the callback path. */
function suggestedRedirect(provider: Provider): string {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/api/oauth/${provider}/callback`;
}

/** App keys of a platform (key, secret, redirect URI) without SSH. Admins only. */
export function PlatformAppPanel({ provider }: { provider: Provider }) {
  const t = TEXT[provider];
  const [data, setData] = useState<PlatformAppStatus | null>(null);
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [redirect, setRedirect] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .platformApp(provider)
      .then((d) => {
        setData(d);
        setKey(d.client_key);
        setRedirect(d.redirect_uri_ok ? d.redirect_uri : suggestedRedirect(provider));
      })
      .catch(() => setData(null)); // not an admin, or older backend: no panel
  }, [provider]);
  if (!data) return null;

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const d = await api.savePlatformApp(provider, {
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
    <Section title={t.title}>
      <p role="status">
        {data.configured ? (
          <Badge tone="ok">Eingerichtet</Badge>
        ) : (
          <Badge tone="warn">Noch nicht eingerichtet</Badge>
        )}{" "}
        <span className="muted small">
          {t.where} Danach kannst du {t.platform} über „Verbinden“ anmelden. Das Geheimnis wird
          verschlüsselt gespeichert und nie wieder angezeigt.
          {data.source === "env" && " Zurzeit gelten die Werte aus der Server-Datei .env."}
        </span>
      </p>
      <form className="acc-rev-form" onSubmit={save} aria-label={`${t.title}-Schlüssel`}>
        <label>
          {t.key}
          <input
            value={key}
            onChange={(e) => setKey(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            required
          />
        </label>
        <label>
          {t.secret}
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
          Weiterleitungs-URI (genau so in der App eintragen)
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
          Gespeichert. Du kannst den Kanal jetzt verbinden.
        </p>
      )}
      <ErrorText error={error} />
    </Section>
  );
}
