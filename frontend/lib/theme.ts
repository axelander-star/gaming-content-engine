// Colour theme: dark by default, light on request. Stored only in this browser.

export type Theme = "dark" | "light";

const KEY = "gce-theme";

export function readTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function setTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // private mode or blocked storage: the choice lasts for this page only
  }
}

/** Runs before the first paint (inline in the root layout) to avoid a flash. */
export const THEME_BOOT_SCRIPT = `try{document.documentElement.dataset.theme=localStorage.getItem("${KEY}")==="light"?"light":"dark"}catch(e){document.documentElement.dataset.theme="dark"}`;
