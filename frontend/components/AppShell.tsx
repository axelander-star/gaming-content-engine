"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Icon } from "@/components/icons";
import type { IconName } from "@/components/icons";
import { HelpButton } from "@/components/HelpPanel";
import { NotificationBell } from "@/components/NotificationBell";
import { api } from "@/lib/api";
import { onEmergencyStop } from "@/lib/events";
import { ROLE_LABELS } from "@/lib/roles";
import { readTheme, setTheme } from "@/lib/theme";
import type { Theme } from "@/lib/theme";

interface NavItem {
  href: string;
  label: string;
  icon: IconName;
}

/** Navigation groups. Later phases add their pages here once they exist. */
const NAV: { title: string; items: NavItem[] }[] = [
  {
    title: "Steuerung",
    items: [
      { href: "/", label: "Übersicht", icon: "home" },
      { href: "/assistent", label: "Assistent", icon: "chat" },
      { href: "/ideen", label: "Ideenlabor", icon: "bulb" },
      { href: "/trend-alarm", label: "Trend-Alarm", icon: "alert" },
      { href: "/redaktionsplan", label: "Redaktionsplan", icon: "calendar" },
      { href: "/eigenproduktion", label: "Eigenproduktion", icon: "wand" },
      { href: "/mediathek", label: "Mediathek", icon: "image" },
      { href: "/freigabe", label: "Freigabecenter", icon: "check" },
      { href: "/kampagnen", label: "Kampagnen", icon: "clock" },
      { href: "/themenbereiche", label: "Themenbereiche", icon: "layers" },
      { href: "/konten", label: "Konten", icon: "chart" },
      { href: "/kommentare", label: "Kommentare", icon: "chat" },
      { href: "/kanal-assistent", label: "Kanal-Assistent", icon: "userPlus" },
      { href: "/konkurrenz", label: "Konkurrenz-Radar", icon: "activity" },
      { href: "/linkseiten", label: "Linkseiten", icon: "send" },
      { href: "/sponsoren", label: "Sponsoren", icon: "coins" },
    ],
  },
  {
    title: "Engine",
    items: [
      { href: "/agenten", label: "Agenten", icon: "bot" },
      { href: "/rechte", label: "Rechte", icon: "shield" },
      { href: "/produktion", label: "Videoproduktion", icon: "film" },
      { href: "/publishing", label: "Publishing", icon: "send" },
      { href: "/analytics", label: "Analytics", icon: "chart" },
      { href: "/kosten", label: "Kosten", icon: "coins" },
    ],
  },
  {
    title: "System",
    items: [
      { href: "/system", label: "System", icon: "server" },
      { href: "/einstellungen", label: "Einstellungen", icon: "settings" },
      { href: "/hilfe", label: "Hilfe", icon: "help" },
    ],
  },
];

function initials(name: string): string {
  const parts = name.split(/[\s@._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

/** Layout for every signed-in page: sidebar, header, emergency-stop banner. */
export function AppShell({ children }: { children: ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [emergency, setEmergency] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [theme, setThemeState] = useState<Theme>("dark");
  const sidebarRef = useRef<HTMLElement>(null);

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
  useEffect(() => setThemeState(readTheme()), []);
  useEffect(() => setMenuOpen(false), [pathname]);

  // One scrollbar for the whole page: if the sidebar is taller than the
  // window, stick it with a negative offset so it scrolls along with the page
  // until its last entry is visible, instead of giving it its own scrollbar.
  useEffect(() => {
    const el = sidebarRef.current;
    if (!el) return;
    const update = () => {
      const overflow = el.offsetHeight - window.innerHeight;
      el.style.setProperty("--sidebar-top", `${Math.min(0, -overflow)}px`);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    window.addEventListener("resize", update);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [user]);

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  if (loading || !user) {
    return <div className="center-screen muted">Lade …</div>;
  }

  const name = user.display_name ?? user.email;
  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setThemeState(next);
  };

  return (
    <div className={`shell ${menuOpen ? "menu-open" : ""}`}>
      <aside className="sidebar" id="sidebar" ref={sidebarRef}>
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            CE
          </span>
          <span>
            Content <span className="brand-accent">Engine</span>
          </span>
        </div>
        <nav aria-label="Hauptnavigation">
          {NAV.map((group) => (
            <div className="nav-group" key={group.title}>
              <div className="nav-group-title">{group.title}</div>
              {group.items.map((item) => {
                const active =
                  item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={active ? "active" : undefined}
                    aria-current={active ? "page" : undefined}
                  >
                    <Icon name={item.icon} />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="avatar" aria-hidden="true">
            {initials(name)}
          </span>
          <span className="sidebar-user">
            <span className="sidebar-user-name">{name}</span>
            <span className="sidebar-user-role">{ROLE_LABELS[user.role]}</span>
          </span>
        </div>
      </aside>
      {menuOpen && (
        <button
          type="button"
          className="scrim"
          aria-label="Menü schließen"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <div className="main">
        <header className="topbar">
          <button
            type="button"
            className="icon-btn menu-btn"
            aria-label={menuOpen ? "Menü schließen" : "Menü öffnen"}
            aria-expanded={menuOpen}
            aria-controls="sidebar"
            onClick={() => setMenuOpen((v) => !v)}
          >
            <Icon name={menuOpen ? "close" : "menu"} />
          </button>
          <div className="topbar-spacer" />
          <div className="topbar-user">
            <span className="topbar-name">
              {name} · {ROLE_LABELS[user.role]}
            </span>
            <HelpButton />
            <NotificationBell />
            <button
              type="button"
              className="icon-btn"
              aria-label={theme === "dark" ? "Helles Design" : "Dunkles Design"}
              title={theme === "dark" ? "Helles Design" : "Dunkles Design"}
              onClick={toggleTheme}
            >
              <Icon name={theme === "dark" ? "sun" : "moon"} />
            </button>
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
