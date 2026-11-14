// End-to-end smoke test for the dashboard (Phase 3).
// Needs a running dashboard (BASE_URL, default http://127.0.0.1:3000) wired to a
// backend with an admin account (E2E_EMAIL / E2E_PASSWORD).
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
