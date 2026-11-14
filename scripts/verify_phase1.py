#!/usr/bin/env python3
"""Phase-1 verification for the Gaming Content Engine.

Checks:
  1. Required files and directories from PROJECT_SPEC.md section 18 exist.
  2. docker-compose.yml parses and contains the core services.
  3. .env.example contains the safe publishing defaults.
  4. .gitignore excludes .env and media files.
  5. No obvious secrets are present in tracked text files.
  6. Relative Markdown links between documents resolve.

Exit code 0 on success, 1 on any failure. Uses only the standard library
plus PyYAML (optional: the compose check is skipped with a warning if missing).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FILES = [
    "CLAUDE.md",
    "PROJECT_SPEC.md",
    "README.md",
    ".gitignore",
    "docker-compose.yml",
    ".env.example",
    "docs/ARCHITECTURE.md",
    "docs/DEVELOPMENT_PLAN.md",
    "docs/SECURITY.md",
    "docs/PROJECT_STATUS.md",
    "docs/API_INTEGRATIONS.md",
    "docs/AGENTS.md",
    "infrastructure/caddy/Caddyfile",
]

REQUIRED_DIRS = [
    "backend/app", "backend/agents", "backend/api", "backend/core", "backend/database",
    "backend/models", "backend/services", "backend/workflows", "backend/tests",
    "frontend/app", "frontend/components", "frontend/dashboard", "frontend/lib", "frontend/public",
    "infrastructure/docker", "infrastructure/caddy", "infrastructure/monitoring",
    "scripts",
]

SAFE_DEFAULTS = {
    "AUTO_PUBLISH_ENABLED": "false",
    "PUBLISHING_MODE": "mock",
    "PAID_API_CALLS_ENABLED": "false",
    "EMERGENCY_STOP": "false",
}

SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),                      # AWS access key
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),               # Google API key
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                  # generic sk- keys
    re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),                  # GitHub token
]

TEXT_SUFFIXES = {".md", ".yml", ".yaml", ".py", ".sh", ".txt", ".json", ".toml", ""}

failures: list[str] = []
passes: list[str] = []


def check(cond: bool, ok: str, fail: str) -> None:
    (passes if cond else failures).append(ok if cond else fail)


def check_structure() -> None:
    for f in REQUIRED_FILES:
        check((ROOT / f).is_file(), f"Datei vorhanden: {f}", f"Datei fehlt: {f}")
    for d in REQUIRED_DIRS:
        check((ROOT / d).is_dir(), f"Ordner vorhanden: {d}", f"Ordner fehlt: {d}")


def check_compose() -> None:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        print("WARNUNG: PyYAML fehlt, Compose-Prüfung übersprungen")
        return
    data = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = set((data or {}).get("services", {}))
    for svc in ("postgres", "redis", "caddy", "n8n", "uptime-kuma"):
        check(svc in services, f"Compose-Dienst definiert: {svc}", f"Compose-Dienst fehlt: {svc}")
    for svc in ("postgres", "redis"):
        ports = data["services"][svc].get("ports", [])
        check(all(str(p).startswith("127.0.0.1:") for p in ports),
              f"{svc} nur lokal gebunden", f"{svc} ist öffentlich gebunden: {ports}")


def parse_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.split("#", 1)[0].strip()
    return result


def check_env() -> None:
    env = parse_env(ROOT / ".env.example")
    for key, expected in SAFE_DEFAULTS.items():
        check(env.get(key) == expected, f".env.example {key}={expected}",
              f".env.example {key} ist '{env.get(key)}', erwartet '{expected}'")
    for key, value in env.items():
        if any(s in key for s in ("PASSWORD", "SECRET", "_KEY")) and key not in SAFE_DEFAULTS:
            check(value in ("", "change-me"), f".env.example {key} ohne echten Wert",
                  f".env.example {key} enthält einen Wert, der wie ein echtes Secret aussieht")


def check_gitignore() -> None:
    lines = {l.strip() for l in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    for entry in (".env", "!.env.example", "*.mp4", "node_modules/", "__pycache__/"):
        check(entry in lines, f".gitignore enthält {entry}", f".gitignore fehlt {entry}")


def check_secrets() -> None:
    hits = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                hits.append(f"{path.relative_to(ROOT)} ({pat.pattern[:20]}…)")
    check(not hits, "Keine Secrets im Projekt gefunden", f"Mögliche Secrets: {hits}")


def check_links() -> None:
    link_re = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
    broken = []
    for md in ROOT.rglob("*.md"):
        if ".git" in md.parts or "node_modules" in md.parts:
            continue
        for target in link_re.findall(md.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if not (md.parent / target).resolve().exists():
                broken.append(f"{md.relative_to(ROOT)} → {target}")
    check(not broken, "Alle relativen Markdown-Links gültig", f"Defekte Links: {broken}")


def check_spec_complete() -> None:
    spec = (ROOT / "PROJECT_SPEC.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (\d+)\.", spec, flags=re.MULTILINE)
    check(headings == [str(i) for i in range(1, 21)],
          "PROJECT_SPEC.md enthält Abschnitte 1–20",
          f"PROJECT_SPEC.md Abschnitte unvollständig: {headings}")
    agents = re.findall(r"^### Agent (\d+):", spec, flags=re.MULTILINE)
    check(agents == [str(i) for i in range(1, 19)],
          "PROJECT_SPEC.md enthält Agenten 1–18", f"Agenten unvollständig: {agents}")


def main() -> int:
    check_structure()
    check_compose()
    check_env()
    check_gitignore()
    check_secrets()
    check_links()
    check_spec_complete()
    for p in filter(None, passes):
        print(f"  OK    {p}")
    for f in failures:
        print(f"  FEHLER {f}")
    print(f"\n{len([p for p in passes if p])} bestanden, {len(failures)} fehlgeschlagen")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
