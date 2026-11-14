// End-to-end smoke test for the dashboard (Phase 3, agents since Phase 4, trends since Phase 5,
// rights management since Phase 6, video production since Phase 7).
// Phase 7 also needs FFmpeg on PATH to generate a synthetic test video.
// Needs a running dashboard (BASE_URL, default http://127.0.0.1:3000) wired to a
// backend with an admin account (E2E_EMAIL / E2E_PASSWORD) and a running queue
// worker (`python -m app.worker`) so that a manually started agent really runs.
// Optional: SCREENSHOT_DIR to save screenshots of the overview and settings pages.
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:3000";
const EMAIL = process.env.E2E_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_PASSWORD;
const SHOTS = process.env.SCREENSHOT_DIR;
assert.ok(PASSWORD, "E2E_PASSWORD must be set");

let rightsTag = ""; // licence and game created in the rights step, reused for production
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
    await page.getByText("Folgt in Phase 14").first().waitFor();
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
    await trends
      .getByText(/Trend-Score, letzte 30 Tage|Verlauf erscheint ab dem zweiten Trendlauf/)
      .first()
      .waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/trends.png`, fullPage: true });
    await page.getByRole("link", { name: "Einstellungen", exact: true }).click();
    await page.getByRole("heading", { name: "Einstellungen", level: 1 }).waitFor();
  });

  await step("Rechte: Lizenz mit Nachweis freigeben, Material wird geprüft und freigegeben", async () => {
    const tag = Date.now().toString(36);
    rightsTag = tag;
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

  await step("Videoproduktion: Upload bis geprüfte Variante mit Skript, Stimme, Untertiteln und Qualitätsprüfung", async () => {
    // Licence-free synthetic video: calm part, hard cut, loud action part, calm tail.
    const dir = mkdtempSync(join(tmpdir(), "gce-e2e-"));
    const video = join(dir, `gameplay-${rightsTag}.mp4`);
    const parts = [
      ["color=c=0x303840:s=1280x720:r=30:d=20", "sine=f=220:d=20:sample_rate=48000", 0.03],
      ["testsrc2=s=1280x720:r=30:d=15", "anoisesrc=c=pink:d=15:sample_rate=48000", 0.6],
      ["color=c=0x203020:s=1280x720:r=30:d=10", "sine=f=330:d=10:sample_rate=48000", 0.03],
    ];
    const inputs = parts.flatMap(([v]) => ["-f", "lavfi", "-i", v]);
    inputs.push(...parts.flatMap(([, a]) => ["-f", "lavfi", "-i", a]));
    const graph =
      parts.map(([, , vol], i) => `[${i + 3}:a]volume=${vol},aformat=channel_layouts=stereo[a${i}];`).join("") +
      parts.map((_, i) => `[${i}:v][a${i}]`).join("") +
      "concat=n=3:v=1:a=1[v][a]";
    const ff = spawnSync("ffmpeg", [
      "-v", "error", "-y", ...inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
      "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", video,
    ]);
    assert.equal(ff.status, 0, `ffmpeg failed: ${ff.stderr}`);

    // The whole pipeline of one upload needs about ten production jobs; leave headroom.
    await page.getByRole("link", { name: "Einstellungen", exact: true }).click();
    const ops = page.locator("form").filter({ has: page.getByLabel("Max. tägliche Produktionsjobs") });
    await ops.getByLabel("Max. tägliche Produktionsjobs").fill("500");
    await ops.getByLabel("Kreative Varianten je Clip (1–4)").fill("2");
    await ops.getByRole("button", { name: "Speichern" }).click();
    await ops.getByText("Gespeichert.").waitFor();

    await page.getByRole("link", { name: "Videoproduktion", exact: true }).click();
    await page.getByRole("heading", { name: "Videoproduktion", level: 1 }).waitFor();
    await page.getByLabel("Renderkapazität").waitFor();
    const upload = page.getByRole("form", { name: "Gameplay hochladen" });
    await upload.getByLabel("Videodatei").setInputFiles({
      name: `gameplay-${rightsTag}.mp4`,
      mimeType: "video/mp4",
      buffer: readFileSync(video),
    });
    const approvedIds = await upload
      .getByLabel("Lizenz", { exact: true })
      .locator("option", { hasText: "freigegeben" })
      .evaluateAll((opts) => opts.map((o) => Number(o.getAttribute("value"))));
    const option = String(Math.max(...approvedIds)); // the licence approved in the rights step
    await upload.getByLabel("Lizenz", { exact: true }).selectOption(option);
    await upload.getByLabel("Spiel", { exact: true }).selectOption({ label: `E2E Spiel ${rightsTag}` });
    await upload.getByPlaceholder("Titel").fill(`E2E Gameplay ${rightsTag}`);
    await upload.getByRole("button", { name: "Hochladen" }).click();
    const status = await page.getByRole("status").filter({ hasText: /Material #\d+ hochgeladen/ });
    await status.waitFor({ timeout: 60000 });
    const materialId = (await status.textContent())?.match(/Material #(\d+)/)?.[1];
    assert.ok(materialId, "upload did not report a material id");

    // Master dispatches scout, rights, analysis, rendering, concept, script, localization,
    // voice, subtitles and the quality check in turn. A re-run on the same database may
    // reject the variant as a duplicate of an earlier run; both outcomes show the check.
    const row = page.locator("tr").filter({ hasText: `#${materialId} ·` }).first();
    let scripted = false;
    for (let i = 0; i < 36 && !scripted; i++) {
      await page.getByRole("link", { name: "Agenten", exact: true }).click();
      await page.getByRole("button", { name: "Master Orchestrator jetzt ausführen" }).click();
      await page.getByText("Master Orchestrator wurde gestartet.").waitFor();
      await page.waitForTimeout(4000);
      await page.getByRole("link", { name: "Videoproduktion", exact: true }).click();
      await page.getByRole("heading", { name: "Videoproduktion", level: 1 }).waitFor();
      scripted = await row
        .getByText(/Bereit zur Veröffentlichung|Von Qualitätsprüfung abgelehnt/)
        .first()
        .waitFor({ timeout: 2000 })
        .then(() => true)
        .catch(() => false);
    }
    assert.ok(scripted, "the uploaded gameplay did not become a finished variant");
    await row.getByText(/×\d+, \d+(\.\d+)? fps/).waitFor();
    await row.getByRole("button", { name: /^Clip \d+$/ }).click();
    const preview = page.getByLabel(/^Vorschau Clip \d+$/);
    await preview.waitFor();
    await page.getByText("Szenenbewertung").waitFor();
    const script = page.getByLabel(/^Skript (DE|EN) A$/).first();
    await script.getByText("Hauptvariante").waitFor();
    await script.getByText(/Hook:/).waitFor();
    await script.getByText(/Vorlage \(kostenlos\)/).waitFor();
    await page.getByText(/Untertitel eingebrannt/).first().waitFor();
    const qc = page.getByLabel(/^Qualitätsprüfung (DE|EN) [A-D]$/).first();
    await qc.getByText(/Qualitätswert \d\.\d\d/).waitFor();
    await qc.getByText(/\d+ von \d+ Prüfungen bestanden/).waitFor();
    const final = page.getByLabel(/^Fertiges Video (DE|EN) [A-D]$/).first();
    const finalSize = await final.evaluate(
      (el) =>
        new Promise((resolve) => {
          const v = /** @type {HTMLVideoElement} */ (el);
          if (v.readyState >= 1) return resolve(v.videoWidth + "x" + v.videoHeight);
          v.addEventListener("loadedmetadata", () => resolve(v.videoWidth + "x" + v.videoHeight));
          v.addEventListener("error", () => resolve("error"));
        }),
    );
    assert.match(String(finalSize), /^(720x1280|1080x1920)$/);
    const playable = await preview.evaluate(
      (el) =>
        new Promise((resolve) => {
          const v = /** @type {HTMLVideoElement} */ (el);
          if (v.readyState >= 1) return resolve(v.videoWidth + "x" + v.videoHeight);
          v.addEventListener("loadedmetadata", () => resolve(v.videoWidth + "x" + v.videoHeight));
          v.addEventListener("error", () => resolve("error"));
        }),
    );
    assert.match(String(playable), /^(720x1280|1080x1920)$/);
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/production.png`, fullPage: true });
  });

  await step("Publishing: Strategie je Kanal mit Begründung, keine echten Posts", async () => {
    // The ready variant makes the master dispatch the strategy agent for its channel.
    let decided = false;
    for (let i = 0; i < 8 && !decided; i++) {
      await page.getByRole("link", { name: "Agenten", exact: true }).click();
      await page.getByRole("button", { name: "Master Orchestrator jetzt ausführen" }).click();
      await page.getByText("Master Orchestrator wurde gestartet.").waitFor();
      await page.waitForTimeout(2500);
      await page.getByRole("link", { name: "Publishing", exact: true }).click();
      await page.getByRole("heading", { name: "Publishing", level: 1 }).waitFor();
      decided = await page
        .getByText(/^Entscheidung:/)
        .first()
        .waitFor({ timeout: 2000 })
        .then(() => true)
        .catch(() => false);
    }
    assert.ok(decided, "the strategy agent made no decision for any channel");
    await page.getByText("Es gibt keine feste Menge.", { exact: false }).waitFor();
    await page.getByLabel("Begründung").first().waitFor();
    // seeded channels are paused, so nothing is planned and nothing is published
    await page.getByText("Kanal ist pausiert", { exact: true }).first().waitFor();
    await page.getByText("Test (keine echten Posts)").waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/publishing.png`, fullPage: true });
  });

  await step("Trendquellen zeigen Modus, Zugangsdaten und Status", async () => {
    await page.getByRole("link", { name: "Einstellungen", exact: true }).click();
    const sources = page.locator("section").filter({ hasText: "Trendquellen" });
    await sources.getByText("Testdaten (Mock)").waitFor();
    for (const label of ["YouTube Data API v3", "Twitch Helix", "Steam Web API"]) {
      await sources.getByRole("cell", { name: label }).waitFor();
    }
    await sources.getByText("Testdaten, keine Verbindung").first().waitFor(); // never "connected"
    assert.equal(await sources.getByText("Verbunden", { exact: true }).count(), 0);
    if (SHOTS) await sources.screenshot({ path: `${SHOTS}/trend-sources.png` });
  });

  await step("YouTube-Verbindung: ohne OAuth-Client keine Anmeldung, nichts verbunden", async () => {
    const channels = page.locator("section").filter({ hasText: "Kanäle und Sicherheitsgrenzen" });
    await channels.getByRole("columnheader", { name: "Verbindung" }).waitFor();
    const connect = channels.getByRole("button", { name: "Mit YouTube verbinden" }).first();
    await connect.click();
    await channels.getByText("YouTube-OAuth-Client ist nicht eingerichtet").waitFor();
    assert.ok(page.url().includes("/einstellungen"), "must not leave the dashboard");
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
