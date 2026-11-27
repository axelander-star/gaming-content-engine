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

/** One-page PDF with a real text layer, built by hand. */
function textPdf(text) {
  const stream = `BT /F1 12 Tf 72 720 Td (${text}) Tj ET`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let out = "%PDF-1.4\n";
  const offsets = [];
  objects.forEach((body, i) => {
    offsets.push(out.length);
    out += `${i + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = out.length;
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const off of offsets) out += `${String(off).padStart(10, "0")} 00000 n \n`;
  out += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
}

let rightsTag = ""; // licence and game created in the rights step, reused for production
const steps = [];
const step = async (name, fn) => {
  await fn();
  steps.push(name);
  console.log(`  OK  ${name}`);
};

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1360, height: 900 },
  deviceScaleFactor: 2,
});
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
    // seed channels are placeholders, not counted (stat card and platform tiles)
    await page.locator(".stat-value", { hasText: /^0 \/ 0$/ }).waitFor();
    await page.getByText("Bereit", { exact: true }).waitFor();
    for (const name of ["YouTube", "Twitch", "Instagram", "TikTok"]) {
      await page.getByRole("article", { name }).waitFor();
    }
    await page.getByText("Videos können nicht zu Twitch hochgeladen werden.").waitFor();
    await page.getByRole("heading", { name: "Status aller Videos" }).waitFor();
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

  await step("Agentenseite zeigt alle 26 Agenten", async () => {
    await page.getByRole("link", { name: "Agenten", exact: true }).click();
    await page.getByRole("heading", { name: "Agenten", level: 1 }).waitFor();
    await page.getByRole("button", { name: "Master Orchestrator", exact: true }).waitFor();
    const rows = page.locator("table").first().locator("tbody tr");
    await rows.nth(25).waitFor();
    assert.equal(await rows.count(), 26);
    assert.equal(await page.getByText(/Folgt in Phase/).count(), 0); // all 26 agents are built
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

  await step(
    "Rechte: Lizenz mit Nachweis freigeben, Material wird geprüft und freigegeben",
    async () => {
      const tag = Date.now().toString(36);
      rightsTag = tag;
      const sha = Array.from(
        { length: 64 },
        () => "0123456789abcdef"[Math.floor(Math.random() * 16)],
      ).join("");
      await page.getByRole("link", { name: "Rechte", exact: true }).click();
      await page.getByRole("heading", { name: "Rechte und Lizenzen", level: 1 }).waitFor();
      await page.getByRole("cell", { name: /Grand Theft Auto VI/ }).waitFor(); // seeded policy

      const sources = page.locator("section").filter({ hasText: "Quellen und Creator" });
      await sources.getByPlaceholder("Name des Creators").fill(`E2E Creator ${tag}`);
      await sources.getByRole("button", { name: "Creator anlegen" }).click();
      await sources
        .getByRole("listitem")
        .filter({ hasText: `E2E Creator ${tag}` })
        .waitFor();
      await sources.getByPlaceholder("Name der Quelle").fill(`E2E Quelle ${tag}`);
      await sources
        .getByLabel("Creator", { exact: true })
        .selectOption({ label: `E2E Creator ${tag}` });
      await sources.getByPlaceholder("Herkunftsnotiz").fill("Lizenzvertrag E2E");
      await sources.getByRole("button", { name: "Quelle anlegen" }).click();
      await sources.getByRole("cell", { name: `E2E Quelle ${tag}` }).waitFor();

      const policies = page.locator("section").filter({ hasText: "Publisher-Richtlinien" });
      await policies.getByPlaceholder("Neues Spiel").fill(`E2E Spiel ${tag}`);
      await policies.getByRole("button", { name: "Spiel anlegen" }).click();
      await policies.getByLabel("Spiel der Richtlinie").selectOption({ label: `E2E Spiel ${tag}` });
      await policies.getByLabel("Richtlinie", { exact: true }).selectOption("permitted");
      await policies
        .getByPlaceholder("Begründung / Fundstelle")
        .fill("Clips laut Richtlinie erlaubt");
      await policies.getByRole("button", { name: "Richtlinie speichern" }).click();
      await policies.getByRole("cell", { name: `E2E Spiel ${tag}` }).waitFor();

      const licenses = page.locator("section").filter({ hasText: "Lizenzen" }).first();
      await licenses.getByLabel("Quelle der Lizenz").selectOption({ label: `E2E Quelle ${tag}` });
      await licenses.getByRole("button", { name: "Lizenz anlegen" }).click();
      await licenses.getByText("Ohne Nachweis keine Freigabe.").waitFor();
      for (const label of [
        "Kommerziell",
        "Bearbeitung",
        "Kurzvideos",
        "Monetarisierung",
        "Musik freigegeben",
      ]) {
        await licenses.getByLabel(label, { exact: true }).check();
      }
      for (const label of [
        "YouTube Shorts",
        "TikTok",
        "Instagram Reels",
        "Facebook Reels",
        "Deutsch",
        "Englisch",
      ]) {
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
      await material
        .getByLabel("Spiel", { exact: true })
        .selectOption({ label: `E2E Spiel ${tag}` });
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
    },
  );

  await step(
    "Videoproduktion: Upload bis geprüfte Variante mit Skript, Stimme, Untertiteln und Qualitätsprüfung",
    async () => {
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
        parts
          .map(([, , vol], i) => `[${i + 3}:a]volume=${vol},aformat=channel_layouts=stereo[a${i}];`)
          .join("") +
        parts.map((_, i) => `[${i}:v][a${i}]`).join("") +
        "concat=n=3:v=1:a=1[v][a]";
      const ff = spawnSync("ffmpeg", [
        "-v",
        "error",
        "-y",
        ...inputs,
        "-filter_complex",
        graph,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        video,
      ]);
      assert.equal(ff.status, 0, `ffmpeg failed: ${ff.stderr}`);

      // The whole pipeline of one upload needs about ten production jobs; leave headroom.
      await page.getByRole("link", { name: "Einstellungen", exact: true }).click();
      const ops = page
        .locator("form")
        .filter({ has: page.getByLabel("Max. tägliche Produktionsjobs") });
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
      await upload
        .getByLabel("Spiel", { exact: true })
        .selectOption({ label: `E2E Spiel ${rightsTag}` });
      await upload.getByPlaceholder("Titel").fill(`E2E Gameplay ${rightsTag}`);
      await upload.getByRole("button", { name: "Hochladen" }).click();
      const status = await page
        .getByRole("status")
        .filter({ hasText: /Material #\d+ hochgeladen/ });
      await status.waitFor({ timeout: 60000 });
      const materialId = (await status.textContent())?.match(/Material #(\d+)/)?.[1];
      assert.ok(materialId, "upload did not report a material id");

      // Master dispatches scout, rights, analysis, rendering, concept, script, localization,
      // voice, subtitles and the quality check in turn. A re-run on the same database may
      // reject the variant as a duplicate of an earlier run; both outcomes show the check.
      const row = page
        .locator("tr")
        .filter({ hasText: `#${materialId} ·` })
        .first();
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
      await page
        .getByText(/Untertitel eingebrannt/)
        .first()
        .waitFor();
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
    },
  );

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

  await step("Analytics und Kosten: Filter, Diagramme, Lernstand und Budget", async () => {
    await page.getByRole("link", { name: "Analytics", exact: true }).click();
    await page.getByRole("heading", { name: "Analytics", level: 1 }).waitFor();
    const filters = page.getByRole("group", { name: "Filter" });
    for (const label of ["Zeitraum", "Plattform", "Sprache", "Spiel", "Format", "Hook"]) {
      await filters.getByRole("combobox", { name: label }).waitFor();
    }
    await page.getByRole("figure", { name: "Aufrufe", exact: true }).waitFor();
    await page.getByRole("figure", { name: "Aufrufe pro Spiel" }).waitFor();
    await page.getByText("Erkenntnisse (Learning Agent)").waitFor();
    await page.getByText("Hook-Tests und Gewinner").waitFor();
    await filters.getByRole("combobox", { name: "Zeitraum" }).selectOption("7");
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/analytics.png`, fullPage: true });
    await page.getByRole("link", { name: "Kosten", exact: true }).click();
    await page.getByRole("heading", { name: "Kosten", level: 1 }).waitFor();
    await page.getByText("Monatskosten gesamt", { exact: true }).waitFor();
    await page.getByText(/^Stand \d/).waitFor();
    await page.getByText("Budgetstufe:").waitFor();
    await page.getByRole("figure", { name: "Kosten im Monat" }).waitFor();
    const fixed = page.getByRole("table", { name: "Fixkosten" });
    await fixed.waitFor();
    await page.getByText("Posten hinzufügen").click();
    const form = page.getByRole("form", { name: "Neuen Fixkosten-Posten anlegen" });
    await form.getByRole("textbox", { name: "Name" }).fill("E2E Testposten");
    await form.getByRole("textbox", { name: "Betrag" }).fill("12,00");
    await form.getByRole("combobox", { name: "Zahlweise" }).selectOption("year");
    await form.getByRole("button", { name: "Speichern" }).click();
    const row = fixed.getByRole("row").filter({ hasText: "E2E Testposten" });
    await row.getByText("1,00 €").waitFor();
    await row.getByRole("button", { name: "Löschen" }).click();
    await row.waitFor({ state: "detached" });
    await page.getByRole("table", { name: "Token-Verbrauch" }).waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/kosten.png`, fullPage: true });
  });

  await step("KI-Schicht: Monatsgrenze sichtbar, Testaufruf im Mock-Modus kostenlos", async () => {
    const panel = page.locator("section").filter({ hasText: "KI-Nutzung (Claude)" });
    await panel.getByText("Test (Mock): keine Kosten").waitFor();
    await panel.getByText(/von 20,00\s\$ API-Monatsgrenze der Engine/).waitFor();
    await panel.getByText("claude-haiku-5-5").first().waitFor();
    await panel.getByText("claude-sonnet-5-5").first().waitFor();
    await panel.getByRole("button", { name: "KI testen" }).click();
    await panel.getByText("Testantwort (Mock)").waitFor();
    await panel.getByText(/\[Testantwort\] test:/).waitFor();
    await panel.getByText("Letzte Aufrufe").click();
    await panel.getByText("Testaufruf · claude-haiku-5-5 · Test").waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/ki-nutzung.png`, fullPage: true });
  });

  await step("System: Prüfungen, Datensicherung und Skalierung", async () => {
    await page.getByRole("link", { name: "System", exact: true }).click();
    await page.getByRole("heading", { name: "System", level: 1 }).waitFor();
    await page.getByText("Gesamtzustand:").waitFor();
    const checks = page.getByRole("table", { name: "Prüfungen" });
    for (const label of ["Datenbank", "Redis", "Worker", "Zeitsteuerung", "Datensicherung"]) {
      await checks.getByRole("cell", { name: label, exact: true }).waitFor();
    }
    await page.getByText("Wiederherstellungstest", { exact: true }).waitFor();
    await page.getByRole("list", { name: "Skalierungsempfehlung" }).waitFor();
    await page.getByRole("figure", { name: "CPU-Last je Kern (%)" }).waitFor();
    await page.getByRole("button", { name: "Neu prüfen" }).click();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/system.png`, fullPage: true });
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

  await step(
    "Plattform-Verbindungen: ohne App-Zugang keine Anmeldung, nichts verbunden",
    async () => {
      const channels = page.locator("section").filter({ hasText: "Kanäle und Sicherheitsgrenzen" });
      await channels.getByRole("columnheader", { name: "Verbindung" }).waitFor();
      const connect = channels.getByRole("button", { name: "Mit YouTube verbinden" }).first();
      await connect.click();
      await channels.getByText("YouTube-OAuth-Client ist nicht eingerichtet").waitFor();
      await channels.getByRole("button", { name: "Mit TikTok verbinden" }).first().click();
      await channels.getByText("TikTok-App ist nicht eingerichtet").waitFor();
      await channels.getByRole("button", { name: "Mit Instagram verbinden" }).first().click();
      await channels.getByText("Instagram-App ist nicht eingerichtet").waitFor();
      await channels.getByRole("button", { name: "Mit Facebook verbinden" }).first().click();
      await channels.getByText("Meta-App ist nicht eingerichtet").waitFor();
      assert.equal(await channels.getByText("Verbunden", { exact: true }).count(), 0);
      assert.ok(page.url().includes("/einstellungen"), "must not leave the dashboard");
    },
  );

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
    await page
      .getByRole("alert")
      .filter({ hasText: "Not-Aus ist aktiv" })
      .waitFor({ state: "detached" });
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/settings.png`, fullPage: true });
  });

  await step("Themenbereiche: Bereich und Kanal anlegen, Bereich pausieren", async () => {
    await page.getByRole("link", { name: "Themenbereiche", exact: true }).click();
    await page.getByRole("heading", { name: "Themenbereiche", level: 1 }).waitFor();
    await page.getByRole("article", { name: "Themenbereich Gaming" }).waitFor();
    // topic ideas from trends (sample data without live access), taken into the form
    await page.getByRole("button", { name: "Themen vorschlagen" }).click();
    await page.getByText(/Beispieldaten/).waitFor();
    const idea = page.getByRole("article", { name: /^Vorschlag / }).first();
    const ideaName = (await idea.getAttribute("aria-label")).replace(/^Vorschlag /, "");
    await idea.getByText("Zahlen dahinter").click();
    await idea.getByText(/Aufrufe pro Stunde/).first().waitFor();
    await idea.getByRole("button", { name: "Übernehmen" }).click();
    assert.equal(await page.getByLabel("Name", { exact: true }).inputValue(), ideaName);
    // the AI fills the rest of the form; a second click asks again
    await page.getByRole("button", { name: "Von der KI ausfüllen" }).click();
    await page.getByRole("button", { name: "Neu von der KI ausfüllen" }).waitFor();
    assert.ok((await page.getByLabel("Zielgruppe").inputValue()).length > 10);
    assert.ok((await page.getByLabel("Tonalität").inputValue()).length > 2);
    await page.getByRole("button", { name: "Abbrechen" }).click();
    await page.getByRole("button", { name: "Neuer Themenbereich" }).click();
    const form = page.locator("form.project-form");
    await form.getByLabel("Name").fill("Ernährung E2E");
    await form.getByLabel("Unterthemen (mit Komma getrennt)").fill("Rezepte, Lebensmittelwissen");
    await form.getByRole("button", { name: "Anlegen" }).click();
    const card = page.getByRole("article", { name: "Themenbereich Ernährung E2E" });
    await card.getByText("Lebensmittelwissen").waitFor();
    const newChannel = page.getByRole("form", { name: "Neuer Kanal" });
    await newChannel.getByLabel("Kanalname").fill("YouTube Ernährung E2E");
    await newChannel
      .getByLabel("Themenbereich des neuen Kanals")
      .selectOption({ label: "Ernährung E2E" });
    await newChannel.getByRole("button", { name: "Kanal anlegen" }).click();
    const select = page.getByLabel("Themenbereich von YouTube Ernährung E2E");
    await select.waitFor();
    const selected = await select.evaluate((el) => el.options[el.selectedIndex].text);
    assert.equal(selected, "Ernährung E2E");
    await card.getByText("1", { exact: true }).first().waitFor();
    await card.getByRole("button", { name: "Pausieren" }).click();
    await card.getByText("Pausiert", { exact: true }).waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/themenbereiche.png`, fullPage: true });
  });

  await step("Plan per Chat ändern: Bereich fortsetzen, Tag einplanen, rückgängig", async () => {
    await page.getByRole("link", { name: "Assistent", exact: true }).click();
    await page.getByRole("heading", { name: "Assistent", level: 1 }).waitFor();
    await page.getByText("Test (Mock): Befehlserkennung, keine Kosten").waitFor();
    const input = page.getByLabel("Nachricht an den Assistenten");
    const log = page.locator(".chat-log");
    const plan = page.getByRole("list", { name: "Wochenplan" });

    await input.fill("Ernährung E2E fortsetzen");
    await page.getByRole("button", { name: "Senden" }).click();
    await log.getByText("Themenbereich Ernährung E2E fortgesetzt").first().waitFor();

    await input.fill("Heute zusätzlich Ernährung E2E");
    await input.press("Enter");
    const card = page.getByRole("group", { name: "Aktion" }).filter({ hasText: "eingeplant" });
    await card.waitFor();
    await plan.getByText("Ernährung E2E").waitFor();
    await card.getByRole("button", { name: "Rückgängig" }).click();
    await card.getByText("Rückgängig gemacht").waitFor();
    await plan.getByText("Ernährung E2E").waitFor({ state: "detached" });

    await input.fill("Diese Woche GTA 6");
    await input.press("Enter");
    await page.locator(".focus-list").getByText("GTA 6").waitFor();

    await input.fill("Veröffentliche das Video jetzt");
    await input.press("Enter");
    await log.getByText(/Veröffentlichen kann ich nicht/).last().waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/assistent.png`, fullPage: true });
  });

  // area of the idea taken over today; the plan step below finds it in today's cell
  let ideaArea = "Ernährung E2E";
  await step("Ideenlabor: Recherche starten, Idee übernehmen", async () => {
    await page.getByRole("link", { name: "Ideenlabor", exact: true }).click();
    await page.getByRole("heading", { name: "Ideenlabor", level: 1 }).waitFor();
    await page.getByText("Test: Beispiel-Feeds, kein Abruf").waitFor();
    await page.getByRole("button", { name: "Recherche starten" }).click();
    const researchStarted = Date.now();
    // progress lives on the server: visible right away and after leaving the page
    await page.getByRole("status").getByText(/Recherche läuft im Hintergrund|Fertig: /).waitFor();
    await page.getByRole("link", { name: "Übersicht" }).click();
    await page.getByRole("link", { name: "Ideenlabor", exact: true }).click();
    await page.getByRole("heading", { name: "Ideenlabor", level: 1 }).waitFor();
    await page.getByRole("status").getByText(/Recherche läuft im Hintergrund|Fertig: /).waitFor();
    await page.getByText(/Fertig: \d+ neue Idee/).waitFor({ timeout: 30000 });
    const cards = page.getByRole("article", { name: /^Idee / });
    await cards.first().waitFor({ timeout: 30000 });
    // five per page, best ranking first, with pages and a sort choice
    await cards.nth(4).waitFor();
    assert.equal(await cards.count(), 5);
    await page.getByText(/Seite 1 von \d+/).waitFor();
    assert.equal(await page.getByText("#1", { exact: true }).count(), 1);
    await page.getByRole("button", { name: "Weiter →" }).click();
    await page.getByText(/Seite 2 von \d+/).waitFor();
    await page.getByText("#6", { exact: true }).waitFor();
    await page.getByRole("button", { name: "← Zurück" }).click();
    await page.getByText(/Seite 1 von \d+/).waitFor();
    await page.getByLabel("Sortieren nach").selectOption("title");
    await page.getByLabel("Sortieren nach").selectOption("score");
    await page.getByText("#1", { exact: true }).waitFor();
    // the heading also shows the rank (#1), the card's label is the plain title; ideas of
    // other areas may still arrive and reorder the list, so keep to this card by name
    // research for other areas may still be running: keep to one area, its ideas are
    // stored together, so this list no longer changes
    // the page reloads the list 3, 8 and 15 s after the start; ideas that arrive in
    // between can push a card to page 2. Pick the card only after the last reload.
    await page.waitForTimeout(Math.max(0, researchStarted + 16000 - Date.now()));
    const area = (await cards.first().locator(".chip").first().textContent()).trim();
    ideaArea = area;
    await page.locator(".toolbar").getByLabel("Themenbereich").selectOption({ label: area });
    await page.getByText(/Seite 1 von \d+/).waitFor();
    const title = (await cards.first().getAttribute("aria-label")).replace(/^Idee /, "");
    const card = page.getByRole("article", { name: `Idee ${title}` });
    await card.getByText("Rechte-Risiko", { exact: true }).waitFor();
    await card.getByText(/^Quellen \(\d+\)$/).click();
    await card.getByRole("link").first().waitFor();
    const today = new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Berlin" });
    await card.getByLabel("Tag im Plan (optional)").fill(today);
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/ideenlabor.png`, fullPage: true });
    await card.getByRole("button", { name: "Übernehmen" }).click();
    await page.getByRole("article", { name: `Idee ${title}` }).waitFor({ state: "detached" });
    await page.getByRole("tab", { name: "Übernommen" }).click();
    await page.getByRole("article", { name: `Idee ${title}` }).getByText(/Übernommen für/).waitFor();
    await page.getByRole("link", { name: "Assistent", exact: true }).click();
    await page.getByRole("list", { name: "Wochenplan" }).locator(".is-today .chip").first().waitFor();
  });

  await step("Trend-Alarm: Test-Alarm mit Zahlen und Entwürfen, verwerfen", async () => {
    await page.getByRole("link", { name: "Trend-Alarm", exact: true }).click();
    await page.getByRole("heading", { name: "Trend-Alarm", level: 1 }).waitFor();
    await page.getByText("Test: Beispieldaten").waitFor();
    await page.getByText(/TREND_AUTOPILOT_ENABLED=false/).waitFor();
    await page.getByRole("button", { name: "Jetzt prüfen" }).click();
    await page.getByText(/Prüfung mit Testdaten läuft/).waitFor();
    const alarm = page.getByRole("region", { name: /^Trend-Alarm / }).first();
    await alarm.waitFor({ timeout: 70000 });
    await alarm.getByText(/Aufrufe in \d+ Stunden/).waitFor();
    await alarm.getByText("Kurz erklärt", { exact: true }).waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/trend-alarm.png`, fullPage: true });
    await alarm.getByRole("button", { name: "Alarm verwerfen" }).click();
    await alarm.getByText("Verworfen", { exact: true }).waitFor();
    // one test alarm per topic area: dismiss the rest so their drafts are not rendered
    const more = page.getByRole("button", { name: "Alarm verwerfen" });
    for (let n = await more.count(); n > 0; n = await more.count()) {
      await more.first().click();
      for (let i = 0; i < 50 && (await more.count()) >= n; i++) await page.waitForTimeout(200);
    }
  });

  await step("Redaktionsplan: Bereich einplanen, verschieben, entfernen", async () => {
    await page.getByRole("link", { name: "Redaktionsplan", exact: true }).click();
    await page.getByRole("heading", { name: "Redaktionsplan", level: 1 }).waitFor();
    const label = (d) =>
      new Intl.DateTimeFormat("de-DE", {
        weekday: "long",
        day: "2-digit",
        month: "2-digit",
        timeZone: "UTC",
      }).format(new Date(`${d}T12:00:00Z`));
    const today = new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Berlin" });
    const t = new Date(`${today}T12:00:00Z`);
    t.setUTCDate(t.getUTCDate() + (t.getUTCDay() === 1 ? 1 : -1)); // stay in this week
    const target = t.toISOString().slice(0, 10);
    const todayCell = page.getByRole("group", { name: label(today) });
    const other = ideaArea === "Gaming" ? "Ernährung E2E" : "Gaming";
    await todayCell.getByRole("button", { name: `Eintrag ${ideaArea}` }).waitFor();
    await todayCell.getByRole("button", { name: /einplanen$/ }).click();
    await todayCell.getByRole("combobox").selectOption({ label: other });
    await todayCell.getByRole("button", { name: "Einplanen", exact: true }).click();
    await todayCell.getByRole("button", { name: `Eintrag ${other}` }).click();
    const editor = page.getByRole("form", { name: `${other} bearbeiten` });
    await editor.getByLabel("Verschieben auf").fill(target);
    await editor.getByRole("button", { name: "Speichern" }).click();
    const targetCell = page.getByRole("group", { name: label(target) });
    await targetCell.getByRole("button", { name: `Eintrag ${other}` }).waitFor();
    await todayCell.getByRole("button", { name: `Eintrag ${other}` }).waitFor({ state: "detached" });
    await page.locator("section").filter({ hasText: "Schwerpunkte" }).getByText("GTA 6").waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/redaktionsplan.png`, fullPage: true });
    await targetCell.getByRole("button", { name: `Eintrag ${other}` }).click();
    await page.getByRole("button", { name: "Aus dem Plan nehmen" }).click();
    await targetCell.getByRole("button", { name: `Eintrag ${other}` }).waitFor({ state: "detached" });
    await page.getByRole("tab", { name: "Monat" }).click();
    await page.locator(".cal-month").waitFor();
  });

  await step("Mediathek und Eigenproduktion: Bild hochladen, Video erzeugen", async () => {
    const dir = mkdtempSync(join(tmpdir(), "gce-e2e-lib-"));
    const image = join(dir, `kueche-${rightsTag}.png`);
    const ff = spawnSync("ffmpeg", [
      "-v",
      "error",
      "-y",
      "-f",
      "lavfi",
      "-i",
      "testsrc2=s=800x600",
      "-frames:v",
      "1",
      image,
    ]);
    assert.equal(ff.status, 0, String(ff.stderr));
    await page.getByRole("link", { name: "Mediathek", exact: true }).click();
    await page.getByRole("heading", { name: "Mediathek", level: 1 }).waitFor();
    const form = page.getByRole("form", { name: "Datei hochladen" });
    await form.getByRole("combobox").selectOption({ label: "Ernährung E2E" });
    await form.getByLabel("Datei", { exact: true }).setInputFiles(image);
    await form.getByLabel("Titel (optional)").fill("Küchenbild");
    await form.getByRole("checkbox").check();
    await form.getByRole("button", { name: "Hochladen" }).click();
    await page.getByText(/gespeichert\. Vorschau und Hochformat/).waitFor({ timeout: 30000 });
    const card = page.getByRole("article", { name: "Datei Küchenbild" });
    await card.getByText("Hochformat 9:16 fertig", { exact: false }).waitFor({ timeout: 30000 });
    await card.locator(".lib-thumb img").waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/mediathek.png`, fullPage: true });

    await page.getByRole("link", { name: "Eigenproduktion", exact: true }).click();
    await page.getByRole("heading", { name: "Eigenproduktion", level: 1 }).waitFor();
    await page.getByRole("tab", { name: "Einzelvideos" }).click();
    const create = page.getByRole("form", { name: "Neue Produktion" });
    await create.getByLabel("Themenbereich").selectOption({ label: "Ernährung E2E" });
    await create.getByRole("textbox", { name: "Thema" }).fill("Haferflocken richtig lagern");
    await create.getByRole("button", { name: "Skript erstellen" }).click();
    const first = page.getByRole("listitem", { name: "Abschnitt 1" });
    await first.getByLabel("Überschrift im Bild").waitFor();
    await first.getByRole("combobox").selectOption({ label: "Küchenbild" });
    await page.getByRole("button", { name: "Video erzeugen" }).click();
    await page.getByLabel("Fertiges Video").waitFor({ timeout: 90000 });
    await page.getByText(/gerendert in/).waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/eigenproduktion.png`, fullPage: true });

    await page.getByRole("link", { name: "Mediathek", exact: true }).click();
    await page.getByRole("article", { name: "Datei Haferflocken richtig lagern" })
      .getByText("Selbst erzeugt").waitFor();
  });

  await step("Freigabecenter: Beitrag vorbereiten, Texte prüfen, freigeben", async () => {
    await page.getByRole("link", { name: "Freigabecenter", exact: true }).click();
    await page.getByRole("heading", { name: "Freigabecenter", level: 1 }).waitFor();
    await page.getByText(/Testbetrieb: Freigegebene Beiträge werden nur simuliert/).waitFor();
    await page.getByText(/Twitch: Twitch bietet keine offizielle Schnittstelle/).waitFor();
    const form = page.getByRole("form", { name: "Beitrag vorbereiten" });
    await form.getByLabel("Themenbereich").selectOption({ label: "Ernährung E2E" });
    const video = form.getByLabel("Video");
    await video.locator("option", { hasText: "Haferflocken richtig lagern" }).waitFor({ state: "attached" });
    await video.selectOption({ label: "Haferflocken richtig lagern" });
    await form.getByLabel(/YouTube Ernährung E2E/).check();
    await form.getByRole("button", { name: "Beiträge vorbereiten" }).click();
    const card = page.getByRole("article", { name: "Beitrag YouTube Ernährung E2E" });
    await card.getByText("Wartet auf Freigabe").waitFor({ timeout: 30000 });
    const texts = card.getByRole("form", { name: "Texte YouTube Ernährung E2E" });
    await texts.getByLabel("Hashtags").fill("#Hafer #Vorrat");
    await texts.getByRole("button", { name: "Texte speichern" }).click();
    await card.getByText(/technisch in Ordnung/).click();
    await card.locator(".appr-preview-text").getByText("#Hafer #Vorrat").waitFor();
    await card.getByLabel("Sichtbarkeit").selectOption("unlisted");
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/freigabecenter.png`, fullPage: true });
    await card.getByRole("button", { name: "Freigeben" }).click();
    await page.getByRole("tab", { name: /Freigegeben/ }).click();
    await card.getByText("Freigegeben", { exact: true }).waitFor();
    await card.getByRole("button", { name: "Freigabe zurückziehen" }).click();
    await page.getByRole("tab", { name: /Zu prüfen/ }).click();
    await card.getByText("Wartet auf Freigabe").waitFor();
  });

  await step("Kampagnen: Content-Rewards-Kampagne anlegen, pausieren, fortsetzen", async () => {
    await page.getByRole("link", { name: "Kampagnen", exact: true }).click();
    await page.getByRole("heading", { name: "Kampagnen", level: 1 }).waitFor();
    await page.getByText(/Keine offenen Links/).waitFor();
    const form = page.getByRole("form", { name: "Neue Kampagne" });
    await form
      .getByLabel(/^Text der Kampagnenseite einfügen/)
      .fill(
        "Streamer E2E Highlights\nhttps://contentrewards.com/e2e\n" +
          "Earn $1.50 per 1,000 views. YouTube Shorts, English.\n" +
          "Clips max 45 seconds. Use #ad #StreamerE2E\nShow the best moments of the stream.",
      );
    await form.getByRole("button", { name: "Formular automatisch ausfüllen" }).click();
    await form.getByText(/Angaben übernommen/).waitFor();
    assert.equal(await form.getByLabel("Name", { exact: true }).inputValue(), "Streamer E2E Highlights");
    assert.equal(
      await form.getByLabel("Kampagnenseite (Content Rewards)").inputValue(),
      "https://contentrewards.com/e2e",
    );
    assert.equal(await form.getByLabel("Höchstlänge (s)").inputValue(), "45");
    // The project list may load after the first pick and reset it; pick until it sticks.
    const ytEn = form.getByLabel(/YouTube Shorts EN \(/);
    for (let i = 0; i < 5 && !(await ytEn.count()); i++) {
      await form.getByLabel("Themenbereich").selectOption({ label: "Gaming" });
      await page.waitForTimeout(300);
    }
    await form.getByLabel("$ pro 1.000 Aufrufe").fill("1,5");
    await form.getByLabel("Pflicht-Hashtags").fill("#StreamerE2E");
    await form.getByLabel(/YouTube Shorts EN \(/).check();
    const create = form.getByRole("button", { name: "Kampagne anlegen" });
    assert.equal(await create.isDisabled(), true); // rules not confirmed yet
    await form.getByLabel(/Ich habe die Kampagnenregeln gelesen/).check();
    await create.click();
    const card = page.getByRole("article", { name: "Kampagne Streamer E2E Highlights" });
    await card.getByText("1,5 $ / 1.000 Aufrufe").waitFor();
    await card.getByText("#ad #StreamerE2E", { exact: true }).waitFor();
    await card.getByText(/Nächster Schritt:/).waitFor();
    // Bookmark "Ins Studio": the campaign page text arrives in the URL and fills the form.
    await page.getByText("Noch schneller: Lesezeichen „Ins Studio“").click();
    const href = await page.getByRole("link", { name: "Ins Studio" }).getAttribute("href");
    assert.ok(href?.startsWith("javascript:") && href.includes("/kampagnen#import="));
    const handed =
      "https://contentrewards.com/c/bookmark-e2e\nBookmark E2E Clips\n" +
      "Earn $2 per 1,000 views on TikTok. English. Max 30 seconds. #ad #BookmarkE2E";
    await page.goto(`${BASE}/kampagnen#import=${encodeURIComponent(handed)}`);
    const form2 = page.getByRole("form", { name: "Neue Kampagne" });
    await form2.getByText(/Angaben übernommen/).waitFor();
    assert.equal(await form2.getByLabel("Höchstlänge (s)").inputValue(), "30");
    assert.equal(
      await form2.getByLabel("Kampagnenseite (Content Rewards)").inputValue(),
      "https://contentrewards.com/c/bookmark-e2e",
    );
    assert.equal(new URL(page.url()).hash, "");
    await card.getByText("Videovorschläge (3)").click();
    await card.getByRole("button", { name: "Neue Vorschläge schreiben" }).waitFor();
    await card.getByRole("form", { name: "Material für Streamer E2E Highlights" }).waitFor();
    await card.getByRole("button", { name: "Pausieren" }).click();
    await card.getByText("Pausiert", { exact: true }).waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/kampagnen.png`, fullPage: true });
    await card.getByRole("button", { name: "Aktivieren" }).click();
    await card.getByText("Aktiv", { exact: true }).waitFor();
  });

  await step("Kanal-Assistent: fehlende Kanäle vorbereiten, anpassen, abschließen", async () => {
    await page.getByRole("link", { name: "Kanal-Assistent", exact: true }).click();
    await page.getByRole("heading", { name: "Kanal-Assistent", level: 1 }).waitFor();
    const area = page.getByRole("article", { name: "Themenbereich Ernährung E2E" });
    await area.getByText("Angelegt, nicht verbunden").waitFor();
    await area.getByRole("button", { name: "2 fehlende vorbereiten" }).click();
    await page.getByText("2 Kanäle vorbereitet.").waitFor();
    const tiktok = page.getByRole("article", { name: "Aufgabe TikTok DE: Ernährung E2E" });
    await tiktok.getByRole("link", { name: "Bei TikTok registrieren" }).waitFor();
    await tiktok.getByRole("img", { name: /^Profilbild / }).waitFor();
    await tiktok.getByLabel(/^Benutzername/).waitFor();
    await tiktok.getByRole("button", { name: "Werte ändern" }).click();
    const form = tiktok.getByRole("form", { name: "Werte TikTok DE: Ernährung E2E" });
    await form.getByLabel("Name", { exact: true }).fill("Küchenwissen E2E");
    await form.getByLabel("Benutzername", { exact: true }).fill("Küchen Wissen");
    await form.getByRole("button", { name: "Speichern" }).click();
    await form.waitFor({ state: "detached" });
    assert.equal(await tiktok.getByLabel("Name", { exact: true }).inputValue(), "Küchenwissen E2E");
    assert.equal(await tiktok.getByLabel(/^Benutzername/).inputValue(), "kuechen_wissen");
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/kanal-assistent.png`, fullPage: true });
    const insta = page.getByRole("article", { name: "Aufgabe Instagram DE: Ernährung E2E" });
    await insta.getByText(/professionelles Konto/).waitFor({ state: "attached" });
    // names are based on market data; the basis is shown and can be refreshed
    await insta.getByText("Datengrundlage").waitFor();
    await Promise.all([
      page.waitForResponse((r) => r.url().endsWith("/research") && r.status() === 200),
      insta.getByRole("button", { name: "Neu recherchieren" }).click(),
    ]);
    await insta.getByRole("button", { name: "Nicht gebraucht" }).click();
    await insta.waitFor({ state: "detached" });
    await tiktok.getByRole("button", { name: "Kanal ist angelegt" }).click();
    await page.getByText(/^Kanal angelegt\./).waitFor();
    await tiktok.waitFor({ state: "detached" });
    assert.equal(await area.getByText("Angelegt, nicht verbunden").count(), 2);

    // a placeholder channel (seed) can be prepared on its own and becomes the real one later
    const gaming = page.getByRole("article", { name: "Themenbereich Gaming" });
    await gaming.getByText("Platzhalter, noch kein Konto").first().waitFor();
    await gaming.getByRole("button", { name: "6 fehlende vorbereiten" }).waitFor();
    await gaming.getByRole("button", { name: "YouTube Shorts DE vorbereiten" }).click();
    await page.getByText("Kanal vorbereitet. Die Aufgabe steht oben.").waitFor();
    const yt = page.getByRole("article", { name: "Aufgabe YouTube DE: Gaming" });
    await yt.getByRole("img", { name: /^Profilbild / }).waitFor();
    await gaming.getByText("Vorbereitet").waitFor();
    await yt.getByRole("button", { name: "Nicht gebraucht" }).click();
    await yt.waitFor({ state: "detached" });
  });

  await step("Konten: filtern, suchen, Einnahme eintragen", async () => {
    await page.getByRole("link", { name: "Konten", exact: true }).click();
    await page.getByRole("heading", { name: "Konten", level: 1 }).waitFor();
    await page.getByText("Einnahmen (30 Tage)").waitFor();
    await page.getByLabel("Plattform").selectOption("tiktok");
    await page.getByLabel("Suche").fill("Küchenwissen");
    const row = page.getByRole("row", { name: /Küchenwissen E2E/ });
    await row.getByText("Noch verbinden").waitFor();
    await row.getByRole("button", { name: "Details Küchenwissen E2E" }).click();
    const form = page.getByRole("form", { name: "Einnahme für Küchenwissen E2E" });
    await form.getByLabel("Betrag in €").fill("12,50");
    await form.getByRole("button", { name: "Einnahme speichern" }).click();
    await page.getByText(/Affiliate: 12,50/).waitFor();
    await row.getByText(/^12,50\s€$/).first().waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/konten.png`, fullPage: true });
  });

  await step("Kommentare: TikTok-Kommentar einfügen, Antwort kopieren, erledigen", async () => {
    await page.getByRole("link", { name: "Kommentare", exact: true }).click();
    await page.getByRole("heading", { name: "Kommentare", level: 1 }).waitFor();
    await page.getByText(/Antworten werden nur simuliert/).waitFor();
    const form = page.getByRole("form", { name: "TikTok-Kommentar einfügen" });
    await form.getByLabel("Kanal").selectOption({ label: "Küchenwissen E2E" });
    await form.getByLabel("Name (optional)").fill("Lena");
    await form.getByLabel("Kommentar").fill("Wie lange hält sich Hafer?");
    await form.getByRole("button", { name: "Antwort vorschlagen" }).click();
    const card = page.getByRole("article", { name: "Kommentar von Lena" });
    await card.getByText(/TikTok hat keine Schnittstelle|Selbst eingefügt/).waitFor();
    assert.ok((await card.getByLabel("Antwort").inputValue()).length > 5);
    await card.getByRole("button", { name: "Antwort kopieren" }).waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/kommentare.png`, fullPage: true });
    await card.getByRole("button", { name: "Erledigt" }).click();
    await card.waitFor({ state: "detached" });
    await page.getByRole("tab", { name: /Beantwortet/ }).click();
    await page.getByRole("article", { name: "Kommentar von Lena" }).waitFor();
  });

  await step("Assistent: PDF anhängen, Antwort vorlesen; Hinweise und Test-Push", async () => {
    await page.getByRole("link", { name: "Assistent", exact: true }).click();
    await page.getByRole("heading", { name: "Assistent", level: 1 }).waitFor();
    await page.locator("[data-testid=chat-file]").setInputFiles({
      name: "angebot.pdf",
      mimeType: "application/pdf",
      buffer: textPdf("Kooperation Uhren 300 Euro"),
    });
    const pending = page.getByLabel("Angehängte Dateien");
    await pending.getByText("angebot.pdf · 1 S.").waitFor();
    await page.getByLabel("Nachricht an den Assistenten").fill("Was steht drin?");
    await page.getByRole("button", { name: "Senden" }).click();
    const log = page.locator(".chat-log");
    await log.getByText(/angebot\.pdf.*gelesen/).waitFor();
    await log.getByText("Kooperation Uhren 300 Euro", { exact: false }).first().waitFor();
    await log.getByRole("link", { name: /PDF angebot\.pdf/ }).waitFor();
    await log.getByRole("button", { name: "Vorlesen" }).last().waitFor();
    await page.getByLabel("Antworten vorlesen").waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/assistent-dateien.png`, fullPage: true });

    await page.getByRole("button", { name: /^Hinweise/ }).click();
    const panel = page.getByRole("dialog", { name: "Hinweise" });
    await panel.getByText(/Push aufs Handy ist noch aus/).waitFor();
    await panel.getByRole("button", { name: "Test-Push" }).click();
    await panel.getByText("Testmodus: nichts gesendet.").waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/hinweise.png` });
    await page.keyboard.press("Escape");
    await panel.waitFor({ state: "detached" });
  });

  await step("Redaktionsplan: feste Regel, eigener Termin; Konkurrenz-Radar prüfen", async () => {
    await page.getByRole("link", { name: "Redaktionsplan", exact: true }).click();
    await page.getByRole("heading", { name: "Redaktionsplan", level: 1 }).waitFor();
    await page.getByRole("tab", { name: "Woche" }).click();
    const today = new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Berlin" });
    const weekday = (new Date(`${today}T12:00:00Z`).getUTCDay() + 6) % 7; // 0 = Monday
    const names = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
    const ruleForm = page.getByRole("form", { name: "Neue Regel" });
    await ruleForm.getByLabel("Themenbereich").selectOption({ label: "Gaming" });
    await ruleForm.getByLabel("Wochentag").selectOption({ label: names[weekday] });
    await ruleForm.getByRole("button", { name: "Regel anlegen" }).click();
    await page
      .getByRole("list", { name: "Feste Regeln" })
      .getByText(`jeden ${names[weekday]}: Gaming`)
      .waitFor();
    await page.getByRole("button", { name: "Eintrag Gaming (Regel)" }).first().waitFor();

    const evForm = page.getByRole("form", { name: "Eigener Termin" });
    await evForm.getByLabel("Termin").fill("E2E Uhrenmesse");
    await evForm.getByLabel("Datum").fill(today);
    await evForm.getByRole("button", { name: "Termin eintragen" }).click();
    await page.locator(".cal-grid .cal-event", { hasText: "E2E Uhrenmesse" }).waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/redaktionsplan-regeln.png`, fullPage: true });

    await page.getByRole("link", { name: "Konkurrenz-Radar", exact: true }).click();
    await page.getByRole("heading", { name: "Konkurrenz-Radar", level: 1 }).waitFor();
    const form = page.getByRole("form", { name: "Kanal beobachten" });
    await form.getByLabel("Themenbereich").selectOption({ label: "Gaming" });
    await form.getByLabel("YouTube-Kanal").fill("https://www.youtube.com/@e2ekanal");
    await form.getByRole("button", { name: "Beobachten" }).click();
    await page.getByRole("list", { name: "Beobachtete Kanäle" }).getByText("@e2ekanal").first().waitFor();
    await page.getByRole("button", { name: "Jetzt prüfen" }).click();
    await page.getByText(/Prüfung gestartet/).waitFor();
    const standouts = page.getByRole("list", { name: "Auffällige Videos" });
    for (let i = 0; i < 30 && !(await standouts.count()); i++) {
      await page.waitForTimeout(1000);
      await page.reload();
      await page.getByRole("heading", { name: "Konkurrenz-Radar", level: 1 }).waitFor();
    }
    await standouts.getByText("Im Ideenlabor").first().waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/konkurrenz.png`, fullPage: true });
  });

  await step("Langes Video in Shorts zerlegen, englische Fassung, überall vorbereiten", async () => {
    const dir = mkdtempSync(join(tmpdir(), "gce-e2e-split-"));
    const long = join(dir, `stream-${rightsTag}.mp4`);
    const ff = spawnSync("ffmpeg", [
      "-v", "error", "-y",
      "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=40",
      "-f", "lavfi", "-i", "color=c=0x303840:s=640x360:r=25:d=25",
      "-f", "lavfi", "-i", "anoisesrc=c=pink:d=65",
      "-filter_complex", "[1:v][0:v]concat=n=2:v=1:a=0[v]",
      "-map", "[v]", "-map", "2:a", "-shortest",
      "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", long,
    ]);
    assert.equal(ff.status, 0, String(ff.stderr));
    await page.getByRole("link", { name: "Mediathek", exact: true }).click();
    await page.getByRole("heading", { name: "Mediathek", level: 1 }).waitFor();
    const form = page.getByRole("form", { name: "Datei hochladen" });
    await form.getByRole("combobox").selectOption({ label: "Ernährung E2E" });
    await form.getByLabel("Datei", { exact: true }).setInputFiles(long);
    await form.getByLabel("Titel (optional)").fill("Langer Stream");
    await form.getByRole("checkbox").check();
    await form.getByRole("button", { name: "Hochladen" }).click();
    const card = page.getByRole("article", { name: "Datei Langer Stream" });
    await card.getByRole("button", { name: "In Shorts zerlegen" }).click({ timeout: 90000 });
    const split = card.getByRole("form", { name: "Langer Stream zerlegen" });
    await split.getByLabel("Shorts").fill("2");
    await split.getByLabel("Länge (s)").fill("15");
    await split.getByRole("button", { name: "Zerlegen" }).click();
    await card.getByText("In 2 Shorts zerlegt", { exact: false }).waitFor({ timeout: 120000 });
    const part = page.getByRole("article", { name: "Datei Langer Stream – Teil 1" });
    await part.getByText(/Ausschnitt \d+:\d\d–\d+:\d\d/).waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/mediathek-zerlegt.png`, fullPage: true });

    await page.getByRole("link", { name: "Eigenproduktion", exact: true }).click();
    await page.getByRole("heading", { name: "Eigenproduktion", level: 1 }).waitFor();
    await page.getByRole("tab", { name: "Einzelvideos" }).click();
    await page.getByRole("button", { name: "Englische Fassung erstellen" }).click();
    await page.getByText(/übersetzt/).first().waitFor();
    await page.getByRole("button", { name: "Deutsche Fassung erstellen" }).waitFor();

    await page.getByRole("link", { name: "Freigabecenter", exact: true }).click();
    await page.getByRole("heading", { name: "Freigabecenter", level: 1 }).waitFor();
    const prep = page.getByRole("form", { name: "Beitrag vorbereiten" });
    await prep.getByLabel("Themenbereich").selectOption({ label: "Ernährung E2E" });
    const video = prep.getByLabel("Video");
    await video.locator("option", { hasText: "Langer Stream – Teil 1" }).waitFor({ state: "attached" });
    await video.selectOption({ label: "Langer Stream – Teil 1" });
    await prep.getByRole("button", { name: "Überall vorbereiten" }).click();
    await page.getByText("Video: Langer Stream – Teil 1").first().waitFor({ timeout: 30000 });
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/freigabe-ueberall.png`, fullPage: true });
  });

  await step("Linkseite einschalten, Affiliate-Link mit Anzeige, Newsletter-Anmeldung", async () => {
    await page.getByRole("link", { name: "Linkseiten", exact: true }).click();
    await page.getByRole("heading", { name: "Linkseiten und Newsletter", level: 1 }).waitFor();
    await page.getByRole("button", { name: /^Linkseite .* einschalten$/ }).first().click();
    await page.getByRole("list", { name: "Linkseiten" }).getByText("online").first().waitFor();
    const aff = page.getByRole("form", { name: "Affiliate-Link anlegen" });
    await aff.getByLabel("Themenbereich").selectOption({ label: "Gaming" });
    await aff.getByLabel("Titel").fill("E2E Headset");
    await aff.getByLabel("Link", { exact: true }).fill("https://partner.example/headset");
    await aff.getByLabel("Partnerprogramm").fill("Testprogramm");
    await aff.getByRole("button", { name: "Hinzufügen" }).click();
    await page.getByRole("list", { name: "Affiliate-Links" }).getByText("E2E Headset").waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/linkseiten.png`, fullPage: true });

    const href = await page
      .getByRole("list", { name: "Linkseiten" })
      .locator("li", { hasText: "online" })
      .first()
      .getByRole("link", { name: "Vorschau" })
      .getAttribute("href");
    const pub = await browser.newPage();
    await pub.goto(new URL(href ?? "", BASE).toString());
    await pub.getByText("E2E Headset").waitFor();
    await pub.locator(".tag", { hasText: "Anzeige" }).first().waitFor();
    await pub.getByLabel("E-Mail-Adresse").fill("fan@example.com");
    await pub.getByRole("checkbox").check();
    if (SHOTS) await pub.screenshot({ path: `${SHOTS}/linkseite-oeffentlich.png`, fullPage: true });
    await pub.getByRole("button", { name: "Anmelden" }).click();
    await pub.getByText("Fast geschafft").waitFor();
    await pub.close();

    await page.reload();
    await page.getByRole("heading", { name: "Linkseiten und Newsletter", level: 1 }).waitFor();
    await page.getByRole("list", { name: "Newsletter-Adressen" }).getByText("fan@example.com").waitFor();
    await page.getByRole("list", { name: "Postausgang" }).getByText("Bitte bestätige deine Anmeldung").waitFor();
  });

  await step("Sponsoren-Postfach: Anfrage einordnen, Preis und Antwortentwurf", async () => {
    await page.getByRole("link", { name: "Sponsoren", exact: true }).click();
    await page.getByRole("heading", { name: "Sponsoren-Postfach", level: 1 }).waitFor();
    const form = page.getByRole("form", { name: "Anfrage einfügen" });
    await form.getByLabel("Absender").fill("Lisa <lisa@hyper-gear.com>");
    await form.getByLabel("Betreff").fill("Kooperation Headset");
    await form
      .getByLabel("Text der Mail")
      .fill("Hallo, wir möchten eine bezahlte Kooperation für ein Short mit unserem Headset. Was kostet das?");
    await form.getByRole("button", { name: "Einordnen und Antwort entwerfen" }).click();
    const card = page.getByRole("article", { name: "Anfrage Hyper Gear" });
    await card.locator(".chip", { hasText: "Bezahlte Kooperation" }).waitFor();
    await card.getByText(/Preisvorschlag: .* je Short/).waitFor();
    const draft = await card.getByLabel(/Antwortentwurf/).inputValue();
    assert.ok(draft.includes("Anzeige"), draft);
    await card.getByRole("link", { name: "Im Mailprogramm öffnen" }).waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/sponsoren.png`, fullPage: true });
    await card.getByRole("button", { name: "Beantwortet" }).click();
    await card.getByText("Beantwortet", { exact: true }).first().waitFor();
  });

  await step("Wochenbericht: Vorschau und Jetzt senden (Postausgang)", async () => {
    await page.getByRole("link", { name: "Analytics", exact: true }).click();
    await page.getByText("Wochenbericht per E-Mail").waitFor();
    await page.getByText(/Vorschau: Wochenbericht KW \d+/).click();
    await page.getByLabel("Wochenbericht Vorschau").getByText(/Kurz: \d+ Beiträge/).waitFor();
    await page.getByRole("button", { name: "Jetzt senden" }).click();
    await page.getByText("Liegt im Postausgang").waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/wochenbericht.png`, fullPage: true });
  });

  await step("Eigenproduktion: Serie planen, alle Teile erzeugen und freigeben", async () => {
    await page.getByRole("link", { name: "Eigenproduktion", exact: true }).click();
    await page.getByRole("heading", { name: "Eigenproduktion", level: 1 }).waitFor();
    await page.getByRole("tab", { name: "Serien" }).click();
    const form = page.getByRole("form", { name: "Neue Serie" });
    await form.getByLabel("Themenbereich").selectOption({ label: "Ernährung E2E" });
    await page.getByRole("list", { name: "Serienvorschläge" }).getByRole("listitem").first().waitFor();
    await form.getByLabel("Thema der Serie").fill("Wie entsteht Brot");
    await form.getByLabel("Umfang").selectOption("parts");
    await form.getByLabel(/Teile \(2 bis 30\)/).fill("2");
    await form.getByLabel("Länge je Teil").selectOption("60");
    await form.getByRole("button", { name: "Serie planen" }).click();
    const steps = page.getByRole("list", { name: "Schritte der Serie" });
    await steps.getByText("2 von 2 geschrieben").waitFor({ timeout: 60000 });
    await steps.getByText(/2 von 2 fertig/).waitFor({ timeout: 180000 });
    await page.getByRole("button", { name: "Alle fertigen Teile freigeben" }).click();
    await page.getByText(/Beiträge vorbereitet, \d+ freigegeben/).waitFor({ timeout: 30000 });
    await page.getByLabel(/^Plan /).first().getByText(/Teil 1/).waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/eigenproduktion-serie.png`, fullPage: true });
  });

  await step("Hilfe: Fragezeichen zeigt Anleitung der Seite, Hilfe-Seite mit Erste Schritte", async () => {
    await page.getByRole("link", { name: "Kanal-Assistent", exact: true }).click();
    await page.getByRole("heading", { name: "Kanal-Assistent", level: 1 }).waitFor();
    await page.getByRole("button", { name: "Anleitung für diese Seite" }).click();
    const panel = page.getByRole("dialog", { name: "Kanal-Assistent" });
    await panel.getByRole("heading", { name: "So gehst du vor" }).waitFor();
    await panel.getByRole("heading", { name: "Das machst du selbst" }).waitFor();
    // a side panel on the right, not part of the top bar (a broken stylesheet did that)
    await page.waitForTimeout(300); // slide-in animation
    const box = await panel.evaluate((el) => {
      const r = el.getBoundingClientRect();
      const top = document.querySelector(".topbar, header");
      return {
        position: getComputedStyle(el).position,
        left: r.left,
        width: r.width,
        page: window.innerWidth,
        inTopbar: Boolean(top && top.contains(el) && getComputedStyle(el).position !== "fixed"),
      };
    });
    assert.equal(box.position, "fixed", JSON.stringify(box));
    assert.ok(box.width <= 421 && box.left >= box.page / 2 && !box.inTopbar, JSON.stringify(box));
    await page.keyboard.press("Escape");
    await panel.waitFor({ state: "detached" });
    // every page in the navigation has its own guide
    const hrefs = await page
      .locator('nav[aria-label="Hauptnavigation"] a')
      .evaluateAll((links) => links.map((a) => new URL(a.href).pathname));
    for (const href of hrefs) {
      await page.goto(BASE + href);
      await page.getByRole("button", { name: "Anleitung für diese Seite" }).click();
      await page.getByRole("dialog").getByRole("heading", { name: "So gehst du vor" }).waitFor();
    }
    await page.getByRole("dialog").getByRole("link", { name: /Alle Anleitungen/ }).click();
    await page.getByRole("heading", { name: "Hilfe", level: 1 }).waitFor();
    assert.equal(await page.getByRole("list", { name: "Erste Schritte" }).locator("li").count(), 5);
    await page.getByPlaceholder(/Suchen/).fill("Captcha");
    await page.getByText("Seite „Kanal-Assistent“ öffnen").waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/hilfe.png`, fullPage: true });
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
