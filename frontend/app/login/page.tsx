"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { ErrorText } from "@/components/ui";
import { ApiError } from "@/lib/api";

export default function LoginPage() {
  const { user, loading, login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [loading, user, router]);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      router.replace("/");
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError("Zu viele Fehlversuche. Bitte in einigen Minuten erneut versuchen.");
      } else if (err instanceof ApiError && err.status === 401) {
        setError("E-Mail oder Passwort ist falsch.");
      } else {
        setError("Anmeldung fehlgeschlagen. Ist das Backend erreichbar?");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center-screen">
      <form className="card login" onSubmit={onSubmit}>
        <h1>
          Gaming Content <span>Engine</span>
        </h1>
        <p className="muted">Bitte anmelden.</p>
        <label>
          E-Mail
          <input
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          Passwort
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <ErrorText error={error} />
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Anmelden …" : "Anmelden"}
        </button>
      </form>
    </div>
  );
}
