"use client";

// Bell in the top bar (Ausbau A4): warnings and "done" messages in one quiet list.
// Important ones also go to the phone (ntfy), see docs/AUSBAU_PLAN.md.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Icon } from "@/components/icons";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type { AppNotification, NotificationList, PushSettings } from "@/lib/types";

const POLL_MS = 60_000;

function pushLine(push: PushSettings | null): string {
  if (!push) return "";
  if (push.mode !== "live" || !push.configured) {
    return "Push aufs Handy ist noch aus (Testmodus).";
  }
  return `Push aufs Handy an: ab „Warnung“, Ruhe ${push.quiet_start}–${push.quiet_end} Uhr außer Notfällen.`;
}

export function NotificationBell() {
  const { user } = useAuth();
  const pathname = usePathname();
  const [data, setData] = useState<NotificationList | null>(null);
  const [open, setOpen] = useState(false);
  const [push, setPush] = useState<PushSettings | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    api
      .notifications(30)
      .then(setData)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(t);
  }, [load]);
  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    api
      .pushSettings()
      .then(setPush)
      .catch(() => setPush(null));
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function markAll() {
    await api.markNotificationsRead().catch(() => undefined);
    load();
  }

  async function markOne(n: AppNotification) {
    if (n.read) return;
    await api.markNotificationsRead([n.id]).catch(() => undefined);
    load();
  }

  async function test() {
    setNote(null);
    try {
      const r = await api.testPush();
      setNote(r.result === "sent" ? "Test gesendet." : "Testmodus: nichts gesendet.");
    } catch (err) {
      setNote((err as Error).message);
    }
  }

  const unread = data?.unread ?? 0;
  return (
    <div className="bell" ref={ref}>
      <button
        type="button"
        className="icon-btn bell-btn"
        aria-label={unread ? `Hinweise, ${unread} neu` : "Hinweise"}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
      >
        <Icon name="bell" />
        {unread > 0 && <span className="bell-count">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="bell-panel" role="dialog" aria-label="Hinweise">
          <div className="bell-head">
            <strong>Hinweise</strong>
            {unread > 0 && (
              <button type="button" className="btn btn-ghost btn-small" onClick={() => void markAll()}>
                Alle gelesen
              </button>
            )}
          </div>
          {!data || data.items.length === 0 ? (
            <p className="muted small bell-empty">Alles ruhig. Keine Hinweise.</p>
          ) : (
            <ul className="bell-list">
              {data.items.map((n) => {
                const inner = (
                  <>
                    <span className={`bell-dot level-${n.level}`} aria-hidden="true" />
                    <span className="bell-text">
                      <span className="bell-title">{n.title}</span>
                      {n.body && <span className="bell-body">{n.body}</span>}
                      <span className="muted small">{formatDateTime(n.created_at)}</span>
                    </span>
                  </>
                );
                return (
                  <li key={n.id} className={n.read ? "is-read" : undefined}>
                    {n.link ? (
                      <Link href={n.link} className="bell-item" onClick={() => void markOne(n)}>
                        {inner}
                      </Link>
                    ) : (
                      <button type="button" className="bell-item" onClick={() => void markOne(n)}>
                        {inner}
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          <div className="bell-foot muted small">
            <span>{pushLine(push)}</span>
            {hasRole(user?.role, "admin") && (
              <button type="button" className="btn btn-ghost btn-small" onClick={() => void test()}>
                Test-Push
              </button>
            )}
            {note && <span role="status">{note}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
