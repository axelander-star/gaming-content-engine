"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { Badge, ErrorText, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import { ROLE_LABELS } from "@/lib/roles";
import type { User, UserRole } from "@/lib/types";

const ROLES: UserRole[] = ["viewer", "operator", "admin"];

/** User management, rendered for admins only. */
export function UsersPanel({ currentUserId }: { currentUserId: number }) {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("viewer");

  useEffect(() => {
    api.users().then(setUsers).catch((e: Error) => setError(e.message));
  }, []);

  const replace = (u: User) => setUsers((all) => all.map((x) => (x.id === u.id ? u : x)));

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    try {
      const user = await api.createUser({ email, password, role });
      setUsers((all) => [...all, user]);
      setEmail("");
      setPassword("");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function patch(id: number, data: Parameters<typeof api.updateUser>[1]) {
    setError(null);
    try {
      replace(await api.updateUser(id, data));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <Section title="Benutzer">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>E-Mail</th>
              <th>Rolle</th>
              <th>Status</th>
              <th>Letzte Anmeldung</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>
                  {u.email}
                  {u.id === currentUserId && <span className="muted small"> (du)</span>}
                </td>
                <td>
                  <select
                    aria-label={`Rolle ${u.email}`}
                    value={u.role}
                    onChange={(e) => void patch(u.id, { role: e.target.value as UserRole })}
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {ROLE_LABELS[r]}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => void patch(u.id, { is_active: !u.is_active })}
                  >
                    <Badge tone={u.is_active ? "ok" : "neutral"}>
                      {u.is_active ? "Aktiv" : "Deaktiviert"}
                    </Badge>
                  </button>
                </td>
                <td>{formatDateTime(u.last_login_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form className="inline-form" onSubmit={create}>
        <input
          type="email"
          placeholder="E-Mail"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          type="password"
          placeholder="Passwort (min. 12 Zeichen)"
          required
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <select aria-label="Rolle" value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r]}
            </option>
          ))}
        </select>
        <button className="btn btn-primary" type="submit">
          Benutzer anlegen
        </button>
      </form>
      <ErrorText error={error} />
    </Section>
  );
}
