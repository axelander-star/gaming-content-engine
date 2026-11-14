// End-to-end smoke test for the dashboard (Phase 3, agents since Phase 4, trends since Phase 5,
// rights management since Phase 6).
// Needs a running dashboard (BASE_URL, default http://127.0.0.1:3000) wired to a
// backend with an admin account (E2E_EMAIL / E2E_PASSWORD) and a running queue
// worker (`python -m app.worker`) so that a manually started agent really runs.
// Optional: SCREENSHOT_DIR to save screenshots of the overview and settings pages.
import { chromium } from "playwright";
import assert from "node:assert/strict";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:3000";
const EMAIL = process.env.E2E_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_PASSWORD;
const SHOTS = process.env.SCREENSHOT_DIR;
assert.ok(PASSWORD, "E2E_PASSWORD must be set");

const steps = [];
const step = async (name, fn) => {
  await fn();
  steps.push(name);
  console.log(`  OK  ${name}`);
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1360, height: 900 }, deviceScaleFactor: 2 });
try {
  await step("Unangemeldet wird auf /login umgeleitet", async () => {
    await page.goto(BASE + "/");
    await page.waitForURL("**/login");
  });

  await step("Falsches Passwort zeigt Fehlermeldung", async () => {
    await page.getByLabel("E-Mail").fill(EMAIL);
    await page.getByLabel("Passwort").fill("falsches-passwort");
    await page.getByRole("button", { name: "Anmelden" }).click();
    await page.getByText("E-Mail oder Passwort ist falsch.").waitFor();
  });

  await step("Anmeldung führt zur Übersicht", async () => {
    await page.getByLabel("Passwort").fill(PASSWORD);
    await page.getByRole("button", { name: "Anmelden" }).click();
    await page.getByRole("heading", { name: "Übersicht" }).waitFor();
    await page.getByText("0 / 8").waitFor();
    await page.getByText("Bereit").waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/overview.png`, fullPage: true });
  });

  await step("Alle Navigationsseiten laden", async () => {
    for (const [link, heading] of [
      ["Agenten", "Agenten"],
      ["Rechte", "Rechte und Lizenzen"],
      ["Videoproduktion", "Videoproduktion"],
      ["Publishing", "Publishing"],
      ["Analytics", "Analytics"],
      ["Kosten", "Kosten"],
      ["Einstellungen", "Einstellungen"],
    ]) {
      await page.getByRole("link", { name: link, exact: true }).click();
      await page.getByRole("heading", { name: heading, level: 1 }).waitFor();
    }
  });

  await step("Agentenseite zeigt alle 18 Agenten", async () => {
    await page.getByRole("link", { name: "Agenten", exact: true }).click();
    await page.getByRole("heading", { name: "Agenten", level: 1 }).waitFor();
    await page.getByRole("button", { name: "Master Orchestrator", exact: true }).waitFor();
    const rows = page.locator("table").first().locator("tbody tr");
    await rows.nth(17).waitFor();
    assert.equal(await rows.count(), 18);
    await page.getByText("Folgt in Phase 9").first().waitFor();
  });

  await step("Agent pausieren und fortsetzen", async () => {
    await page.getByRole("button", { name: "Budget & Cost pausieren" }).click();
    await page.getByRole("button", { name: "Budget & Cost fortsetzen" }).waitFor();
    await page.getByRole("button", { name: "Budget & Cost fortsetzen" }).click();
    await page.getByRole("button", { name: "Budget & Cost pausieren" }).waitFor();
  });

  await step("Master Orchestrator manuell starten und Lauf protokollieren", async () => {
    await page.getByRole("button", { name: "Master Orchestrator jetzt ausführen" }).click();
    await page.getByText("Master Orchestrator wurde gestartet.").waitFor();
    const runs = page.locator("section").filter({ hasText: "Letzte Läufe: Master Orchestrator" });
    for (let i = 0; i < 20; i++) {
      if (await runs.getByText("Erfolgreich").count()) break;
      await page.waitForTimeout(1000);
      await page.reload();
    }
    await runs.getByText("Erfolgreich").first().waitFor({ timeout: 5000 });
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/agents.png`, fullPage: true });
    await page.getByRole("link", { name: "Einstellungen", exact: true }).click();
    await page.getByRole("heading", { name: "Einstellungen", level: 1 }).waitFor();
  });

  await step("Trend Research und Game Intelligence starten, Trends auf der Übersicht", async () => {
    await page.getByRole("link", { name: "Agenten", exact: true }).click();
    for (const agent of ["Trend Research", "Game Intelligence"]) {
      await page.getByRole("button", { name: `${agent} jetzt ausführen` }).click();
      await page.getByText(`${agent} wurde gestartet.`).waitFor();
      const runs = page.locator("section").filter({ hasText: `Letzte Läufe: ${agent}` });
      let done = false;
      for (let i = 0; i < 15 && !done; i++) {
        await page.getByRole("button", { name: agent, exact: true }).click();
        done = await runs
          .getByText("Erfolgreich")
          .first()
          .waitFor({ timeout: 2000 })
          .then(() => true)
          .catch(() => false);
        if (!done) await page.reload();
      }
      assert.ok(done, `${agent} did not finish successfully`);
    }
    await page.getByRole("link", { name: "Übersicht" }).click();
    const trends = page.locator("section").filter({ hasText: "Aktuelle Trends" });
    await trends.getByText("Testdaten", { exact: true }).waitFor();
    await trends.locator("tbody tr").nth(9).waitFor();
    await trends.getByText(/^Testdaten\. Top-Trend \(DE\)/).waitFor();
    await trends.getByRole("button", { name: "Englisch" }).click();
    await trends.getByText(/Top-Trend \(EN\)/).waitFor();
    await trends.locator("tbody tr").first().getByRole("button").first().click();
    await trends.getByText("Zielgruppe:").waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/trends.png`, fullPage: true });
    await page.getByRole("link", { name: "Einstellungen", exact: true }).click();
    await page.getByRole("heading", { name: "Einstellungen", level: 1 }).waitFor();
  });

  await step("Rechte: Lizenz mit Nachweis freigeben, Material wird geprüft und freigegeben", async () => {
    const tag = Date.now().toString(36);
    const sha = Array.from({ length: 64 }, () => "0123456789abcdef"[Math.floor(Math.random() * 16)]).join("");
    await page.getByRole("link", { name: "Rechte", exact: true }).click();
    await page.getByRole("heading", { name: "Rechte und Lizenzen", level: 1 }).waitFor();
    await page.getByRole("cell", { name: /Grand Theft Auto VI/ }).waitFor(); // seeded policy

    const sources = page.locator("section").filter({ hasText: "Quellen und Creator" });
    await sources.getByPlaceholder("Name des Creators").fill(`E2E Creator ${tag}`);
    await sources.getByRole("button", { name: "Creator anlegen" }).click();
    await sources.getByRole("listitem").filter({ hasText: `E2E Creator ${tag}` }).waitFor();
    await sources.getByPlaceholder("Name der Quelle").fill(`E2E Quelle ${tag}`);
    await sources.getByLabel("Creator", { exact: true }).selectOption({ label: `E2E Creator ${tag}` });
    await sources.getByPlaceholder("Herkunftsnotiz").fill("Lizenzvertrag E2E");
    await sources.getByRole("button", { name: "Quelle anlegen" }).click();
    await sources.getByRole("cell", { name: `E2E Quelle ${tag}` }).waitFor();

    const policies = page.locator("section").filter({ hasText: "Publisher-Richtlinien" });
    await policies.getByPlaceholder("Neues Spiel").fill(`E2E Spiel ${tag}`);
    await policies.getByRole("button", { name: "Spiel anlegen" }).click();
    await policies.getByLabel("Spiel der Richtlinie").selectOption({ label: `E2E Spiel ${tag}` });
    await policies.getByLabel("Richtlinie", { exact: true }).selectOption("permitted");
    await policies.getByPlaceholder("Begründung / Fundstelle").fill("Clips laut Richtlinie erlaubt");
    await policies.getByRole("button", { name: "Richtlinie speichern" }).click();
    await policies.getByRole("cell", { name: `E2E Spiel ${tag}` }).waitFor();

    const licenses = page.locator("section").filter({ hasText: "Lizenzen" }).first();
    await licenses.getByLabel("Quelle der Lizenz").selectOption({ label: `E2E Quelle ${tag}` });
    await licenses.getByRole("button", { name: "Lizenz anlegen" }).click();
    await licenses.getByText("Ohne Nachweis keine Freigabe.").waitFor();
    for (const label of ["Kommerziell", "Bearbeitung", "Kurzvideos", "Monetarisierung", "Musik freigegeben"]) {
      await licenses.getByLabel(label, { exact: true }).check();
    }
    for (const label of ["YouTube Shorts", "TikTok", "Instagram Reels", "Facebook Reels", "Deutsch", "Englisch"]) {
      await licenses.getByLabel(label, { exact: true }).check();
    }
    await licenses.getByRole("button", { name: "Bedingungen speichern" }).click();
    await licenses.getByLabel("Lizenzdokument").setInputFiles({
      name: "lizenz.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from(`%PDF-1.4\n% E2E ${tag}\n`),
    });
    await licenses.getByRole("button", { name: "Dokument hochladen" }).click();
    await licenses.getByText("Version 1: lizenz.pdf").waitFor();
    await licenses.getByRole("button", { name: "Lizenz freigeben" }).click();
    await licenses.getByText(/Geprüft am/).waitFor();

    const material = page.locator("section").filter({ hasText: "Material" }).first();
    const option = await page
      .getByLabel("Lizenz", { exact: true })
      .locator("option", { hasText: `E2E Quelle ${tag}` })
      .getAttribute("value");
    await material.getByLabel("Lizenz", { exact: true }).selectOption(option);
    await material.getByLabel("Spiel", { exact: true }).selectOption({ label: `E2E Spiel ${tag}` });
    await material.getByPlaceholder("Titel").fill(`E2E Material ${tag}`);
    await material.getByPlaceholder("Speicherort (z. B. r2://…)").fill(`mock://e2e/${tag}.mp4`);
    await material.getByPlaceholder("SHA-256 der Datei").fill(sha);
    await material.getByRole("button", { name: "Material registrieren" }).click();
    const row = material.locator("tr").filter({ hasText: `E2E Material ${tag}` });
    await row.getByText("Neu erfasst").waitFor();

    // Master dispatches the Material Scout, then the Rights & License Agent.
    let approved = false;
    for (let i = 0; i < 6 && !approved; i++) {
      await page.getByRole("link", { name: "Agenten", exact: true }).click();
      await page.getByRole("button", { name: "Master Orchestrator jetzt ausführen" }).click();
      await page.getByText("Master Orchestrator wurde gestartet.").waitFor();
      await page.waitForTimeout(2500);
      await page.getByRole("link", { name: "Rechte", exact: true }).click();
      approved = await page
        .locator("tr")
        .filter({ hasText: `E2E Material ${tag}` })
        .getByText("Freigegeben")
        .waitFor({ timeout: 2000 })
        .then(() => true)
        .catch(() => false);
    }
    assert.ok(approved, "material was not approved by the rights check");
    await page.getByRole("button", { name: `E2E Material ${tag}` }).click();
    const checks = page.getByRole("table", { name: /Rechteprüfung Material/ });
    await checks.getByText("Publisher-Richtlinie geprüft und erfüllt").waitFor();
    assert.equal(await checks.getByText("erfüllt", { exact: true }).count(), 12);
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/rights.png`, fullPage: true });
    await page.getByRole("link", { name: "Einstellungen", exact: true }).click();
    await page.getByRole("heading", { name: "Einstellungen", level: 1 }).waitFor();
  });

  await step("Automatische Veröffentlichung ist gesperrt", async () => {
    const auto = page.getByRole("switch", { name: "Automatische Veröffentlichung" });
    assert.equal(await auto.getAttribute("aria-checked"), "false");
    assert.equal(await auto.isDisabled(), true);
  });

  await step("Not-Aus aktivieren zeigt Warnbanner", async () => {
    await page.getByRole("switch", { name: "Not-Aus" }).click();
    await page.getByRole("switch", { name: "Not-Aus", checked: true }).waitFor();
    await page.getByRole("alert").filter({ hasText: "Not-Aus ist aktiv" }).waitFor();
    await page.getByRole("link", { name: "Übersicht" }).click();
    await page.getByRole("alert").filter({ hasText: "Not-Aus ist aktiv" }).waitFor();
  });

  await step("Not-Aus wieder lösen", async () => {
    await page.getByRole("link", { name: "Einstellungen" }).click();
    await page.getByRole("switch", { name: "Not-Aus", checked: true }).click();
    await page.getByRole("switch", { name: "Not-Aus", checked: false }).waitFor();
    await page.getByRole("alert").filter({ hasText: "Not-Aus ist aktiv" }).waitFor({ state: "detached" });
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/settings.png`, fullPage: true });
  });

  await step("Abmelden", async () => {
    await page.getByRole("button", { name: "Abmelden" }).click();
    await page.waitForURL("**/login");
    const res = await page.request.get(BASE + "/api/auth/me");
    assert.equal(res.status(), 401);
  });
  console.log(`\n${steps.length} E2E-Schritte bestanden`);
} catch (err) {
  console.error(`  FEHLER nach ${steps.length} Schritten:`, err.message);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/failure.png`, fullPage: true });
  process.exitCode = 1;
} finally {
  await browser.close();
}
