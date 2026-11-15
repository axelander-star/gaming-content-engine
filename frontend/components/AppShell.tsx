"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { useAuth } from "@/components/AuthProvider";
import { api } from "@/lib/api";
import { onEmergencyStop } from "@/lib/events";
import { ROLE_LABELS } from "@/lib/roles";

const NAV = [
  { href: "/", label: "Übersicht" },
  { href: "/themenbereiche", label: "Themenbereiche" },
  { href: "/agenten", label: "Agenten" },
  { href: "/rechte", label: "Rechte" },
  { href: "/produktion", label: "Videoproduktion" },
  { href: "/publishing", label: "Publishing" },
  { href: "/analytics", label: "Analytics" },
  { href: "/kosten", label: "Kosten" },
  { href: "/system", label: "System" },
  { href: "/einstellungen", label: "Einstellungen" },
] as const;

/** Layout for every signed-in page: sidebar, header, emergency-stop banner. */
export function AppShell({ children }: { children: ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [emergency, setEmergency] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    api
      .settings()
      .then((s) => setEmergency(s.controls.emergency_stop))
      .catch(() => undefined);
  }, [user, pathname]);

  useEffect(() => onEmergencyStop(setEmergency), []);

  if (loading || !user) {
    return <div className="center-screen muted">Lade …</div>;
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          Gaming Content <span>Engine</span>
        </div>
        <nav aria-label="Hauptnavigation">
          {NAV.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link key={item.href} href={item.href} className={active ? "active" : undefined}>
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <div />
          <div className="topbar-user">
            <span>
              {user.display_name ?? user.email} · {ROLE_LABELS[user.role]}
            </span>
            <button type="button" className="btn btn-ghost" onClick={() => void logout()}>
              Abmelden
            </button>
          </div>
        </header>
        {emergency && (
          <div className="banner banner-danger" role="alert">
            Not-Aus ist aktiv. Agenten und Veröffentlichungen sind gestoppt.
          </div>
        )}
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
