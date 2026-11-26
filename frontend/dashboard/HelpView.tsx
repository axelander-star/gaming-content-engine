"use client";

// Help page (/hilfe): the "Erste Schritte" flow from nothing to the first video,
// then the guide for every page, searchable and collapsible.

import Link from "next/link";
import { useMemo, useState } from "react";

import { GuideBody } from "@/components/HelpPanel";
import { PageHeader, Section } from "@/components/ui";
import { GETTING_STARTED, HELP_GUIDES } from "@/lib/help";

function matches(text: string, query: string): boolean {
  return text.toLowerCase().includes(query.toLowerCase());
}

export function HelpView() {
  const [query, setQuery] = useState("");
  const guides = useMemo(() => {
    const q = query.trim();
    const all = HELP_GUIDES.filter((g) => g.href !== "/hilfe");
    if (!q) return all;
    return all.filter((g) =>
      [g.title, g.what, ...g.steps, ...(g.yourPart ?? []), ...(g.tips ?? [])].some((t) =>
        matches(t, q),
      ),
    );
  }, [query]);

  return (
    <>
      <PageHeader
        title="Hilfe"
        description="Der Weg zum ersten Video und eine kurze Anleitung für jede Seite. Auf jeder Seite öffnet das Fragezeichen oben rechts die passende Anleitung."
      />

      <Section title="Erste Schritte">
        <ol className="start-steps" aria-label="Erste Schritte">
          {GETTING_STARTED.map((s, i) => (
            <li key={s.href} className="start-step">
              <span className="start-num" aria-hidden="true">
                {i + 1}
              </span>
              <div>
                <h3>{s.title}</h3>
                <p className="muted">{s.text}</p>
                <Link href={s.href} className="btn btn-small">
                  {s.linkLabel}
                </Link>
              </div>
            </li>
          ))}
        </ol>
      </Section>

      <Section title="Anleitungen für jede Seite">
        <label className="help-search">
          <span className="sr-only">Anleitungen durchsuchen</span>
          <input
            type="search"
            placeholder="Suchen, z. B. „verbinden“ oder „TikTok“"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        {guides.length === 0 ? (
          <p className="muted">Keine Anleitung gefunden.</p>
        ) : (
          <div className="help-list">
            {guides.map((g) => (
              <details key={g.href} className="help-item" open={query.trim() !== ""}>
                <summary>
                  <span className="help-item-title">{g.title}</span>
                  <span className="muted small help-item-what">{g.what}</span>
                </summary>
                <GuideBody guide={g} />
                <Link href={g.href} className="btn btn-small">
                  Seite „{g.title}“ öffnen
                </Link>
              </details>
            ))}
          </div>
        )}
      </Section>
    </>
  );
}
