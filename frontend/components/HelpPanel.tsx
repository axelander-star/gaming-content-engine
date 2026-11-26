"use client";

// Question mark in the top bar: opens a side panel with the short guide for the
// current page. All guides live in lib/help.ts and are collected on /hilfe.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Icon } from "@/components/icons";
import { guideFor } from "@/lib/help";
import type { HelpGuide } from "@/lib/help";

/** The body of one guide; shared by the side panel and the help page. */
export function GuideBody({ guide }: { guide: HelpGuide }) {
  return (
    <div className="guide">
      <p>{guide.what}</p>
      <h3>So gehst du vor</h3>
      <ol className="guide-steps">
        {guide.steps.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ol>
      {guide.yourPart && guide.yourPart.length > 0 && (
        <div className="guide-you">
          <h3>Das machst du selbst</h3>
          <ul>
            {guide.yourPart.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}
      {guide.tips && guide.tips.length > 0 && (
        <div className="guide-tips">
          <h3>Gut zu wissen</h3>
          <ul>
            {guide.tips.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function HelpButton() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const guide = guideFor(pathname);

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className="icon-btn help-btn"
        aria-label="Anleitung für diese Seite"
        title="Anleitung für diese Seite"
        aria-expanded={open}
        aria-controls="help-panel"
        onClick={() => setOpen((v) => !v)}
      >
        <Icon name="help" />
      </button>
      {open && (
        <>
          <button
            type="button"
            className="help-scrim"
            aria-label="Anleitung schließen"
            tabIndex={-1}
            onClick={() => setOpen(false)}
          />
          <aside
            id="help-panel"
            className="help-panel"
            role="dialog"
            aria-modal="false"
            aria-labelledby="help-panel-title"
          >
            <div className="help-panel-head">
              <span className="help-panel-kicker">Anleitung</span>
              <button
                ref={closeRef}
                type="button"
                className="icon-btn"
                aria-label="Anleitung schließen"
                onClick={() => setOpen(false)}
              >
                <Icon name="close" />
              </button>
            </div>
            <h2 id="help-panel-title">{guide ? guide.title : "Hilfe"}</h2>
            {guide ? (
              <GuideBody guide={guide} />
            ) : (
              <p className="muted">Für diese Seite gibt es noch keine eigene Anleitung.</p>
            )}
            <div className="help-panel-foot">
              <Link href="/hilfe" className="btn" onClick={() => setOpen(false)}>
                <Icon name="book" /> Alle Anleitungen und Erste Schritte
              </Link>
            </div>
          </aside>
        </>
      )}
    </>
  );
}
